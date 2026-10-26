import asyncio
import json
import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from services.automation import intent
from services.automation.system_control import AutomationError
from services.mind import notifications
from services.watch import asked, done
from services.watch.auto import Downloads, HeavyWork

MIN = 60
REAL_NOTIFICATION_REASON = notifications._reason


# ── Claude Code and terminal ──────────────────────────────────────────────────

@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setattr(done, "_started", {})

    def event(name, at, **extra):
        return done.claude_event({"hook_event_name": name, "session_id": "s1", "cwd": r"C:\code\catjang", **extra}, now=at)
    return event


def test_long_claude_reply_is_reported(claude):
    assert claude("UserPromptSubmit", 1000) is None
    assert claude("Stop", 1000 + 12 * MIN) == "Claude finished in catjang after 12 min."
    assert claude("Stop", 1000 + 20 * MIN) is None  # that reply was already reported


def test_short_or_unknown_claude_replies_are_not(claude):
    claude("UserPromptSubmit", 1000)
    assert claude("Stop", 1030) is None
    assert claude("Stop", 5000) is None  # prompt sent before FRIDAY started


def test_permission_request_is_always_reported(claude):
    assert claude("PermissionRequest", 1000, tool_name="Bash") == "Claude needs your permission in catjang (Bash)."


def test_terminal_commands():
    assert done.terminal_event("npm run build", 30, True) is None
    assert done.terminal_event("npm run build", 6 * MIN, True) == "npm run build finished after 6 min."
    assert done.terminal_event("pytest", 3 * MIN, False) == "pytest finished after 3 min — it failed."
    long = done.terminal_event("x" * 200, 3 * MIN, True)
    assert long.startswith("x" * 59 + "…")


@pytest.fixture
def toasts(monkeypatch):
    from services.activity import log
    from services.reminders import service

    shown = []
    monkeypatch.setattr(service, "show_toast", lambda title, body, buttons=None, **kwargs: shown.append(body) or True)
    monkeypatch.setattr(log, "idle_seconds", lambda: 5)
    monkeypatch.setattr(log, "foreground_app", lambda: "windowsterminal")
    return shown


def test_terminal_alerts_are_skipped_while_watching_the_terminal(toasts, monkeypatch):
    from services.activity import log

    done.notify("Claude finished.", about_terminal=True)
    done.notify("Downloaded a.zip.")
    assert toasts == ["Downloaded a.zip."]
    monkeypatch.setattr(log, "idle_seconds", lambda: 600)  # walked away
    done.notify("Claude finished.", about_terminal=True)
    assert toasts[-1] == "Claude finished."


@pytest.mark.parametrize("approved", [False, True])
def test_completion_notification_requires_brain_approval(toasts, monkeypatch, approved):
    from services.mind import notifications
    from services.mind.cognition import cognition

    candidates = []
    async def decide(items, now, observations):
        candidates.extend(items)
        return [notifications.Choice(id="0", send=approved, reason="Current facts checked.")]
    monkeypatch.setattr(notifications, "_reason", decide)

    done.notify("Downloaded archive.zip.")

    assert len(candidates) == 1 and candidates[0].kind == "work_completion"
    assert toasts == (["Downloaded archive.zip."] if approved else [])
    assert cognition.latest("notification_decision")["status"] == ("submitted" if approved else "suppressed")


def test_claude_permission_alert_remains_available_without_brain(toasts, monkeypatch):
    from services.mind import notifications

    async def forbidden(*args):
        pytest.fail("An outstanding permission request must remain visible.")
    monkeypatch.setattr(notifications, "_reason", forbidden)
    done.notify("Claude needs your permission in FRIDAY (Bash).")
    assert toasts == ["Claude needs your permission in FRIDAY (Bash)."]


def test_completion_brain_receives_current_owner_schedule_facts(toasts, monkeypatch):
    from providers import failover
    from services.memory import schedule

    schedule.capture("No classes today", datetime.now())
    received = []
    async def decide(provider, messages, prompt, *args, **kwargs):
        received.append(json.loads(messages[0].content))
        return SimpleNamespace(content=json.dumps({"decisions": [
            {"id": "0", "send": False, "reason": "The current owner context makes this unnecessary."}]}))
    monkeypatch.setattr(notifications, "_reason", REAL_NOTIFICATION_REASON)
    monkeypatch.setattr(failover, "complete_with_failover", decide)

    done.notify("Downloaded DBMS notes.txt.")

    assert received[0]["dated_facts"][0]["classes_available"] is False
    assert received[0]["candidates"][0]["kind"] == "work_completion"
    assert toasts == []


