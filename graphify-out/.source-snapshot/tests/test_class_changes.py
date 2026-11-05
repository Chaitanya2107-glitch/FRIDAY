import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.automation import intent
from services.proactive import attendance, timetable
from services.reminders.service import ReminderService
from services.mind.reminder_review import review as REAL_REVIEW, recheck as REAL_RECHECK

NOW = datetime(2026, 10, 13, 8)  # Tuesday; tomorrow is Wednesday


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


@pytest.fixture
def local(monkeypatch):
    from services.proactive import class_changes

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(class_changes, "datetime", Clock)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    timetable._save([{"day": "wednesday", "start": "09:00", "end": "10:00", "subject": "DBMS", "room": "204"}])
    service = ReminderService()
    service.add_from_message("remind me tomorrow at 8am to take my class notes", NOW)
    return service


def test_dated_move_preserves_weekly_template_history_and_duration(local):
    original = timetable.load()
    result = say("tomorrow's DBMS class moved from 9 AM to 11 AM")
    assert result.success, result.message
    effective = timetable.classes_for_date((NOW + timedelta(days=1)).date())
    assert [(c["start"], c["end"]) for c in effective] == [("11:00", "12:00")]
    assert timetable.load() == original
    assert timetable.classes_for_date((NOW + timedelta(days=8)).date()) == original
    assert "11:00" in say("when is tomorrow's DBMS class").message
    history = say("show class history for tomorrow's DBMS").message
    assert "09:00" in history and "11:00" in history


def test_warnings_next_class_and_attendance_follow_new_time(local):
    say("tomorrow's DBMS class moved from 9 AM to 11 AM")
    tomorrow = NOW + timedelta(days=1)
    assert timetable.due_warnings(tomorrow.replace(hour=8, minute=55)) == []
    assert "11:00 am" in timetable.next_class(tomorrow.replace(hour=10))
    assert timetable.due_warnings(tomorrow.replace(hour=10, minute=55))
    assert attendance.due_asks(tomorrow.replace(hour=10, minute=10)) == []
    asks = attendance.due_asks(tomorrow.replace(hour=12, minute=10))
    assert len(asks) == 1 and asks[0]["start"] == "11:00"
    assert "no attendance" in attendance.answer({"date": "2026-10-14", "subject": "DBMS", "start": "09:00"}, "yes")
    assert attendance.load()["records"] == []
    assert "Marked" in attendance.answer(asks[0], "yes")


def test_linked_reminders_wait_for_approval(local):
    before = local.pending()[0]
    assert say("link reminder 1 to tomorrow's DBMS class").success
    result = say("tomorrow's DBMS class moved from 9 AM to 11 AM")
    assert result.success and "apply class reminder updates" in result.message
    assert local.pending()[0] == before
    assert say("review class reminder updates for tomorrow's DBMS").success
    applied = say("apply class reminder updates for tomorrow's DBMS")
    assert applied.success, applied.message
    assert local.pending()[0].due_at == before.due_at + 7200
    assert not say("apply class reminder updates for tomorrow's DBMS").success


def test_wrong_old_time_and_past_target_do_not_change_schedule(local):
    assert not say("tomorrow's DBMS class moved from 10 AM to 11 AM").success
    assert not say("tomorrow's DBMS class moved to 11 PM").success  # duration would cross midnight
    assert timetable.classes_for_date((NOW + timedelta(days=1)).date())[0]["start"] == "09:00"


def cancel_class():
    from services.memory.semantic import semantic_memory
    with semantic_memory._connect() as db:
        db.execute("INSERT INTO memories (text,vector,source,created_at) VALUES (?,?,'told',?)",
                   ("no classes tomorrow", b"\0" * 16, NOW.isoformat()))
    semantic_memory._cache = None


def test_cancelled_class_cannot_be_resumed_by_a_time_change(local):
    cancel_class()
    reply = say("tomorrow's DBMS class moved to 11 AM")
    assert not reply.success and "cancelled" in reply.message
    assert timetable.classes_for_date((NOW + timedelta(days=1)).date()) == []


def test_later_cancellation_wins_over_saved_shift_and_pending_reminders(local, monkeypatch):
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    cancel_class()
    before = local.pending()[0]
    assert not say("apply class reminder updates for tomorrow's DBMS").success
    assert local.pending()[0] == before
    assert "cancelled" in say("when is tomorrow's DBMS class").message
    result = asyncio.run(REAL_REVIEW(before, NOW))
    assert result.action == "suppress" and "cancelled" in result.reason


