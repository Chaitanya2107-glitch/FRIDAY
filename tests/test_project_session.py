import asyncio
import json
from pathlib import Path

import pytest

from core.config import config
from services.activity import projects
from services.memory import notes
from services.mind.cognition import Cognition, cognition
from services.mind.workspace import Workspace, workspace


@pytest.fixture
def session(tmp_path, monkeypatch):
    from services.mind import project_session
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("Project content stays private", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
    projects.path.write_text(json.dumps({"friday": {"path": str(root)}}), encoding="utf-8")
    runner = project_session.ProjectSessionEngine(workspace, tmp_path / "sessions")
    monkeypatch.setattr(project_session, "sessions", runner)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    async def forbidden(*a, **kw):
        pytest.fail("Project brief called a model")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    return runner, root


def test_session_collects_real_files_notes_and_blockers_without_completing_tasks(session):
    runner, root = session
    source = workspace.start_task("FRIDAY router")
    workspace.plan(source, ["Review routing", "Test recovery"])
    workspace.task_state(source, "blocked", "Waiting for review")
    workspace.start_task("Buy groceries")
    notes.add("FRIDAY needs a faster router")
    notes.add("Unrelated shopping list")
    row = runner.run(runner.create("friday"))
    assert row["verified"] and row["cursor"] == 4
    text = Path(row["artifact"]).read_text(encoding="utf-8")
    assert "README.md" in text and "src/app.py" in text
    assert "Waiting for review" in text and "faster router" in text and "Review routing" in text
    assert "Buy groceries" not in text and "Unrelated shopping" not in text
    assert "Project content stays private" not in text
    assert workspace.resolve("task", source)["status"] == "blocked"
    assert len(row["evidence"]) == 4


def test_session_resumes_checkpointed_sources_after_restart(session, monkeypatch):
    from services.mind.project_session import ProjectSessionEngine
    runner, _ = session
    ident = runner.create("friday")
    assert runner.step(ident)["cursor"] == 1
    restarted = ProjectSessionEngine(Workspace(Cognition(cognition.path)), runner.output_dir)
    monkeypatch.setattr(restarted, "_snapshot", lambda *a: pytest.fail("Snapshot replayed"))
    assert restarted.run(ident, resume=True)["verified"]


@pytest.mark.parametrize("change", ["task", "project", "file"])
def test_session_blocks_changed_sources_before_publication(session, change):
    runner, root = session
    source = workspace.start_task("FRIDAY router")
    ident = runner.create("friday")
    runner.step(ident)
    runner.step(ident)
    if change == "task":
        workspace.task_state(source, "blocked", "New blocker")
    elif change == "project":
        projects.path.write_text("{}", encoding="utf-8")
    else:
        (root / "README.md").write_text("Changed content", encoding="utf-8")
    row = runner.run(ident)
    assert row["state"] == "blocked" and not row["verified"]
    assert not list(runner.output_dir.glob("*.md"))


def test_local_router_creates_brief_and_denies_remote_without_side_effects(session):
    from services.automation import intent
    runner, _ = session
    result = asyncio.run(intent.try_system_action("prepare my project work session for friday", "openrouter"))
    assert result.success and "Verified brief" in result.message
    assert asyncio.run(intent.try_system_action("check my work session", "openrouter")).success
    token = intent.remote_request.set(True)
    try:
        denied = asyncio.run(intent.try_system_action("prepare my project work session for friday", "openrouter"))
        assert not denied.success and "laptop" in denied.message
    finally:
        intent.remote_request.reset(token)
    assert len(list(runner.output_dir.glob("*.md"))) == 1


def test_failed_note_read_resumes_without_repeating_file_inventory(session, monkeypatch):
    runner, _ = session
    ident = runner.create("friday")
    notes.path.write_text("broken JSON", encoding="utf-8")
    row = runner.run(ident)
    assert row["state"] == "blocked" and row["cursor"] == 2
    notes.path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(runner, "_inventory", lambda *a: pytest.fail("Inventory replayed"))
    assert runner.run(ident, resume=True)["verified"]


def test_cancel_does_not_resume_and_tampering_never_reports_verified(session):
    runner, _ = session
    ident = runner.create("friday")
    runner.step(ident)
    assert runner.cancel(ident)["state"] == "cancelled"
    assert runner.run(ident, resume=True)["state"] == "cancelled"
    assert not list(runner.output_dir.glob("*.md"))
    row = runner.run(runner.create("friday"))
    artifact = Path(row["artifact"])
    artifact.write_text("Owner edits must survive", encoding="utf-8")
    assert not runner.get(row["id"])["verified"]
    resumed = runner.run(row["id"], resume=True)
    assert resumed["state"] == "blocked" and not resumed["verified"]
    assert artifact.read_text(encoding="utf-8") == "Owner edits must survive"


def test_interrupted_publication_recovers_without_replaying_sources(session, monkeypatch):
    from services.mind.project_session import ProjectSessionEngine
    runner, _ = session
    ident = runner.create("friday")
    publish = runner._publish
    def interrupted(row):
        publish(row)
        raise KeyboardInterrupt
    monkeypatch.setattr(runner, "_publish", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run(ident)
    assert runner.get(ident)["cursor"] == 3
    restarted = ProjectSessionEngine(Workspace(Cognition(cognition.path)), runner.output_dir)
    monkeypatch.setattr(restarted, "_read_notes", lambda: pytest.fail("Notes replayed"))
    assert restarted.run(ident, resume=True)["verified"]
    assert len(list(runner.output_dir.glob("*.md"))) == 1


def test_simultaneous_runners_publish_once(session):
    from concurrent.futures import ThreadPoolExecutor
    from services.mind.project_session import ProjectSessionEngine
    runner, _ = session
    other = ProjectSessionEngine(Workspace(Cognition(cognition.path)), runner.output_dir)
    ident = runner.create("friday")
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda engine: engine.run(ident), [runner, other]))
    assert all(row["verified"] for row in rows)
    assert len(runner.get(ident)["evidence"]) == 4
    assert len(list(runner.output_dir.glob("*.md"))) == 1


