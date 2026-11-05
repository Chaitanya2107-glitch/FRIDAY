import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.config import config
from providers import failover
from services.mind import reminder_review
from services.mind.cognition import cognition
from services.reminders.service import Reminder

REAL_REVIEW = reminder_review.review
REAL_RECHECK = reminder_review.recheck
NOW = datetime(2026, 10, 16, 11)


@pytest.fixture
def brain(monkeypatch):
    monkeypatch.setattr(reminder_review, "review", REAL_REVIEW)
    monkeypatch.setattr(reminder_review, "recheck", REAL_RECHECK)
    monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", True)
    snapshot = {"date": NOW.date().isoformat(), "dated_facts": [], "remembered_facts": [],
                "live": {"activity": "coding", "away": False}, "busy": False,
                "telegram_eligible": False, "workspace": {}, "recent_outcomes": []}
    async def read(*args):
        return json.loads(json.dumps(snapshot))
    monkeypatch.setattr(reminder_review, "_snapshot", read)
    async def decide(provider, messages, prompt, *args, **kwargs):
        assert kwargs["purpose"] == "notification_review"
        data = json.loads(messages[0].content)
        return SimpleNamespace(content=json.dumps({"id": data["reminder"]["id"], "action": "send",
             "reason": "Explicit reminder is due and the user is available.", "evidence": ["live"],
             "retry_after_seconds": 60, "allow_speech": True}))
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    return snapshot


def test_due_reminder_requires_brain_review_even_in_assistance_mode(brain, monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    result = asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW))
    assert result.action == "send" and result.allow_speech
    assert cognition.latest("notification_decision")["public"] == 0


@pytest.mark.parametrize("content", ["not JSON", '{"id":"wrong","action":"send"}',
    '{"id":"7","action":"send","reason":"Fine","evidence":["invented"],"allow_speech":true,"retry_after_seconds":60}',
    '{"id":"7","action":"suppress","reason":"Ignore it","evidence":["live"],"allow_speech":false,"retry_after_seconds":60}'])
def test_invalid_or_unsubstantiated_decision_is_recoverably_unavailable(brain, monkeypatch, content):
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=content)
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    result = asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW))
    assert result.action == "unavailable" and result.retry_after_seconds > 0


def test_new_facts_invalidate_approval_before_transport(brain):
    reminder = Reminder(7, "Attend DBMS class", NOW.timestamp())
    approved = asyncio.run(reminder_review.review(reminder, NOW))
    brain["dated_facts"] = [{"id": "schedule:1", "fact": "No classes today", "from": "2026-10-16",
                            "through": "2026-10-16", "classes_available": False, "subject": "all regular classes"}]
    result = asyncio.run(reminder_review.recheck(reminder, approved, NOW))
    assert result.action == "suppress" and result.evidence


@pytest.mark.parametrize("text", ["Finish class homework", "Submit DBMS assignment", "Review Python class implementation",
                                  "Attend meeting about class structure", "Join class-action meeting"])
def test_cancelled_classes_do_not_cancel_homework_or_programming(brain, text):
    brain["dated_facts"] = [{"id": "schedule:1", "fact": "No classes today", "from": "2026-10-16",
                            "through": "2026-10-16", "classes_available": False, "subject": "all regular classes"}]
    assert asyncio.run(reminder_review.review(Reminder(7, text, NOW.timestamp()), NOW)).action == "send"


def test_busy_state_defers_and_prevents_speech_without_model(brain, monkeypatch):
    brain["busy"] = True
    async def forbidden(*args, **kwargs):
        pytest.fail("Busy policy does not need a model")
    monkeypatch.setattr(failover, "complete_with_failover", forbidden)
    result = asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW))
    assert result.action == "defer" and not result.allow_speech


def test_changed_context_cannot_reuse_model_approval(brain):
    reminder = Reminder(7, "Drink water", NOW.timestamp())
    approved = asyncio.run(reminder_review.review(reminder, NOW))
    brain["workspace"] = {"tasks": [{"id": 1, "title": "Interview", "status": "active"}]}
    assert asyncio.run(reminder_review.recheck(reminder, approved, NOW)).action == "defer"


def test_unknown_context_or_provider_failure_never_autoapproves(brain, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("SENTINEL_PROVIDER_SECRET")
    monkeypatch.setattr(failover, "complete_with_failover", unavailable)
    result = asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW))
    assert result.action == "unavailable"
    assert "SENTINEL_PROVIDER_SECRET" not in str(cognition.recent())


def test_today_cancellation_cannot_cancel_yesterdays_class_reminder(brain):
    brain["dated_facts"] = [{"id": "schedule:1", "fact": "No classes today", "from": "2026-10-16",
                            "through": "2026-10-16", "classes_available": False, "subject": "all regular classes"}]
    reminder = Reminder(7, "Attend DBMS class", datetime(2026, 10, 15, 11).timestamp())
    assert asyncio.run(reminder_review.review(reminder, NOW)).action == "send"