def test_ambiguous_occurrences_wait_for_explicit_choice(local):
    timetable._save(timetable.load() + [{"day": "wednesday", "start": "13:00", "end": "14:00", "subject": "DBMS", "room": "205"}])
    from services.proactive import class_sessions
    reply = say("tomorrow's DBMS class moved to 11 AM")
    assert not reply.success and "Which class" in reply.message
    assert class_sessions.load() == []
    assert not say("the fifth one").success
    assert say("the first one").success
    assert [c["start"] for c in timetable.classes_for_date((NOW + timedelta(days=1)).date())] == ["11:00", "13:00"]


def test_subject_alias_and_explicit_clock_choose_one_occurrence(local):
    timetable._save_subjects(["Database Management Systems"])
    timetable._save(timetable.load() + [{"day": "wednesday", "start": "13:00", "end": "14:00", "subject": "DBMS", "room": None}])
    result = say("move tomorrow's Database Management Systems at 9 AM class to 11 AM")
    assert result.success, result.message
    assert [c["start"] for c in timetable.classes_for_date((NOW + timedelta(days=1)).date())] == ["11:00", "13:00"]


def test_stale_choice_and_channel_isolation(local):
    from services.proactive import class_changes
    timetable._save(timetable.load() * 2)
    say("tomorrow's DBMS class moved to 11 AM")
    parsed = class_changes.match_turn("the first one")
    token = intent.remote_request.set(True)
    try:
        assert say("the first one") is None
    finally:
        intent.remote_request.reset(token)
    timetable._save([{**timetable.load()[0], "room": "new room"}])
    assert not class_changes.run(parsed).success


def test_expired_or_retired_choice_does_not_guess(local, monkeypatch):
    from services.mind import reference_context, conversation_context
    timetable._save(timetable.load() * 2)
    say("tomorrow's DBMS class moved to 11 AM")
    conversation_context.observe("what's the weather")
    assert say("the first one") is None
    say("tomorrow's DBMS class moved to 11 AM")
    now = reference_context.time.time()
    monkeypatch.setattr(reference_context.time, "time", lambda: now + reference_context.TTL_SECONDS + 1)
    assert say("the first one") is None


def test_pending_shift_uses_real_review_and_recheck_without_model(local, monkeypatch):
    from providers import failover
    from services.mind.reminder_review import Review
    async def forbidden(*a, **kw):
        pytest.fail("Pending class shift should not need model review")
    monkeypatch.setattr(failover, "complete_with_failover", forbidden)
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    reminder = local.pending()[0]
    assert asyncio.run(REAL_REVIEW(reminder, NOW)).action == "defer"
    assert asyncio.run(REAL_RECHECK(reminder, Review("send", "Earlier approval"), NOW)).action == "defer"


def test_rejection_releases_hold_and_preserves_future_offset(local):
    from services.proactive.class_sessions import delivery_decision
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    before = local.pending()[0]
    assert say("reject class reminder updates for tomorrow's DBMS").success
    assert local.pending()[0] == before and delivery_decision(before) is None
    say("tomorrow's DBMS class moved to 12 PM")
    assert say("apply class reminder updates for tomorrow's DBMS").success
    assert local.pending()[0].due_at == before.due_at + 3600


def test_class_and_deadline_cannot_share_one_reminder(local):
    from services.proactive import deadlines
    deadlines.add("DBMS assignment", NOW + timedelta(days=2), NOW)
    assert say("link reminder 1 to tomorrow's DBMS class").success
    assert not say("link reminder 1 to deadline DBMS").success
    local.add_from_message("remind me tomorrow at 7am to review DBMS", NOW)
    assert say("link reminder 1 to deadline DBMS").success
    assert not say("link reminder 1 to tomorrow's DBMS class").success


def test_saved_approval_cannot_apply_a_newer_class_revision_or_proposal(local):
    from services.proactive import class_changes, class_sessions
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    parsed = class_changes.match_turn("apply class reminder updates for tomorrow's DBMS")
    before = local.pending()[0]
    rows = class_sessions.load()
    rows[0]["reminder_updates"][-1]["items"][0]["new_due"] += 3600
    class_sessions.save(rows)
    assert not class_changes.run(parsed).success
    say("tomorrow's DBMS class moved to 12 PM")
    assert not class_changes.run(parsed).success
    assert local.pending()[0] == before


def test_other_channel_cannot_apply_proposal(local):
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    token = intent.remote_request.set(True)
    try:
        assert not say("apply class reminder updates for tomorrow's DBMS").success
    finally:
        intent.remote_request.reset(token)
    assert say("apply class reminder updates for tomorrow's DBMS").success


