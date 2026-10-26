import asyncio
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.config import config
from services.automation import intent
from services.proactive import briefing, watcher
from services.proactive.nudges import Nudger, Readings

MORNING = datetime(2026, 9, 24, 9, 0)


def test_watcher_queues_task_help_and_avoids_a_second_generic_question(delivered, monkeypatch):
    from services.mind import talk, task_followups
    from services.mind.workspace import workspace
    task = workspace.start_task("Review FRIDAY code")
    with workspace._db() as db:
        db.execute("UPDATE workspace_tasks SET updated=? WHERE id=?", ((MORNING - timedelta(days=3)).timestamp(), task))
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 10)
    sent = []
    monkeypatch.setattr(watcher, "show_toast", lambda *a, **kw: sent.append(a) or True)
    async def unexpected(*a, **kw):
        pytest.fail("Task followup was accompanied by a generic proactive question")
    monkeypatch.setattr(talk, "tick", unexpected)
    asyncio.run(watcher.tick(MORNING))
    asyncio.run(watcher.tick(MORNING + timedelta(minutes=1)))
    assert len(sent) == 1 and "Review FRIDAY code" in sent[0][1]
    with task_followups._db() as db:
        assert db.execute("SELECT state FROM workspace_followups").fetchone()[0] == "submitted"


# ── Briefing text ─────────────────────────────────────────────────────────────

@pytest.fixture
def quiet_parts(monkeypatch):
    """Every briefing part empty unless a test fills it in."""
    monkeypatch.setattr(briefing, "weather", lambda: "")
    monkeypatch.setattr(briefing.reminders, "pending", lambda: [])
    monkeypatch.setattr(briefing, "_system", lambda: "")
    monkeypatch.setattr(briefing.activity_log, "day_summary", lambda day: briefing.NO_ACTIVITY)


def test_mode_does_not_disable_optional_reasoning_and_learning(delivered, monkeypatch):
    from services.automation import modes
    from services.learning import service as learning_service
    from services.mind import brain, reasoning
    modes.begin('gaming', None)
    monkeypatch.setattr(watcher, 'is_busy', lambda: True)
    monkeypatch.setattr(config, 'LEARNING_DATA_ENABLED', True)
    called = []
    async def review(*args, **kwargs):
        called.append('reasoning')
    monkeypatch.setattr(learning_service, 'refresh', lambda *a: called.append('learning'))
    monkeypatch.setattr(reasoning, 'review', review)
    monkeypatch.setattr(brain, 'think', lambda *a: called.append('brain'))
    asyncio.run(watcher.tick(MORNING))
    assert called == ['reasoning', 'learning', 'brain']


def test_briefing_with_everything(quiet_parts, monkeypatch):
    due = MORNING.replace(hour=17).timestamp()
    tomorrow = (MORNING + timedelta(days=1)).timestamp()
    monkeypatch.setattr(briefing, "weather", lambda: "It's 24° and cloudy in Pune, with a high of 29°.")
    monkeypatch.setattr(briefing.reminders, "pending", lambda: [
        SimpleNamespace(text="call mom", due_at=due), SimpleNamespace(text="not today", due_at=tomorrow),
    ])
    monkeypatch.setattr(briefing, "_system", lambda: "Battery is at 64% and charging.")
    monkeypatch.setattr(briefing.activity_log, "day_summary", lambda day: "Yesterday you were active for 4h 0m: code 4h 0m.")

    assert briefing.build(MORNING) == (
        "Good morning. It's 24° and cloudy in Pune, with a high of 29°. "
        "You have 1 reminder today: call mom at 5:00 PM. Battery is at 64% and charging. "
        "Yesterday you were active for 4h 0m: code 4h 0m."
    )


def test_briefing_skips_what_it_has_nothing_to_say_about(quiet_parts):
    assert briefing.build(MORNING.replace(hour=14)) == "Good afternoon. No reminders today."


def test_weather_is_skipped_without_a_city_or_a_connection(monkeypatch):
    assert briefing.weather("") == ""

    def offline(*args, **kwargs):
        raise briefing.httpx.ConnectError("no internet")
    monkeypatch.setattr(briefing.httpx.Client, "get", offline)
    assert briefing.weather("Nowhere-town") == ""


def test_weather_sentence(monkeypatch):
    replies = iter([
        {"results": [{"latitude": 18.5, "longitude": 73.9, "name": "Pune"}]},
        {"current": {"temperature_2m": 24.4, "weather_code": 2},
         "daily": {"temperature_2m_max": [29.2], "precipitation_probability_max": [60]}},
    ])
    monkeypatch.setattr(briefing.httpx.Client, "get", lambda self, url, params: SimpleNamespace(json=lambda: next(replies)))
    monkeypatch.setattr(briefing, "_places", {})
    assert briefing.weather("pune") == "It's 24° and partly cloudy in Pune, with a high of 29° and a 60% chance of rain."


# ── When the briefing plays ───────────────────────────────────────────────────

