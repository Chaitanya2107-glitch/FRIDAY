from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.automation import system_health as health
from services.proactive import watcher
from services.proactive.nudges import Nudger, Readings


@pytest.mark.parametrize("text, action", [
    ("how's my battery health?", "battery_health"),
    ("how worn out is my battery", "battery_health"),
    ("how long has the laptop been on", "uptime"),
    ("do I need to restart", "pending_restart"),
    ("what's taking up space", "disk_hogs"),
    ("show me my biggest files", "disk_hogs"),
    ("how's my system", None),  # system stats
])
def test_health_commands(text, action):
    match = health.match_health_command(text)
    assert (match and match["action"]) == action


def test_battery_health_verdicts():
    assert health.battery_health(lambda: (60000, 58360, 123)) == \
        "Your battery holds 97% of its original charge (58.4 of 60.0 Wh) — healthy. 123 charge cycles so far."
    assert "worn — expect shorter" in health.battery_health(lambda: (60000, 42000, None))


def test_uptime_mentions_a_waiting_restart(monkeypatch):
    now = datetime(2026, 9, 30, 12, 0).timestamp()
    monkeypatch.setattr(health.psutil, "boot_time", lambda: now - 2 * 86400 - 3 * 3600)
    text = health.uptime(now, pending=True)
    assert text.startswith("Windows has been running since Mon 28 Sep at 9:00 AM (2d 3h")
    assert text.endswith("A restart is waiting for updates.")


def test_disk_hogs_add_up_big_files_per_folder(monkeypatch):
    monkeypatch.setattr(health.psutil, "disk_usage", lambda drive: SimpleNamespace(free=400e9, total=1000e9))
    lines = [r"30,000,000,000 C:\games\Wukong\b1\a.pak", r"20,000,000,000 C:\games\Wukong\b1\b.pak",
             r"25,000,000,000 C:\pagefile.sys", r"16,000,000,000 C:\Users\me\Downloads\kali\kali.vdi",
             r"2,000,000,000 C:\Users\me\AppData\Local\NVIDIA\cache\x.bin"]
    text = health.disk_hogs(lambda args: lines)
    assert r"C:\games\Wukong 50.0 GB; C:\Users\me\Downloads\kali 16.0 GB; C:\Users\me\AppData\Local\NVIDIA 2.0 GB" in text
    assert "pagefile" not in text and text.endswith("Drive C: 400 GB free of 1000 GB.")


def test_eye_breaks_every_20_minutes_of_screen_time():
    nudger, start = Nudger(), datetime(2026, 9, 30, 10, 0)

    def eyes(minute, app="code", on=True):
        return [n for n in nudger.check(Readings(app=app), start + timedelta(minutes=minute), on) if "Eye break" in n.text]
    assert eyes(0) == [] and eyes(19) == []
    first = eyes(20)
    assert len(first) == 1 and not first[0].keep  # dropped, not held, while gaming
    assert eyes(21) == []
    assert eyes(30, app=None) == []  # a break resets it
    assert eyes(31) == [] and len(eyes(51)) == 1
    assert eyes(90, on=False) == []


def test_eye_breaks_switch():
    assert watcher.run_proactive_command(watcher.match_proactive_command("turn on eye breaks")).startswith("Eye breaks on")
    assert watcher.load_state()["eye_breaks"] is True
    watcher.run_proactive_command(watcher.match_proactive_command("stop eye breaks"))
    assert watcher.load_state()["eye_breaks"] is False


@pytest.mark.parametrize("typed", ["hows my battery health", "whats taking up space", "whats my study streak"])
def test_commands_typed_without_apostrophes_still_match(typed, monkeypatch):
    import asyncio
    from services.automation import intent
    monkeypatch.setattr(health, "run", lambda parsed: f"ran {parsed['action']}")
    monkeypatch.setattr("services.activity.fun.run", lambda parsed, log: f"ran {parsed['action']}")
    reply = asyncio.run(intent.try_system_action(typed, "openai"))
    assert reply is not None and reply.message.startswith("ran ")
