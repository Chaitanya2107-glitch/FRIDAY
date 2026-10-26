"""Durable reminder outcomes: transport failures must never consume owner intent."""

import asyncio
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.reminders import service as module


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    store = module.ReminderService(str(tmp_path / "reminders.db"))
    store.add_from_message("remind me in 1 minute to stretch", datetime.now() - timedelta(minutes=2))
    decision = SimpleNamespace(action="send", reason="Owner requested reminder", retry_after_seconds=30,
                               allow_speech=True, allow_telegram=False, evidence=[], decision_id="test",
                               fingerprint="test")
    async def review(*args):
        return decision
    gate = SimpleNamespace(review=review, recheck=review)
    import services.mind
    monkeypatch.setitem(sys.modules, "services.mind.reminder_review", gate)
    monkeypatch.setattr(services.mind, "reminder_review", gate, raising=False)
    calls = []
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: calls.append(a) or True)
    async def speak(*args):
        return None
    monkeypatch.setattr(module.tts, "speak", speak)
    return store, decision, calls


@pytest.mark.parametrize("accepted", [False, None])
def test_failed_or_unacknowledged_notification_retains_reminder(delivery, monkeypatch, accepted):
    store, _, _ = delivery
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: accepted)
    asyncio.run(module.deliver_due(store))
    assert len(store.pending()) == 1
    assert store.delivery_status()[0]["status"] == "retry"


def test_successful_notification_is_not_repeated_when_speech_fails(delivery, monkeypatch):
    store, _, calls = delivery
    async def broken_speech(*args):
        raise RuntimeError("voice unavailable")
    monkeypatch.setattr(module.tts, "speak", broken_speech)
    asyncio.run(module.deliver_due(store))
    asyncio.run(module.deliver_due(store))
    assert store.pending() == []
    assert len(calls) == 1
    assert store.delivery_status()[0]["speech_status"] == "failed"


@pytest.mark.parametrize("action", ["defer", "suppress", "unavailable"])
def test_brain_withholding_is_retained_and_not_sent(delivery, action):
    store, decision, calls = delivery
    decision.action = action
    asyncio.run(module.deliver_due(store))
    assert len(store.pending()) == 1
    assert calls == []
    assert store.delivery_status()[0]["status"] == {"defer": "deferred", "suppress": "withheld", "unavailable": "retry"}[action]


def test_claim_is_not_delivery_and_other_workers_cannot_claim_it(delivery):
    store, _, _ = delivery
    now = datetime.now().timestamp()
    assert len(store.take_due(now)) == 1
    assert len(store.pending()) == 1
    other = module.ReminderService(store.db_path)
    assert other.take_due(now) == []


def test_cancel_during_brain_review_prevents_notification(delivery):
    store, _, calls = delivery
    import services.mind.reminder_review as gate
    old = gate.review
    async def cancel(*args):
        store.cancel(1)
        return await old(*args)
    gate.review = cancel
    asyncio.run(module.deliver_due(store))
    assert calls == []


def test_reschedule_during_brain_review_prevents_notification(delivery):
    store, _, calls = delivery
    import services.mind.reminder_review as gate
    old = gate.review
    async def reschedule(reminder, now):
        with store._connect() as conn:
            conn.execute("UPDATE reminders SET due_at=due_at+3600 WHERE id=?", (reminder.id,))
        return await old(reminder, now)
    gate.review = reschedule
    asyncio.run(module.deliver_due(store))
    assert calls == []
    assert len(store.pending()) == 1


def retry_now(store):
    with store._connect() as conn:
        conn.execute("UPDATE reminder_delivery SET next_retry=0")


def test_failed_phone_retries_phone_without_duplicate_desktop(delivery, monkeypatch):
    from services.telegram import client
    store, decision, calls = delivery
    decision.allow_telegram = True
    phone = []
    monkeypatch.setattr(client, "mirror", lambda *a, **kw: phone.append(a) or len(phone) > 1)
    asyncio.run(module.deliver_due(store))
    assert len(store.pending()) == 1
    retry_now(store)
    asyncio.run(module.deliver_due(module.ReminderService(store.db_path)))
    assert len(calls) == 1 and len(phone) == 2
    assert store.pending() == []


