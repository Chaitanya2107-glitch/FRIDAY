import asyncio
from datetime import datetime, timedelta
import json

import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate

NOW = datetime(2026, 10, 20, 15)
SUBJECT = 'synthetic optics practical'
INITIAL = 'My synthetic optics practical is in 4 days'
CORRECTION = 'My synthetic optics practical was moved from Saturday to 2026-10-27'


@pytest.fixture
def correction(tmp_path, monkeypatch):
    from services.mind import reasoning, cognition_context, executive
    from services.mind.reasoning_store import ReasoningStore
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    store = Cognition(tmp_path / 'correction.db')
    episodes, temporal = BrainMemory(store), TemporalMemory(store)
    first = episodes.remember(INITIAL, now=NOW)
    value = TemporalUpdate(source=f'owner_episode:{first}', quote=INITIAL, subject=SUBJECT,
        status='planned', date_phrase='in 4 days', start=None, end=None, supersedes=[])
    known = episodes.evidence()
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([value], known), NOW, known)
    episodes.remember(CORRECTION, now=NOW + timedelta(hours=1))
    known = lambda: {**episodes.evidence(), **temporal.evidence()}
    memory = ReasoningStore(store)
    monkeypatch.setattr(memory, 'evidence', known)
    monkeypatch.setattr(reasoning, 'reasoning_store', memory)
    monkeypatch.setattr(reasoning, 'cognition', store)
    monkeypatch.setattr(cognition_context, 'live_state', lambda: {'activity': 'idle', 'away': False})
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle', 'away': False})
    control = executive.ExecutiveControl(store)
    monkeypatch.setattr(control, '_known', known)
    return store, episodes, temporal, known, control


def work_kinds(schema):
    return {branch['properties']['work_kind']['const'] for branch in schema['oneOf']}


def test_named_unrepresented_correction_narrows_native_work(correction):
    from services.mind.reasoning import cognitive_schema
    _, _, _, known, _ = correction
    schema = cognitive_schema(known())
    assert work_kinds(schema) == {'situations', 'silence'}
    assert schema['$defs']['TemporalUpdate']['properties']['source']['enum'] == ['owner_episode:2']
    situation = next(branch for branch in schema['oneOf'] if branch['properties']['work_kind']['const'] == 'situations')
    assert situation['properties']['items']['maxItems'] == 1
    assert schema['$defs']['TemporalUpdate']['properties']['quote']['enum'] == [CORRECTION]


@pytest.mark.parametrize('change', ['remote', 'historical', 'older', 'unrelated', 'already_represented', 'negated', 'question'])
def test_ineligible_report_does_not_displace_normal_work(correction, change):
    from services.mind.reasoning import cognitive_schema
    _, _, _, known, _ = correction
    evidence = known()
    row = evidence['owner_episode:2']
    if change == 'remote': row['channel'] = 'telegram'
    if change == 'historical': row['historical_recall'] = True
    if change == 'older': row['noted'] = '2026-10-19T16:00:00'
    if change == 'unrelated': row['text'] = 'My synthetic biology practical was moved to Friday'
    if change == 'negated': row['text'] = 'My synthetic optics practical was not moved to Friday'
    if change == 'question': row['text'] = 'Was my synthetic optics practical moved to Friday?'
    if change == 'already_represented':
        evidence['temporal:2'] = {**evidence['temporal:1'], 'source': 'owner_episode:2'}
    assert 'conclusions' in work_kinds(cognitive_schema(evidence))