def test_partial_provider_response_is_not_a_brain_decision(brain, monkeypatch):
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"id": "7", "action": "send", "reason": "Available",
            "evidence": ["live"], "retry_after_seconds": 60, "allow_speech": True}), metadata={"incomplete": True})
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    assert asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW)).action == "unavailable"


def test_newer_resumption_wins_over_older_cancellation(brain):
    brain["dated_facts"] = [
        {"id": "schedule:2", "fact": "Classes resumed", "from": "2026-10-16", "through": "2026-10-20",
         "classes_available": True, "subject": "all regular classes"},
        {"id": "schedule:1", "fact": "No classes", "from": "2026-10-16", "through": "2026-10-20",
         "classes_available": False, "subject": "all regular classes"}]
    assert asyncio.run(reminder_review.review(Reminder(7, "Attend DBMS class", NOW.timestamp()), NOW)).action == "send"


def test_disabled_brain_retains_explicit_reminder(brain, monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", False)
    result = asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW))
    assert result.action == "unavailable" and not result.allow_speech


def test_real_snapshot_is_stable_across_its_own_decision(monkeypatch):
    from services.mind import cognition_context
    from services.telegram import client
    monkeypatch.setattr(reminder_review, "review", REAL_REVIEW)
    monkeypatch.setattr(reminder_review, "recheck", REAL_RECHECK)
    monkeypatch.setattr(cognition_context, "live_state", lambda: {"activity": "coding", "away": False,
        "thinking": bool(cognition.recent()), "active_operations": []})
    monkeypatch.setattr(client, "mirror_eligible", lambda: False)
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"id": "7", "action": "send", "reason": "User available",
            "evidence": ["live"], "retry_after_seconds": 60, "allow_speech": True}))
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    reminder = Reminder(7, "Drink water", NOW.timestamp())
    result = asyncio.run(reminder_review.review(reminder, NOW))
    assert result.action == "send"
    assert asyncio.run(reminder_review.recheck(reminder, result, NOW)).action == "send"


@pytest.mark.parametrize("source, expected", [("learned", "unavailable"), ("told", "suppress")])
def test_learned_guess_cannot_cancel_explicit_reminder(brain, monkeypatch, source, expected):
    brain["remembered_facts"] = [{"id": 1, "text": "The interview is cancelled", "source": source,
                                  "created_at": NOW.isoformat(), "happens_on": "2026-10-16"}]
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"id": "7", "action": "suppress", "reason": "Interview cancelled",
            "evidence": ["memory:1"], "retry_after_seconds": 60, "allow_speech": False}))
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    assert asyncio.run(reminder_review.review(Reminder(7, "Join interview", NOW.timestamp()), NOW)).action == expected


def test_model_cannot_repurpose_class_cancellation_to_cancel_homework(brain, monkeypatch):
    brain["dated_facts"] = [{"id": "schedule:1", "fact": "No classes today", "from": "2026-10-16",
                            "through": "2026-10-16", "classes_available": False, "subject": "all regular classes"}]
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"id": "7", "action": "suppress", "reason": "No classes",
            "evidence": ["dated:schedule:1"], "retry_after_seconds": 60, "allow_speech": False}))
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    assert asyncio.run(reminder_review.review(Reminder(7, "Submit class homework", NOW.timestamp()), NOW)).action == "unavailable"


def test_old_dated_memory_cannot_suppress_new_event(brain, monkeypatch):
    brain["remembered_facts"] = [{"id": 1, "text": "Interview cancelled", "source": "told",
                                  "created_at": "2026-10-10T11:00:00", "happens_on": "2026-10-10"}]
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"id": "7", "action": "suppress", "reason": "Interview cancelled",
            "evidence": ["memory:1"], "retry_after_seconds": 60, "allow_speech": False}))
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    assert asyncio.run(reminder_review.review(Reminder(7, "Join interview", NOW.timestamp()), NOW)).action == "unavailable"


def test_provider_contract_constrains_ids_and_leaves_time_for_fallback(brain, monkeypatch):
    async def decide(*args, **kwargs):
        schema = kwargs["response_schema"]
        assert schema["properties"]["id"]["enum"] == ["7"]
        assert "live" in schema["properties"]["evidence"]["items"]["enum"]
        assert 0 < kwargs["attempt_timeout"] < config.NOTIFICATION_REVIEW_TIMEOUT_SECONDS
        return SimpleNamespace(content=json.dumps({"id": "7", "action": "send", "reason": "User available",
            "evidence": ["live"], "retry_after_seconds": 60, "allow_speech": False}))

    monkeypatch.setattr(failover, "complete_with_failover", decide)
    assert asyncio.run(reminder_review.review(Reminder(7, "Drink water", NOW.timestamp()), NOW)).action == "send"

