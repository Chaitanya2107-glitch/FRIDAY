import asyncio
from datetime import datetime, timedelta
import json

import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.curiosity import gaps
from services.mind.inquiry import Inquiry, Decision
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate

NOW = datetime(2026, 10, 20, 15)
QUESTION = 'What is the exact date of your robotics assessment?'
SUBJECT = 'robotics assessment'


@pytest.fixture
def inquiry_answer(tmp_path, monkeypatch):
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    store = Cognition(tmp_path / 'answers.db')
    episodes, temporal, inquiry = BrainMemory(store), TemporalMemory(store), Inquiry(store)
    quote = 'My robotics assessment was postponed'
    first = episodes.remember(quote, now=NOW)
    value = TemporalUpdate(source=f'owner_episode:{first}', quote=quote, subject=SUBJECT,
        status='postponed', date_phrase='', start=None, end=None, supersedes=[])
    with temporal._db() as db:
        temporal.save(db, [value], NOW, episodes.evidence())
    known = lambda: {**temporal.evidence(), **episodes.evidence()}
    gap = gaps(temporal.evidence())[0]
    job = inquiry.claim('synthetic-date-question', NOW, True)
    decision = Decision(ask=True, question=QUESTION, topic=SUBJECT, basis=['temporal:1'],
        reason='The exact date changes the review plan.', purpose={'gap': gap['id'],
            'decision': 'Choose which day to plan assessment preparation.',
            'if_answer_a': {'answer': 'October 27', 'next_step': 'Propose preparation before October 27.'},
            'if_answer_b': {'answer': 'November 3', 'next_step': 'Propose preparation before November 3.'},
            'usefulness': 'changes_decision'})
    assert inquiry.finish(job, 'queued', decision.reason, NOW, decision, known(), gap)
    inquiry.mark(job['id'], 'submitted')
    return store, episodes, temporal, inquiry, job, known


def linked_answer(fixture, text='October 27', question=QUESTION, **changes):
    _, episodes, _, inquiry, job, _ = fixture
    inquiry.mark(job['id'], 'answered')
    return episodes.remember(text, question=question, inquiry_id=job['id'],
                             now=NOW + timedelta(minutes=1), **changes)


def revision(source, quote='October 27', phrase='Tuesday'):
    return TemporalUpdate(source=f'owner_episode:{source}', quote=quote, subject=SUBJECT,
        status='planned', date_phrase=phrase, start=None, end=None, supersedes=['temporal:1'])


def test_verified_answer_is_prioritized_and_keeps_original_question(inquiry_answer):
    from services.mind.reasoning import cognitive_schema
    source = linked_answer(inquiry_answer)
    store, _, _, _, job, known = inquiry_answer
    row = known()[f'owner_episode:{source}']
    assert row['inquiry_id'] == job['id'] and row['question'] == QUESTION
    assert row['date_clarification']['target'] == 'temporal:1'
    assert TemporalMemory.pending_corrections(known()) == {f'owner_episode:{source}': ['temporal:1']}
    schema = cognitive_schema(known())
    assert {b['properties']['work_kind']['const'] for b in schema['oneOf']} == {'situations', 'silence'}
    assert schema['$defs']['TemporalUpdate']['properties']['subject']['enum'] == [SUBJECT]
    restored = BrainMemory(Cognition(store.path)).evidence()
    assert restored[f'owner_episode:{source}']['date_clarification'] == row['date_clarification']


def test_answer_repairs_stale_model_date_and_preserves_history(inquiry_answer):
    source = linked_answer(inquiry_answer)
    store, _, temporal, _, _, known = inquiry_answer
    evidence = known()
    result = temporal.resolve([revision(source)], evidence)
    assert result[0].date_phrase == 'October 27' and result[0].start == '2026-10-27'
    with temporal._db() as db:
        temporal.save(db, result, NOW + timedelta(days=3), evidence)
    restored = TemporalMemory(Cognition(store.path))
    history = restored.history(SUBJECT)
    assert len(history) == 2 and history[1]['superseded_by'] == history[0]['id']
    assert history[0]['source_question'] == QUESTION
    assert not gaps(restored.evidence())
    with restored._db() as db:
        restored.save(db, result, NOW + timedelta(days=4), known())
    assert len(restored.history(SUBJECT)) == 2