@pytest.fixture
def delivered(monkeypatch, quiet_parts):
    out = []

    async def deliver(text, habit=None):
        out.append(text)
    monkeypatch.setattr(watcher, "_deliver", deliver)
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 5)
    monkeypatch.setattr(watcher, "read_system", lambda: Readings())
    monkeypatch.setattr(config, "BRIEFING_AFTER_HOUR", 6)
    return out


def test_briefing_plays_once_a_day_when_the_user_shows_up(delivered):
    asyncio.run(watcher.tick(MORNING))
    asyncio.run(watcher.tick(MORNING + timedelta(hours=2)))
    assert delivered == ["Good morning. No reminders today."]
    asyncio.run(watcher.tick(MORNING + timedelta(days=1)))
    assert len(delivered) == 2


def test_briefing_waits_for_the_hour_and_for_the_user(delivered, monkeypatch):
    asyncio.run(watcher.tick(MORNING.replace(hour=5)))
    monkeypatch.setattr(watcher, "idle_seconds", lambda: 600)  # away from the laptop
    asyncio.run(watcher.tick(MORNING))
    assert delivered == []


def test_asking_for_the_briefing_counts_as_todays(delivered):
    reply = asyncio.run(intent.try_system_action("hey friday, brief me", "openai"))
    assert reply.message.startswith("Good ")
    asyncio.run(watcher.tick(datetime.now().replace(hour=max(datetime.now().hour, 6))))
    assert delivered == []


# ── Nudge rules ───────────────────────────────────────────────────────────────

def run_nudges(nudger, *readings, now=MORNING):
    return [[n.text for n in nudger.check(r, now)] for r in readings]


def test_low_battery_nudges_once_per_drop():
    nudger = Nudger()
    low = Readings(battery=19, plugged_in=False)
    assert run_nudges(nudger, low, low._replace(battery=18)) == [["Battery is at 19%. Plug in soon."], []]
    critical = nudger.check(low._replace(battery=9), MORNING)
    assert critical[0].urgent and "9%" in critical[0].text
    assert run_nudges(nudger, low._replace(battery=8)) == [[]]
    assert run_nudges(nudger, low._replace(plugged_in=True), low) == [[], ["Battery is at 19%. Plug in soon."]]


def test_gpu_and_memory_must_stay_high_for_a_few_minutes():
    nudger = Nudger()
    hot = Readings(gpu_temperature=90)
    assert run_nudges(nudger, hot, hot, Readings(), hot, hot) == [[], [], [], [], []]
    assert "90°C" in run_nudges(nudger, hot)[0][0]
    assert run_nudges(nudger, hot) == [[]]  # once until it cools down

    full = Readings(memory=91, top_memory_app="chrome")
    assert run_nudges(nudger, full, full, full)[2] == ["Memory is 91% full. chrome is using the most."]


def test_long_stretch_in_one_app(monkeypatch):
    monkeypatch.setattr(config, "LONG_APP_HOURS", 3)
    nudger = Nudger()
    since = MORNING - timedelta(hours=2)
    coding = Readings(app="code", app_since=since)
    assert run_nudges(nudger, coding) == [[]]
    later = MORNING + timedelta(hours=1, minutes=5)
    assert run_nudges(nudger, coding, coding, now=later) == [
        ["You've been in code for 3 hours straight. Time for a short break?"], [],
    ]
    new_stretch = coding._replace(app_since=later)
    assert run_nudges(nudger, new_stretch, now=later + timedelta(hours=3)) != [[]]


def test_low_disk_at_most_once_a_day():
    nudger = Nudger()
    full = Readings(disk_free_gb=12)
    assert run_nudges(nudger, full, full) == [["Drive C is nearly full — only 12 GB left."], []]
    assert run_nudges(nudger, full, now=MORNING + timedelta(days=1)) != [[]]


# ── Delivery: switches ────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, action", [
    ("brief me", "briefing"), ("what's my morning briefing", "briefing"), ("daily briefing", "briefing"),
    ("pause nudges", "pause_nudges"), ("snooze nudges for 30 minutes", "pause_nudges"),
    ("turn off nudges", "nudges_off"), ("stop nudges", "nudges_off"), ("turn on nudges", "nudges_on"),
    ("brief me on the history of rome", None), ("pause the music", None),
])
def test_commands(message, action):
    match = watcher.match_proactive_command(message)
    assert (match and match["action"]) == action


def test_pausing_and_turning_nudges_off():
    say = lambda m: asyncio.run(intent.try_system_action(m, "openai")).message
    assert say("pause nudges for 2 hours") == "Okay, no nudges for 2 hours."
    assert not watcher.nudges_active()
    assert watcher.nudges_active(time.time() + 2 * 3600 + 1)
    assert say("snooze nudges for 20 minutes") == "Okay, no nudges for 20 minutes."
    assert say("turn off nudges").startswith("Nudges are off.")
    assert not watcher.nudges_active(time.time() + 10 ** 6)  # stays off, even after restarts
    assert say("turn on nudges") == "Nudges are back on."
    assert watcher.nudges_active()
