import asyncio
import sqlite3
from datetime import datetime, timedelta

from core.config import config
from services.activity.log import ActivityLog, activity_log
from services.automation import intent
from services.memory.semantic import semantic_memory
from services.mind import activity_awareness as awareness
from services.mind import brain, knowledge

NOW = datetime(2026, 10, 27, 15)


def front(log, app="chrome", title="Graph algorithms - Google Chrome", at=NOW, window=(10, 20)):
    log.last_window = window
    log.observe(app, at, title)


def test_metadata_does_not_establish_intent_or_attendance(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    text = awareness.summary(log, NOW)
    assert "chrome is in the foreground" in text and "Graph algorithms" in text
    assert "don't yet know your exact task" in text
    assert "studying" not in text


def test_an_owner_label_is_scoped_and_preserves_provenance(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    result = awareness.command("I'm studying graph algorithms", log, NOW)
    assert result.success
    text = awareness.summary(log, NOW)
    assert 'You told me at 15:00: "studying graph algorithms"' in text
    assert "not independently verified progress" in text
    with knowledge.db() as db:
        assert db.execute("SELECT source FROM owner_activities").fetchone()[0] == "owner_report"


def test_app_use_is_not_current_intent(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    assert awareness.command("I use Chrome for college notes", log, NOW).success
    text = awareness.summary(log, NOW)
    assert "college notes" in text and "doesn't establish today's task" in text
    assert awareness.current_task(log, NOW) is None
    assert awareness.command("I use this app for music", log, NOW).success
    assert "music" in awareness.summary(log, NOW)


def test_stale_and_future_observations_are_not_current(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    assert "don't have a fresh" in awareness.summary(log, NOW + timedelta(seconds=21))
    assert "don't have a fresh" in awareness.summary(log, NOW - timedelta(seconds=1))
    assert not awareness.command("I'm doing my homework", log, NOW + timedelta(minutes=3)).success


def test_title_switch_idle_and_restart_do_not_revive_labels(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    awareness.command("I'm studying graphs", log, NOW)
    front(log, title="Other document", at=NOW + timedelta(seconds=5))
    front(log, at=NOW + timedelta(seconds=10))
    assert awareness.current_task(log, NOW + timedelta(seconds=10)) is None
    awareness.command("I'm studying graphs", log, NOW + timedelta(seconds=10))
    log.observe(None, NOW + timedelta(seconds=15))
    front(log, at=NOW + timedelta(seconds=20))
    assert awareness.current_task(log, NOW + timedelta(seconds=20)) is None
    awareness.command("I'm studying graphs", log, NOW + timedelta(seconds=20))
    restarted = ActivityLog(log.db_path)
    front(restarted, at=NOW + timedelta(seconds=25))
    assert awareness.current_task(restarted, NOW + timedelta(seconds=25)) is None


def test_identical_titles_in_different_windows_do_not_share_a_task(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log, app="notepad", title="Untitled", window=(10, 20))
    awareness.command("I'm working on a birthday note", log, NOW)
    front(log, app="notepad", title="Untitled", at=NOW + timedelta(seconds=5), window=(11, 20))
    assert awareness.current_task(log, NOW + timedelta(seconds=5)) is None
    front(log, app="notepad", title="Untitled", at=NOW + timedelta(seconds=10), window=(10, 20))
    assert awareness.current_task(log, NOW + timedelta(seconds=10)) is None


def test_same_app_after_observation_gap_does_not_restore_a_task(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    awareness.command("I'm studying graphs", log, NOW)
    front(log, at=NOW + timedelta(minutes=20))
    assert awareness.current_task(log, NOW + timedelta(minutes=20)) is None


def test_command_bar_can_label_a_recent_app_without_calling_it_current(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    log.observe(None, NOW + timedelta(seconds=5))
    result = awareness.command("I'm studying graphs", log, NOW + timedelta(seconds=6))
    assert result.success and "recent chrome activity" in result.message
    assert awareness.current_task(log, NOW + timedelta(seconds=6)) is None
    front(log, at=NOW + timedelta(seconds=10))
    assert awareness.current_task(log, NOW + timedelta(seconds=10))["task"] == "studying graphs"


def test_optional_store_failure_does_not_break_the_system_prompt(monkeypatch):
    front(activity_log, at=datetime.now())
    def broken(*a, **k):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(awareness, "current_task", broken)
    assert "exact task unknown" in awareness.prompt_section()
    assert "personal assistant" in config.SYSTEM_PROMPT


def test_private_title_is_not_in_general_prompt_and_remote_has_no_activity_context():
    front(activity_log, title="PRIVATE 793892", at=datetime.now())
    text = awareness.prompt_section()
    assert "chrome" in text and "793892" not in text
    token = intent.remote_request.set(True)
    try:
        assert awareness.prompt_section() == ""
    finally:
        intent.remote_request.reset(token)


def test_forgetting_personal_data_removes_labels_and_app_uses(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    awareness.command("I'm studying graphs", log, NOW)
    awareness.command("I use Chrome for college notes", log, NOW)
    assert semantic_memory.forget_all() >= 2
    front(log, at=NOW + timedelta(seconds=5))
    assert awareness.current_task(log, NOW + timedelta(seconds=5)) is None
    assert "college notes" not in awareness.summary(log, NOW + timedelta(seconds=5))


def test_targeted_forget_and_clear_activity_remove_their_labels(tmp_path):
    from services.memory.semantic import run_memory_command
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log)
    awareness.command("I'm studying graphs", log, NOW)
    assert "Forgot" in run_memory_command({"action": "forget_memory", "text": "graphs"})
    assert awareness.current_task(log, NOW) is None
    awareness.command("I'm studying sorting", log, NOW)
    log.clear()
    assert awareness.current_task(log, datetime.now()) is None


def test_tracking_durations_do_not_double_count_or_credit_a_sleep_gap(tmp_path):
    log = ActivityLog(str(tmp_path / "activity.db"))
    front(log, app="mystery")
    brain.sense(log, NOW)
    for seconds in (5, 10, 15):
        front(log, app="mystery", at=NOW + timedelta(seconds=seconds))
        brain.sense(log, NOW + timedelta(seconds=seconds))
    assert knowledge.get("app:mystery").seconds == 15
    front(log, app="mystery", at=NOW + timedelta(hours=2))
    brain.sense(log, NOW + timedelta(hours=2))
    assert knowledge.get("app:mystery").seconds == 15
    front(log, app="spotify", at=NOW + timedelta(hours=2, seconds=5))
    brain.sense(log, NOW + timedelta(hours=2, seconds=5))
    assert knowledge.get("app:mystery").seconds == 20


def test_explicit_activity_reports_work_through_local_command_router():
    front(activity_log, at=datetime.now())
    result = asyncio.run(intent.try_system_action("I'm studying graphs", "openrouter"))
    assert result.success
    assert awareness.current_task(activity_log)["task"] == "studying graphs"
