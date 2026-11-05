from datetime import datetime, timedelta
import asyncio

import pytest

from services.mind.workspace import workspace
from services.mind.notifications import _reason as REAL_REASON

NOW = datetime(2026, 10, 18, 14)


def age_task(task, days=3):
    with workspace._db() as db:
        db.execute("UPDATE workspace_tasks SET updated=? WHERE id=?", ((NOW - timedelta(days=days)).timestamp(), task))


def test_ranks_owner_priorities_and_explains_saved_blocker():
    from services.mind import task_followups
    goal = workspace.add_goal("Ship FRIDAY", "high")
    low = workspace.start_task("Read a book")
    high = workspace.start_task("Fix voice input", goal)
    workspace.task_state(high, "blocked", "Waiting for a microphone test")
    age_task(low)
    age_task(high)
    offer = task_followups.offer(NOW)
    assert offer["task_id"] == high
    assert "microphone test" in offer["text"] and "Ship FRIDAY" in offer["reason"]
    assert workspace.tasks()[0]["status"] == "blocked"


def test_recent_progress_paused_goals_and_finished_tasks_do_not_nudge():
    from services.mind import task_followups
    recent = workspace.start_task("Work in progress")
    with workspace._db() as db:
        db.execute("UPDATE workspace_tasks SET updated=? WHERE id=?", (NOW.timestamp(), recent))
    goal = workspace.add_goal("Paused project")
    paused = workspace.start_task("Old paused project task", goal)
    age_task(paused)
    workspace.goal_state(goal, "paused")
    done = workspace.start_task("Completed task")
    workspace.task_state(done, "completed", "Owner confirmed completion")
    age_task(done)
    assert task_followups.offer(NOW) is None


def test_selection_is_durable_and_does_not_repeat_every_tick():
    from services.mind import task_followups
    task = workspace.start_task("Review code")
    age_task(task)
    first = task_followups.offer(NOW)
    assert first
    assert task_followups.offer(NOW + timedelta(minutes=1)) is None
    assert task_followups.current(first["token"], NOW)
    workspace.task_state(task, "completed", "Reviewed all changes")
    assert not task_followups.current(first["token"], NOW)


def test_snooze_and_mute_persist_without_changing_task_progress():
    from services.mind import task_followups
    task = workspace.start_task("Review code")
    age_task(task)
    task_followups.control("pause", task, NOW)
    assert task_followups.offer(NOW + timedelta(hours=23)) is None
    assert task_followups.offer(NOW + timedelta(hours=25))
    task_followups.control("stop", task, NOW)
    assert task_followups.offer(NOW + timedelta(days=5)) is None
    task_followups.control("resume", task, NOW + timedelta(days=6))
    assert task_followups.offer(NOW + timedelta(days=6))
    assert workspace.tasks()[0]["status"] == "active"


def test_claim_is_once_only_and_only_actual_submission_creates_reply_context():
    from services.mind import task_followups, reference_context
    task = workspace.start_task("Review code")
    age_task(task)
    offer = task_followups.offer(NOW)
    assert task_followups.claim(offer["token"], NOW)
    assert not task_followups.claim(offer["token"], NOW)
    with workspace._db() as db:
        assert reference_context.read(db, "task_followup") is None
    task_followups.settle(offer["token"], "submitted", 7, NOW)
    with workspace._db() as db:
        assert reference_context.read(db, "task_followup")["payload"]["token"] == offer["token"]
    assert task_followups.offer(NOW + timedelta(hours=5)) is None


def test_feedback_is_explicit_and_does_not_complete_the_task():
    from services.mind import task_followups
    task = workspace.start_task("Review code")
    workspace.plan(task, ["Read diff", "Run tests"])
    age_task(task)
    offer = task_followups.offer(NOW)
    task_followups.claim(offer["token"], NOW)
    task_followups.settle(offer["token"], "submitted", None, NOW)
    assert "Read diff" in task_followups.respond(offer["token"], "review", NOW)
    assert workspace.tasks()[0]["cursor"] == 0
    assert workspace.tasks()[0]["status"] == "active"


def test_stale_buttons_cannot_change_followup_preferences():
    from services.mind import task_followups
    task = workspace.start_task("Review code")
    age_task(task)
    offer = task_followups.offer(NOW)
    task_followups.claim(offer["token"], NOW)
    task_followups.settle(offer["token"], "submitted", None, NOW)
    workspace.task_state(task, "blocked", "New blocker")
    with pytest.raises(ValueError, match="changed"):
        task_followups.respond(offer["token"], "stop", NOW)


