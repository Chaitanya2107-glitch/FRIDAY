import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import config
from services.activity import projects
from services.mind.cognition import Cognition, cognition
from services.mind.workspace import Workspace, workspace


class Desktop:
    def __init__(self):
        self.windows = {}
        self.opens = 0

    def find_folder(self, folder):
        return self.windows.get(str(folder))

    def open_folder(self, folder, *, active):
        assert active()
        self.opens += 1
        self.windows[str(folder)] = {"path": str(folder), "hwnd": 123}
        return self.find_folder(folder)


@pytest.fixture
def launched(tmp_path, monkeypatch):
    from services.mind import project_execution
    root = tmp_path / "college"
    root.mkdir()
    (root / "README.md").write_text("Private content", encoding="utf-8")
    projects.path.write_text(json.dumps({"college": {"path": str(root), "resume": ["delete everything"]}}), encoding="utf-8")
    desktop = Desktop()
    runner = project_execution.ProjectExecutionEngine(workspace, tmp_path / "sessions", desktop=desktop)
    monkeypatch.setattr(project_execution, "executions", runner)
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    return runner, root, desktop


def test_launch_uses_existing_brief_checkpoints_then_verifies_folder(launched):
    runner, root, desktop = launched
    task = workspace.start_task("College assignment")
    row = runner.run(runner.create("college"))
    assert row["state"] == "completed" and row["verified"] and row["cursor"] == 5
    assert len(row["evidence"]) == 5 and desktop.opens == 1
    assert row["payload"]["folder_window"] == {"path": str(root), "hwnd": 123}
    assert Path(row["artifact"]).is_file()
    assert workspace.resolve("task", task)["status"] == "active"


def test_project_preflight_records_intention_versions_and_observed_outcome(launched):
    from services.mind.executive import ExecutiveControl
    runner, root, _ = launched
    row = runner.run(runner.create("college"))
    control = ExecutiveControl(cognition)
    text = control.describe(why=True)
    assert "proceed" in text and "independently observed" in text and "verified: True" in text
    with control._db() as conn:
        decision = conn.execute("SELECT * FROM executive_decisions ORDER BY id DESC LIMIT 1").fetchone()
    situation = control.read(decision["situation_id"])
    assert situation["intention"] == "open_registered_project_folder"
    assert situation["versions"]["project"]
    assert str(root) not in json.dumps(situation)


def test_source_change_after_assessment_is_checked_before_os_submission(launched):
    runner, root, desktop = launched
    def changed(folder):
        (root / "README.md").write_text("Edited while observing the desktop", encoding="utf-8")
        return None
    desktop.find_folder = changed
    def refuse_input(folder, *, active):
        assert not active()
        raise ValueError("Source changed before OS submission")
    desktop.open_folder = refuse_input
    row = runner.run(runner.create("college"))
    assert row["state"] == "blocked" and desktop.opens == 0


def test_direct_remote_engine_call_cannot_bypass_project_preflight(launched):
    from services.automation.intent import remote_request
    runner, _, desktop = launched
    token = remote_request.set(True)
    try:
        row = runner.run(runner.create("college"))
    finally:
        remote_request.reset(token)
    assert row["state"] == "blocked" and desktop.opens == 0


def test_disabling_cognition_preserves_local_execution_without_private_snapshots(launched, monkeypatch):
    runner, _, _ = launched
    monkeypatch.setattr(config, "COGNITION_ENABLED", False)
    assert runner.run(runner.create("college"))["verified"]
    with workspace._db() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='executive_situations'").fetchone()


def test_already_open_folder_is_reused(launched):
    runner, root, desktop = launched
    desktop.windows[str(root)] = {"path": str(root), "hwnd": 456}
    assert runner.run(runner.create("college"))["verified"]
    assert desktop.opens == 0


def test_launch_return_without_observable_folder_cannot_complete(launched):
    runner, _, desktop = launched
    desktop.open_folder = lambda *a, **kw: None
    row = runner.run(runner.create("college"))
    assert row["state"] == "blocked" and not row["verified"] and row["cursor"] == 4


def test_interrupt_after_open_reconciles_on_restart_without_reopening(launched):
    from services.mind.project_execution import ProjectExecutionEngine
    runner, root, desktop = launched
    original = desktop.open_folder
    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt
    desktop.open_folder = interrupt
    ident = runner.create("college")
    with pytest.raises(KeyboardInterrupt):
        runner.run(ident)
    restarted = ProjectExecutionEngine(Workspace(Cognition(cognition.path)), runner.output_dir, desktop=desktop)
    assert restarted.run(ident, resume=True)["verified"]
    assert desktop.opens == 1


def test_uncertain_missing_outcome_never_replays_action(launched):
    runner, _, desktop = launched
    def interrupt(*a, **kw):
        desktop.opens += 1
        raise KeyboardInterrupt
    desktop.open_folder = interrupt
    ident = runner.create("college")
    with pytest.raises(KeyboardInterrupt):
        runner.run(ident)
    row = runner.run(ident, resume=True)
    assert row["state"] == "blocked" and "uncertain" in row["error"].lower()
    assert desktop.opens == 1


def test_expired_claim_only_reconciles_observable_outcome(launched):
    runner, root, desktop = launched
    ident = runner.create("college")
    for _ in range(4):
        runner.step(ident)
    with workspace._db() as conn:
        conn.execute("INSERT INTO workspace_execution_claims VALUES(?, 'dead-process', 0, 0)", (ident,))
    row = runner.run(ident, resume=True)
    assert row["state"] == "blocked" and desktop.opens == 0
    desktop.windows[str(root)] = {"path": str(root), "hwnd": 456}
    assert runner.run(ident, resume=True)["verified"]
    assert desktop.opens == 0


