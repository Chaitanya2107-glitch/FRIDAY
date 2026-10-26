"""A mode left on: a reminder, then it ends itself (services/automation/modes.py left_on, watcher.py)."""

import asyncio
from datetime import datetime, timedelta

import pytest

from services.automation import intent, modes
from services.automation.results import ActionResult
from services.proactive import watcher


@pytest.mark.parametrize("name, off, idle, expected", [
    ("work", 0, 0, None),
    ("work", 16, 0, "remind"),
    ("work", 46, 0, "end"),
    ("work", 0, 61, "end"),        # away for an hour
    ("chill", 300, 0, None),       # chill fits anything
    ("my focus", 300, 0, None),    # your own modes: only being away ends them
    ("my focus", 0, 90, "end"),
])
def test_left_on(name, off, idle, expected):
    assert modes.left_on(name, off, idle) == expected


@pytest.fixture
def watching(monkeypatch):
    toasts, ended = [], []
    modes._set_active({"name": "work", "opened": [], "volume": 50, "quiet": True, "since": 1.0})
    monkeypatch.setattr(watcher, "_off_mode_since", None)
    monkeypatch.setattr(watcher, "_reminded_mode", None)
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 5)
    monkeypatch.setattr(watcher, "show_toast", lambda title, text, buttons=None, **kw: toasts.append((text, bool(buttons))))
    monkeypatch.setattr(intent, "_end_mode", lambda name: ended.append(name) or ActionResult(True, "Work mode off."))
    monkeypatch.setattr(watcher.activity_log, "app", "chrome")
    monkeypatch.setattr(watcher.activity_log, "title", "lofi beats - YouTube - Google Chrome")
    return toasts, ended


def test_videos_during_work_mode_remind_once_then_end_it(watching):
    toasts, ended = watching
    start = datetime(2026, 9, 30, 20, 0)
    for minute in range(0, 47):
        asyncio.run(watcher._check_mode_left_on(start + timedelta(minutes=minute)))
    reminders = [t for t in toasts if "still on" in t[0]]
    assert len(reminders) == 1 and reminders[0][1]  # once, with an [End mode] button
    assert "videos" in reminders[0][0]
    assert ended == ["work"]
    assert "Ended work mode — you'd moved on to videos" in toasts[-1][0]


def test_apps_that_fit_the_mode_never_nag(watching, monkeypatch):
    toasts, ended = watching
    monkeypatch.setattr(watcher.activity_log, "app", "code")
    monkeypatch.setattr(watcher.activity_log, "title", "modes.py - Visual Studio Code")
    start = datetime(2026, 9, 30, 20, 0)
    for minute in range(0, 120, 5):
        asyncio.run(watcher._check_mode_left_on(start + timedelta(minutes=minute)))
    assert toasts == [] and ended == []


def test_away_for_an_hour_ends_it(watching, monkeypatch):
    toasts, ended = watching
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 3700)
    monkeypatch.setattr(watcher.activity_log, "app", None)
    asyncio.run(watcher._check_mode_left_on(datetime(2026, 9, 30, 20, 0)))
    assert ended == ["work"] and "you'd stepped away" in toasts[-1][0]
