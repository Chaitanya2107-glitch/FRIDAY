import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.config import config
from core.errors import ProviderError
from services.mind.cognition import Cognition, cognition
from services.mind.workspace import Workspace, workspace

NOW = datetime(2026, 10, 19, 12)
ATTENTION = {"activity": "coding", "away": False, "mode_active": False,
             "waiting_for_answer": False, "speaking": False, "listening": False}


@pytest.fixture
def control(monkeypatch):
    from services.mind import executive
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "REASONING_ENABLED", True)
    monkeypatch.setattr(config, "COGNITIVE_REVIEW_ENABLED", True)
    monkeypatch.setattr(executive, "attention_state", lambda: dict(ATTENTION))
    return executive.ExecutiveControl(cognition)


def known(text="Review the router"):
    return {"task:1": {"kind": "task", "id": 1, "title": text, "status": "active", "updated": 1}}


def test_snapshots_are_immutable_versioned_and_bounded(control):
    first = control.capture(NOW, known=known(), attention=ATTENTION)
    first["evidence"]["task:1"]["title"] = "Mutated caller copy"
    restored = control.read(first["id"])
    assert restored["evidence"]["task:1"]["title"] == "Review the router"
    assert restored["versions"]["task:1"]
    second = control.capture(NOW, known=known("Corrected task"), attention=ATTENTION)
    assert second["signature"] != first["signature"]
    huge = {f"task:{i}": {"kind": "task", "title": "X" * 1000} for i in range(100)}
    bounded = control.capture(NOW, known=huge, attention=ATTENTION)
    assert len(json.dumps(bounded)) < 25000


def test_retention_keeps_active_evidence_within_the_memory_bound(control):
    first = control.capture(NOW, known=known("In-flight evidence"), attention=ATTENTION)
    control.enqueue(first, NOW)
    control.claim(NOW)
    for index in range(201):
        control.capture(NOW, known=known(str(index)), attention=ATTENTION)
    with control._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM executive_situations").fetchone()[0] == 200
    assert control.read(first["id"])


def test_queue_claims_and_unchanged_evidence_survive_restart(control):
    from services.mind.executive import ExecutiveControl
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    job = control.claim(NOW)
    assert job
    other = ExecutiveControl(Cognition(cognition.path))
    assert other.claim(NOW) is None
    assert control.finish(job, "completed", NOW)
    other.enqueue(snapshot, NOW + timedelta(minutes=6))
    assert other.claim(NOW + timedelta(minutes=6)) is None


def test_hourly_budget_cannot_be_reset_by_restarts_or_switches(control):
    from services.mind.executive import ExecutiveControl
    for index in range(4):
        now = NOW + timedelta(minutes=index * 6)
        snapshot = control.capture(now, known=known(str(index)), attention=ATTENTION)
        control.enqueue(snapshot, now)
        job = control.claim(now)
        assert job
        control.finish(job, "completed", now)
    control.set_enabled(False)
    control.set_enabled(True)
    other = ExecutiveControl(Cognition(cognition.path))
    snapshot = other.capture(NOW, known=known("Fifth"), attention=ATTENTION)
    other.enqueue(snapshot, NOW + timedelta(minutes=24))
    assert other.claim(NOW + timedelta(minutes=24)) is None
    assert other.claim(NOW + timedelta(hours=1, seconds=1))


def test_failure_backoff_and_five_minute_gap_are_durable(control):
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    job = control.claim(NOW)
    assert control.finish(job, "unavailable", NOW)
    assert control.claim(NOW + timedelta(minutes=1)) is None
    assert control.claim(NOW + timedelta(minutes=6))


def test_switch_back_on_can_requeue_interrupted_same_situation(control):
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    old = control.claim(NOW)
    control.set_enabled(False)
    control.set_enabled(True)
    control.enqueue(snapshot, NOW + timedelta(minutes=6))
    assert control.claim(NOW + timedelta(minutes=6))
    assert not control.finish(old, "completed", NOW + timedelta(minutes=6))


def test_independent_workers_get_only_one_review_claim(control):
    from services.mind.executive import ExecutiveControl
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    other = ExecutiveControl(Cognition(cognition.path))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda runner: runner.claim(NOW), [control, other]))
    assert sum(job is not None for job in jobs) == 1


def test_expired_worker_cannot_finalize_after_lease_recovery(control):
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    old = control.claim(NOW)
    replacement = control.claim(NOW + timedelta(minutes=6))
    assert replacement and replacement["token"] != old["token"]
    assert not control.finish(old, "completed", NOW + timedelta(minutes=6))


