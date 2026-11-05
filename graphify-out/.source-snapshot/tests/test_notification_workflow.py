"""Real facts -> brain decision -> durable reminder -> verified transport outcome."""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.config import config
from providers import failover
from services.memory import schedule
from services.mind import cognition_context, reminder_review
from services.mind.cognition import cognition
from services.reminders import service

REAL_REVIEW = reminder_review.review
REAL_RECHECK = reminder_review.recheck


@pytest.fixture
def workflow(monkeypatch):
    # This workflow concerns a class and reminder on the SAME day. Near midnight,
    # subtracting two minutes otherwise creates yesterday's reminder and today's
    # cancellation, which correctly do not match in production.
    fixed = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)
    import sys
    monkeypatch.setattr(sys.modules[__name__], "datetime", Clock)
    monkeypatch.setattr(service, "datetime", Clock)
    monkeypatch.setattr(service, "time", SimpleNamespace(time=lambda: fixed.timestamp()))
    from services.reminders import delivery_state
    monkeypatch.setattr(delivery_state, "time", SimpleNamespace(time=lambda: fixed.timestamp()))
    monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", True)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(reminder_review, "review", REAL_REVIEW)
    monkeypatch.setattr(reminder_review, "recheck", REAL_RECHECK)
    monkeypatch.setattr(cognition_context, "live_state", lambda: {"activity": "coding", "away": False,
                                                                "speaking": False, "listening": False})
    from services.telegram import client
    monkeypatch.setattr(client, "mirror_eligible", lambda: False)
    calls, notices = [], []

    async def decide(provider, messages, prompt, *args, **kwargs):
        assert kwargs["purpose"] == "notification_review"
        data = json.loads(messages[0].content)
        calls.append(data)
        return SimpleNamespace(content=json.dumps({"id": data["reminder"]["id"], "action": "send",
            "reason": "Owner requested a due reminder and current context permits it.", "evidence": ["live"],
            "allow_speech": False, "retry_after_seconds": 60}))

    monkeypatch.setattr(failover, "complete_with_failover", decide)
    monkeypatch.setattr(service, "show_toast", lambda *args, **kwargs: notices.append(args) or True)
    store = service.ReminderService()
    store.add_from_message("remind me in 1 minute to attend DBMS class", datetime.now() - timedelta(minutes=2))
    return SimpleNamespace(store=store, calls=calls, notices=notices, decide=decide)


def test_cancelled_class_reminder_is_retained_then_reviewed_after_fact_correction(workflow):
    schedule.capture("No classes today", datetime.now())
    asyncio.run(service.deliver_due(workflow.store))
    assert not workflow.notices and not workflow.calls
    assert len(workflow.store.pending()) == 1
    assert workflow.store.delivery_status()[0]["status"] == "withheld"
    assert "schedule" in str(workflow.store.delivery_status()[0]["evidence"])

    schedule.capture("Classes resume today", datetime.now() + timedelta(seconds=1))
    assert workflow.store.retry_failed() == 1
    asyncio.run(service.deliver_due(workflow.store))

    assert len(workflow.notices) == len(workflow.calls) == 1
    assert workflow.store.pending() == []
    assert workflow.store.delivery_status()[0]["status"] == "delivered"
    assert cognition.latest("notification_decision")["status"] == "submitted"


def test_fact_changed_during_model_review_blocks_even_a_send_approval(workflow, monkeypatch):
    async def changing(provider, messages, prompt, *args, **kwargs):
        result = await workflow.decide(provider, messages, prompt, *args, **kwargs)
        schedule.capture("No classes today", datetime.now())
        return result

    monkeypatch.setattr(failover, "complete_with_failover", changing)
    asyncio.run(service.deliver_due(workflow.store))

    assert workflow.calls and not workflow.notices
    assert len(workflow.store.pending()) == 1
    assert workflow.store.delivery_status()[0]["status"] == "withheld"


def test_internal_executive_bookkeeping_does_not_invalidate_reminder_approval(workflow, monkeypatch):
    phase = {"state": "running"}
    monkeypatch.setattr(cognition_context, "live_state", lambda: {"activity": "coding", "away": False,
        "speaking": False, "listening": False, "executive": {"last_review": phase["state"]}})
    async def completed_review(*args, **kwargs):
        result = await workflow.decide(*args, **kwargs)
        phase["state"] = "completed"
        return result
    monkeypatch.setattr(failover, "complete_with_failover", completed_review)
    asyncio.run(service.deliver_due(workflow.store))
    assert len(workflow.notices) == 1 and not workflow.store.pending()


def test_failed_delivery_must_pass_fresh_facts_before_retry(workflow, monkeypatch):
    attempts = []
    monkeypatch.setattr(service, "show_toast", lambda *args, **kwargs: attempts.append(args) or False)
    asyncio.run(service.deliver_due(workflow.store))
    assert len(attempts) == 1
    assert workflow.store.delivery_status()[0]["status"] == "retry"

    schedule.capture("No classes today", datetime.now())
    workflow.store.retry_failed()
    asyncio.run(service.deliver_due(workflow.store))

    assert len(attempts) == 1
    assert workflow.store.delivery_status()[0]["status"] == "withheld"
    assert len(workflow.store.pending()) == 1