def test_failed_desktop_does_not_block_phone_or_repeat_acknowledged_phone(delivery, monkeypatch):
    from services.telegram import client
    store, decision, calls = delivery
    decision.allow_telegram = True
    phone = []
    monkeypatch.setattr(client, "mirror", lambda *a, **kw: phone.append(a) or True)
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: False)
    asyncio.run(module.deliver_due(store))
    assert len(phone) == 1 and len(store.pending()) == 1
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: calls.append(a) or True)
    retry_now(store)
    asyncio.run(module.deliver_due(store))
    assert len(phone) == 1 and len(calls) == 1 and store.pending() == []


def test_review_crash_retries_without_using_transport_attempts(delivery):
    store, _, calls = delivery
    import services.mind.reminder_review as gate
    async def broken(*a):
        raise RuntimeError("brain unavailable")
    gate.review = broken
    asyncio.run(module.deliver_due(store))
    assert calls == []
    assert store.delivery_status()[0]["attempts"] == 0
    assert store.delivery_status()[0]["status"] == "retry"


def test_expired_review_claim_recovers_after_restart(delivery):
    store, _, calls = delivery
    store.take_due(datetime.now().timestamp())
    with store._connect() as conn:
        conn.execute("UPDATE reminder_delivery SET lease_until=0")
    asyncio.run(module.deliver_due(module.ReminderService(store.db_path)))
    assert len(calls) == 1 and store.pending() == []


def test_expired_transport_claim_requires_explicit_retry(delivery):
    store, _, calls = delivery
    claim = store._claim_due(datetime.now().timestamp())[0]
    store._state(claim, status="submitting", lease_until=0)
    asyncio.run(module.deliver_due(module.ReminderService(store.db_path)))
    assert calls == [] and len(store.pending()) == 1
    assert store.delivery_status()[0]["status"] == "uncertain"
    assert store.retry_failed() == 1
    asyncio.run(module.deliver_due(store))
    assert len(calls) == 1 and store.pending() == []


def test_automatic_retries_are_bounded_and_owner_can_retry(delivery, monkeypatch):
    store, _, calls = delivery
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: False)
    for _ in range(7):
        asyncio.run(module.deliver_due(store))
        retry_now(store)
    assert store.delivery_status()[0]["status"] == "failed"
    assert store.delivery_status()[0]["attempts"] == 5
    assert len(store.pending()) == 1
    assert store.retry_failed() == 1
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: calls.append(a) or True)
    asyncio.run(module.deliver_due(store))
    assert store.pending() == []


def test_cancel_during_phone_context_recheck_prevents_phone(delivery, monkeypatch):
    from services.telegram import client
    store, decision, calls = delivery
    decision.allow_telegram = True
    phone = []
    monkeypatch.setattr(client, "mirror", lambda *a, **kw: phone.append(a) or True)
    import services.mind.reminder_review as gate
    count = 0
    async def cancel(reminder, reviewed, now):
        nonlocal count
        count += 1
        if count == 2:
            store.cancel(1)
        return reviewed
    gate.recheck = cancel
    asyncio.run(module.deliver_due(store))
    assert len(calls) == 1 and phone == []


def test_feedback_crash_cannot_downgrade_successful_delivery(delivery, monkeypatch):
    from services import body_state
    store, _, _ = delivery
    def broken(*a):
        raise RuntimeError("feedback unavailable")
    monkeypatch.setattr(body_state, "push", broken)
    asyncio.run(module.deliver_due(store))
    assert store.pending() == []
    assert store.delivery_status()[0]["status"] == "delivered"