def test_changed_evidence_supersedes_inflight_review(control):
    first = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(first, NOW)
    old = control.claim(NOW)
    corrected = control.capture(NOW, known=known("Corrected"), attention=ATTENTION)
    control.enqueue(corrected, NOW)
    assert not control.finish(old, "completed", NOW)


@pytest.fixture
def provider(monkeypatch):
    from providers import failover
    captured = []
    async def complete(provider, messages, prompt, *args, **kwargs):
        assert kwargs.get("purpose") == "cognitive_review"
        assert kwargs.get("attempt_timeout") == 8
        payload = json.loads(messages[0].content)
        captured.append(payload)
        if "check_items" in payload:
            data = {"checks": [{"id": item["id"], "supported": True, "reason": "Supplied task supports the proposal"}
                               for item in payload["check_items"]]}
        else:
            assert all('facts' not in branch['properties'] for branch in kwargs['response_schema']['oneOf'])
            task = next(key for key in payload["evidence"] if key.startswith("task:"))
            data = {"facts": [], "conclusions": [{"kind": "proposal", "text": "Review the recorded next step.",
                    "evidence": [task], "confidence": .8, "start": None, "end": None,
                    "effect": {"type": "task_plan", "task_id": int(task.split(":")[1]), "steps": ["Review the router"]}}],
                    "questions": []}
        return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    return captured


def test_background_review_runs_in_assist_only_and_never_executes_plan(control, provider):
    from services.mind.reasoning_store import reasoning_store
    task = workspace.start_task("Review FRIDAY")
    result = asyncio.run(control.review(NOW))
    assert result["status"] == "completed"
    claim = reasoning_store.context(NOW)["conclusions"][0]
    assert claim["status"] == "proposed" and not reasoning_store.facts()
    with workspace._db() as conn:
        assert workspace._task(conn, task)["steps"] == []
    assert len(provider) == 2
    assert asyncio.run(control.review(NOW + timedelta(minutes=6)))["status"] == "idle"
    assert len(provider) == 2


@pytest.mark.parametrize("change", ["source", "disable", "forget"])
def test_inflight_corrections_switches_and_forgetting_discard_result(control, provider, monkeypatch, change):
    from providers import failover
    from services.mind.reasoning_store import reasoning_store
    task = workspace.start_task("Review FRIDAY")
    complete = failover.complete_with_failover
    async def mutate(*args, **kwargs):
        response = await complete(*args, **kwargs)
        if "check_items" in json.loads(args[1][0].content):
            if change == "source":
                workspace.task_state(task, "blocked", "Waiting for a new source")
            elif change == "disable":
                control.set_enabled(False)
            else:
                cognition.clear()
        return response
    monkeypatch.setattr(failover, "complete_with_failover", mutate)
    result = asyncio.run(control.review(NOW))
    assert result["status"] != "completed"
    assert not reasoning_store.context(NOW)["conclusions"]


def test_busy_and_disabled_review_never_calls_provider(control, provider):
    workspace.start_task("Review FRIDAY")
    assert asyncio.run(control.review(NOW, busy=True))["status"] == "deferred"
    control.set_enabled(False)
    assert asyncio.run(control.review(NOW))["status"] == "disabled"
    assert not provider


def test_slow_primary_cannot_starve_cognitive_fallback(control, monkeypatch):
    from providers import failover
    from providers.base_provider import ProviderResponse
    from services.mind import reasoning
    workspace.start_task("Review FRIDAY")
    cancelled, fallbacks = [], []
    class Slow:
        async def complete(self, **kwargs):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
    class Fast:
        async def complete(self, messages, **kwargs):
            fallbacks.append(True)
            return ProviderResponse('{"facts":[],"conclusions":[],"questions":[]}', "ollama", "test")
    monkeypatch.setattr(reasoning, "COGNITIVE_ATTEMPT_SECONDS", .01)
    monkeypatch.setattr(failover, "provider_chain", lambda name: ["openrouter", "ollama"])
    monkeypatch.setattr(failover, "get_provider", lambda name, **kw: Slow() if name == "openrouter" else Fast())
    assert asyncio.run(control.review(NOW))["status"] == "completed"
    assert cancelled == [True] and fallbacks == [True]


