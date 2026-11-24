"""Exercise the model boundary and the owner paths that must work without it."""
import ast
import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from core.config import config
from core.errors import ModelUnavailable
from providers import execution, failover
from providers.base_provider import Message


def test_runtime_only_imports_model_clients_through_the_gateway():
    root = Path(__file__).resolve().parents[1]
    packages = ("core", "providers", "services", "interfaces", "plugins", "scripts", "src")
    files = [root / name for name in ("main.py", "train_friday.py")]
    files += [path for name in packages for path in (root / name).rglob("*.py")
              if not any(part.startswith(".") or part in {"venv", "node_modules"} for part in path.relative_to(root).parts)]
    files += list((root / "tasks").glob("*.py"))
    adapter_modules = {"providers/registry.py", "providers/ollama/runtime.py",
                       "providers/openai/client.py", "providers/openrouter/client.py", "providers/anthropic/client.py"}
    sdk_names = ("ollama", "openai", "anthropic")
    client_names = tuple(f"providers.{name}.client" for name in sdk_names + ("openrouter",))
    violations = []
    for path in files:
        name = path.relative_to(root).as_posix()
        if name in adapter_modules:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=name)):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [f"{node.module or ''}.{alias.name}".strip(".") for alias in node.names]
            else:
                continue
            for target in imports:
                direct_factory = target == "providers.registry.get_provider" and name != "providers/failover.py"
                if direct_factory or any(target == item or target.startswith(item + ".") for item in sdk_names + client_names):
                    violations.append(f"{name}:{node.lineno} {target}")
    assert not violations, "\n".join(violations)


def test_off_refuses_before_provider_setup_or_background_work(monkeypatch, fake_gateway):
    from services.files import embed
    from services.screen_watch import inference

    fake_gateway.use("off")
    monkeypatch.setattr(failover, "get_provider", lambda *a, **k: pytest.fail("Provider factory was called"))
    monkeypatch.setattr(execution, "_invoke_embedding", lambda *a: pytest.fail("Embedding work started"))
    async def check():
        for call in (failover.complete_with_failover("ollama", [Message("user", "test")], "", 60),
                     failover.prepare_local_model(),
                     inference.local_chat([{"role": "user", "content": "test"}])):
            with pytest.raises(ModelUnavailable, match="model is off"):
                await call
    asyncio.run(check())
    with pytest.raises(ModelUnavailable, match="model is off"):
        embed.encode(["test"])


@pytest.mark.parametrize("mode", ["slow", "garbage"])
def test_gateway_rejects_bad_results_and_opens_a_circuit(monkeypatch, fake_gateway, mode):
    fake_gateway.use(mode)
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "none")
    async def check():
        for _ in range(execution.FAILURES_BEFORE_OPEN):
            with pytest.raises(ModelUnavailable, match="timed out|invalid structured output"):
                await failover.complete_with_failover("ollama", [], "", 40,
                    response_schema={"type": "object", "required": ["value"]})
        with pytest.raises(ModelUnavailable, match="recovering"):
            await failover.complete_exact("ollama", [], "", 40)
    asyncio.run(check())
    assert fake_gateway.calls == execution.FAILURES_BEFORE_OPEN
    assert failover.model_state()["open_until"] > time.time()


