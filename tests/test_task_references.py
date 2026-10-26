import asyncio

import pytest

from core.config import config
from services.automation import intent
from services.mind import workspace_commands
from services.mind.cognition import Cognition, cognition
from services.mind.workspace import Workspace, workspace


@pytest.fixture
def local(tmp_path, monkeypatch):
    from services.mind import execution
    runner = execution.ExecutionEngine(workspace, tmp_path / "handoffs")
    monkeypatch.setattr(execution, "executions", runner)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    async def forbidden(*a, **kw):
        pytest.fail("Task reference called a model")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    return runner


def say(message):
    return asyncio.run(intent.try_system_action(message, "openrouter"))


def test_prepare_handoff_by_name_and_read_latest_without_ids(local):
    workspace.start_task("DBMS revision")
    source = workspace.start_task("FRIDAY project")
    reply = say("prepare a handoff for my FRIDAY project")
    assert reply.success and "FRIDAY project" in reply.message and "Verified" in reply.message
    assert local.get(1)["task_id"] == source
    assert say("check the latest handoff").success
    assert say("check the handoff").success
    assert say("resume the handoff").success


def test_new_task_becomes_current_and_focus_survives_restart(local):
    say("start task: DBMS revision")
    say("start task: FRIDAY project")
    assert "FRIDAY project" in say("prepare a handoff for my current task").message
    restarted = Workspace(Cognition(cognition.path))
    assert restarted.resolve("task", "current task")["title"] == "FRIDAY project"
    assert restarted.resolve("execution", "the handoff")["title"] == "FRIDAY project"


def test_unique_task_is_used_when_no_name_is_given(local):
    workspace.start_task("FRIDAY project")
    assert say("prepare a handoff").success


def test_ambiguous_task_names_ask_instead_of_creating_an_execution(local):
    workspace.start_task("FRIDAY UI project")
    workspace.start_task("FRIDAY voice project")
    result = say("prepare a handoff for FRIDAY")
    assert not result.success and "Which task" in result.message
    assert "FRIDAY UI project" in result.message and "FRIDAY voice project" in result.message
    with pytest.raises(ValueError):
        local.get(1)


def test_current_task_is_not_guessed_from_recency_without_focus(local):
    workspace.start_task("FRIDAY project")
    workspace.start_task("DBMS revision")
    assert "Which task" in say("prepare a handoff for my current task").message


def test_exact_name_wins_over_partial_names_and_latest_is_explicit(local):
    first = workspace.start_task("FRIDAY")
    workspace.start_task("FRIDAY project")
    assert workspace.resolve("task", "FRIDAY")["id"] == first
    assert workspace.resolve("task", "latest task")["title"] == "FRIDAY project"


def test_handoff_name_selects_latest_for_that_task_not_another_task(local):
    friday = workspace.start_task("FRIDAY project")
    dbms = workspace.start_task("DBMS revision")
    first = local.run(local.create(friday))
    second = local.run(local.create(friday))
    local.run(local.create(dbms))
    assert workspace.resolve("execution", "FRIDAY project")["id"] == second["id"]
    assert workspace.resolve("execution", str(first["id"]))["id"] == first["id"]
    assert "FRIDAY project" in say("check the handoff for FRIDAY project").message


def test_named_workspace_controls_and_goal_linking_work_locally(local):
    assert say("add goal high: Build Friday").success
    assert say("start task for goal Build Friday: FRIDAY project").success
    task = workspace.tasks()[0]
    assert task["goal_id"] == workspace.goals()[0]["id"]
    assert say("plan task FRIDAY project: Review; Test").success
    assert say("finish task step FRIDAY project: Review finished").success
    assert say("block task FRIDAY project: Waiting for feedback").success
    assert workspace.tasks()[0]["status"] == "blocked"
    assert say("resume task current").success
    assert say("set goal Build Friday priority low").success
    assert workspace.goals()[0]["priority"] == 1


def test_cancel_handoff_uses_focus_and_does_not_cancel_other_jobs(local):
    source = workspace.start_task("FRIDAY project")
    other = local.create(source)
    selected = local.create(source)
    workspace.focus("execution", selected)
    assert say("cancel the handoff").success
    assert local.get(selected)["state"] == "cancelled"
    assert local.get(other)["state"] == "pending"


def test_clear_removes_focus_and_never_retargets_a_stale_reference(local):
    say("start task: FRIDAY project")
    assert say("prepare a handoff").success
    workspace.clear()
    assert not say("check the handoff").success


def test_remote_workspace_focus_is_separate_from_laptop_focus(local):
    say("start task: FRIDAY project")
    token = intent.remote_request.set(True)
    try:
        say("start task: DBMS revision")
        assert not say("check the latest handoff").success
    finally:
        intent.remote_request.reset(token)
    assert workspace.resolve("task", "current")["title"] == "FRIDAY project"
    assert workspace.resolve("task", "current", scope="remote")["title"] == "DBMS revision"


def test_reference_syntax_does_not_consume_literal_or_hypothetical_text():
    from services.mind import execution_commands
    assert not execution_commands.match_command("type prepare a handoff for my current task")
    assert not execution_commands.match_command("if I prepare a handoff for FRIDAY")
    assert not workspace_commands.match_command("note cancel task FRIDAY project")


def test_zero_id_does_not_fall_back_to_current_handoff(local):
    source = workspace.start_task("FRIDAY project")
    job = local.create(source)
    workspace.focus("execution", job)
    assert not say("cancel execution 0").success
    assert local.get(job)["state"] == "pending"


def test_completed_focus_never_retargets_a_different_active_task(local):
    say("start task: First project")
    first = workspace.resolve("task", "current")["id"]
    say("start task: Second project")
    say("complete task First project: Finished review")
    assert not say("cancel task current").success
    assert workspace.resolve("task", "current")["id"] == first
    assert workspace.resolve("task", "Second project")["status"] == "active"


def test_latest_named_resolves_duplicate_titles_only_when_explicit(local):
    workspace.start_task("FRIDAY project")
    latest = workspace.start_task("FRIDAY project")
    with pytest.raises(ValueError, match="Which task"):
        workspace.resolve("task", "FRIDAY project")
    assert workspace.resolve("task", "latest FRIDAY project")["id"] == latest


def test_named_handoffs_work_through_chat_and_voice_and_preserve_friday_names(local, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    workspace.start_task("FRIDAY")
    workspace.start_task("DBMS revision")
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/chat", json={"message": "prepare a handoff for FRIDAY"})
    assert result.status_code == 200
    assert 'Handoff for "FRIDAY"' in result.json()["response"]
    assert "Verified" in result.json()["response"]
    spoken = asyncio.run(voice._reply("check the latest handoff", voice.VoiceRequest(speak=False)))
    assert 'Handoff for "FRIDAY"' in spoken.response and "Verified" in spoken.response