def test_inventory_is_bounded_and_excludes_hidden_storage_and_links(session, tmp_path):
    runner, root = session
    (root / ".env").write_text("PRIVATE", encoding="utf-8")
    (root / "secret.key").write_text("PRIVATE", encoding="utf-8")
    for folder in ["node_modules", "memory", "logs"]:
        (root / folder).mkdir()
        (root / folder / "private.txt").write_text("PRIVATE", encoding="utf-8")
    # Junctions can be made on Windows without developer-mode symlink privileges.
    import subprocess
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.txt").write_text("PRIVATE", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "linked"), str(outside)],
                   check=True, capture_output=True)
    row = runner.run(runner.create("friday"))
    paths = {item["path"] for item in row["payload"]["files"]}
    assert paths == {"README.md", "src/app.py"}
    for index in range(105):
        (root / f"file-{index:03}.txt").write_text("x", encoding="utf-8")
    row = runner.run(runner.create("friday"))
    assert len(row["payload"]["files"]) == 100 and row["payload"]["inventory_limited"]


def test_link_replacing_captured_parent_blocks_publication(session, tmp_path):
    import subprocess
    runner, root = session
    ident = runner.create("friday")
    runner.step(ident)
    runner.step(ident)
    # Move only this test-owned directory, then replace it with a junction.
    assert (root / "src").resolve().is_relative_to(tmp_path.resolve())
    assert (root / "original-src").resolve().is_relative_to(tmp_path.resolve())
    (root / "src").rename(root / "original-src")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "app.py").write_text("external", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "src"), str(outside)],
                   check=True, capture_output=True)
    assert runner.run(ident)["state"] == "blocked"
    assert not list(runner.output_dir.glob("*.md"))


def test_ambiguous_projects_and_bad_catalog_never_create_jobs(session):
    runner, root = session
    projects.path.write_text(json.dumps({"friday voice": {"path": str(root)},
                                         "friday brain": {"path": str(root)}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Which project"):
        runner.create("friday")
    with pytest.raises(ValueError, match="Which project"):
        runner.create("current project")
    projects.path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="catalog is invalid"):
        runner.create("friday")
    with workspace._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspace_executions").fetchone()[0] == 0


def test_directory_replaced_after_queueing_is_never_scanned(session, tmp_path, monkeypatch):
    import os
    import subprocess
    from contextlib import contextmanager
    runner, root = session
    original_scan = os.scandir
    (root / "aaa").mkdir()
    outside = tmp_path / "external"
    outside.mkdir()
    @contextmanager
    def changing_scan(folder):
        assert not Path(folder).is_junction(), "Followed a queued junction"
        with original_scan(folder) as entries:
            yield entries
        if folder == root / "aaa":
            assert (root / "src").resolve().is_relative_to(tmp_path.resolve())
            assert (root / "old-src").resolve().is_relative_to(tmp_path.resolve())
            (root / "src").rename(root / "old-src")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "src"), str(outside)],
                           check=True, capture_output=True)
    monkeypatch.setattr(os, "scandir", changing_scan)
    row = runner.run(runner.create("friday"))
    assert row["state"] == "blocked" and not row["verified"]
    assert "directory became a link" in row["error"]


