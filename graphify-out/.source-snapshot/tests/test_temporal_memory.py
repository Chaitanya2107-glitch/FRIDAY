import asyncio
import json
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition
from services.mind.brain_memory import BrainMemory

NOW = datetime(2026, 10, 20, 15)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    from services.mind.temporal_memory import TemporalMemory
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    store = Cognition(tmp_path / 'brain.db')
    return TemporalMemory(store), BrainMemory(store)


def update(source_id, **changes):
    from services.mind.temporal_memory import TemporalUpdate
    return TemporalUpdate(**{'source': f'owner_episode:{source_id}', 'quote': 'My exam is tomorrow',
        'subject': 'exam', 'status': 'planned', 'date_phrase': 'tomorrow',
        'start': '2026-10-21', 'end': '2026-10-21', 'supersedes': [], **changes})


def save(memory, value, now=NOW):
    temporal, episodes = memory
    known = {**episodes.evidence(), **temporal.evidence()}
    with temporal._db() as db:
        temporal.save(db, [value], now, known)


def test_relative_date_survives_restart_without_rolling_forward(memory):
    from services.mind.temporal_memory import TemporalMemory
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source), NOW + timedelta(days=2))
    restored = TemporalMemory(Cognition(temporal.store.path))
    past = restored.snapshot(NOW + timedelta(days=2))['past']
    assert past[0]['start'] == '2026-10-21'
    assert past[0]['source_noted'] == NOW.isoformat()
    assert past[0]['status'] == 'planned'  # elapsed is not proof of completion


