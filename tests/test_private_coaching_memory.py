from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition
from services.mind.goals_parser import parse
from services.mind.outcome_learning import OutcomeLearning
from services.mind.temporal_memory import TemporalMemory

NOW = datetime(2026, 11, 17, 10)
SECRET = 'private-coaching-sentinel'


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', False)
    store = Cognition(tmp_path / 'coaching.db')
    return store, TemporalMemory(store), OutcomeLearning(store)


def test_private_commitments_are_source_linked_revisable_and_not_legacy_evidence(memory):
    store, temporal, outcomes = memory
    definition = parse(f'finish 100 {SECRET} problems by Dec 15', NOW)
    first = temporal.save_private_commitment(definition, SECRET + ' owner confirmed', now=NOW)
    assert first['source_key'].startswith('coaching_source:') and first['revision'] == 1
    temporal.save_private_commitment(dict(definition, target=80), 'Owner confirmed a smaller target', identity=first['id'], expected_revision=1, now=NOW)
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM private_coaching_revisions').fetchone()[0] == 2
        assert db.execute('SELECT text FROM private_coaching_sources WHERE id=?', (first['source_key'],)).fetchone()[0].startswith(SECRET)
    from services.mind.brain_memory import BrainMemory
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.consolidation import Consolidation
    assert not temporal.evidence()
    assert not BrainMemory(store).evidence()
    assert not BrainMemory(store).recall(SECRET)
    assert SECRET not in str(ReasoningStore(store).evidence())
    assert SECRET not in str(ReasoningStore(store).context())
    assert not Consolidation(store).source_evidence()
    assert not outcomes.evidence() and not store.recent()


def test_numeric_experiment_needs_confirm_and_end_then_records_noncausal_delta(memory):
    store, _, outcomes = memory
    end = NOW + timedelta(days=7)
    identity = outcomes.propose_private_experiment(dict(name=SECRET, metric='phone_study_minutes', direction='decrease'),
        50, NOW, end, [{'device': 'one'}], now=NOW)
    assert outcomes.finish_private_experiment(identity, 30, [{'device': 'one'}], end) is None
    assert outcomes.confirm_private_experiment(identity, now=NOW)['state'] == 'confirmed'
    assert outcomes.finish_private_experiment(identity, 30, [{'device': 'one'}], NOW) is None
    result = outcomes.finish_private_experiment(identity, 30, [{'device': 'one'}], end)
    assert result['state'] == 'measured' and result['delta'] == -20
    assert 'not proof' in result['meaning']
    assert outcomes.finish_private_experiment(identity, 60, [], end) is None
    assert outcomes.private_experiments()[0]['observed'] == 30
    assert not outcomes.evidence() and not outcomes.context()['receipts']
    assert not store.recent()


def test_missing_metric_remains_unavailable_and_invalid_numbers_are_rejected(memory):
    _, _, outcomes = memory
    end = NOW + timedelta(days=7)
    identity = outcomes.propose_private_experiment({'name': SECRET}, 50, NOW, end, [], now=NOW)
    outcomes.confirm_private_experiment(identity, now=NOW)
    result = outcomes.finish_private_experiment(identity, None, [], end)
    assert result['state'] == 'unavailable' and result['observed'] is None and result['delta'] is None
    for bad in (True, -1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            outcomes.propose_private_experiment({'name': SECRET}, bad, NOW, end, [])


def test_forget_phone_removes_derived_logs_experiments_and_suspends_its_source(memory):
    _, temporal, outcomes = memory
    definition = parse('walk 8000 steps every day', NOW)
    definition['source']['device'] = 'one'
    goal = temporal.save_private_commitment(definition, 'Owner confirmed source one', now=NOW)
    one = outcomes.propose_private_experiment({'name': 'first'}, 50, NOW, NOW + timedelta(days=7), [{'device': 'one'}], now=NOW)
    two = outcomes.propose_private_experiment({'name': 'second'}, 10, NOW, NOW + timedelta(days=7), [{'device': 'two'}], now=NOW)
    temporal.forget_private_phone('one'); outcomes.forget_private_phone('one')
    assert temporal.private_commitments()[0]['definition']['source_suspended']
    assert {r['id'] for r in outcomes.private_experiments()} == {two}
    assert outcomes.confirm_private_experiment(one, now=NOW) is None
    assert temporal.private_commitments()[0]['id'] == goal['id']


def test_legacy_action_whitelist_and_evidence_remain_unchanged(memory):
    _, _, outcomes = memory
    with pytest.raises(ValueError):
        outcomes.begin('care_experiment', {'minutes': 30}, NOW)
    job = outcomes.begin('set_volume', {'volume': 30}, NOW)
    outcomes.finish(job, {'volume': 30}, True, NOW)
    assert outcomes.recent()[0]['state'] == 'verified'
    assert outcomes.evidence()['action_outcome:1']['action'] == 'set_volume'


def test_forget_erases_deleted_private_payloads_from_sqlite_pages(memory):
    store, temporal, outcomes = memory
    phone_id = 'PHONE_DEVICE_ERASURE_SENTINEL_8a731b'
    private_name = 'PHONE_EXPERIMENT_ERASURE_SENTINEL_9fd127'
    goal = temporal.save_private_commitment(parse('gym 3 times a week', NOW), 'Owner chose manual logs', now=NOW)
    temporal.log_private_progress(goal['id'], 1, event_id='private-phone-log', now=NOW, source_links=[{'device': phone_id}])
    outcomes.propose_private_experiment({'name': private_name}, 50, NOW, NOW + timedelta(days=7), [{'device': phone_id}], now=NOW)
    assert private_name.encode() in store.path.read_bytes()
    temporal.forget_private_phone(phone_id)
    outcomes.forget_private_phone(phone_id)
    assert phone_id.encode() not in store.path.read_bytes()
    assert private_name.encode() not in store.path.read_bytes()