@pytest.fixture
def delivery(monkeypatch):
    from services.proactive import watcher
    from services.mind import talk
    sent = []
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 10)
    monkeypatch.setattr(watcher, "show_toast", lambda *a, **kw: sent.append(a) or True)
    monkeypatch.setattr(talk, "mic_in_use", lambda: False)
    return sent


def test_real_notification_pipeline_submits_once_and_buttons_remember_feedback(delivery, monkeypatch):
    from services.mind import task_followups
    from services.proactive import buttons
    task = workspace.start_task("Review code")
    age_task(task)
    assert asyncio.run(task_followups.tick(NOW, False, 10))
    assert len(delivery) == 1
    with task_followups._db() as db:
        row = db.execute("SELECT * FROM workspace_followups").fetchone()
        assert row["state"] == "submitted"
    token = next(t for t, about in buttons._offers.items() if about["kind"] == "task_followup")
    class ButtonClock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    # The button uses a local datetime import; its click belongs to the same fixture time.
    with monkeypatch.context() as clock:
        clock.setattr('datetime.datetime', ButtonClock)
        assert "24 hours" in buttons.respond(token, "pause")
    assert task_followups.offer(NOW + timedelta(hours=5)) is None


def test_provider_silence_does_not_create_a_delivery_or_reply_target(delivery, monkeypatch):
    from services.mind import task_followups, notifications, reference_context
    task = workspace.start_task("Review code")
    age_task(task)
    async def silent(candidates, now, observations):
        return [notifications.Choice(id="0", send=False, reason="Not useful now")]
    monkeypatch.setattr(notifications, "_reason", silent)
    asyncio.run(task_followups.tick(NOW, False, 10))
    assert delivery == []
    with task_followups._db() as db:
        assert db.execute("SELECT state FROM workspace_followups").fetchone()[0] == "withheld"
        assert reference_context.read(db, "task_followup") is None


def test_task_progress_during_brain_review_invalidates_the_notification(delivery, monkeypatch):
    from services.mind import task_followups, notifications
    task = workspace.start_task("Review code")
    workspace.plan(task, ["Read diff", "Run tests"])
    age_task(task)
    async def changed(candidates, now, observations):
        workspace.advance(task, "Diff reviewed")
        return [notifications.Choice(id="0", send=True, reason="Review task")]
    monkeypatch.setattr(notifications, "_reason", changed)
    asyncio.run(task_followups.tick(NOW, False, 10))
    assert delivery == []


def test_task_help_commands_and_short_replies_are_scoped(delivery, monkeypatch):
    from services.automation import intent
    from services.mind import followup_commands, task_followups
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(followup_commands, "datetime", Clock)
    task = workspace.start_task("Review code")
    age_task(task)
    asyncio.run(task_followups.tick(NOW, False, 10))
    token = intent.remote_request.set(True)
    try:
        assert followup_commands.match_turn("not now", remote=True) is None
    finally:
        intent.remote_request.reset(token)
    result = asyncio.run(intent.try_system_action("why this followup", "openrouter"))
    assert result.success and "saved task" in result.message
    result = asyncio.run(intent.try_system_action("not now", "openrouter"))
    assert result.success and "24 hours" in result.message
    assert task_followups.offer(NOW + timedelta(hours=5)) is None


@pytest.mark.parametrize("guard", ["busy", "typing", "away", "mic", "freewill", "nudges", "review", "pending"])
def test_attention_and_owner_switches_hold_task_help(delivery, monkeypatch, guard):
    from core.config import config
    from services.mind import task_followups, talk
    from services.proactive import watcher
    task = workspace.start_task("Review code")
    age_task(task)
    busy, idle = guard == "busy", 0 if guard == "typing" else 600 if guard == "away" else 10
    if guard == "mic":
        monkeypatch.setattr(talk, "mic_in_use", lambda: True)
    elif guard == "freewill":
        talk.set_on(False)
    elif guard == "nudges":
        watcher.run_proactive_command({"action": "nudges_off"})
    elif guard == "review":
        monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", False)
    elif guard == "pending":
        talk._save({"pending": {"at": NOW.timestamp()}})
    assert not asyncio.run(task_followups.tick(NOW, busy, idle))
    assert delivery == []
    with task_followups._db() as db:
        assert db.execute("SELECT COUNT(*) FROM workspace_followups").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["stop", "priority", "goal", "busy"])