def test_explicit_correction_replaces_current_date_and_preserves_history(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    old = next(iter(temporal.evidence()))
    correction = episodes.remember('The exam was postponed to Friday', now=NOW + timedelta(hours=1))
    revision = update(correction, quote='The exam was postponed to Friday', date_phrase='Friday',
                      start='2026-10-23', end='2026-10-23', supersedes=[old])
    save(memory, revision)
    save(memory, revision)  # replay of the same correction is harmless
    snapshot = temporal.snapshot(NOW)
    assert len(snapshot['upcoming']) == 1 and snapshot['upcoming'][0]['start'] == '2026-10-23'
    history = temporal.history('exam')
    assert len(history) == 2 and history[-1]['superseded_by'] == snapshot['upcoming'][0]['id']
    assert history[-1]['quote'] == 'My exam is tomorrow'


def test_undated_postponement_is_unresolved_not_still_due_tomorrow(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    old = next(iter(temporal.evidence()))
    correction = episodes.remember('It was postponed', question='Did your exam date change?',
                                    now=NOW + timedelta(hours=1))
    save(memory, update(correction, quote='It was postponed', status='postponed', date_phrase='',
                        start=None, end=None, supersedes=[old]))
    view = temporal.snapshot(NOW)
    assert not view['upcoming'] and view['unresolved'][0]['start'] is None


@pytest.mark.parametrize('changes', [
    {'start': '2026-10-22', 'end': '2026-10-22'},  # rolled tomorrow forward
    {'source': 'owner_episode:999'}, {'quote': 'A fabricated source quote'},
    {'date_phrase': 'Friday'}, {'start': None},
])
def test_invalid_or_ungrounded_interpretation_saves_nothing(memory, changes):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    with pytest.raises(ValueError):
        save(memory, update(source, **changes))
    assert not temporal.evidence()


def test_ambiguous_date_stays_unresolved(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is sometime next week', now=NOW)
    save(memory, update(source, quote='My exam is sometime next week', status='uncertain',
                        date_phrase='sometime next week', start=None, end=None))
    assert temporal.snapshot(NOW)['unresolved'][0]['start'] is None


def test_remote_episode_cannot_enter_laptop_situation(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', channel='telegram', now=NOW)
    with pytest.raises(ValueError):
        save(memory, update(source))
    assert not temporal.evidence()


def test_duplicate_save_is_idempotent_and_forgetting_clears_history(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    value = update(source)
    save(memory, value)
    save(memory, value)
    assert len(temporal.history('exam')) == 1
    temporal.store.clear()
    assert not temporal.evidence() and not temporal.history('exam')


def test_uncertain_or_unrelated_correction_cannot_withdraw_commitment(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    old = next(iter(temporal.evidence()))
    source = episodes.remember('Maybe my dentist appointment moved', now=NOW + timedelta(hours=1))
    for changes in ({'status': 'uncertain'}, {'subject': 'dentist appointment'}):
        with pytest.raises(ValueError):
            save(memory, update(source, quote='Maybe my dentist appointment moved',
                date_phrase='', start=None, end=None, supersedes=[old], **changes))
    assert temporal.snapshot(NOW)['upcoming'][0]['subject'] == 'exam'


def test_source_removed_during_review_cannot_be_resurrected(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    stale = episodes.evidence()
    temporal.store.clear()
    with pytest.raises(ValueError), temporal._db() as db:
        temporal.save(db, [update(source)], NOW, stale)
    assert not temporal.evidence()


def test_real_executive_path_validates_critiques_and_saves_temporal_report(memory, monkeypatch):
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    from providers.base_provider import ProviderResponse
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle', 'away': False})
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(temporal.store))
    calls = []
    async def complete(*args, **kwargs):
        calls.append((json.loads(args[1][0].content), kwargs))
        result = ({'facts': [], 'conclusions': [], 'questions': [], 'situations': [update(source).model_dump()]}
                  if len(calls) == 1 else
                  {'checks': [{'id': 0, 'supported': True, 'reason': 'Direct owner report; original tomorrow is October 21.'}]})
        return ProviderResponse(content=json.dumps(result), provider='ollama', model='local')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(executive.ExecutiveControl(temporal.store).review(NOW))
    assert result['status'] == 'completed' and len(calls) == 2
    assert all(call[1]['purpose'] == 'cognitive_review' for call in calls)
    assert temporal.snapshot(NOW)['upcoming'][0]['start'] == '2026-10-21'
    assert not ReasoningStore(temporal.store).facts()


def test_life_and_language_share_current_situation(memory, monkeypatch):
    from services.mind import life, language, temporal_memory
    from providers.base_provider import ProviderResponse
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    monkeypatch.setattr(temporal_memory, 'temporal_memory', temporal)
    assert life.feeling(NOW)['situation']['upcoming'][0]['subject'] == 'exam'
    prompts = []
    async def complete(*args, **kwargs):
        prompts.append(args[2])
        return ProviderResponse(content='Your exam is on October 21.', provider='local', model='test')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    asyncio.run(language.answer('When is my exam?', 'ollama', [], 100))
    assert '2026-10-21' in prompts[0] and 'temporal interpretation' in prompts[0].lower()


def test_completed_report_is_closed_and_does_not_change_service_deadlines(memory):
    from services.proactive import deadlines
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    old = next(iter(temporal.evidence()))
    source = episodes.remember('I finished my exam', now=NOW + timedelta(days=1))
    save(memory, update(source, quote='I finished my exam', status='completed', date_phrase='',
                        start=None, end=None, supersedes=[old]))
    view = temporal.snapshot(NOW + timedelta(days=1))
    assert len(view['closed']) == 1 and not view['upcoming'] and not view['current']
    assert deadlines.load() == []  # interpretations never edit the canonical service


def test_concurrent_conflicting_corrections_accept_only_one(memory):
    from concurrent.futures import ThreadPoolExecutor
    from services.mind.temporal_memory import TemporalMemory
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    old = next(iter(temporal.evidence()))
    source = episodes.remember('The exam was postponed to Friday', now=NOW + timedelta(hours=1))
    other_source = episodes.remember('My exam is cancelled', now=NOW + timedelta(hours=2))
    values = [update(source, quote='The exam was postponed to Friday', date_phrase='Friday',
                     start='2026-10-23', end='2026-10-23', supersedes=[old]),
              update(other_source, quote='My exam is cancelled', status='cancelled', date_phrase='',
                     start=None, end=None, supersedes=[old])]
    known = {**episodes.evidence(), **temporal.evidence()}
    def commit(value):
        connection = TemporalMemory(Cognition(temporal.store.path))
        try:
            with connection._db() as db:
                connection.save(db, [value], NOW + timedelta(hours=3), known)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, values)) == [False, True]
    assert len(temporal.history('exam')) == 2 and len(temporal.evidence()) == 1


def test_failed_multi_record_report_rolls_back_all_interpretations(memory):
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    value = update(source)
    # Same existing source+subject cannot later be silently reinterpreted.
    save(memory, value)
    other = episodes.remember('My dentist appointment is tomorrow', now=NOW)
    known = {**episodes.evidence(), **temporal.evidence()}
    with pytest.raises(ValueError), temporal._db() as db:
        temporal.save(db, [update(other, subject='dentist appointment', quote='My dentist appointment is tomorrow'),
                           update(source, status='uncertain')], NOW, known)
    assert len(temporal.evidence()) == 1


def test_critique_rejects_hypothetical_without_retaining_a_situation(memory, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import ReasoningStore
    from providers.base_provider import ProviderResponse
    temporal, episodes = memory
    source = episodes.remember('Imagine my exam is tomorrow', now=NOW)
    known = episodes.evidence()
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    source_store = ReasoningStore(temporal.store)
    monkeypatch.setattr(reasoning, 'reasoning_store', source_store)
    calls = []
    async def complete(*args, **kwargs):
        calls.append(json.loads(args[1][0].content))
        result = ({'checks': [{'id': 0, 'supported': False, 'reason': 'This is a hypothetical, not a commitment.'}]}
                  if 'check_items' in calls[-1] else
                  {'facts': [], 'conclusions': [], 'questions': [], 'situations': [
                      update(source, quote='Imagine my exam is tomorrow').model_dump()]})
        return ProviderResponse(content=json.dumps(result), provider='ollama', model='test')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(reasoning.analyze('', now=NOW, cognitive=True, evidence=known, save=source_store.save))
    assert result['status'] == 'unavailable' and len(calls) == 4
    assert not temporal.evidence()


def test_local_situation_is_not_attached_to_remote_conversation(memory, monkeypatch):
    from services.mind import language, temporal_memory
    from services.mind.cognition import _channel
    from providers.base_provider import ProviderResponse
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    monkeypatch.setattr(temporal_memory, 'temporal_memory', temporal)
    prompts = []
    async def complete(*args, **kwargs):
        prompts.append(args[2])
        return ProviderResponse(content='Remote reply.', provider='local', model='test')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    token = _channel.set('telegram')
    try:
        asyncio.run(language.answer('Hello', 'ollama', [], 100))
    finally:
        _channel.reset(token)
    assert '2026-10-21' not in prompts[0] and 'Shared situation' not in prompts[0]


@pytest.mark.parametrize('phrase,expected', [('tomorrow afternoon', '2026-10-21'),
    ('day after tomorrow', '2026-10-22'), ('in 2 weeks', '2026-11-03'), ('23/10/2026', '2026-10-23'),
    ('next week', None), ('next Friday', None), ('at 5pm', None)])
def test_calendar_anchor_handles_supported_phrases_and_defers_ambiguity(phrase, expected):
    from services.mind.temporal_memory import anchored_dates
    result = anchored_dates(phrase, NOW)
    assert result == ((expected, expected) if expected else None)


def test_model_date_arithmetic_is_replaced_by_original_local_calendar(memory):
    from services.mind.temporal_memory import TemporalMemory
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    bad_arithmetic = update(source, start='2026-10-20', end='2026-10-20')
    resolved = TemporalMemory.resolve([bad_arithmetic], episodes.evidence())[0]
    assert resolved.start == resolved.end == '2026-10-21'
    save(memory, resolved, NOW + timedelta(days=5))
    assert temporal.snapshot(NOW)['upcoming'][0]['start'] == '2026-10-21'


def test_uncertain_expression_cannot_acquire_an_invented_exact_day(memory):
    from services.mind.temporal_memory import TemporalMemory
    temporal, episodes = memory
    source = episodes.remember('My exam is next week', now=NOW)
    guessed = update(source, quote='My exam is next week', date_phrase='next week',
                     start='2026-10-26', end='2026-10-26')
    resolved = TemporalMemory.resolve([guessed], episodes.evidence())[0]
    assert resolved.start is resolved.end is None
    save(memory, resolved)
    assert temporal.snapshot(NOW)['unresolved']


def test_local_api_exposes_same_revision_history(memory, monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from services.mind import temporal_memory
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    monkeypatch.setattr(temporal_memory, 'temporal_memory', temporal)
    client = TestClient(create_app(), base_url='http://127.0.0.1')
    response = client.get('/api/v1/mind/situation/history', params={'subject': 'exam'})
    assert response.status_code == 200
    assert response.json()['revisions'][0]['quote'] == 'My exam is tomorrow'
    assert client.get('/api/v1/mind/situation').status_code == 200


def test_correction_invalidates_conclusions_based_on_the_superseded_episode(memory):
    from services.mind.reasoning import Report
    from services.mind.reasoning_store import ReasoningStore
    temporal, episodes = memory
    source = episodes.remember('My exam is tomorrow', now=NOW)
    save(memory, update(source))
    reasoner = ReasoningStore(temporal.store)
    report = Report(facts=[], questions=[], conclusions=[{'kind': 'implication',
        'text': 'The exam is tomorrow', 'evidence': [f'owner_episode:{source}'], 'confidence': .9,
        'effect': {'type': 'guidance'}}])
    reasoner.save(report, NOW, reasoner.evidence())
    assert reasoner.conclusions(NOW)
    old = next(iter(temporal.evidence()))
    correction = episodes.remember('The exam was postponed to Friday', now=NOW + timedelta(hours=1))
    save(memory, update(correction, quote='The exam was postponed to Friday', date_phrase='Friday',
                        start='2026-10-23', end='2026-10-23', supersedes=[old]))
    assert not reasoner.conclusions(NOW)
    assert reasoner.evidence()[f'owner_episode:{source}']['historical_commitment_revisions']


@pytest.mark.parametrize('phrase', ['2026-10-21 to 2020-10-22', '2026-10-21 to 2030-10-22'])
def test_calendar_resolution_revalidates_date_window_bounds(memory, phrase):
    from services.mind.temporal_memory import TemporalMemory
    temporal, episodes = memory
    text = f'My exam is {phrase}'
    source = episodes.remember(text, now=NOW)
    value = update(source, quote=text, date_phrase=phrase, start=None, end=None)
    with pytest.raises(ValueError):
        TemporalMemory.resolve([value], episodes.evidence())
    assert not temporal.evidence()
