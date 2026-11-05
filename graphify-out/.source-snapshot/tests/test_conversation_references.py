"""Real local workflows; OS opening is replaced at the Windows boundary."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.config import config
from services.automation import intent
from services.files import assistant
from services.files.search import FileHit
from services.mind import execution
from services.mind.workspace import workspace


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


@pytest.fixture
def local(tmp_path, monkeypatch):
    runner = execution.ExecutionEngine(workspace, tmp_path / "handoffs")
    monkeypatch.setattr(execution, "executions", runner)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "FILE_SEARCH_ENABLED", True)
    hits = []
    for name in ("project.pdf", "project-notes.pdf"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        hits.append(FileHit(str(path), name))
    monkeypatch.setattr(assistant, "find_files", lambda q: hits)
    opened = []
    monkeypatch.setattr(assistant.os, "startfile", opened.append)
    return runner, hits, opened


def test_file_pronoun_asks_then_opens_the_offered_choice(local):
    _, hits, opened = local
    assert say("find my project pdf").success
    result = say("open that one")
    assert not result.success and "Which file" in result.message
    assert opened == []
    assert say("the second one").success
    assert opened == [hits[1].path]
    assert say("open it").success
    assert opened == [hits[1].path, hits[1].path]


def test_file_results_and_selected_target_survive_a_new_client(local, monkeypatch):
    _, hits, opened = local
    say("find my project pdf")
    assert say("open 2").success
    monkeypatch.setattr(assistant, "last_results", assistant._LastResults())
    assert say("open that one").success
    assert opened == [hits[1].path, hits[1].path]


def test_file_correction_selects_without_opening_and_other_is_unambiguous(local):
    _, hits, opened = local
    say("find my project pdf")
    assert say("actually, use project-notes.pdf instead").success
    assert opened == []
    assert say("open it").success
    assert opened == [hits[1].path]
    assert say("actually use the other file").success
    assert say("open it").success
    assert opened[-1] == hits[0].path


def test_replaced_file_is_refused(local):
    _, hits, opened = local
    say("find my project pdf")
    Path(hits[0].path).write_bytes(b"different file contents")
    result = say("open 1")
    assert not result.success and "changed" in result.message.lower()
    assert opened == []


def test_handoff_correction_publishes_new_artifact_and_preserves_old(local):
    runner, _, _ = local
    login = workspace.start_task("login bug")
    notification = workspace.start_task("notification bug")
    assert say("prepare a handoff for the login bug").success
    first = runner.get(1)
    assert say("actually, use the notification bug").success
    second = runner.get(2)
    assert first["task_id"] == login and second["task_id"] == notification
    assert runner.get(1)["verified"] and second["verified"]
    assert first["artifact"] != second["artifact"]
    assert workspace.tasks()[0]["status"] == "active"


def test_handoff_ambiguity_waits_for_choice_and_survives_restart(local, monkeypatch):
    runner, _, _ = local
    workspace.start_task("login bug")
    expected = workspace.start_task("notification bug")
    result = say("prepare a handoff for bug")
    assert not result.success and "Which task" in result.message
    monkeypatch.setattr(execution, "executions", execution.ExecutionEngine(workspace, runner.output_dir))
    assert say("notification bug").success
    assert runner.get(1)["task_id"] == expected


def test_remote_turn_does_not_consume_laptop_handoff_choice(local):
    runner, _, _ = local
    workspace.start_task("login bug")
    chosen = workspace.start_task("notification bug")
    say("prepare a handoff for bug")
    token = intent.remote_request.set(True)
    try:
        result = say("actually use the notification bug")
        assert result is None or not result.success
    finally:
        intent.remote_request.reset(token)
    assert say("notification bug").success
    assert runner.get(1)["task_id"] == chosen


def test_unrelated_turn_retires_short_handoff_correction(local):
    runner, _, _ = local
    workspace.start_task("login bug")
    workspace.start_task("notification bug")
    assert say("prepare a handoff for login bug").success
    assert say("what is the date and time").success
    result = say("actually use the notification bug")
    assert result is None or not result.success
    with pytest.raises(ValueError):
        runner.get(2)


def test_expired_references_do_not_execute(local, monkeypatch):
    from services.mind import reference_context
    runner, _, opened = local
    workspace.start_task("login bug")
    workspace.start_task("notification bug")
    assert say("prepare a handoff for login bug").success
    now = reference_context.time.time()
    monkeypatch.setattr(reference_context.time, "time", lambda: now + reference_context.TTL_SECONDS + 1)
    result = say("actually use the notification bug")
    assert result is None or not result.success
    with pytest.raises(ValueError):
        runner.get(2)
    say("find my project pdf")
    now += reference_context.TTL_SECONDS + 2
    result = say("open that one")
    assert result is None or not result.success
    assert opened == []


def test_changed_offered_task_requires_a_fresh_request(local):
    runner, _, _ = local
    workspace.start_task("login bug")
    chosen = workspace.start_task("notification bug")
    assert not say("prepare a handoff for bug").success
    workspace.plan(chosen, ["new step"])
    result = say("notification bug")
    assert not result.success and "changed" in result.message
    with pytest.raises(ValueError):
        runner.get(1)


def test_handoff_correction_to_a_task_named_project(local):
    runner, _, _ = local
    workspace.start_task("login bug")
    other = workspace.start_task("college project")
    assert say("prepare a handoff for login bug").success
    assert say("actually use the college project").success
    assert runner.get(2)["task_id"] == other


def test_stale_file_choice_cannot_open_new_results(local):
    _, hits, opened = local
    say("find my project pdf")
    parsed = assistant.match_file_command("open 2")
    assistant.last_results.set(list(reversed(hits)))
    result = intent._execute(parsed)
    assert not result.success and "changed" in result.message
    assert opened == []


def test_history_clear_retires_both_reference_types(local, monkeypatch):
    from types import SimpleNamespace
    from interfaces.api.routes import chat
    runner, _, opened = local
    workspace.start_task("login bug")
    workspace.start_task("notification bug")
    say("prepare a handoff for login bug")
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(clear_history=lambda: None))
    asyncio.run(chat.clear_history())
    result = say("actually use the notification bug")
    assert result is None or not result.success
    with pytest.raises(ValueError):
        runner.get(2)
    say("find my project pdf")
    assert say("open 2").success
    asyncio.run(chat.clear_history())
    assert assistant.last_results.get() == []


def test_file_choice_rejects_an_unknown_name_and_keeps_pending_request(local):
    _, hits, opened = local
    say("find my project pdf")
    assert not say("open that one").success
    result = say("actually use missing.pdf")
    assert result is not None and not result.success
    assert say("the second one").success
    assert opened == [hits[1].path]


def test_chat_and_voice_share_choices_without_search_or_question_learning(local, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    runner, hits, opened = local
    stored = []
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: stored.append(a)))
    def forbidden(*a, **kw):
        pytest.fail("Reference turn entered search, screen interpretation or learning")
    for route in (chat, voice):
        for name in ("build_file_context", "build_search_context", "extract_screen_question", "complete_with_failover"):
            monkeypatch.setattr(route, name, forbidden)
    monkeypatch.setattr(chat.talk, "hear", forbidden)
    monkeypatch.setattr(chat.humour, "hear", forbidden)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    def typed(text):
        response = client.post("/api/v1/chat", json={"message": text})
        assert response.status_code == 200
        return response.json()
    assert typed("find my project pdf")["action_success"]
    reply = asyncio.run(voice._reply("open that one", voice.VoiceRequest(speak=False)))
    assert not reply.action_success
    assert typed("project-notes.pdf")["action_success"]
    assert opened == [hits[1].path]
    workspace.start_task("login bug")
    notification = workspace.start_task("notification bug")
    assert typed("prepare a handoff for bug")["action_success"] is False
    reply = asyncio.run(voice._reply("notification bug", voice.VoiceRequest(speak=False)))
    assert reply.action_success and runner.get(1)["task_id"] == notification
    assert typed("actually, use the login bug")["action_success"]
    assert runner.get(2)["verified"]
    assert str(runner.output_dir) not in str(stored)


def test_file_selection_and_pending_handoff_are_read_by_another_process(local):
    from services.mind.cognition import cognition
    runner, hits, _ = local
    say("find my project pdf")
    assert say("actually use project-notes.pdf").success
    script = '''
import json, logging, sys
from pathlib import Path
from core.logger import logger
for handler in list(logger.handlers):
    if isinstance(handler, logging.FileHandler):
        logger.removeHandler(handler)
        handler.close()
from services.mind.cognition import cognition
cognition.path = Path(sys.argv[1])
from services.files import assistant
print("RESULT=" + json.dumps(assistant.last_results.selected.path))
'''
    child = subprocess.run([sys.executable, "-c", script, str(cognition.path)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert json.loads(next(line[7:] for line in child.stdout.splitlines() if line.startswith("RESULT="))) == hits[1].path
    workspace.start_task("login bug")
    expected = workspace.start_task("notification bug")
    assert not say("prepare a handoff for bug").success
    script = '''
import json, logging, sys
from pathlib import Path
from core.logger import logger
for handler in list(logger.handlers):
    if isinstance(handler, logging.FileHandler):
        logger.removeHandler(handler)
        handler.close()
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.mind import execution, handoff_context
from services.memory import notes
notes.path = Path(sys.argv[2]) / "no-notes.json"
execution.executions = execution.ExecutionEngine(Workspace(Cognition(Path(sys.argv[1]))), sys.argv[2])
reply = handoff_context.run(handoff_context.match_turn("notification bug"))
print("RESULT=" + json.dumps(reply.success))
'''
    child = subprocess.run([sys.executable, "-c", script, str(cognition.path), str(runner.output_dir)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert "RESULT=true" in child.stdout
    assert runner.get(1)["verified"] and runner.get(1)["task_id"] == expected


def test_replayed_file_snapshot_is_claimed_before_os_open(local, monkeypatch):
    _, hits, opened = local
    say("find my project pdf")
    parsed = assistant.match_file_command("open 2")
    def open_once(path):
        opened.append(path)
        replay = intent._execute(parsed)
        assert not replay.success
    monkeypatch.setattr(assistant.os, "startfile", open_once)
    assert intent._execute(parsed).success
    assert opened == [hits[1].path]


def test_stale_handoff_turn_cannot_replace_a_newer_context(local):
    from services.mind import handoff_context
    runner, _, _ = local
    workspace.start_task("login bug")
    workspace.start_task("notification bug")
    say("prepare a handoff for login bug")
    parsed = handoff_context.match_turn("actually use the notification bug")
    say("prepare a handoff for login bug")
    result = handoff_context.run(parsed)
    assert not result.success and "changed" in result.message
    assert runner.get(2)["verified"]
    with pytest.raises(ValueError):
        runner.get(3)


def test_a_late_handoff_completion_does_not_restore_retired_context(local, monkeypatch):
    from services.mind import conversation_context, handoff_context
    runner, _, _ = local
    workspace.start_task("login bug")
    original = runner.run
    def finish_after_topic_change(ident):
        row = original(ident)
        conversation_context.observe("what is the date and time")
        return row
    monkeypatch.setattr(runner, "run", finish_after_topic_change)
    assert say("prepare a handoff for login bug").success
    assert handoff_context.read(runner) is None


def test_handoff_correction_cancels_a_blocked_job(local):
    from services.memory import notes
    runner, _, _ = local
    workspace.start_task("login bug")
    other = workspace.start_task("notification bug")
    notes.path.write_text("invalid JSON", encoding="utf-8")
    assert not say("prepare a handoff for login bug").success
    assert runner.get(1)["state"] == "blocked"
    notes.path.write_text("[]", encoding="utf-8")
    assert say("actually use the notification bug").success
    assert runner.get(1)["state"] == "cancelled"
    assert runner.run(1, resume=True)["state"] == "cancelled"
    assert runner.get(2)["task_id"] == other and runner.get(2)["verified"]


def test_unrelated_laptop_turn_clears_only_laptop_file_references(local):
    _, hits, opened = local
    say("find my project pdf")
    token = intent.remote_request.set(True)
    try:
        assistant.last_results.set([hits[1]])
    finally:
        intent.remote_request.reset(token)
    assert say("what is the date and time").success
    assert assistant.last_results.get() == []
    token = intent.remote_request.set(True)
    try:
        assert assistant.last_results.get() == [hits[1]]
    finally:
        intent.remote_request.reset(token)
    assert opened == []


def test_duplicate_task_names_require_an_offered_ordinal(local):
    runner, _, _ = local
    workspace.start_task("login bug")
    second = workspace.start_task("login bug")
    assert not say("prepare a handoff for login bug").success
    assert not say("login bug").success
    assert say("the first one").success
    assert runner.get(1)["task_id"] == second
