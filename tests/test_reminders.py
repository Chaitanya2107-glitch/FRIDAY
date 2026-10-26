import asyncio
from datetime import datetime, timedelta

import pytest

from services.automation import intent
from services.automation.intent import ActionResult, try_system_action
from services.reminders import service as reminder_service
from services.reminders.parser import ReminderParseError, describe_due, is_reminder_request, parse_reminder
from services.reminders.service import ReminderError, ReminderService

NOW = datetime(2026, 9, 14, 14, 0)  # Monday, 2:00 PM


def at(hour, minute=0, days=0):
    return (NOW + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)


# ── Parsing ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, task, due", [
    ("remind me in 10 minutes to stretch", "stretch", NOW + timedelta(minutes=10)),
    ("Remind me to call mom at 5pm.", "call mom", at(17)),
    ("remind me at 5:30 p.m. to submit the report", "submit the report", at(17, 30)),
    ("remind me at 17:45 to leave for the gym", "leave for the gym", at(17, 45)),
    ("remind me at 9am to email Bob", "email Bob", at(9, days=1)),
    ("remind me tomorrow at 9am to email Bob", "email Bob", at(9, days=1)),
    ("remind me at 3 to pick up the kids", "pick up the kids", at(15)),
    ("remind me in an hour to drink water", "drink water", NOW + timedelta(hours=1)),
    ("remind me in half an hour to check the oven", "check the oven", NOW + timedelta(minutes=30)),
    ("remind me about the standup in 2 hours", "the standup", NOW + timedelta(hours=2)),
    ("remind me to look at the oven in 5 mins", "look at the oven", NOW + timedelta(minutes=5)),
])
def test_parse_reminder(message, task, due):
    assert parse_reminder(message, NOW) == (task, due)


@pytest.mark.parametrize("message, error", [
    ("remind me to call mom", "When should I remind you"),
    ("remind me in 10 minutes", "What should I remind you about"),
    ("remind me at 25:00 to sleep", "doesn't look right"),
    ("remind me at 13pm to eat", "doesn't look right"),
    ("remind me in 0 minutes to blink", "future"),
])
def test_parse_reminder_errors(message, error):
    with pytest.raises(ReminderParseError, match=error):
        parse_reminder(message, NOW)


@pytest.mark.parametrize("message, expected", [
    ("remind me in 10 minutes to stretch", True),
    ("remind me to call mom", True),
    ("Remind me tomorrow to call the bank", True),
    ("remind me what the capital of France is", False),
    ("can you remind me later", False),
    ("reminders", False),
])
def test_is_reminder_request(message, expected):
    assert is_reminder_request(message) is expected


def test_describe_due():
    assert describe_due(at(17), NOW) == "5:00 PM today"
    assert describe_due(at(9, days=1), NOW) == "9:00 AM tomorrow"
    assert describe_due(at(9, days=3), NOW) == "9:00 AM on Thu 17 Sep"


# ── Storage ───────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return ReminderService(str(tmp_path / "friday.db"))


def test_add_and_list_in_due_order(store):
    assert store.add_from_message("remind me at 5pm to call mom", NOW) == "Okay, I'll remind you at 5:00 PM today: call mom."
    store.add_from_message("remind me in 10 minutes to stretch", NOW)
    assert store.list_message(NOW) == "Your reminders:\n1. stretch — 2:10 PM today\n2. call mom — 5:00 PM today"


def test_parse_problems_become_reminder_errors(store):
    with pytest.raises(ReminderError, match="When should I remind you"):
        store.add_from_message("remind me to call mom", NOW)
    assert store.pending() == []


def test_cancel_by_number(store):
    store.add_from_message("remind me at 5pm to call mom", NOW)
    store.add_from_message("remind me in 10 minutes to stretch", NOW)

    assert store.cancel(1) == "Cancelled reminder 1: stretch."
    assert [r.text for r in store.pending()] == ["call mom"]
    with pytest.raises(ReminderError, match="no reminder 5"):
        store.cancel(5)


def test_cancel_all(store):
    assert store.cancel_all() == "You don't have any reminders."
    store.add_from_message("remind me at 5pm to call mom", NOW)
    store.add_from_message("remind me in 10 minutes to stretch", NOW)

    assert store.cancel_all() == "Cancelled 2 reminders."
    assert store.list_message(NOW) == "You don't have any reminders."


def test_due_reminders_are_claimed_without_false_delivery(store):
    store.add_from_message("remind me in 10 minutes to stretch", NOW)
    store.add_from_message("remind me at 5pm to call mom", NOW)
    later = (NOW + timedelta(minutes=11)).timestamp()

    assert [r.text for r in store.take_due(later)] == ["stretch"]
    assert store.take_due(later) == []
    assert [r.text for r in store.pending()] == ["stretch", "call mom"]