def test_hook_route_replies_empty_and_stays_local(toasts, monkeypatch):
    monkeypatch.setattr(done, "_started", {"s9": 0.0})
    api = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    reply = api.post("/api/v1/done/claude", json={"hook_event_name": "Stop", "session_id": "s9", "cwd": "C:/x/proj"})
    assert reply.status_code == 204 and reply.content == b""
    assert api.post("/api/v1/done/terminal", json={"command": "make", "seconds": 400, "ok": True}).status_code == 204
    assert api.post("/api/v1/done/terminal", json={"command": "make", "seconds": 1},
                    headers={"Origin": "https://evil.example"}).status_code == 403
    assert toasts == []  # the terminal is in front and the user is active


# ── Downloads ─────────────────────────────────────────────────────────────────

def test_finished_downloads_are_reported(tmp_path):
    downloads = Downloads(tmp_path)
    (tmp_path / "movie.mkv.crdownload").write_bytes(b"x" * 2048)
    (tmp_path / "quick.pdf.part").write_bytes(b"x")
    (tmp_path / "old.txt").write_text("already here")
    assert downloads.check(now=1000) == []  # what's there at start doesn't count

    os.replace(tmp_path / "movie.mkv.crdownload", tmp_path / "movie.mkv")
    (tmp_path / "quick.pdf.part").unlink()  # cancelled: no final file
    (tmp_path / "notes.pdf").write_bytes(b"x")  # a quick one that was never seen half-done
    assert downloads.check(now=1000 + 5 * MIN) == [(tmp_path / "movie.mkv", True), (tmp_path / "notes.pdf", False)]
    assert downloads.check(now=1000 + 6 * MIN) == []


def test_firefox_placeholder_waits_for_the_real_file(tmp_path):
    downloads = Downloads(tmp_path)
    downloads.check(now=1000)
    (tmp_path / "big.iso").write_bytes(b"")  # Firefox's empty placeholder
    (tmp_path / "big.iso.part").write_bytes(b"x")
    assert downloads.check(now=1010) == []
    (tmp_path / "big.iso.part").unlink()
    (tmp_path / "big.iso").write_bytes(b"x" * 10)
    assert downloads.check(now=1010 + 5 * MIN) == [(tmp_path / "big.iso", True)]


def test_downloads_that_took_under_a_minute_are_not_announced(tmp_path, monkeypatch):
    from services.watch import auto
    monkeypatch.setattr("services.files.filing.suggest", lambda path: None)
    (tmp_path / "a.zip").write_bytes(b"x" * 2048)
    assert auto.announce(tmp_path / "a.zip", slow=False) is None
    assert auto.announce(tmp_path / "a.zip", slow=True) == "Downloaded a.zip (2 KB)."


# ── Heavy work ────────────────────────────────────────────────────────────────

def run_load(heavy, samples, start=0, step=30):
    alerts = []
    for i, (cpu, gpu, gaming) in enumerate(samples):
        if alert := heavy.check(cpu, gpu, gaming, now=start + i * step):
            alerts.append(alert)
    return alerts


def test_heavy_work_finishing_is_reported():
    samples = [(20, 95, False)] * 24 + [(5, 3, False)] * 6  # GPU 12 min, then calm
    assert run_load(HeavyWork(), samples) == ["Heavy work finished — GPU busy for 12 min."]


def test_short_bursts_and_games_are_not():
    assert run_load(HeavyWork(), [(90, None, False)] * 4 + [(5, None, False)] * 6) == []
    assert run_load(HeavyWork(), [(40, 97, True)] * 30 + [(5, 3, False)] * 6) == []


def test_heavy_work_ends_when_normal_use_takes_over():
    samples = [(95, 90, False)] * 31 + [(50, 40, False)] * 12  # 15 min busy, then ordinary use
    assert run_load(HeavyWork(), samples) == ["Heavy work finished — CPU and GPU busy for 15 min."]


