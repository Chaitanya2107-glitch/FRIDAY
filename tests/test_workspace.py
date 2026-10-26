import asyncio
from types import SimpleNamespace

import pytest

from services.mind.cognition import Cognition, cognition


def test_goals_survive_restart_and_rank_by_owner_priority():
    from services.mind.workspace import Workspace, workspace
    low = workspace.add_goal("Learn guitar", "low")
    high = workspace.add_goal("Prepare for placement", "high")
    restarted = Workspace(Cognition(cognition.path))
    assert [g["id"] for g in restarted.goals()] == [high, low]
    workspace.goal_state(high, "paused")
    assert [g["id"] for g in restarted.goals()] == [low]
    workspace.goal_state(high, "active")
    assert restarted.goals()[0]["id"] == high


def test_task_plan_block_resume_and_owner_evidence_survive_restart():
    from services.mind.workspace import Workspace, workspace
    goal = workspace.add_goal("Build a portfolio")
    task = workspace.start_task("Publish portfolio", goal)
    workspace.plan(task, ["Write content", "Review", "Publish"])
    workspace.advance(task, "Content saved in my draft")
    workspace.task_state(task, "blocked", "Waiting for photos")
    restarted = Workspace(Cognition(cognition.path))
    saved = restarted.tasks()[0]
    assert saved["status"] == "blocked" and saved["cursor"] == 1
    assert saved["blocker"] == "Waiting for photos"
    assert saved["evidence"][0]["source"] == "owner_report"
    workspace.task_state(task, "active")
    workspace.advance(task, "Reviewed spelling")
    workspace.advance(task, "I checked the published site")
    assert restarted.tasks(include_finished=True)[0]["status"] == "completed"


def test_completion_cannot_erase_unfinished_plan_and_requires_evidence():
    from services.mind.workspace import workspace
    task = workspace.start_task("Test deployment")
    workspace.plan(task, ["Run tests", "Check health"])
    with pytest.raises(ValueError):
        workspace.task_state(task, "completed", "done")
    with pytest.raises(ValueError):
        workspace.advance(task, "")
    workspace.advance(task, "Tests passed")
    with pytest.raises(ValueError):
        workspace.plan(task, ["Forget old progress"])
    with pytest.raises(ValueError):
        workspace.start_task("Orphan", 999)


def test_goal_and_task_retention_is_separate_from_event_history(monkeypatch):
    from core.config import config
    from services.mind.workspace import workspace
    monkeypatch.setattr(config, "COGNITION_MAX_EVENTS", 2)
    workspace.add_goal("Keep this goal")
    workspace.start_task("Keep this task")
    for _ in range(5):
        cognition.record("observation", "activity", "changed")
    assert workspace.goals() and workspace.tasks()
    cognition.clear()
    assert workspace.goals() and workspace.tasks()
    workspace.clear()
    assert not workspace.goals() and not workspace.tasks()


def test_prompt_and_brain_share_goals_tasks_without_claiming_permissions(monkeypatch):
    from core.config import config
    from services.mind import brain, cognition_context
    from services.mind.workspace import workspace
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-secret-goal")
    workspace.add_goal("Prepare for interviews test-secret-goal", "high")
    task = workspace.start_task("Practise algorithms")
    workspace.plan(task, ["Arrays", "Graphs"])
    context = workspace.context()
    assert "test-secret-goal" not in str(context)
    prompt = cognition_context.prompt_section()
    assert "Practise algorithms" in prompt and "Arrays" in prompt
    assert "not permission" in prompt
    assert len(prompt) <= config.COGNITION_PROMPT_CHARS
    assert brain.awareness()["workspace"] == context


def test_explicit_commands_are_local_and_do_not_consume_pending_questions(monkeypatch, tmp_path):
    from services.automation.intent import try_system_action
    from services.mind import talk, workspace_commands
    from services.mind.workspace import workspace
    assert workspace_commands.match_command("add goal high: Learn cooking")
    assert not workspace_commands.match_command("if I add goal high: Learn cooking")
    assert not workspace_commands.match_command("type add goal high: Learn cooking")
    assert workspace_commands.match_command("please add goal high: Improve Friday!")["title"] == "Improve Friday!"
    result = asyncio.run(try_system_action("add goal high: Learn cooking", "unavailable"))
    assert result.success and workspace.goals()[0]["title"] == "Learn cooking"
    from interfaces.api.routes import chat
    from services.memory.sqlite_memory import MemoryService
    monkeypatch.setattr(chat, "_memory", MemoryService(str(tmp_path / "workspace_chat.db")))
    monkeypatch.setattr(talk, "hear", lambda _: pytest.fail("workspace command consumed pending question"))
    answer = asyncio.run(chat.chat(chat.ChatRequest(message="please show my goals", speak=False)))
    assert answer.model == "system_control" and "Learn cooking" in answer.response


def test_read_only_api_exposes_inventory_and_bounded_workspace():
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from services.mind.workspace import workspace
    workspace.add_goal("Read more novels")
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    assert len(client.get("/api/v1/mind/layers").json()["layers"]) == 10
    assert client.get("/api/v1/mind/workspace").json()["goals"][0]["title"] == "Read more novels"


def test_layer_inventory_has_ten_real_foundations():
    from services.mind.layers import inventory
    layers = inventory()
    assert len(layers) == 10
    assert all(layer["modules"] and layer["limits"] for layer in layers)
    from services.mind import cognition_commands
    result = cognition_commands.run(cognition_commands.match_command("brain layers"))
    assert result.success and "Goals and motivation" in result.message


def test_notification_reasoning_receives_arbitrary_goals_and_task_progress(monkeypatch):
    from services.mind.workspace import workspace
    from services.mind import notifications
    from providers import failover
    workspace.add_goal("Learn gardening", "high")
    task = workspace.start_task("Plant tomatoes")
    workspace.plan(task, ["Buy seeds", "Plant seeds"])
    captured = {}
    async def complete(provider, messages, prompt, max_tokens, **kwargs):
        captured["payload"] = messages[0].content
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":false,"reason":"Focus on current task"}]}')
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    # conftest replaces _reason, so call the module's saved implementation.
    from datetime import datetime
    result = asyncio.run(REAL_REASON([notifications.Candidate("Take a break")], datetime.now(), {}))
    assert not result[0].send
    assert "Learn gardening" in captured["payload"] and "Buy seeds" in captured["payload"]


from services.mind.notifications import _reason as REAL_REASON