@pytest.mark.parametrize('text', ['Maybe October 27', 'October 27 or 28', 'Tuesday', 'pizza',
                                '2026-10-27 through 2026-10-28', 'not October 27',
                                'October 27' + ' ' * 1300 + 'maybe'])
def test_uncertain_ambiguous_or_unrelated_replies_cannot_supply_a_revision(inquiry_answer, text):
    source = linked_answer(inquiry_answer, text=text)
    _, _, temporal, _, _, known = inquiry_answer
    assert not temporal.pending_corrections(known())
    with pytest.raises(ValueError):
        values = temporal.resolve([revision(source, quote=text, phrase='')], known())
        temporal.validate(values, known())
    assert len(temporal.history(SUBJECT)) == 1


@pytest.mark.parametrize('change', ['question', 'remote', 'version', 'epoch', 'multiple', 'job_removed', 'future_question'])
def test_invalid_provenance_does_not_link_an_answer(inquiry_answer, change):
    _, episodes, temporal, inquiry, job, known = inquiry_answer
    if change == 'version':
        with temporal._db() as db:
            body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
            body['noted'] = '2026-10-20T15:00:01'
            db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
    if change in {'epoch', 'multiple', 'job_removed', 'future_question'}:
        with inquiry._db() as db:
            if change == 'epoch': db.execute('UPDATE inquiry_meta SET epoch=epoch+1')
            if change == 'multiple': db.execute('UPDATE inquiry_jobs SET basis=?', ('{"temporal:1":"x","temporal:2":"y"}',))
            if change == 'job_removed': db.execute('DELETE FROM inquiry_jobs')
            if change == 'future_question': db.execute('UPDATE inquiry_jobs SET created=?', ((NOW + timedelta(minutes=5)).timestamp(),))
    source = linked_answer(inquiry_answer, question='When is the dentist appointment?' if change == 'question' else QUESTION,
                           channel='telegram' if change == 'remote' else 'chat')
    row = episodes.evidence()[f'owner_episode:{source}']
    assert not row.get('date_clarification')
    assert not temporal.pending_corrections(known())
    with pytest.raises(ValueError):
        temporal.validate(temporal.resolve([revision(source, phrase='October 27')], known()), known())


@pytest.mark.parametrize('subject', [SUBJECT, 'October'])
def test_unlinked_date_fragment_cannot_bypass_through_ordinary_review(inquiry_answer, subject):
    _, episodes, temporal, _, _, known = inquiry_answer
    source = episodes.remember('October 27', question=QUESTION, now=NOW + timedelta(minutes=1))
    evidence = known()
    evidence['temporal:1']['subject'] = subject
    value = revision(source, phrase='October 27').model_copy(update={'subject': subject})
    with pytest.raises(ValueError):
        temporal.validate(temporal.resolve([value], evidence), evidence)


@pytest.mark.parametrize('offered', [True, False])
@pytest.mark.parametrize('text', ['October 27', "It's on October 27."])
def test_talk_only_attaches_an_offered_local_inquiry(inquiry_answer, monkeypatch, offered, text):
    from services.mind import talk
    _, episodes, _, inquiry, job, _ = inquiry_answer
    monkeypatch.setattr('services.mind.brain_memory.brain_memory', episodes)
    monkeypatch.setattr('services.mind.inquiry.inquiry', inquiry)
    monkeypatch.setattr(talk, '_learn_answer', lambda *a: None)
    talk._save({**talk.load(), 'pending': {'where': 'asked', 'at': NOW.timestamp(),
        'question': QUESTION, 'inquiry_id': job['id'], 'offered': offered}})
    assert talk.hear(text, now=(NOW + timedelta(seconds=30)).timestamp()) == 'answered'
    answer = next(row for row in episodes.evidence().values() if row['kind'] == 'owner_answer')
    assert bool(answer.get('date_clarification')) is offered