def test_stale_worker_cannot_acknowledge_rescheduled_intent(delivery):
    store, _, _ = delivery
    claim = store._claim_due(datetime.now().timestamp())[0]
    with store._connect() as conn:
        conn.execute("UPDATE reminders SET due_at=due_at+3600")
    assert not store._state(claim, desktop_status="submitted")
    assert not store._complete(claim)
    assert len(store.pending()) == 1


def test_concurrent_scheduler_ticks_submit_once(delivery):
    store, _, calls = delivery
    async def ticks():
        await asyncio.gather(module.deliver_due(store), module.deliver_due(module.ReminderService(store.db_path)))
    asyncio.run(ticks())
    assert len(calls) == 1 and store.pending() == []


def test_windows_timeout_is_uncertain_and_never_automatically_repeated(delivery, monkeypatch):
    store, _, _ = delivery
    def timed_out(*a, **kw):
        raise module.subprocess.TimeoutExpired("powershell", 20)
    monkeypatch.setattr(module.subprocess, "run", timed_out)
    monkeypatch.setattr(module, "_toast_app_id", lambda: "test")
    # The fixture replaces show_toast; restore the actual wrapper for this transport test.
    def actual_toast(title, body, buttons=None, **kw):
        return module._show_toast(title, body, buttons, **kw)
    monkeypatch.setattr(module, "show_toast", actual_toast)
    asyncio.run(module.deliver_due(store))
    assert len(store.pending()) == 1
    assert store.delivery_status()[0]["status"] == "uncertain"
    assert store.delivery_status()[0]["desktop_status"] == "uncertain"
    monkeypatch.setattr(module, "show_toast", lambda *a, **kw: pytest.fail("uncertain submission retried itself"))
    asyncio.run(module.deliver_due(store))


def test_status_ignores_obsolete_rescheduled_snapshot(delivery):
    store, _, _ = delivery
    store.take_due(datetime.now().timestamp())
    with store._connect() as conn:
        conn.execute("UPDATE reminders SET due_at=due_at+3600")
    assert store.delivery_status() == []


def test_status_does_not_create_missing_database(delivery, tmp_path):
    store, _, _ = delivery
    missing = tmp_path / "missing.db"
    store.db_path = str(missing)
    assert store.delivery_status() == []
    assert not missing.exists()


def test_context_deferral_cannot_turn_uncertain_submission_into_auto_retry(delivery, monkeypatch):
    store, decision, _ = delivery
    decision.allow_telegram = True
    monkeypatch.setattr(module, "_submit_desktop", lambda *a: (False, {"uncertain": True}))
    import services.mind.reminder_review as gate
    checks = 0
    async def changed(reminder, reviewed, now):
        nonlocal checks
        checks += 1
        if checks > 1:
            return SimpleNamespace(action="defer", reason="Context changed", retry_after_seconds=30,
                                   evidence=[], decision_id="test", fingerprint="changed", allow_speech=False,
                                   allow_telegram=False)
        return reviewed
    gate.recheck = changed
    asyncio.run(module.deliver_due(store))
    assert store.delivery_status()[0]["status"] == "uncertain"
    assert store.retry_failed() == 1
    assert store.delivery_status()[0]["desktop_status"] == "pending"


def test_phone_uncertainty_retains_desktop_ack_and_requires_owner_retry(delivery, monkeypatch):
    from services.telegram import client
    store, decision, calls = delivery
    decision.allow_telegram = True
    def ambiguous(*a, outcome=None):
        outcome['uncertain'] = True
        return False
    monkeypatch.setattr(client, "mirror", ambiguous)
    asyncio.run(module.deliver_due(store))
    row = store.delivery_status()[0]
    assert row["status"] == "uncertain" and row["telegram_status"] == "uncertain"
    assert row["desktop_status"] == "submitted"
    assert store.retry_failed() == 1
    monkeypatch.setattr(client, "mirror", lambda *a, **kw: True)
    asyncio.run(module.deliver_due(store))
    assert store.pending() == [] and len(calls) == 1