def test_cognitive_purpose_is_separate_and_tools_remain_blocked(control, monkeypatch):
    from providers.policy import check_allowed
    from providers.failover import complete_with_failover
    from providers.base_provider import Message
    check_allowed("cognitive_review")
    with pytest.raises(ProviderError):
        check_allowed()
    with pytest.raises(ProviderError):
        asyncio.run(complete_with_failover("ollama", [Message("user", "hi")], "", 100,
                                          purpose="cognitive_review", tools=[{}]))
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", False)
    with pytest.raises(ProviderError):
        asyncio.run(complete_with_failover("ollama", [Message("user", "hi")], "", 100,
                                          purpose="cognitive_review", tools=[{}]))
    monkeypatch.setattr(config, "COGNITIVE_REVIEW_ENABLED", False)
    with pytest.raises(ProviderError):
        check_allowed("cognitive_review")


def test_history_clear_removes_snapshots_without_resetting_hour_budget(control):
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    control.claim(NOW)
    cognition.clear()
    assert control.read(snapshot["id"]) is None
    new = control.capture(NOW, known=known("New"), attention=ATTENTION)
    control.enqueue(new, NOW)
    assert control.claim(NOW + timedelta(minutes=1)) is None


def test_local_controls_persist_and_remote_cannot_inspect_or_toggle(control):
    from services.mind import cognition_commands
    assert cognition_commands.run("executive_off").success
    assert not control.status(NOW)["enabled"]
    assert cognition_commands.run("executive_on").success
    assert control.status(NOW)["enabled"]
    assert not cognition_commands.run("executive_off", remote=True).success
    assert control.status(NOW)["enabled"]


def test_source_correction_invalidates_an_already_saved_proposal(control, provider):
    from services.mind.reasoning_store import reasoning_store
    task = workspace.start_task("Review FRIDAY")
    assert asyncio.run(control.review(NOW))["status"] == "completed"
    workspace.task_state(task, "blocked", "Owner corrected the current blocker")
    assert not reasoning_store.context(NOW)["conclusions"]


def test_interruption_after_report_commit_does_not_repeat_review(control, provider, monkeypatch):
    from services.mind.reasoning_store import ReasoningStore
    workspace.start_task("Review FRIDAY")
    original = ReasoningStore.save
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt
    monkeypatch.setattr(ReasoningStore, "save", interrupted)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(control.review(NOW))
    monkeypatch.setattr(ReasoningStore, "save", original)
    assert len(provider) == 2
    asyncio.run(control.review(NOW + timedelta(minutes=6)))
    assert len(provider) == 2


@pytest.mark.parametrize("invalid", ["new_fact", "unknown_evidence", "invented_tool"])
def test_bad_cognitive_output_cannot_become_memory_or_actions(control, monkeypatch, invalid):
    from providers import failover
    from services.mind.reasoning_store import reasoning_store
    workspace.start_task("Review FRIDAY")
    data = {"facts": [], "conclusions": [], "questions": []}
    if invalid == "new_fact":
        data["facts"] = [{"id": "f0", "quote": "The user finished everything", "certainty": "confirmed", "supersedes": []}]
    else:
        data["conclusions"] = [{"kind": "proposal", "text": "Run an action", "evidence": ["unknown:999"],
                                "confidence": .9, "start": None, "end": None, "effect": {"type": "guidance"}}]
        if invalid == "invented_tool":
            data["conclusions"][0]["effect"] = {"type": "shell", "command": "erase"}
    async def invalid_result(*a, **kw):
        return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", invalid_result)
    assert asyncio.run(control.review(NOW))["status"] == "unavailable"
    assert not reasoning_store.facts() and not reasoning_store.context(NOW)["conclusions"]


def test_watcher_runs_changed_evidence_review_without_new_user_message(control, provider, monkeypatch):
    from services.mind import executive
    from services.proactive import watcher
    workspace.start_task("Review FRIDAY")
    monkeypatch.setattr(executive, "executive", control)
    monkeypatch.setattr(watcher, "is_busy", lambda: False)
    monkeypatch.setattr(watcher, "nudges_active", lambda *a: False)
    async def no_optional_work(*a):
        pass
    monkeypatch.setattr(watcher, "_tick", no_optional_work)
    asyncio.run(watcher.tick(NOW))
    assert provider and control.status(NOW)["last_review"] == "completed"