# ── Asked-for watches ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("tell me when blender closes", {"action": "watch_program", "app": "blender"}),
    ("let me know when the installer finishes", {"action": "watch_program", "app": "installer"}),
    ("tell me when it's done", {"action": "watch_foreground"}),
    ("ping me when its done", {"action": "watch_foreground"}),
    ("tell me when it's charged", {"action": "watch_battery", "percent": 100}),
    ("tell me when the battery reaches 80%", {"action": "watch_battery", "percent": 80}),
    ("tell me when results.example.com/Class10 changes", {"action": "watch_web", "url": "results.example.com/Class10"}),
    ("tell me when the download finishes", {"action": "watch_auto"}),
    ("what are you watching", {"action": "list_watches"}),
    ("stop watching blender", {"action": "stop_watching", "what": "blender"}),
    ("cancel all watches", {"action": "stop_watching", "what": ""}),
    ("tell me a joke", None),
    ("tell me when my next class is", None),
])
def test_watch_commands(text, expected):
    match = asked.match_watch_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected


def test_program_watch_fires_once_when_it_closes(monkeypatch):
    alive = {True}
    monkeypatch.setattr(asked, "_alive", lambda pid, created: True in alive)
    assert asked.watch_program("blender", {(123, 1.0)}) == "Okay, I'll tell you when blender closes."
    assert asked.check(now=asked._programs["blender"]["since"] + 60) == []
    alive.clear()
    assert asked.check(now=asked._programs["blender"]["since"] + 25 * MIN) == ["Blender closed after 25 min."]
    assert asked.check() == [] and asked._programs == {}


def test_program_that_isnt_running(monkeypatch):
    monkeypatch.setattr(asked, "_find_processes", lambda app: set())
    with pytest.raises(AutomationError, match="I don't see photoshop running"):
        asked.watch_program("photoshop")


def test_battery_watch(monkeypatch):
    level = SimpleNamespace(percent=62.0, power_plugged=True)
    monkeypatch.setattr(asked.psutil, "sensors_battery", lambda: level)
    assert asked.watch_battery(80) == "Okay, I'll tell you when the battery reaches 80%."
    assert asked.check() == []
    level.percent = 80.0
    assert asked.check() == ["The battery is at 80%."]
    assert asked.check() == []
    assert asked.watch_battery(50) == "The battery is already at 80%."


def test_web_watch(monkeypatch):
    pages = {"https://example.com/results": "first"}
    monkeypatch.setattr(asked, "fingerprint", lambda url: pages[url])
    assert "example.com changes" in asked.watch_web("example.com/results")
    assert "already watching" in asked.watch_web("https://example.com/results")
    assert asked.check(now=1000) == []
    pages["https://example.com/results"] = "second"
    assert asked.check(now=1000 + 60) == []  # not due yet
    assert asked.check(now=1000 + 60, online=False) == []
    assert asked.check(now=1000 + 11 * MIN) == ["example.com changed: https://example.com/results"]
    assert asked._load() == []  # one alert, then the watch ends


def test_page_text_ignores_markup_and_scripts():
    page = "<html><script>var t = Date.now()</script><style>p{}</style><p>Results &amp; marks</p><!-- x --></html>"
    assert asked.page_text(page) == "Results & marks"


def test_list_and_stop(monkeypatch):
    monkeypatch.setattr(asked, "fingerprint", lambda url: "same")
    asked.watch_program("blender", {(1, 1.0)})
    asked.watch_web("example.com")
    listed = asked.list_message()
    assert listed.startswith("I'm watching for blender closing, example.com changing.")
    assert asked.stop("blender") == "Stopped watching blender."
    assert asked.stop("example") == "Stopped watching example."
    assert asked.stop("everything") == "I wasn't watching anything."


def test_watch_command_through_the_command_path(monkeypatch):
    monkeypatch.setattr(asked, "_find_processes", lambda app: {(7, 1.0)})
    result = asyncio.run(intent.try_system_action("hey friday, tell me when blender closes please", "openai"))
    assert result.success and result.message == "Okay, I'll tell you when blender closes."
