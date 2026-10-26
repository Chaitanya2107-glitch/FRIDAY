import asyncio
import json
from datetime import datetime

import pytest

from services.automation import intent
from services.mind import evening, inquiry, talk

NOW = datetime(2026, 10, 20, 22, 5)


@pytest.fixture
def brain(monkeypatch):
    calls = []
    async def propose(now=None, **kwargs):
        calls.append(kwargs)
        return {'say': 'What is still blocking the project you mentioned?', 'basis': ['task:1']}
    monkeypatch.setattr(inquiry.inquiry, 'propose', propose)
    return calls


def test_no_hour_starts_a_scheduled_interview():
    assert not any(evening.due(NOW.replace(hour=hour), 10, False) for hour in range(24))


def test_explicit_day_review_asks_the_brain_once_without_a_queue(brain):
    first = asyncio.run(evening.start(None, NOW))
    assert first == 'What is still blocking the project you mentioned?'
    assert brain == [{'explicit': True, 'intention': 'day_review'}]
    assert evening.load()['total'] == 1 and evening.load()['queue'] == []
    assert talk.load()['pending']['question'] == first


def test_answer_is_retained_without_an_automatic_next_question(brain, monkeypatch):
    delivered = []
    async def deliver(text):
        delivered.append(text)
    monkeypatch.setattr(talk, 'deliver', deliver)
    async def run():
        await evening.start(None, NOW)
        assert talk.hear('I need the review notes from my teammate') == 'answered'
        await asyncio.sleep(.02)
    asyncio.run(run())
    rows = [json.loads(line) for line in evening.answers_path.read_text(encoding='utf-8').splitlines()]
    assert len(rows) == 1 and rows[0]['answer'] == 'I need the review notes from my teammate'
    assert delivered == [] and len(brain) == 1
    assert not evening.load()['active'] and evening.load()['queue'] == []


def test_stale_pre_upgrade_queue_and_callback_never_replay(brain):
    evening._save({'active': True, 'queue': [{'raw': {'ask': 'Old question?'}}], 'total': 7})
    assert asyncio.run(evening._ask_next()) is None
    asyncio.run(evening._carry_on(True))
    assert not brain and not evening.load()['active'] and not evening.load()['queue']


def test_explicit_learning_request_is_not_a_fixed_quota(brain):
    result = asyncio.run(intent.try_system_action('start learning session', 'openrouter'))
    assert result.success and result.message.endswith('?')
    assert brain == [{'explicit': True, 'intention': 'learning'}]
    assert evening.load()['extended'] and evening.load()['total'] == 1


def test_unavailable_brain_does_not_fall_back_to_seven_questions(monkeypatch):
    async def unavailable(*args, **kwargs):
        return None
    monkeypatch.setattr(inquiry.inquiry, 'propose', unavailable)
    assert asyncio.run(evening.start(None, NOW)) is None
    assert not evening.load()['active'] and not talk.load().get('pending')


def test_brush_off_stops_the_requested_question(brain):
    asyncio.run(evening.start(None, NOW))
    assert talk.hear("that's all friday") == 'shushed'
    assert not evening.load()['active'] and not evening.load()['queue']