def test_reminders_survive_a_restart(tmp_path):
    db = str(tmp_path / "friday.db")
    ReminderService(db).add_from_message("remind me at 5pm to call mom", NOW)
    assert [r.text for r in ReminderService(db).pending()] == ["call mom"]


# ── Delivery ──────────────────────────────────────────────────────────────────

@pytest.fixture
def delivered(monkeypatch):
    record = {"toasts": [], "spoken": []}
    monkeypatch.setattr(reminder_service, "show_toast",
                        lambda title, body, buttons=None, **kw: record["toasts"].append((title, body)) or True)

    async def speak(text):
        record["spoken"].append(text)
    monkeypatch.setattr(reminder_service.tts, "speak", speak)
    return record


def test_due_reminder_is_shown_and_spoken(store, delivered):
    store.add_from_message("remind me in 1 minute to stretch", datetime.now() - timedelta(minutes=2))

    asyncio.run(reminder_service.deliver_due(store))

    assert delivered["toasts"] == [("F.R.I.D.A.Y reminder", "stretch")]
    assert delivered["spoken"] == ["Reminder: stretch"]
    assert store.pending() == []


def test_reminder_missed_while_off_is_marked_late(store, delivered):
    store.add_from_message("remind me in 10 minutes to stretch", datetime.now() - timedelta(hours=1))

    asyncio.run(reminder_service.deliver_due(store))

    assert delivered["toasts"][0][1].startswith("stretch (was due ")


def test_one_failed_delivery_does_not_block_the_rest(store, monkeypatch, delivered):
    def toast(title, body, buttons=None, **kw):
        if body.startswith("first"):
            raise RuntimeError("notification broke")
        delivered["toasts"].append(body)
        return True
    monkeypatch.setattr(reminder_service, "show_toast", toast)
    past = datetime.now() - timedelta(minutes=10)
    store.add_from_message("remind me in 1 minute to first", past)
    store.add_from_message("remind me in 2 minutes to second", past)

    asyncio.run(reminder_service.deliver_due(store))

    assert delivered["toasts"][0].startswith("second")
    assert [r.text for r in store.pending()] == ["first"]


# ── Chat / voice commands ─────────────────────────────────────────────────────

@pytest.fixture
def intent_store(store, monkeypatch):
    monkeypatch.setattr(intent, "reminders", store)
    monkeypatch.setattr(intent, "get_provider", lambda name: pytest.fail("no AI call expected"))
    return store


def ask(message):
    return asyncio.run(try_system_action(message, "openrouter"))


def test_commands_set_list_and_cancel_reminders(intent_store):
    set_result = ask("Remind me in 20 minutes to stretch.")
    assert set_result.success and set_result.message.startswith("Okay, I'll remind you at ")

    assert ask("list reminders").message.startswith("Your reminders:\n1. stretch — ")
    assert ask("what are my reminders").message.startswith("Your reminders:")
    assert ask("cancel reminder 1") == ActionResult(True, "Cancelled reminder 1: stretch.")
    assert ask("show my reminders") == ActionResult(True, "You don't have any reminders.")


def test_clear_reminders(intent_store):
    ask("remind me at 5pm to call mom")
    assert ask("clear reminders") == ActionResult(True, "Cancelled 1 reminder.")


def test_reminder_without_time_asks_when(intent_store):
    result = ask("remind me to call mom")
    assert result.success is False and "When should I remind you" in result.message


@pytest.mark.parametrize("message", ["remind me what the capital of France is", "delete reminder"])
def test_other_messages_are_left_to_chat(intent_store, message):
    assert ask(message) is None


def test_transient_toasts_expire_and_skip_the_phone(monkeypatch):
    from services.reminders import service
    from services.telegram import client as telegram
    runs, mirrored = [], []
    monkeypatch.setattr(service.subprocess, "run", lambda args, **kw: runs.append(kw["env"]) or
                        type("R", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(telegram, "mirror", lambda *a: mirrored.append(a))
    service.show_toast("F.R.I.D.A.Y", "Opening Chrome.", transient=True)
    service.show_toast("F.R.I.D.A.Y", "Reminder: call mom")
    assert runs[0]["FRIDAY_TOAST_EXPIRE"] == str(service.TRANSIENT_SECONDS) and runs[1]["FRIDAY_TOAST_EXPIRE"] == "0"
    assert len(mirrored) == 1  # only the one that stays goes to the phone