def test_reminder_batch_rolls_back_if_any_identity_changed(local):
    say("link reminder 1 to tomorrow's DBMS class")
    local.add_from_message("remind me tomorrow at 8:30am to pack my DBMS book", NOW)
    say("link reminder 2 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    before = local.pending()[0]
    with local._connect() as db:
        db.execute("UPDATE reminders SET text='Changed instruction' WHERE id=2")
    assert not say("apply class reminder updates for tomorrow's DBMS").success
    assert local.pending()[0] == before


def test_reminder_commit_recovers_without_replaying_after_json_failure(local, monkeypatch):
    from services.proactive import class_sessions
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    save = class_sessions.save
    def fail(*a):
        raise OSError("Interrupted finalization")
    monkeypatch.setattr(class_sessions, "save", fail)
    assert not say("apply class reminder updates for tomorrow's DBMS").success
    moved = local.pending()[0]
    assert moved.due_at == datetime(2026, 10, 14, 10).timestamp()
    monkeypatch.setattr(class_sessions, "save", save)
    assert say("apply class reminder updates for tomorrow's DBMS").success
    assert local.pending()[0] == moved
    assert class_sessions.load()[0]["reminder_updates"][-1]["status"] == "applied"


@pytest.mark.parametrize("change", ["broken", "history", "end", "template"])
def test_corrupt_store_is_retained_and_refused(local, change):
    import json
    from services.proactive import class_sessions
    say("tomorrow's DBMS class moved to 11 AM")
    rows = class_sessions.load()
    if change == "history":
        rows[0]["history"][0].pop("new_end")
    elif change == "end":
        rows[0]["end"] = "01:00"
    elif change == "template":
        rows[0]["template"]["day"] = "bad day"
    class_sessions.path().write_text("broken" if change == "broken" else json.dumps(rows), encoding="utf-8")
    before = class_sessions.path().read_bytes()
    assert not say("tomorrow's DBMS class moved to 12 PM").success
    assert class_sessions.path().read_bytes() == before


def test_changed_weekly_template_does_not_rebind_old_shift_or_reminders(local):
    from services.proactive import class_sessions
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    timetable._save([{**timetable.load()[0], "room": "305"}])
    assert timetable.classes_for_date((NOW + timedelta(days=1)).date())[0]["start"] == "09:00"
    assert class_sessions.delivery_decision(local.pending()[0])["action"] == "defer"
    assert not say("apply class reminder updates for tomorrow's DBMS").success
    assert not say("tomorrow's DBMS class moved to 12 PM").success
    assert len(class_sessions.load()) == 1


def test_atomic_write_failure_preserves_original_state(local, monkeypatch):
    from services.proactive import class_sessions, deadline_store
    say("tomorrow's DBMS class moved to 11 AM")
    before = class_sessions.path().read_bytes()
    def fail(*a):
        raise OSError("Atomic replace failed")
    monkeypatch.setattr(deadline_store.os, "replace", fail)
    assert not say("tomorrow's DBMS class moved to 12 PM").success
    assert class_sessions.path().read_bytes() == before


def test_parallel_corrections_consume_only_one_snapshot(local):
    from concurrent.futures import ThreadPoolExecutor
    from services.proactive import class_changes, class_sessions
    requests = [class_changes.match_turn(f"tomorrow's DBMS class moved to {h} AM") for h in (10, 11)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(class_changes.run, requests))
    assert sum(r.success for r in results) == 1
    assert len(class_sessions.load()[0]["history"]) == 1


def test_started_classes_and_recorded_attendance_cannot_be_moved(local, monkeypatch):
    from services.proactive import class_changes
    data = attendance.load()
    attendance.record(data, (NOW + timedelta(days=1)).date(), "DBMS", "09:00", True)
    attendance._save(data)
    assert not say("tomorrow's DBMS class moved to 11 AM").success
    data["records"] = []
    attendance._save(data)
    class LateClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 14, 9, 5)
    monkeypatch.setattr(class_changes, "datetime", LateClock)
    assert not say("today's DBMS class moved to 11 AM").success


@pytest.mark.parametrize("text", ["if tomorrow's DBMS class moved to 11 AM", "did tomorrow's DBMS class move to 11 AM?",
    "tomorrow's DBMS class might move to 11 AM", "tomorrow's imaginary class moved to 11 AM", "tomorrow's DBMS class moved to 13 AM"])
def test_questions_hypotheticals_missing_subjects_and_bad_clocks_do_not_write(local, text):
    from services.proactive import class_changes, class_sessions
    parsed = class_changes.match_command(text)
    if parsed:
        assert not class_changes.run(parsed).success
    assert class_sessions.load() == []