def test_chat_and_voice_expose_local_executive_controls_without_model(control, monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    from providers import failover
    async def forbidden(*a, **kw):
        pytest.fail("Executive controls tried a model")
    monkeypatch.setattr(failover, "complete_with_failover", forbidden)
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/chat", json={"message": "executive review off"})
    assert result.status_code == 200 and result.json()["action_success"]
    result = asyncio.run(voice._reply("executive review on", voice.VoiceRequest(speak=False)))
    assert result.action_success and control.status(NOW)["enabled"]


def test_background_class_consequence_remains_a_proposal(control, monkeypatch):
    from providers import failover
    from services.mind.reasoning import Fact, Report
    from services.mind.reasoning_store import reasoning_store
    from services.memory import schedule
    text = "My regular classes are cancelled today."
    reasoning_store.save(Report(facts=[Fact(id="f0", quote=text, certainty="confirmed")], conclusions=[], questions=[]), NOW, {})
    ident = reasoning_store.facts()[0]["id"]
    data = {"facts": [], "conclusions": [{"kind": "proposal", "text": text, "evidence": [ident],
            "confidence": .99, "start": NOW.date().isoformat(), "end": NOW.date().isoformat(),
            "effect": {"type": "class_availability", "available": False, "subject": "", "basis": "explicit"}}], "questions": []}
    async def complete(provider, messages, prompt, *a, **kw):
        payload = json.loads(messages[0].content)
        result = {"checks": [{"id": 0, "supported": True, "reason": "Explicit owner fact"}]} if "check_items" in payload else data
        return SimpleNamespace(content=json.dumps(result))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    assert asyncio.run(control.review(NOW))["status"] == "completed"
    assert reasoning_store.context(NOW)["conclusions"][0]["status"] == "proposed"
    assert schedule.allowed(NOW.date())


def test_receipts_are_historical_and_exclude_private_project_payload(control):
    from services.mind.executive import execution_evidence
    payload = {"workflow": "project_execution", "project": {"path": "private-path"},
               "notes": ["secret note"], "folder_window": {"path": "private-path", "hwnd": 1}}
    with workspace._db() as conn:
        conn.execute("INSERT INTO workspace_executions(task_id,state,cursor,payload,digest,evidence,created,updated) "
                     "VALUES(0,'completed',5,?,'digest',?,0,0)",
                     (json.dumps(payload), json.dumps([{"step": i, "source": "executor"} for i in range(5)])))
    data = execution_evidence(cognition)
    assert data["execution:1"]["historically_verified"]
    assert "private-path" not in json.dumps(data) and "secret note" not in json.dumps(data)
    with workspace._db() as conn:
        conn.execute("UPDATE workspace_executions SET state='cancelled'")
    assert not execution_evidence(cognition)["execution:1"]["historically_verified"]


def test_background_situation_tracks_local_focus_without_project_paths(control):
    task = workspace.start_task("Current project task")
    workspace.focus("task", task)
    snapshot = control.capture(NOW)
    assert snapshot["evidence"]["focus:local"]["targets"]["task"] == task


def test_selected_task_is_retrieved_even_outside_latest_five(control):
    selected = workspace.start_task("Selected older task")
    for index in range(7):
        workspace.start_task(f"Unrelated newer task {index}")
    workspace.focus("task", selected)
    assert control.capture(NOW)["evidence"][f"task:{selected}"]["title"] == "Selected older task"


def test_uncertain_desktop_receipt_is_not_a_verified_action(control):
    from services.mind.executive import execution_evidence
    with workspace._db() as conn:
        conn.execute("INSERT INTO workspace_executions(task_id,state,cursor,payload,created,updated) "
                     "VALUES(0,'pending',4,'{\"workflow\":\"project_execution\"}',0,0)")
        conn.execute("INSERT INTO workspace_execution_claims VALUES(1,'uncertain-request',0,1)")
    assert execution_evidence(cognition)["execution:1"]["effect_status"] == "uncertain"


def test_separate_process_retains_lease_and_review_budget(control):
    import subprocess
    import sys
    snapshot = control.capture(NOW, known=known(), attention=ATTENTION)
    control.enqueue(snapshot, NOW)
    job = control.claim(NOW)
    script = '''import sys
from datetime import datetime
from pathlib import Path
from core.config import config
config.COGNITIVE_REVIEW_ENABLED = config.REASONING_ENABLED = config.COGNITION_ENABLED = True
from services.mind.cognition import Cognition
from services.mind.executive import ExecutiveControl
runner = ExecutiveControl(Cognition(Path(sys.argv[1])))
now = datetime.fromisoformat(sys.argv[2])
assert runner.claim(now) is None
assert runner.status(now)['reviews_this_hour'] == 1
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(cognition.path), NOW.isoformat()],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_forgetting_retires_derived_private_context(control):
    from services.memory.semantic import run_memory_command
    private = "Private source to withdraw"
    snapshot = control.capture(NOW, known=known(private), attention=ATTENTION)
    run_memory_command({"action": "forget_memory", "text": "nothing currently matches"})
    assert control.read(snapshot["id"]) is None