def test_off_settings_and_commands_round_trip_without_provider_access(monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api import app
    from services.automation import intent

    monkeypatch.setattr(failover, "get_provider", lambda *a, **k: pytest.fail("Provider factory was called"))
    client = TestClient(app.create_app(), base_url="http://127.0.0.1")
    assert client.put("/api/v1/customization/model", json={"mode": "off"}).json() == {"mode": "off"}
    assert client.get("/api/v1/customization/model").json() == {"mode": "off"}
    assert client.put("/api/v1/customization/model", json={"mode": "maybe"}).status_code == 422
    assert client.put("/api/v1/customization/status-report", json={"time": "19:30"}).json() == {"time": "19:30"}
    assert client.put("/api/v1/customization/status-report", json={"time": "28:00"}).status_code == 400
    assert "19:30" in (config.MEMORY_DIR / "health.json").read_text(encoding="utf-8")
    assert "on" in asyncio.run(intent.try_system_action("turn the model on", "ollama")).message
    assert config.FRIDAY_LLM == "on"
    assert "off" in asyncio.run(intent.try_system_action("turn the model off", "ollama")).message
    assert config.FRIDAY_LLM == "off"
    assert asyncio.run(intent.try_system_action("status report", "ollama")).message.startswith("Status report.")


def test_explicit_text_memory_keeps_working_without_embeddings(tmp_path, fake_gateway):
    from services.memory.semantic import SemanticMemory

    fake_gateway.use("off")
    memory = SemanticMemory(str(tmp_path / "remember.db"))
    assert memory.remember("My torque wrench is in the blue box")
    assert not memory.remember("My torque wrench is in the blue box.")
    reloaded = SemanticMemory(memory.db_path)
    assert reloaded.recall("torque wrench")[0][0] == "My torque wrench is in the blue box"
    assert reloaded.forget("blue box") is None
    assert reloaded.forget("My torque wrench is in the blue box") == "My torque wrench is in the blue box"


@pytest.mark.parametrize("mode", ["on", "off", "slow", "garbage"])
def test_killed_model_does_not_delay_startup_or_local_delivery(monkeypatch, tmp_path, fake_gateway, mode):
    from interfaces.api import app as api
    from interfaces.api.routes import chat
    from plugins.focus.timer import Focus
    from providers.ollama import runtime as model_runtime
    from services import plugin_runtime
    from services.automation import intent
    from services.browser.service import automation
    from services.friday_island_server import server
    from services.mind import cognitive_runtime, development, reminder_review
    from services.proactive import timetable, watcher
    from services.reminders import service as reminders
    from services.screen_watch import service as screen
    from test_focus_plugin import FakeAPI, FakeClock
    from test_reminder_review import REAL_RECHECK, REAL_REVIEW

    server_script = """from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == '/api/version' else 404)
        self.end_headers()
with HTTPServer(('127.0.0.1', 0), Handler) as server:
    print(server.server_port, flush=True)
    server.serve_forever()
"""
    job = subprocess.Popen([sys.executable, "-B", "-c", server_script], stdout=subprocess.PIPE, text=True,
                           stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        port = int(job.stdout.readline())
        runtime = model_runtime.OllamaRuntime()
        monkeypatch.setattr(model_runtime, "runtime", runtime)
        monkeypatch.setattr(config, "OLLAMA_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setattr(config, "OLLAMA_AUTO_START", False)
        assert asyncio.run(runtime.ready(config.OLLAMA_BASE_URL))
        fake_gateway.use(mode)
        monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
        monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
        monkeypatch.setattr(config, "ACTIVE_PROVIDER", "ollama")
        # Own only this disposable process. Nobody's running Ollama is touched.
        job.kill()
        job.wait(timeout=5)
        assert job.returncode != 0

        async def worker(*args):
            await asyncio.Future()
        async def noop(*args):
            pass
        for name in ("run_scheduler", "watch_clipboard", "preload_speech_model", "run_indexer", "watch_activity",
                     "run_proactive", "watch_network", "run_bot", "run_watches"):
            monkeypatch.setattr(api, name, worker)
        monkeypatch.setattr(api.tts, "prewarm", worker)
        monkeypatch.setattr(reminders.tts, "speak", noop)
        monkeypatch.setattr(server, "run_integrated_bridge", worker)
        monkeypatch.setattr(plugin_runtime, "run_monitored", worker)
        monkeypatch.setattr(cognitive_runtime, "run", worker)
        monkeypatch.setattr(screen.watch, "run", worker)
        monkeypatch.setattr(development.development, "run", worker)
        monkeypatch.setattr(development.development, "scan", lambda: None)
        monkeypatch.setattr(api.app_finder, "wake_everything", lambda: None)
        monkeypatch.setattr(automation, "close", noop)
        monkeypatch.setattr(reminder_review, "review", REAL_REVIEW)
        monkeypatch.setattr(reminder_review, "recheck", REAL_RECHECK)
        async def snapshot(*a):
            return {"live": {"activity": "coding"}, "busy": False, "telegram_eligible": False}
        monkeypatch.setattr(reminder_review, "_snapshot", snapshot)
        sent = []
        monkeypatch.setattr(reminders, "_submit_desktop", lambda body, offers: (sent.append(body) or True, {"uncertain": False}))
        monkeypatch.setattr(watcher, "show_toast", lambda title, text, *a, **k: sent.append(text) or True)
        monkeypatch.setattr(watcher, "is_busy", lambda: False)
        monkeypatch.setattr(timetable, "due_warnings", lambda now: ["DBMS starts in 5 minutes"])
        monkeypatch.setattr(intent.system, "open_app", lambda name: f"Opening {name}.")
        now = datetime.now()
        reminder = reminders.ReminderService(str(tmp_path / "reminders.db"))
        reminder.add_from_message("remind me in 1 minute to stretch", now - timedelta(seconds=61))
        alarm = Focus(FakeAPI(tmp_path / "timer"), FakeClock())
        assert alarm.start(1)["ok"]
        alarm.clock.advance(61)
        app = SimpleNamespace(state=SimpleNamespace(remote=SimpleNamespace(monitor=worker, fence_off=lambda: None)))

        async def scenario():
            begin = time.monotonic()
            async with api.lifespan(app):
                assert time.monotonic() - begin < 2
                start = time.monotonic()
                reply = await chat.chat(chat.ChatRequest(message="open notepad"))
                assert reply.action_success and "notepad" in reply.response.casefold()
                assert time.monotonic() - start < 2
                await reminders.deliver_due(reminder)
                await watcher._schedule_alerts(now)
                alarm.tick()
                assert reminder.pending() == []
                assert sent == ["stretch", "DBMS starts in 5 minutes"]
                assert alarm.api.notifications == [("Focus complete", "Focus finished.", "critical")]
                with pytest.raises(ModelUnavailable):
                    await failover.complete_with_failover("ollama", [Message("user", "test")], "", 60,
                                                          purpose="conversation", attempt_timeout=.1)
        asyncio.run(scenario())
    finally:
        if job.poll() is None:
            job.kill()
            job.wait(timeout=5)
        job.stdout.close()