def test_chat_voice_and_prompt_use_corrected_class_without_search_or_models(local, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    def forbidden(*a, **kw):
        pytest.fail("Class correction entered search, learning or a model")
    for route in (chat, voice):
        for name in ("build_file_context", "build_search_context", "extract_screen_question", "complete_with_failover"):
            monkeypatch.setattr(route, name, forbidden)
    monkeypatch.setattr(chat.talk, "hear", forbidden)
    monkeypatch.setattr(chat.humour, "hear", forbidden)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    reply = client.post("/api/v1/chat", json={"message": "tomorrow's DBMS class moved from 9 AM to 11 AM"})
    assert reply.status_code == 200 and reply.json()["action_success"]
    reply = asyncio.run(voice._reply("when is tomorrow's DBMS class", voice.VoiceRequest(speak=False)))
    assert reply.action_success and "11:00" in reply.response
    assert "11:00 am" in timetable.prompt_line(NOW)


def test_new_process_reads_occurrence_and_applies_durable_proposal(local):
    import subprocess
    import sys
    from services.mind.cognition import cognition
    from services.proactive import deadlines
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    script = '''
import logging, sys
from pathlib import Path
from datetime import datetime
from core.config import config
from core.logger import logger
for handler in list(logger.handlers):
    if isinstance(handler, logging.FileHandler):
        logger.removeHandler(handler)
        handler.close()
config.MEMORY_DIR = Path(sys.argv[1])
config.MEMORY_DB_PATH = sys.argv[2]
from services.proactive import class_changes, timetable, deadlines
from services.mind.cognition import cognition
timetable.path = Path(sys.argv[3])
timetable.subjects_path = config.MEMORY_DIR / "subjects.json"
deadlines.path = Path(sys.argv[4])
cognition.path = Path(sys.argv[5])
class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return datetime(2026, 10, 13, 8)
class_changes.datetime = Clock
parsed = class_changes.match_turn("apply class reminder updates for tomorrow's DBMS")
print("APPLIED=" + str(class_changes.run(parsed).success))
print("START=" + timetable.classes_for_date(datetime(2026, 10, 14).date())[0]["start"])
'''
    child = subprocess.run([sys.executable, "-c", script, str(config.MEMORY_DIR), local.db_path,
                            str(timetable.path), str(deadlines.path), str(cognition.path)],
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert "APPLIED=True" in child.stdout and "START=11:00" in child.stdout
    assert local.pending()[0].due_at == datetime(2026, 10, 14, 10).timestamp()


def test_inflight_class_warning_is_rechecked_after_time_change(local, monkeypatch):
    from services.mind import notifications
    from services.proactive import class_changes
    sent = []
    async def decide(candidates, now, observations):
        request = class_changes.match_turn("tomorrow's DBMS class moved to 11 AM")
        assert class_changes.run(request).success
        return [notifications.Choice(id="0", send=True, reason="Class is due soon")]
    monkeypatch.setattr(notifications, "_reason", decide)
    result = asyncio.run(notifications.notify("DBMS starts in 5 minutes", kind="class_warning", subject="DBMS",
        now=NOW + timedelta(days=1, minutes=55), transport=lambda *a, **kw: sent.append(a) or True))
    assert result is False and sent == []


@pytest.mark.parametrize("state,channel", [("submitting", "pending"), ("uncertain", "uncertain"), ("retry", "submitted")])
def test_active_or_uncertain_reminder_delivery_cannot_be_shifted(local, state, channel):
    import time
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    before = local.pending()[0]
    claim = local._claim_due(time.time())[0]
    local._state(claim, status=state, desktop_status=channel, token=None, lease_until=None)
    assert not say("apply class reminder updates for tomorrow's DBMS").success
    assert local.pending()[0] == before


def test_stale_attendance_revision_cannot_record_even_if_start_matches(local):
    say("tomorrow's DBMS class moved to 11 AM")
    about = attendance.due_asks(datetime(2026, 10, 14, 12, 5))[0]
    say("tomorrow's DBMS class moved to 12 PM")
    say("tomorrow's DBMS class moved to 11 AM")
    assert "no attendance" in attendance.answer(about, "yes")
    assert attendance.load()["records"] == []


@pytest.mark.parametrize("alias", ["what time is tomorrow's dbms class", "when is my tomorrow's dbms class"])
def test_class_recall_aliases_reach_real_router_with_saved_state(local, alias):
    result = say("Could you please " + alias)
    assert result.success and "2026-10-14T09:00" in result.message


def test_cancellation_still_matches_after_receipt_precedes_json_finalization(local, monkeypatch):
    from services.proactive import class_sessions
    say("link reminder 1 to tomorrow's DBMS class")
    say("tomorrow's DBMS class moved to 11 AM")
    def fail(*a):
        raise OSError("Interrupted finalization")
    monkeypatch.setattr(class_sessions, "save", fail)
    assert not say("apply class reminder updates for tomorrow's DBMS").success
    cancel_class()
    assert class_sessions.delivery_decision(local.pending()[0])["action"] == "suppress"
