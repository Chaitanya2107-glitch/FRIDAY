import asyncio
from datetime import datetime, timedelta

import pytest

from services.proactive import watcher
from services.proactive.nudges import Nudge, Nudger, Readings
from services.reminders import service as reminder_service


@pytest.fixture
def delivered(monkeypatch):
    out = []

    async def deliver(text, habit=None, *, urgent=False):
        out.append(text)
    monkeypatch.setattr(watcher, "_deliver", deliver)
    monkeypatch.setattr(watcher.config, "BRIEFING_ENABLED", True)
    monkeypatch.setattr(watcher.config, "BRIEFING_AFTER_HOUR", 6)
    monkeypatch.setattr(watcher.config, "NUDGES_ENABLED", True)
    monkeypatch.setattr(watcher.config, "GIT_REMINDER_HOUR", "")
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 5)
    monkeypatch.setattr(watcher.briefing, "build", lambda now: "Good morning.")
    monkeypatch.setattr(watcher, "_nudger", Nudger())
    return out


NOON = datetime(2026, 9, 28, 12, 0)


def test_nudges_wait_until_the_game_is_over(delivered, monkeypatch):
    monkeypatch.setattr(watcher.config, "LONG_APP_HOURS", 2)
    monkeypatch.setattr(watcher, "is_busy", lambda: True)
    monkeypatch.setattr(watcher, "read_system", lambda: Readings(app="code", app_since=NOON - timedelta(hours=3)))
    asyncio.run(watcher.tick(NOON))
    assert delivered == []  # no briefing, no nudge while gaming

    monkeypatch.setattr(watcher, "is_busy", lambda: False)
    monkeypatch.setattr(watcher, "read_system", lambda: Readings())
    asyncio.run(watcher.tick(NOON))
    assert delivered == ["You've been in code for 3 hours straight. Time for a short break?", "Good morning."]


def test_a_dying_battery_still_shows_while_busy(delivered, monkeypatch):
    monkeypatch.setattr(watcher, "is_busy", lambda: True)
    monkeypatch.setattr(watcher, "read_system", lambda: Readings(battery=5, plugged_in=False))
    asyncio.run(watcher.tick(NOON))
    assert delivered == ["Battery is at 5% — plug in now or the laptop will shut down soon."]


def test_reminders_are_not_spoken_while_busy(tmp_path, monkeypatch):
    spoken, shown = [], []
    monkeypatch.setattr(reminder_service, "show_toast",
                        lambda title, body, buttons=None, **kwargs: shown.append(body) or True)

    async def speak(text):
        spoken.append(text)
    monkeypatch.setattr(reminder_service.tts, "speak", speak)
    monkeypatch.setattr(watcher, "is_busy", lambda: True)
    store = reminder_service.ReminderService(str(tmp_path / "reminders.db"))
    store.add_from_message("remind me in 1 minute to stretch", datetime.now() - timedelta(minutes=2))
    asyncio.run(reminder_service.deliver_due(store))
    assert shown == ["stretch"] and spoken == []


@pytest.mark.parametrize("windows_says, app, busy", [
    (5, "code", False),                 # notifications welcome, not a game
    (3, "code", True),                  # a fullscreen Direct3D game
    (2, "chrome", True),                # something fullscreen (a video)
    (5, "b1-win64-shipping", True),     # a game in a window
])
def test_busy_means_fullscreen_or_a_game(monkeypatch, windows_says, app, busy):
    def query(ref):
        ref._obj.value = windows_says
        return 0
    monkeypatch.setattr(watcher.ctypes, "windll", type("W", (), {"shell32": type("S", (), {
        "SHQueryUserNotificationState": staticmethod(query)})()})())
    monkeypatch.setattr(watcher.activity_log, "app", app)
    assert watcher.fullscreen_or_gaming() is busy