def test_wrong_work_is_repaired_before_any_consolidation_can_save(correction, monkeypatch):
    from services.mind.consolidation import Consolidation
    _, _, temporal, _, control = correction
    calls = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' in payload:
            result = {'checks': [{'id': 0, 'supported': True, 'reason': 'Explicit named correction with an ISO target.'}]}
        elif len(calls) == 1:
            result = {'work_kind': 'memories', 'item': {'subject': SUBJECT,
                'evidence': ['owner_episode:1', 'owner_episode:2']}}
        else:
            result = {'work_kind': 'situations', 'items': [{'source': 'owner_episode:2', 'quote': CORRECTION,
                'subject': SUBJECT, 'status': 'planned', 'date_phrase': '2026-10-27', 'supersedes': ['temporal:1']}]}
        return ProviderResponse(content=json.dumps(result), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(control.review(NOW + timedelta(hours=1)))['status'] == 'completed'
    assert temporal.snapshot(NOW)['upcoming'][0]['start'] == '2026-10-27'
    assert len(temporal.history(SUBJECT)) == 2
    assert not Consolidation(temporal.store).evidence()
    assert len(calls) == 3  # Existing repair allowance, then independent critique.


def test_pending_correction_and_target_survive_crowded_context(correction, monkeypatch):
    from services.mind import reasoning
    _, _, _, known, _ = correction
    evidence = {f'fact:{n}': {'kind': 'owner_fact', 'quote': 'x' * 1100} for n in range(30)}
    evidence.update(known())
    from services.mind.executive import ExecutiveControl
    evidence = ExecutiveControl._build(NOW, evidence, {}, 'background')['evidence']
    assert {'owner_episode:2', 'temporal:1'} <= evidence.keys()
    seen = []
    async def complete(*args, **kwargs):
        seen.append(json.loads(args[1][0].content))
        return ProviderResponse(content='{"work_kind":"silence"}', provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    async def run():
        return await reasoning.analyze('', now=NOW, cognitive=True, evidence=evidence, save=lambda *a: [])
    assert asyncio.run(run())['status'] == 'completed'
    bounded = seen[0]['evidence']
    assert {'owner_episode:2', 'temporal:1'} <= bounded.keys()
    assert work_kinds(reasoning.cognitive_schema(bounded)) == {'situations', 'silence'}


@pytest.mark.parametrize('phrase', ['Tuesday', 'on Tuesday', 'to Tuesday', 'Tuesday morning', 'Tuesday at 5pm', 'Tuesday 10am'])
def test_receipt_weekday_has_no_invented_week(phrase):
    from services.mind.temporal_memory import anchored_dates
    assert anchored_dates(phrase, NOW) is None


def test_same_weekday_revision_becomes_a_gap_until_explicit_dated_followup(correction):
    from services.mind.curiosity import gaps
    store, episodes, temporal, known, _ = correction
    quote = 'My synthetic optics practical was rescheduled from Saturday to Tuesday'
    source = episodes.remember(quote, now=NOW + timedelta(hours=2))
    value = TemporalUpdate(source=f'owner_episode:{source}', quote=quote, subject=SUBJECT,
        status='planned', date_phrase='Saturday', start=None, end=None, supersedes=['temporal:1'])
    evidence = known()
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([value], evidence), NOW + timedelta(hours=2), evidence)
    unresolved = temporal.snapshot(NOW)['unresolved']
    assert len(unresolved) == 1 and unresolved[0]['date_phrase'] == 'Tuesday'
    assert unresolved[0]['start'] is None
    assert gaps(temporal.evidence())[0]['basis'] == [unresolved[0]['id']]
    quote = 'My synthetic optics practical was rescheduled to 2026-10-27'
    source = episodes.remember(quote, now=NOW + timedelta(hours=3))
    value = value.model_copy(update={'source': f'owner_episode:{source}', 'quote': quote,
        'date_phrase': '2026-10-27', 'supersedes': [unresolved[0]['id']]})
    evidence = known()
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([value], evidence), NOW + timedelta(hours=3), evidence)
    restored = TemporalMemory(Cognition(store.path))
    assert restored.snapshot(NOW)['upcoming'][0]['start'] == '2026-10-27'
    assert not gaps(restored.evidence())
    assert len(restored.history(SUBJECT)) == 3
    from services.mind.reasoning import cognitive_schema
    assert 'conclusions' in work_kinds(cognitive_schema(known()))


def test_only_latest_competing_correction_is_offered(correction):
    from services.mind.reasoning import cognitive_schema
    _, episodes, _, known, _ = correction
    latest = episodes.remember('My synthetic optics practical was moved to Sunday', now=NOW + timedelta(hours=2))
    schema = cognitive_schema(known())
    assert schema['$defs']['TemporalUpdate']['properties']['source']['enum'] == [f'owner_episode:{latest}']


def test_pending_candidates_remain_bounded_to_three_newest_targets(correction):
    _, _, _, known, _ = correction
    evidence = known()
    for n in range(5):
        subject = f'synthetic laboratory {n} review'
        evidence[f'temporal:{n+10}'] = {**evidence['temporal:1'], 'subject': subject}
        evidence[f'owner_episode:{n+10}'] = {**evidence['owner_episode:2'],
            'text': f'My {subject} was moved to Friday',
            'noted': (NOW + timedelta(hours=2, minutes=n)).isoformat()}
    assert list(TemporalMemory.pending_corrections(evidence)) == ['owner_episode:14', 'owner_episode:13', 'owner_episode:12']


@pytest.mark.parametrize('phrase,expected', [('today', '2026-10-20'), ('2026-10-20', '2026-10-20'),
                                          ('Wednesday', '2026-10-21')])
def test_explicit_dates_and_other_weekdays_remain_anchored(phrase, expected):
    from services.mind.temporal_memory import anchored_dates
    assert anchored_dates(phrase, NOW) == (expected, expected)


@pytest.mark.parametrize('failure', ['rejected', 'forgotten', 'wrong_source'])
def test_pending_priority_cannot_bypass_acceptance_guards(correction, monkeypatch, failure):
    store, _, temporal, _, control = correction
    calls = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' in payload:
            if failure == 'forgotten': store.clear()
            result = {'checks': [{'id': 0, 'supported': failure != 'rejected', 'reason': 'Synthetic refusal or source change.'}]}
        else:
            result = {'work_kind': 'situations', 'items': [{'source': 'owner_episode:1' if failure == 'wrong_source' else 'owner_episode:2',
                'quote': INITIAL if failure == 'wrong_source' else CORRECTION, 'subject': SUBJECT, 'status': 'planned',
                'date_phrase': 'in 4 days' if failure == 'wrong_source' else '2026-10-27', 'supersedes': ['temporal:1']}]}
        return ProviderResponse(content=json.dumps(result), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(control.review(NOW + timedelta(hours=1)))['status'] in {'unavailable', 'superseded'}
    history = temporal.history(SUBJECT)
    assert not history if failure == 'forgotten' else len(history) == 1
