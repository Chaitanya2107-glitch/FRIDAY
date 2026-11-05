"""Race and shutdown controls for ordinary-chat clarification intake."""
import asyncio
import json
from datetime import timedelta

import pytest

from test_dialogue_followups import conversation, say, NOW
from core.config import config
from services.mind.cognition import cognition


def test_concurrent_date_answer_cannot_replace_the_claimed_answer(conversation, monkeypatch):
    from services.automation import intent
    from providers import failover
    original = failover.complete_with_failover
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def pause(*args, **kwargs):
            if 'pending_temporal_corrections' in json.loads(args[1][0].content):
                started.set()
                await release.wait()
            return await original(*args, **kwargs)
        monkeypatch.setattr(failover, 'complete_with_failover', pause)
        await intent.try_system_action('My exam was postponed', 'openrouter')
        active = asyncio.create_task(intent.try_system_action('Robotics, November 3', 'openrouter'))
        await asyncio.wait_for(started.wait(), 5)
        second = await intent.try_system_action('Maths, December 4', 'openrouter')
        assert second is not None and not second.success
        release.set()
        assert (await asyncio.wait_for(active, 5)).success
    asyncio.run(scenario())
    assert len(conversation[2].history('robotics exam')) == 2
    assert len(conversation[2].history('maths exam')) == 1


def test_disabled_memory_cannot_create_a_new_question_or_source(conversation, monkeypatch):
    dialogue, episodes, _, calls = conversation
    with episodes._db() as db:
        before = db.execute('SELECT COUNT(*) FROM owner_episodes').fetchone()[0]
    monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    assert not say('My exam was postponed').success
    assert not dialogue.awaiting() and calls == []
    with episodes._db() as db:
        assert db.execute('SELECT COUNT(*) FROM owner_episodes').fetchone()[0] == before


def test_history_clear_retires_the_question_and_derived_state(conversation):
    from interfaces.api.routes import chat
    say('My exam was postponed')
    assert conversation[0].awaiting()
    asyncio.run(chat.clear_history())
    assert not conversation[0].awaiting()
    assert conversation[1].evidence() == {} and conversation[2].history('robotics exam') == []


def test_automation_early_route_retires_the_chat_question(conversation, monkeypatch):
    from interfaces.api.routes import chat
    from services.browser.service import automation
    from types import SimpleNamespace
    async def answer(*args):
        return SimpleNamespace(message='Synthetic automation response', success=False, awaiting_reply=False)
    monkeypatch.setattr(automation, 'handle', answer)
    say('My exam was postponed')
    result = asyncio.run(chat.chat(chat.ChatRequest(message=r'\b research robot sensors')))
    assert result.model == 'automation_task' and not conversation[0].awaiting()
    assert len(conversation[2].history('robotics exam')) == 1


def test_cancel_after_committing_cannot_claim_to_undo_the_saved_date(conversation):
    dialogue = conversation[0]
    say('My exam was postponed')
    # Preserve the parsed cancel reference to simulate a save winning the race.
    prepared = dialogue.match_turn('Robotics, November 3')
    ident = dialogue.prepare(prepared)
    cancellation = dialogue.match_turn('never mind')
    from services.mind.dialogue_review import review
    asyncio.run(review(dialogue, ident))
    result = asyncio.run(dialogue.run(cancellation))
    assert not result.success and 'already saved' in result.message
    assert len(conversation[2].history('robotics exam')) == 2


def test_date_after_midnight_uses_the_answer_receipt_calendar(conversation, monkeypatch):
    from services.mind import dialogue
    question_time = NOW.replace(hour=23, minute=58)
    monkeypatch.setattr(dialogue, 'clock', lambda: question_time)
    say('My robotics exam was postponed')
    monkeypatch.setattr(dialogue, 'clock', lambda: question_time + timedelta(minutes=4))
    assert say('tomorrow').success
    assert conversation[2].history('robotics exam')[0]['start'] == '2026-10-24'


def test_unoffered_initial_ordinal_never_selects_by_recency(conversation):
    result = say('My first was postponed')
    assert result is None or not result.success
    assert not conversation[0].awaiting()
