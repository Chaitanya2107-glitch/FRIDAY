import asyncio
import json
from types import SimpleNamespace

import pytest

from services.activity import devtools, projects
from services.automation import intent
from services.proactive import buttons
from services.watch import asked

SERVER = {"port": 3000, "pid": 4242, "program": "node", "where": "catjang"}


@pytest.fixture
def running(monkeypatch):
    monkeypatch.setattr(devtools, "servers", lambda: [SERVER, {"port": 8888, "pid": 7, "program": "python", "where": "notebooks"}])
    stopped = []
    monkeypatch.setattr(devtools, "stop_server", lambda server: stopped.append(server["port"]) or "Stopped node on port 3000 (catjang).")
    return stopped


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


def test_ports_and_servers(running):
    assert say("what's running on port 3000").message == "Port 3000: node in catjang."
    assert say("what dev servers are running").message == "Running: port 3000: node in catjang; port 8888: python in notebooks."
    assert devtools.port_info(5173) == "Nothing from a dev program is listening on port 5173."


def test_stopping_asks_first(running):
    assert say("kill port 3000").message == "Stop node on port 3000 (catjang)? Say yes or no."
    assert running == []
    assert say("yes").message == "Stopped node on port 3000 (catjang)."
    assert running == [3000]
    projects._save({"catjang": {"path": "C:/x/catjang"}})
    assert devtools.match_dev_command("stop catjang's dev server") == {"type": "system", "action": "stop_server",
                                                                         "project": "catjang"}
    assert devtools.match_dev_command("stop the music server") is None  # not a saved project


def test_ci_status(monkeypatch, tmp_path):
    projects._save({"catjang": {"path": str(tmp_path)}})
    run = SimpleNamespace(returncode=0, stderr="", stdout=json.dumps([{"status": "completed", "conclusion": "failure",
                          "workflowName": "build", "headBranch": "main", "createdAt": "2026-09-29T10:00:00Z"}]))
    monkeypatch.setattr(devtools, "_run", lambda args, folder: run)
    now = devtools.datetime(2026, 9, 29, 12, 0, tzinfo=devtools.timezone.utc)
    assert devtools.ci_status("catjang", now) == "catjang: build failed on main 2 h ago."
    monkeypatch.setattr(devtools, "_run", lambda args, folder: SimpleNamespace(returncode=1, stderr="gh auth login", stdout=""))
    assert devtools.ci_status("", now) == "catjang: not signed in to gh (run: gh auth login)."


def test_outdated(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text("{}")
    projects._save({"catjang": {"path": str(tmp_path)}})
    monkeypatch.setattr(devtools, "_run", lambda args, folder: SimpleNamespace(returncode=1, stdout='{"vite": {}, "react": {}}'))
    assert devtools.outdated() == "Outdated packages — catjang: 2 outdated (vite, react)."


def test_log_watch(tmp_path):
    log = tmp_path / "server.log"
    log.write_text("starting\n")
    parsed = asked.match_watch_command(f"tell me when {log} logs an error")
    assert parsed["action"] == "watch_log"
    assert asked.run(parsed) == "Okay, I'll tell you when server.log shows that."
    assert asked.check(online=False) == []
    with log.open("a") as f:
        f.write("GET / 200\nTypeError: cannot read properties of undefined\n")
    assert asked.check(online=False) == ["server.log: TypeError: cannot read properties of undefined"]
    assert asked.check(online=False) == []  # one alert, then the watch ends
    says = asked.match_watch_command(f"tell me when {log} says listening on 3000")
    assert says["pattern"] == "listening\\ on\\ 3000"


def test_explain_button(monkeypatch):
    shown = []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda title, text, links=None: shown.append(text))

    async def ask(question, history, provider, tokens):
        assert "npm run build" in question
        return SimpleNamespace(content="A missing import in App.jsx. Add it and rebuild.")
    monkeypatch.setattr("services.vision.screen.ask_about_screen", ask)
    links = buttons.offer("explain", command="npm run build")
    token = links[0][1].split("token=")[1].split("&")[0]
    assert buttons.respond(token, "explain") == "A missing import in App.jsx. Add it and rebuild."
    assert shown == ["A missing import in App.jsx. Add it and rebuild."]