def test_separate_process_reconciles_claim_without_submitting_input(launched):
    import subprocess
    import sys
    runner, root, _ = launched
    ident = runner.create("college")
    for _ in range(4):
        runner.step(ident)
    with workspace._db() as conn:
        conn.execute("INSERT INTO workspace_execution_claims VALUES(?, 'dead-process', 0, 0)", (ident,))
    script = '''import sys
from pathlib import Path
from services.activity import projects
from services.memory import notes
from services.proactive import deadlines
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.mind.project_execution import ProjectExecutionEngine
projects.path = Path(sys.argv[4])
notes.path = Path(sys.argv[5])
deadlines.path = Path(sys.argv[6])
class Observed:
    def find_folder(self, folder): return {"path": str(folder), "hwnd": 456}
    def open_folder(self, *a, **kw): raise AssertionError("Replayed an uncertain action")
engine = ProjectExecutionEngine(Workspace(Cognition(Path(sys.argv[1]))), Path(sys.argv[2]), desktop=Observed())
row = engine.run(int(sys.argv[3]), resume=True)
assert row['state'] == 'completed' and row['verified'] and row['evidence'][-1]['reconciled']
'''
    from services.memory import notes
    from services.proactive import deadlines
    result = subprocess.run([sys.executable, "-B", "-c", script, str(cognition.path), str(runner.output_dir),
                             str(ident), str(projects.path), str(notes.path), str(deadlines.path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert runner.get(ident)["state"] == "completed"


def test_external_action_holds_no_sqlite_transaction_and_cancel_wins(launched):
    runner, _, desktop = launched
    ident = runner.create("college")
    other = Workspace(Cognition(cognition.path))
    def cancel_during_action(folder, *, active):
        # An independent connection can write while the adapter is running.
        other.start_task("Another task")
        runner.cancel(ident)
        assert not active()
        return {"path": str(folder), "hwnd": 123}
    desktop.open_folder = cancel_during_action
    row = runner.run(ident)
    assert row["state"] == "cancelled" and row["cursor"] == 4 and not row["verified"]
    assert len(row["evidence"]) == 4


def test_two_workers_cannot_run_external_checkpoint_twice(launched):
    from services.mind.project_execution import ProjectExecutionEngine
    runner, _, desktop = launched
    ident = runner.create("college")
    other = ProjectExecutionEngine(Workspace(Cognition(cognition.path)), runner.output_dir, desktop=desktop)
    entered, release = threading.Event(), threading.Event()
    original = desktop.open_folder
    def slow(*a, **kw):
        entered.set()
        assert release.wait(5)
        return original(*a, **kw)
    desktop.open_folder = slow
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner.run, ident)
        assert entered.wait(5)
        try:
            second = pool.submit(other.run, ident).result(timeout=3)
            assert second["state"] == "pending" and second["cursor"] == 4
        finally:
            release.set()
        assert first.result(timeout=5)["verified"]
    assert desktop.opens == 1 and len(runner.get(ident)["evidence"]) == 5


def test_source_change_during_external_action_blocks_completion(launched):
    runner, root, desktop = launched
    original = desktop.open_folder
    def changed(*a, **kw):
        result = original(*a, **kw)
        (root / "README.md").write_text("Changed", encoding="utf-8")
        return result
    desktop.open_folder = changed
    row = runner.run(runner.create("college"))
    assert row["state"] == "blocked" and not row["verified"]


def test_completed_session_reports_closed_window_without_reopening(launched):
    runner, _, desktop = launched
    row = runner.run(runner.create("college"))
    desktop.windows.clear()
    assert not runner.get(row["id"])["verified"]
    assert runner.run(row["id"], resume=True)["state"] == "completed"
    assert desktop.opens == 1


def test_completed_status_observes_desktop_outside_database_lock(launched):
    runner, _, desktop = launched
    row = runner.run(runner.create("college"))
    original = desktop.find_folder
    def inspect(folder):
        Workspace(Cognition(cognition.path)).start_task("Concurrent status observation")
        return original(folder)
    desktop.find_folder = inspect
    assert runner.get(row["id"])["verified"]


def test_tampered_brief_prevents_desktop_action(launched):
    runner, _, desktop = launched
    ident = runner.create("college")
    for _ in range(4):
        row = runner.step(ident)
    Path(row["artifact"]).write_text("Changed", encoding="utf-8")
    row = runner.run(ident)
    assert row["state"] == "blocked" and desktop.opens == 0


def test_commands_use_durable_focus_and_remote_is_denied(launched):
    from services.automation import intent
    runner, _, desktop = launched
    reply = asyncio.run(intent.try_system_action("start project session for college", "openrouter"))
    assert reply.success and "verified" in reply.message.lower()
    assert asyncio.run(intent.try_system_action("project session status", "openrouter")).success
    token = intent.remote_request.set(True)
    try:
        denied = asyncio.run(intent.try_system_action("start project session for college", "openrouter"))
        assert not denied.success and "laptop" in denied.message
    finally:
        intent.remote_request.reset(token)
    assert desktop.opens == 1


def test_chat_and_voice_route_execution_without_ai(launched, monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    runner, _, desktop = launched
    async def forbidden(*a, **kw):
        pytest.fail("Explicit project execution called a model")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/chat", json={"message": "start project session for college"})
    assert result.status_code == 200 and result.json()["action_success"]
    spoken = asyncio.run(voice._reply("project session status", voice.VoiceRequest(speak=False)))
    assert spoken.action_success and desktop.opens == 1