def test_final_recheck_honors_changes_during_review(delivery, monkeypatch, change):
    from services.mind import task_followups, notifications
    from services.proactive import watcher
    goal = workspace.add_goal("Ship FRIDAY", "high")
    task = workspace.start_task("Review code", goal)
    age_task(task)
    async def changed(candidates, now, observations):
        if change == "stop":
            task_followups.control("stop", task, NOW)
        elif change == "priority":
            workspace.goal_state(goal, priority="low")
        elif change == "goal":
            workspace.goal_state(goal, "paused")
        else:
            monkeypatch.setattr(watcher, "is_busy", lambda: True)
        return [notifications.Choice(id="0", send=True, reason="Review task")]
    monkeypatch.setattr(notifications, "_reason", changed)
    asyncio.run(task_followups.tick(NOW, False, 10))
    assert delivery == []


def test_budget_and_ignored_followup_backoff_survive_fresh_calls():
    from services.mind import task_followups
    tasks = [workspace.start_task(f"Task {i}") for i in range(4)]
    for task in tasks:
        age_task(task)
    first = task_followups.offer(NOW)
    task_followups.claim(first["token"], NOW)
    task_followups.settle(first["token"], "submitted", None, NOW)
    assert task_followups.offer(NOW + timedelta(hours=3)) is None
    second_time = NOW + timedelta(hours=4)
    second = task_followups.offer(second_time)
    assert second["task_id"] != first["task_id"]
    task_followups.claim(second["token"], second_time)
    task_followups.settle(second["token"], "submitted", None, second_time)
    assert task_followups.offer(NOW + timedelta(hours=8)) is None  # two on this local day
    # Isolate one task to show longer gaps after repeated unanswered submissions.
    for task in tasks[1:]:
        task_followups.control("stop", task, NOW)
    again_time = NOW + timedelta(days=1)
    again = task_followups.offer(again_time)
    assert again["task_id"] == tasks[0]
    task_followups.claim(again["token"], again_time)
    task_followups.settle(again["token"], "submitted", None, again_time)
    assert task_followups.offer(NOW + timedelta(days=2)) is None
    assert task_followups.offer(NOW + timedelta(days=3))


def test_provider_review_attempts_are_bounded_even_when_all_are_withheld():
    from services.mind import task_followups
    task = workspace.start_task("Review code")
    age_task(task)
    for hour in range(4):
        now = NOW + timedelta(hours=hour)
        offer = task_followups.offer(now)
        assert offer
        task_followups.settle(offer["token"], "withheld", None, now)
    assert task_followups.offer(NOW + timedelta(hours=4)) is None


@pytest.mark.parametrize("accepted,expected", [(False, "failed"), (None, "uncertain")])
def test_failed_or_unknown_transport_never_creates_reply_context(delivery, monkeypatch, accepted, expected):
    from services.mind import task_followups, reference_context
    from services.proactive import watcher
    task = workspace.start_task("Review code")
    age_task(task)
    monkeypatch.setattr(watcher, "show_toast", lambda *a, **kw: accepted)
    asyncio.run(task_followups.tick(NOW, False, 10))
    with task_followups._db() as db:
        assert db.execute("SELECT state FROM workspace_followups").fetchone()[0] == expected
        assert reference_context.read(db, "task_followup") is None
    assert task_followups.offer(NOW + timedelta(hours=5)) is None


def test_cross_process_restart_preserves_feedback_context_and_mute(delivery):
    import subprocess
    import sys
    from core.config import config
    from services.mind import task_followups
    from services.mind.cognition import cognition
    task = workspace.start_task("Review code")
    age_task(task)
    asyncio.run(task_followups.tick(NOW, False, 10))
    script = '''
import logging,sys
from pathlib import Path
from datetime import datetime
from core.config import config
from core.logger import logger
for handler in list(logger.handlers):
    if isinstance(handler,logging.FileHandler):
        logger.removeHandler(handler)
        handler.close()
config.MEMORY_DIR=Path(sys.argv[2])
from services.mind.cognition import cognition
cognition.path=Path(sys.argv[1])
from services.mind import followup_commands
class Clock(datetime):
    @classmethod
    def now(cls,tz=None): return datetime(2026,10,18,14)
followup_commands.datetime=Clock
parsed=followup_commands.match_turn("stop asking about this")
print("STOPPED="+str(followup_commands.run(parsed).success))
'''
    child = subprocess.run([sys.executable, "-c", script, str(cognition.path), str(config.MEMORY_DIR)],
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert "STOPPED=True" in child.stdout
    assert task_followups.offer(NOW + timedelta(days=5)) is None


def test_parallel_selection_and_delivery_claims_are_once_only():
    from concurrent.futures import ThreadPoolExecutor
    from services.mind import task_followups
    task = workspace.start_task("Review code")
    age_task(task)
    with ThreadPoolExecutor(max_workers=2) as pool:
        offers = list(pool.map(task_followups.offer, [NOW, NOW]))
    offered = [item for item in offers if item]
    assert len(offered) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: task_followups.claim(offered[0]["token"], NOW), range(2)))
    assert sum(claims) == 1