@pytest.mark.parametrize('change', ['inquiry', 'source', 'forget'])
@pytest.mark.parametrize('text', ['October 27', "It's on October 27."])
def test_acceptance_rechecks_inquiry_and_original_answer(inquiry_answer, change, text):
    store, episodes, temporal, inquiry, job, known = inquiry_answer
    source = linked_answer(inquiry_answer, text=text)
    evidence = known()
    values = temporal.resolve([revision(source, quote=text)], evidence)
    if change == 'inquiry':
        with inquiry._db() as db: db.execute('DELETE FROM inquiry_jobs WHERE id=?', (job['id'],))
    if change == 'source':
        with episodes._db() as db: db.execute('UPDATE owner_episodes SET inquiry_id=NULL WHERE id=?', (source,))
    if change == 'forget': store.clear()
    with pytest.raises(ValueError), temporal._db() as db:
        temporal.save(db, values, NOW + timedelta(minutes=2), evidence)
    assert len(temporal.history(SUBJECT)) == (0 if change == 'forget' else 1)


def test_relative_date_uses_answer_receipt_after_restart(inquiry_answer):
    source = linked_answer(inquiry_answer, text='tomorrow')
    store, _, temporal, _, _, known = inquiry_answer
    restored = TemporalMemory(Cognition(store.path))
    evidence = known()
    values = restored.resolve([revision(source, quote='tomorrow', phrase='')], evidence)
    with restored._db() as db:
        restored.save(db, values, NOW + timedelta(days=5), evidence)
    assert restored.snapshot(NOW + timedelta(days=5))['past'][0]['start'] == '2026-10-21'


@pytest.mark.parametrize('text,phrase,expected', [
    ("It's on October 27.", 'on October 27', '2026-10-27'),
    ('It’s on October 27!', 'on October 27', '2026-10-27'),
    ('It is on October 27.', 'on October 27', '2026-10-27'),
    ("It'll be on November 3.", 'on November 3', '2026-11-03'),
    ('It’ll be on November 3.', 'on November 3', '2026-11-03'),
    ('It will be on November 3.', 'on November 3', '2026-11-03'),
    ("That's for November 3.", 'for November 3', '2026-11-03'),
    ('The date is October 27.', 'October 27', '2026-10-27'),
    ('It is scheduled for October 27.', 'for October 27', '2026-10-27'),
    ("It's set for October 27.", 'for October 27', '2026-10-27'),
    ('  IT IS   ON October 27. ', 'ON October 27', '2026-10-27'),
    ('That will be tomorrow.', 'tomorrow', '2026-10-21'),
    ('That’ll be on December 4.', 'on December 4', '2026-12-04'),
    ('It will be in 3 days.', 'in 3 days', '2026-10-23'),
])
def test_conversational_date_answer_keeps_exact_span_and_original_receipt(inquiry_answer, text, phrase, expected):
    from services.mind.temporal_memory import answer_date_phrase
    source = linked_answer(inquiry_answer, text=text)
    store, _, temporal, _, _, known = inquiry_answer
    evidence = known()
    assert answer_date_phrase(evidence[f'owner_episode:{source}']) == phrase
    assert temporal.pending_corrections(evidence) == {f'owner_episode:{source}': ['temporal:1']}
    values = temporal.resolve([revision(source, quote=text)], evidence)
    assert values[0].date_phrase == phrase and phrase in text and values[0].quote == text
    temporal.validate(values, evidence)
    with temporal._db() as db:
        temporal.save(db, values, NOW + timedelta(days=5), evidence)
    history = TemporalMemory(Cognition(store.path)).history(SUBJECT)
    assert len(history) == 2 and history[0]['start'] == history[0]['end'] == expected
    assert history[0]['source_question'] == QUESTION
    assert history[1]['superseded_by'] == history[0]['id']


