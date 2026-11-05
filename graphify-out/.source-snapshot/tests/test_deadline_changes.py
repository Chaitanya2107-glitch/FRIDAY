import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.config import config
from services.automation import intent
from services.proactive import deadlines
from services.reminders.service import ReminderService
from services.mind.reminder_review import review as REAL_REVIEW
from test_project_session import session

NOW = datetime(2026, 10, 13, 10)  # Tuesday
OLD = datetime(2026, 10, 16, 17)
NEW = datetime(2026, 10, 19, 17)


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


@pytest.fixture
def local(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(deadlines, "datetime", Clock)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    deadlines.add("DBMS assignment", OLD, NOW)
    store = ReminderService()
    store.add_from_message("remind me tomorrow at 5pm to submit DBMS assignment", NOW)
    return store


def test_correction_changes_canonical_deadline_and_preserves_history(local):
    result = say("my DBMS deadline moved from Friday to Monday")
    assert result.success and "2026-10-19" in result.message
    row = deadlines.load()[0]
    assert datetime.fromisoformat(row["due"]) == NEW
    assert datetime.fromisoformat(row["history"][0]["old_due"]) == OLD
    assert row["history"][0]["source"] == "owner_report"
    assert "2026-10-19" in say("when is my DBMS deadline").message
    assert "2026-10-16" in say("show deadline history for DBMS").message
    assert len(deadlines.load()) == 1


def test_linked_reminders_are_previewed_then_moved_only_on_explicit_apply(local):
    before = local.pending()[0]
    assert say("link reminder 1 to deadline DBMS").success
    result = say("my DBMS deadline moved from Friday to Monday")
    assert result.success and "apply reminder updates" in result.message.lower()
    assert local.pending()[0] == before
    assert say("review reminder updates for DBMS").success
    assert say("apply reminder updates for DBMS").success
    after = local.pending()[0]
    assert after.id == before.id and after.due_at == before.due_at + (NEW - OLD).total_seconds()
    assert not say("apply reminder updates for DBMS").success
    assert local.pending()[0] == after


def test_ambiguous_deadline_waits_for_name_without_mutating(local):
    deadlines.add("DBMS lab", OLD + timedelta(days=1), NOW)
    result = say("my DBMS deadline moved to Monday")
    assert not result.success and "Which deadline" in result.message
    assert all(not d.get("history") for d in deadlines.load())
    assert say("DBMS assignment").success
    assert next(d for d in deadlines.load() if d["what"] == "DBMS assignment")["due"] == NEW.isoformat(timespec="minutes")


def test_wrong_old_date_and_past_new_date_are_refused(local):
    assert not say("my DBMS deadline moved from Thursday to Monday").success
    assert not say("move deadline DBMS to 12/10/2026").success
    assert deadlines.load()[0]["due"] == OLD.isoformat(timespec="minutes")


def test_changed_reminder_blocks_the_entire_approved_batch(local):
    assert say("link reminder 1 to deadline DBMS").success
    say("my DBMS deadline moved to Monday")
    with local._connect() as db:
        db.execute("UPDATE reminders SET text='different owner instruction' WHERE id=1")
    result = say("apply reminder updates for DBMS")
    assert not result.success and "changed" in result.message.lower()
    assert local.pending()[0].text == "different owner instruction"


def test_telegram_cannot_apply_laptop_proposal(local):
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    before = local.pending()[0]
    token = intent.remote_request.set(True)
    try:
        result = say("apply reminder updates for DBMS")
        assert not result.success
    finally:
        intent.remote_request.reset(token)
    assert local.pending()[0] == before
    assert say("apply reminder updates for DBMS").success


def test_new_handoff_reads_corrected_deadline_and_blocks_stale_snapshot(local, tmp_path):
    from services.mind.execution import ExecutionEngine
    from services.mind.workspace import workspace
    task = workspace.start_task("DBMS assignment")
    engine = ExecutionEngine(workspace, tmp_path / "handoffs")
    first = engine.create(task)
    engine.step(first)
    assert say("my DBMS deadline moved to Monday").success
    assert engine.run(first)["state"] == "blocked"
    second = engine.run(engine.create(task))
    text = Path(second["artifact"]).read_text(encoding="utf-8")
    assert "2026-10-19T17:00" in text and "2026-10-16T17:00" not in text


def test_corrupt_deadlines_are_not_overwritten(local):
    deadlines.path.write_text("broken JSON", encoding="utf-8")
    result = say("my DBMS deadline moved to Monday")
    assert result and not result.success
    assert deadlines.path.read_text(encoding="utf-8") == "broken JSON"


def test_stale_approval_snapshot_cannot_apply_a_newer_proposal(local):
    from services.proactive import deadline_changes
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    parsed = deadline_changes.match_turn("apply reminder updates for DBMS")
    say("my DBMS deadline moved to 20/10/2026")
    before = local.pending()
    result = deadline_changes.run(parsed)
    assert not result.success and "changed" in result.message.lower()
    assert local.pending() == before


def test_rejection_keeps_reminder_time_and_releases_delivery_hold(local):
    from services.proactive.deadline_reminders import hold_reason
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    before = local.pending()[0]
    assert hold_reason(before)
    assert say("reject reminder updates for DBMS").success
    assert local.pending()[0] == before and not hold_reason(before)
    assert deadlines.load()[0]["due"] == NEW.isoformat(timespec="minutes")


def test_commit_receipt_recovers_after_json_finalization_failure(local, monkeypatch):
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    original = deadlines._save
    def fail_save(*a):
        raise OSError("simulated interruption after reminder commit")
    monkeypatch.setattr(deadlines, "_save", fail_save)
    assert not say("apply reminder updates for DBMS").success
    moved = local.pending()[0]
    assert moved.due_at == (NOW + timedelta(days=4, hours=7)).timestamp()
    monkeypatch.setattr(deadlines, "_save", original)
    assert say("apply reminder updates for DBMS").success
    assert local.pending()[0] == moved
    assert deadlines.load()[0]["reminder_updates"][-1]["status"] == "applied"


def test_entire_batch_rolls_back_if_one_link_was_delivered(local):
    say("link reminder 1 to deadline DBMS")
    local.add_from_message("remind me tomorrow at 6pm to review DBMS", NOW)
    say("link reminder 2 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    before = local.pending()[0]
    with local._connect() as db:
        db.execute("UPDATE reminders SET delivered_at=? WHERE id=2", (NOW.timestamp(),))
    assert not say("apply reminder updates for DBMS").success
    assert local.pending()[0] == before


def test_active_delivery_refuses_reschedule(local):
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    before = local.pending()[0]
    assert local._claim_due(time.time())
    result = say("apply reminder updates for DBMS")
    assert not result.success and "delivery" in result.message.lower()
    assert local.pending()[0] == before


def test_stale_deadline_choice_and_other_channel_do_not_consume_clarification(local):
    deadlines.add("DBMS lab", OLD, NOW)
    say("my DBMS deadline moved to Monday")
    token = intent.remote_request.set(True)
    try:
        result = say("DBMS assignment")
        assert result is None or not result.success
    finally:
        intent.remote_request.reset(token)
    assert say("the fifth one") is not None
    assert say("DBMS assignment").success


def test_current_dates_feed_shared_context_and_reasoning_evidence(local):
    from services.mind.workspace import workspace
    from services.mind.reasoning_store import reasoning_store
    say("my DBMS deadline moved to Monday")
    assert workspace.context()["deadlines"][0]["due"] == NEW.isoformat(timespec="minutes")
    evidence = [v for v in reasoning_store.evidence().values() if v["kind"] == "deadline"]
    assert evidence[0]["due"] == NEW.isoformat(timespec="minutes")


def test_corrupt_deadline_store_blocks_handoff_publication(local, tmp_path):
    from services.mind.execution import ExecutionEngine
    from services.mind.workspace import workspace
    task = workspace.start_task("DBMS assignment")
    engine = ExecutionEngine(workspace, tmp_path / "handoffs")
    ident = engine.create(task)
    deadlines.path.write_text("broken", encoding="utf-8")
    result = engine.run(ident)
    assert result["state"] == "blocked" and not result["verified"]


def test_project_briefs_capture_current_deadlines_and_refuse_stale_dates(local, session):
    from services.mind.workspace import workspace
    runner, _ = session
    goal = workspace.add_goal("FRIDAY college work")
    workspace.start_task("DBMS assignment", goal)
    ident = runner.create("friday")
    runner.step(ident)
    say("my DBMS deadline moved to Monday")
    assert runner.run(ident)["state"] == "blocked"
    fresh = runner.run(runner.create("friday"))
    assert fresh["verified"]
    assert "2026-10-19T17:00" in Path(fresh["artifact"]).read_text(encoding="utf-8")


def test_pending_deadline_change_holds_the_real_notification_review(local, monkeypatch):
    from providers import failover
    from services.mind import reminder_review
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    async def forbidden(*a, **kw):
        pytest.fail("Pending deadline review called a model")
    monkeypatch.setattr(failover, "complete_with_failover", forbidden)
    decision = asyncio.run(REAL_REVIEW(local.pending()[0], NOW))
    assert decision.action == "defer" and "deadline" in decision.reason


def test_link_edit_cannot_silently_drop_pending_reminder_updates(local):
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    before = deadlines.load()[0]["reminder_updates"][-1]
    assert not say("link reminder 1 to deadline DBMS").success
    assert deadlines.load()[0]["reminder_updates"][-1] == before


def test_pending_choice_expires_and_a_changed_choice_is_refused(local, monkeypatch):
    from services.mind import reference_context
    deadlines.add("DBMS lab", OLD, NOW)
    say("my DBMS deadline moved to Monday")
    with deadlines.edit():
        rows = deadlines.load()
        rows[0]["due"] = "2026-10-18T17:00"
        deadlines._save(rows)
    assert not say("DBMS assignment").success
    say("my DBMS deadline moved to Monday")
    clock = reference_context.time.time()
    monkeypatch.setattr(reference_context.time, "time", lambda: clock + reference_context.TTL_SECONDS + 1)
    result = say("DBMS lab")
    assert result is None or not result.success


def test_date_change_preserves_clock_and_accepts_explicit_iso_time(local):
    assert say("my DBMS deadline moved to 2026-10-20 at 9am").success
    assert deadlines.load()[0]["due"] == "2026-10-20T09:00"
    assert say("my DBMS deadline moved to 22/10/2026").success
    assert deadlines.load()[0]["due"] == "2026-10-22T09:00"
    assert len(deadlines.load()[0]["history"]) == 2


def test_chat_and_voice_bypass_search_learning_and_models(local, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    stored = []
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: stored.append(a)))
    def forbidden(*a, **kw):
        pytest.fail("Deadline turn entered search or learning")
    for route in (chat, voice):
        for name in ("build_file_context", "build_search_context", "extract_screen_question", "complete_with_failover"):
            monkeypatch.setattr(route, name, forbidden)
    monkeypatch.setattr(chat.talk, "hear", forbidden)
    monkeypatch.setattr(chat.humour, "hear", forbidden)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/chat", json={"message": "my DBMS deadline moved from Friday to Monday"})
    assert result.status_code == 200 and result.json()["action_success"]
    result = asyncio.run(voice._reply("when is my DBMS deadline", voice.VoiceRequest(speak=False)))
    assert result.action_success and "2026-10-19" in result.response


def test_new_process_recalls_date_and_applies_saved_proposal(local):
    import subprocess
    import sys
    from services.mind.cognition import cognition
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
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
from services.proactive import deadlines, deadline_changes
from services.mind.cognition import cognition
config.MEMORY_DB_PATH = sys.argv[2]
cognition.path = Path(sys.argv[3])
deadlines.path = Path(sys.argv[1])
class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return datetime(2026, 10, 13, 10)
deadlines.datetime = Clock
reply = deadline_changes.run(deadline_changes.match_turn("apply reminder updates for DBMS"))
print("APPLIED=" + str(reply.success))
print("DUE=" + deadlines.load()[0]["due"])
'''
    child = subprocess.run([sys.executable, "-c", script, str(deadlines.path), local.db_path, str(cognition.path)],
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert "APPLIED=True" in child.stdout and "DUE=2026-10-19T17:00" in child.stdout
    assert local.pending()[0].due_at == datetime(2026, 10, 17, 17).timestamp()


@pytest.mark.parametrize("field,bad", [("history", "invalid history"), ("linked_reminders", [{"id": True}])])
def test_malformed_saved_metadata_is_retained_and_refused(local, field, bad):
    rows = deadlines.load()
    rows[0][field] = bad
    deadlines._save(rows)
    before = deadlines.path.read_bytes()
    assert not say("my DBMS deadline moved to Monday").success
    assert deadlines.path.read_bytes() == before


def test_failed_atomic_publication_keeps_original_date_and_history(local, monkeypatch):
    from services.proactive import deadline_store
    before = deadlines.path.read_bytes()
    def fail(*a):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(deadline_store.os, "replace", fail)
    assert not say("my DBMS deadline moved to Monday").success
    assert deadlines.path.read_bytes() == before


def test_changed_proposal_bytes_cannot_be_applied(local):
    from services.proactive import deadline_changes
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    parsed = deadline_changes.match_turn("apply reminder updates for DBMS")
    rows = deadlines.load()
    rows[0]["reminder_updates"][-1]["items"][0]["new_due"] += 3600
    deadlines._save(rows)
    before = local.pending()
    result = deadline_changes.run(parsed)
    assert not result.success and "changed" in result.message
    assert local.pending() == before


@pytest.mark.parametrize("status,desktop", [("uncertain", "uncertain"), ("submitting", "pending"), ("retry", "submitted")])
def test_uncertain_or_partial_delivery_cannot_be_silently_rescheduled(local, status, desktop):
    say("link reminder 1 to deadline DBMS")
    say("my DBMS deadline moved to Monday")
    before = local.pending()[0]
    claim = local._claim_due(time.time())[0]
    local._state(claim, status=status, desktop_status=desktop, token=None, lease_until=None)
    assert not say("apply reminder updates for DBMS").success
    assert local.pending()[0] == before


def test_concurrent_corrections_use_one_source_snapshot(local):
    from concurrent.futures import ThreadPoolExecutor
    from services.proactive import deadline_changes
    first = deadline_changes.match_turn("my DBMS deadline moved to Monday")
    second = deadline_changes.match_turn("my DBMS deadline moved to 20/10/2026")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(deadline_changes.run, [first, second]))
    assert sum(r.success for r in results) == 1
    assert len(deadlines.load()[0]["history"]) == 1


def test_prompt_budget_keeps_current_deadline_before_older_events(local, monkeypatch):
    from services.mind.cognition_context import prompt_section
    monkeypatch.setattr(config, "COGNITION_ENABLED", True)
    monkeypatch.setattr(config, "COGNITION_PROMPT_CHARS", 2000)
    say("my DBMS deadline moved to Monday")
    for i in range(5):
        deadlines.add(f"Other assignment {i}", OLD + timedelta(days=10 + i), NOW)
    prompt = prompt_section()
    assert len(prompt) <= 2000
    assert "2026-10-19T17:00" in prompt