def test_context_expires_on_unrelated_turn_and_workspace_clear(delivery):
    from services.mind import task_followups, followup_commands, conversation_context
    task = workspace.start_task("Review code")
    age_task(task)
    asyncio.run(task_followups.tick(NOW, False, 10))
    assert followup_commands.match_turn("not now")
    conversation_context.observe("what is the weather")
    assert followup_commands.match_turn("not now") is None
    workspace.clear()
    with task_followups._db() as db:
        assert not db.execute("SELECT * FROM workspace_followups").fetchall()
        assert not db.execute("SELECT * FROM workspace_followup_preferences").fetchall()


def test_brain_receives_the_exact_selected_task_even_outside_shared_top_five(delivery, monkeypatch):
    import json
    from types import SimpleNamespace
    from providers import failover
    from services.mind import task_followups, notifications
    goal = workspace.add_goal("Ship FRIDAY", "high")
    task = workspace.start_task("Review old important code", goal)
    age_task(task)
    for i in range(6):
        workspace.start_task(f"Recent task {i}")
    assert task not in [t["id"] for t in workspace.context()["tasks"]]
    async def decide(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        evidence = payload["candidates"][0]["evidence"]
        assert evidence["task"]["id"] == task and evidence["goal"]["priority"] == 3
        assert evidence["source"] == "owner_saved_workspace"
        assert kwargs["purpose"] == "notification_review"
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":true,"reason":"Useful saved next step"}]}')
    monkeypatch.setattr(notifications, "_reason", REAL_REASON)
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    asyncio.run(task_followups.tick(NOW, False, 10))
    assert len(delivery) == 1


def test_selected_task_outside_shared_context_is_still_rechecked(delivery, monkeypatch):
    from services.mind import task_followups, notifications
    goal = workspace.add_goal("Ship FRIDAY", "high")
    task = workspace.start_task("Review old important code", goal)
    age_task(task)
    for i in range(6):
        workspace.start_task(f"Recent task {i}")
    before = workspace.context()
    async def changed(candidates, now, observations):
        with workspace._db() as db:
            db.execute("UPDATE workspace_tasks SET blocker='Different blocker',updated=updated-1 WHERE id=?", (task,))
        assert workspace.context() == before
        return [notifications.Choice(id="0", send=True, reason="Useful followup")]
    monkeypatch.setattr(notifications, "_reason", changed)
    asyncio.run(task_followups.tick(NOW, False, 10))
    assert delivery == []


def test_short_reference_expires_and_cannot_be_replayed(delivery, monkeypatch):
    from services.mind import task_followups, reference_context, followup_commands
    task = workspace.start_task("Review code")
    age_task(task)
    asyncio.run(task_followups.tick(NOW, False, 10))
    parsed = followup_commands.match_turn("not now")
    now = reference_context.time.time()
    monkeypatch.setattr(reference_context.time, "time", lambda: now + reference_context.TTL_SECONDS + 1)
    assert followup_commands.match_turn("not now") is None
    assert not followup_commands.run(parsed).success


def test_chat_and_voice_controls_bypass_search_learning_and_general_models(delivery, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    def forbidden(*a, **kw):
        pytest.fail("Task followup control entered search, learning or general model generation")
    for route in (chat, voice):
        for name in ("build_file_context", "build_search_context", "extract_screen_question", "complete_with_failover"):
            monkeypatch.setattr(route, name, forbidden)
    monkeypatch.setattr(chat.talk, "hear", forbidden)
    monkeypatch.setattr(chat.humour, "hear", forbidden)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/chat", json={"message": "stop task followups"})
    assert result.status_code == 200 and result.json()["action_success"]
    result = asyncio.run(voice._reply("show task followups", voice.VoiceRequest(speak=False)))
    assert result.action_success and "stopped" in result.response
