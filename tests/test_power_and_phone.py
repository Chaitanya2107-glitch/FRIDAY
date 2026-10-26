import asyncio
import time
from datetime import datetime

import pytest

from core.config import config
from services.activity.log import activity_log
from services.automation import intent, power
from services.proactive import timetable, watcher
from services.telegram import bot, client, summaries


@pytest.fixture
def pc(monkeypatch):
    """Nothing real happens: lock, sleep and shutdown are recorded instead."""
    done = []
    monkeypatch.setattr(power, "_later", lambda do: done.append(getattr(do, "__name__", "sleep")))
    monkeypatch.setattr(power, "_shutdown", lambda args: done.append(" ".join(args)))
    monkeypatch.setattr("services.automation.media_control.pause", lambda: "Paused.")
    return done


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter")).message


def test_lock_at_once_the_rest_ask_first(pc):
    assert say("lock the laptop") == "Locking." and pc == ["lock"]
    assert say("shut down in 30 minutes") == "Shut down the laptop in 30 min? Say yes or no."
    assert say("no") != "" and pc == ["lock"]
    assert say("shut down in 30 minutes").endswith("Say yes or no.")
    assert say("yes") == 'Shutting down in 30 min. Say "cancel the shutdown" to stop it.'
    assert pc[-1] == "/s /t 1800"
    assert say("cancel the shutdown") == "Cancelled — nothing is going to shut down." and pc[-1] == "/a"
    assert power.match_power_command("shut down spotify") is None  # closing an app


def test_slash_commands_and_away(pc, monkeypatch):
    assert bot.slash_command("/shutdown 30") == "shut down in 30 minutes"
    assert bot.slash_command("/lock") == "lock the laptop"
    assert say("I'm going out") == "Away mode: paused, locking, and notifications go to Telegram until you're back."
    assert pc == ["lock"]
    state = client._state()
    assert state["away_since"] and not client.away()  # the first minute (the lock's own keypress) doesn't count
    monkeypatch.setattr(time, "time", lambda: state["away_since"] + 120)
    assert client.away()


def test_menu_from_usual_commands():
    for _ in range(3):
        activity_log.log_command({"action": "open_app", "app_name": "spotify"}, True)
    activity_log.log_command({"action": "take_screenshot"}, True)
    activity_log.log_command({"action": "set_volume", "level": 30}, True)  # not a menu command
    labels = bot.menu()
    assert labels[:2] == ["open spotify", "take a screenshot"] and "what's due" in labels


def test_phone_briefing_is_daily_and_marked_after_delivery(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 1)
    monkeypatch.setattr(config, "TELEGRAM_BRIEFING_HOUR", "7")
    monday = datetime(2026, 9, 28, 7, 5)
    assert ("morning", "2026-09-28") in summaries.due(monday)  # no classes required
    timetable._save([{"day": "monday", "start": "08:30", "end": "09:25", "subject": "DS", "room": None}])
    assert ("morning", "2026-09-28") in summaries.due(monday)
    assert not summaries.due(monday.replace(hour=6))
    summaries._save({"morning": "2026-09-28"})
    assert not summaries.due(monday)