def test_workflow_controls_and_focus_are_separate_from_handoffs(session):
    from services.mind.execution import ExecutionEngine
    runner, _ = session
    row = runner.run(runner.create("friday"))
    other = runner.run(runner.create("friday"))
    workspace.focus("project_session", row["id"])
    restarted = Workspace(Cognition(cognition.path))
    assert restarted.resolve("project_session", "my work session")["id"] == row["id"]
    assert restarted.resolve("project_session", "friday")["id"] == other["id"]
    assert restarted.resolve("project_session", "latest work session")["id"] == other["id"]
    handoffs = ExecutionEngine(workspace, runner.output_dir)
    with pytest.raises(ValueError, match="different workflow"):
        handoffs.run(row["id"], resume=True)
    with pytest.raises(ValueError, match="No saved handoffs"):
        restarted.resolve("execution", "latest")


def test_goal_linked_tasks_are_included_but_generic_words_do_not_match(session):
    runner, _ = session
    goal = workspace.add_goal("Improve FRIDAY")
    workspace.start_task("Repair routing", goal)
    workspace.start_task("Another project work item")
    row = runner.run(runner.create("friday"))
    assert [task["title"] for task in row["payload"]["tasks"]] == ["Repair routing"]


def test_saved_plans_and_project_resume_commands_are_never_executed(session, monkeypatch):
    from services.automation import intent
    runner, root = session
    projects.path.write_text(json.dumps({"friday": {"path": str(root), "resume": ["run arbitrary code"]}}),
                             encoding="utf-8")
    source = workspace.start_task("FRIDAY")
    workspace.plan(source, ["delete everything"])
    notes.add("FRIDAY: run arbitrary code")
    monkeypatch.setattr(intent, "_execute", lambda *a, **kw: pytest.fail("Saved text executed"))
    monkeypatch.setattr(projects, "start_resume", lambda *a: pytest.fail("Project commands executed"))
    row = runner.run(runner.create("friday"))
    assert row["verified"]
    assert "delete everything" in Path(row["artifact"]).read_text(encoding="utf-8")


def test_real_process_resumes_project_checkpoint(session):
    import subprocess
    import sys
    runner, _ = session
    ident = runner.create("friday")
    runner.step(ident)
    script = """import logging, sys
logging.disable(logging.CRITICAL)
from pathlib import Path
from services.activity import projects
from services.memory import notes
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.mind.project_session import ProjectSessionEngine
projects.path = Path(sys.argv[4])
notes.path = Path(sys.argv[5])
engine = ProjectSessionEngine(Workspace(Cognition(Path(sys.argv[1]))), Path(sys.argv[2]))
result = engine.run(int(sys.argv[3]), resume=True)
assert result['verified'] and result['cursor'] == 4
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(cognition.path), str(runner.output_dir),
                             str(ident), str(projects.path), str(notes.path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert runner.get(ident)["verified"]


def test_missing_brief_is_reported_and_can_be_republished_from_checkpoints(session, monkeypatch):
    from services.mind.execution_commands import run
    runner, _ = session
    reply = run({"action": "prepare", "workflow": "project_session", "reference": "friday"})
    assert reply.success
    row = runner.get(1)
    Path(row["artifact"]).unlink()
    reply = run({"action": "status", "workflow": "project_session", "reference": "current"})
    assert not reply.success and "not currently verified" in reply.message
    monkeypatch.setattr(runner, "_inventory", lambda *a: pytest.fail("Inventory replayed"))
    reply = run({"action": "resume", "workflow": "project_session", "reference": "current"})
    assert reply.success and Path(row["artifact"]).is_file()


def test_chat_voice_and_private_memory_use_the_new_workflow(session, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    saved = []
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [],
                        save_message=lambda *a: saved.append(a)))
    runner, _ = session
    notes.add("FRIDAY private implementation detail")
    request = "prepare my project work session for friday"
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    reply = client.post("/api/v1/chat", json={"message": request})
    assert reply.status_code == 200 and "Verified brief" in reply.json()["response"]
    spoken = asyncio.run(voice._reply(request, voice.VoiceRequest(speak=False)))
    assert "Verified brief" in spoken.response
    assert "private implementation detail" not in str(saved)
    assert str(runner.output_dir) not in str(saved)


@pytest.mark.parametrize("phrase,action,reference", [
    ("prepare my project work session", "prepare", "current project"),
    ("please create a work session for Build Friday", "prepare", "Build Friday"),
    ("prepare my work session for Project Work Session", "prepare", "Project Work Session"),
    ("check the latest project work session", "status", "the latest work session"),
    ("show my work session for friday", "status", "friday"),
    ("resume my work session", "resume", "my work session"),
    ("cancel the work session", "cancel", "the work session"),
])
def test_session_language(phrase, action, reference):
    from services.mind.execution_commands import match_command
    assert match_command(phrase) == {"action": action, "workflow": "project_session", "reference": reference}
