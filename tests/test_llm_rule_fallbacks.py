"""The local command path stays useful with the model disabled."""
import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.automation import intent
from services.mind import date_rules, dialogue, language
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import cognition
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
from services.proactive import deadlines

NOW = datetime(2026, 11, 18, 15)


@pytest.fixture
def offline(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    async def forbidden(*args, **kwargs):
        pytest.fail('The offline rule reached model transport')

    monkeypatch.setattr(config, 'FRIDAY_LLM', 'off', raising=False)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(date_rules, 'clock', lambda: NOW)
    monkeypatch.setattr(dialogue, 'clock', lambda: NOW)
    monkeypatch.setattr(deadlines, 'datetime', Clock)
    monkeypatch.setattr('providers.failover.complete_with_failover', forbidden)
    return NOW


def say(text):
    return asyncio.run(intent.try_system_action(text, 'ollama'))


def save_exams(*names):
    deadlines._save([{'id': str(i), 'revision': 'original', 'what': f'{name} exam',
                      'due': '2026-11-20T09:30', 'kind': 'exam', 'alerted': []}
                     for i, name in enumerate(names, 1)])


def test_single_saved_exam_moves_after_confirmation_and_preserves_its_time(offline):
    save_exams('Robotics')
    proposal = say('My exam moved to Monday')
    assert intent.is_awaiting_confirmation() and 'Robotics exam' in proposal.message and '2026-11-23 at 09:30 AM' in proposal.message
    assert deadlines.load()[0]['due'] == '2026-11-20T09:30'
    reply = say('yes')
    assert reply.success and '2026-11-23T09:30' in reply.message
    saved, = deadlines.load()
    assert saved['due'] == '2026-11-23T09:30'
    assert saved['history'][0]['quote'] == 'My exam moved to Monday'


def test_ambiguous_exam_asks_once_then_shows_the_exact_date_without_editing(offline):
    save_exams('Robotics', 'Maths')
    question = say('My exam moved to Monday')
    assert 'Which saved commitment moved?' in question.message
    assert 'Robotics exam' in question.message and 'Maths exam' in question.message
    assert not intent.is_awaiting_confirmation()
    assert 'Maths exam as 2026-11-23' in say('Maths').message
    assert say('no').success
    assert {row['due'] for row in deadlines.load()} == {'2026-11-20T09:30'}


def test_ambiguous_weekday_is_never_inferred(offline):
    save_exams('Robotics')
    assert say('My exam moved to Wednesday').message == 'What is the exact new date for Robotics exam?'
    assert not intent.is_awaiting_confirmation()
    assert '2026-11-25' in say('2026-11-25').message
    assert say('yes').success
    assert deadlines.load()[0]['due'] == '2026-11-25T09:30'


def test_stale_exam_proposal_cannot_overwrite_a_newer_schedule(offline):
    save_exams('Robotics')
    assert say('My exam moved to Monday').success
    rows = deadlines.load()
    rows[0].update(revision='changed', due='2026-11-24T11:30')
    deadlines._save(rows)
    assert not say('yes').success
    assert deadlines.load()[0]['due'] == '2026-11-24T11:30'


def test_offline_dialogue_reuses_selected_commitment_and_requires_yes(offline):
    memory, episodes = TemporalMemory(cognition), BrainMemory(cognition)
    noted = NOW - timedelta(days=1)
    quote = 'My robotics exam is on Friday'
    episode = f'owner_episode:{episodes.remember(quote, now=noted)}'
    original = TemporalUpdate(source=episode, quote=quote, subject='robotics exam', status='planned',
                              date_phrase='Friday', start=None, end=None, supersedes=[])
    known = episodes.evidence()
    with memory._db() as db:
        memory.save(db, memory.resolve([original], known), noted, known)
    question = say('My robotics exam was postponed')
    assert 'new date' in question.message
    proposal = say('Monday')
    assert '2026-11-23' in proposal.message and intent.is_awaiting_confirmation()
    assert len(memory.history('robotics exam')) == 1
    assert say('yes').success
    newest, previous = memory.history('robotics exam')
    assert newest['start'] == '2026-11-23' and newest['quote'] == 'Monday'
    assert previous['superseded_by'] == newest['id']


def test_local_conversation_replies_to_greetings_and_shows_retrieved_excerpts(offline):
    hello = asyncio.run(language.answer('hello', 'ollama', [], 100))
    assert hello.provider == 'local' and "I'm here, Boss." in hello.content
    found = asyncio.run(language.answer('summarize', 'ollama', [], 100, 'Exact saved excerpt'))
    assert found.provider == 'local' and 'Exact saved excerpt' in found.content