@pytest.mark.parametrize('text', [
    "It might be on October 27.", "I think it's on October 27.", "It isn't on October 27.",
    "It's not on October 27.", "It's on October 27 or 28.", "Is it on October 27?",
    "It's on October 27?", "It's on October 27, maybe.",
    "It's on 2026-10-27 through 2026-10-28.", "It's on next Monday.", "It's on Tuesday.",
    "It's on October 27 except if they change it.", "It's on October 27. I cannot attend.",
    "It's on October 27" + ' ' * 1300 + 'maybe', 'It is on 2026-02-30.',
])
def test_conversational_wrapper_cannot_hide_uncertainty_or_qualifiers(inquiry_answer, text):
    from services.mind.temporal_memory import answer_date_phrase
    source = linked_answer(inquiry_answer, text=text)
    _, _, temporal, _, _, known = inquiry_answer
    evidence = known()
    assert not answer_date_phrase(evidence[f'owner_episode:{source}'])
    assert not temporal.pending_corrections(evidence)
    with pytest.raises(ValueError):
        temporal.validate(temporal.resolve([revision(source, quote=text, phrase='')], evidence), evidence)
    assert len(temporal.history(SUBJECT)) == 1


@pytest.mark.parametrize('subject', [SUBJECT, 'October'])
def test_unlinked_conversational_date_cannot_revise_a_month_named_target(inquiry_answer, subject):
    text = "It's on October 27."
    _, episodes, temporal, _, _, known = inquiry_answer
    source = episodes.remember(text, question=QUESTION, now=NOW + timedelta(minutes=1))
    evidence = known()
    evidence['temporal:1']['subject'] = subject
    value = revision(source, quote=text, phrase='October 27').model_copy(update={'subject': subject})
    with pytest.raises(ValueError):
        temporal.validate(temporal.resolve([value], evidence), evidence)


def test_conversational_date_still_requires_the_entire_answer_quote(inquiry_answer):
    source = linked_answer(inquiry_answer, text="It's on October 27.")
    _, _, temporal, _, _, known = inquiry_answer
    with pytest.raises(ValueError):
        temporal.resolve([revision(source, quote='October 27', phrase='October 27')], known())


def test_legacy_episode_migration_preserves_original_data(tmp_path):
    store = Cognition(tmp_path / 'legacy.db')
    with store._connect() as db:
        db.execute('CREATE TABLE owner_episodes(id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT UNIQUE NOT NULL, '
                   'channel TEXT NOT NULL, question TEXT NOT NULL, text TEXT NOT NULL, noted TEXT NOT NULL)')
        db.execute('INSERT INTO owner_episodes(source_key,channel,question,text,noted) VALUES(?,?,?,?,?)',
                   ('legacy', 'chat', QUESTION, 'October 27', NOW.isoformat()))
    memory = BrainMemory(store)
    assert memory.evidence()['owner_episode:1']['question'] == QUESTION
    assert not memory.evidence()['owner_episode:1'].get('date_clarification')
    with memory._db() as db:
        assert 'inquiry_id' in {row[1] for row in db.execute('PRAGMA table_info(owner_episodes)')}


@pytest.mark.parametrize('refuse', [False, True])
@pytest.mark.parametrize('text', ['October 27', "It's on October 27."])
def test_real_executive_keeps_independent_critique_before_save(inquiry_answer, monkeypatch, refuse, text):
    from services.mind import reasoning, executive, cognition_context
    from services.mind.reasoning_store import ReasoningStore
    store, _, temporal, _, _, known = inquiry_answer
    source = linked_answer(inquiry_answer, text=text)
    memory = ReasoningStore(store)
    monkeypatch.setattr(memory, 'evidence', known)
    monkeypatch.setattr(reasoning, 'reasoning_store', memory)
    monkeypatch.setattr(reasoning, 'cognition', store)
    monkeypatch.setattr(cognition_context, 'live_state', lambda: {'activity': 'idle', 'away': False})
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle', 'away': False})
    control = executive.ExecutiveControl(store)
    monkeypatch.setattr(control, '_known', known)
    calls = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' in payload:
            value = {'checks': [{'id': 0, 'supported': not refuse, 'reason': 'Synthetic semantic judgment of the paired answer.'}]}
        else:
            update = revision(source, quote=text).model_dump(exclude={'start', 'end'})
            value = {'work_kind': 'situations', 'items': [update]}
        return ProviderResponse(content=json.dumps(value), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(control.review(NOW + timedelta(minutes=2)))
    assert result['status'] == ('unavailable' if refuse else 'completed')
    assert len(temporal.history(SUBJECT)) == (1 if refuse else 2)
    assert not memory.facts()
    if not refuse: assert len(calls) == 2
