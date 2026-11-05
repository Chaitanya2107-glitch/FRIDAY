import json
from datetime import datetime, timedelta

import pytest

from services.activity import habits
from services.activity.habits import Context, Habit
from services.activity.log import ActivityLog
from services.automation import routines

MONDAY = datetime(2026, 9, 28)
DAYS = [MONDAY + timedelta(days=d) for d in range(5)]  # Mon–Fri


def at(day, hour, minute=0):
    return day.replace(hour=hour, minute=minute).isoformat()


@pytest.fixture
def log(tmp_path):
    """Five weekdays: code + spotify + whatsapp launched together in the morning, obsidian a minute after
    code in the afternoon, catjang (a project, in the terminal) around 10 PM, chrome all day (never a habit)."""
    log = ActivityLog(str(tmp_path / "a.db"))
    add = log._insert
    for i, day in enumerate(DAYS):
        add(at=at(day, 9, i), kind="launch", app="code")
        add(at=at(day, 9, i + 1), kind="launch", app="spotify")
        add(at=at(day, 9, i + 2), kind="launch", app="whatsapp")
        add(at=at(day, 9, i), kind="app", app="code", title="x", duration_s=60)
        add(at=at(day, 9, i + 1), kind="app", app="spotify", title="x", duration_s=60)
        add(at=at(day, 9, i + 2), kind="app", app="whatsapp", title="x", duration_s=60)
        add(at=at(day, 12), kind="app", app="chrome", title="x", duration_s=3600)
        add(at=at(day, 15), kind="app", app="code", title="x", duration_s=60)
        add(at=at(day, 15, 1), kind="app", app="obsidian", title="x", duration_s=600)
        add(at=at(day, 22, 10 + i), kind="app", app="windowsterminal", title="x", duration_s=1800, project="catjang")
    add(at=at(DAYS[0], 15), kind="web", target="www.google.com", title="q - Google Search")
    return log


def learned(log):
    return {h.key: h for h in habits.learn(log.habit_rows(MONDAY - timedelta(days=1)))[0]}


def test_it_learns_time_habits_chains_and_routines(log):
    found = learned(log)
    catjang = found["time:project:catjang:weekday"]
    assert (catjang.days, catjang.observed, habits._clock(catjang.minute)) == (5, 5, "10:12 PM")
    assert found["chain:app:code>app:obsidian"].days == 5
    assert found["routine:code+spotify+whatsapp"].days == 5
    assert sorted(found) == ["chain:app:code>app:obsidian", "routine:code+spotify+whatsapp",
                             "time:app:code:weekday", "time:project:catjang:weekday"]
    # one suggestion per pattern: no smaller groups, no chains inside the routine, no time for its other
    # apps or for a chain's second app, no terminal habit for the project, nothing for chrome or google


def test_the_routine_covers_its_chains_but_other_chains_stay():
    routine = Habit("routine:a+b", "routine", ("app:a", "app:b"), 3, 5, minute=540)
    inside = Habit("chain:app:a>app:b", "chain", ("app:a", "app:b"), 3, 5)
    outside = Habit("chain:app:a>app:c", "chain", ("app:a", "app:c"), 3, 5)
    c_time = Habit("time:app:c:weekday", "time", ("app:c",), 3, 5, minute=541, weekend=False)
    assert habits.prune([routine, inside, outside, c_time]) == [routine, outside]


def test_a_start_needs_a_gap():
    rows = [(at(MONDAY, 9), "app", "code", None, 600, "coding", None),
            (at(MONDAY, 9, 20), "app", "code", None, 600, "coding", None),   # 10 min after: same stretch
            (at(MONDAY, 11), "app", "code", None, 600, "coding", None)]      # 1h30 after: a new start
    assert [when.hour for when, _ in habits.starts(rows)] == [9, 11]


def ctx(now, **kw):
    return Context(now, **kw)


def test_when_each_kind_is_due():
    time_habit = Habit("time:app:code:weekday", "time", ("app:code",), 4, 5, minute=9 * 60, weekend=False)
    tuesday = DAYS[1]
    assert habits.due(time_habit, ctx(tuesday.replace(hour=9, minute=10)))
    assert not habits.due(time_habit, ctx(tuesday.replace(hour=10)))                         # too late
    assert not habits.due(time_habit, ctx(tuesday.replace(hour=9), running=frozenset({"code"})))  # open already
    assert not habits.due(time_habit, ctx(datetime(2026, 10, 3, 9)))                           # a Saturday

    chain = Habit("chain:app:code>app:spotify", "chain", ("app:code", "app:spotify"), 4, 5)
    now = tuesday.replace(hour=9)
    assert habits.due(chain, ctx(now, app="code", app_since=now - timedelta(minutes=1)))
    assert not habits.due(chain, ctx(now, app="code", app_since=now - timedelta(minutes=30)))

    routine = Habit("routine:code+spotify", "routine", ("app:code", "app:spotify"), 3, 5, minute=540)
    assert habits.due(routine, ctx(now))
    assert not habits.due(routine, ctx(now.replace(hour=15)))                             # not its time
    assert not habits.due(routine, ctx(now, routines=({"vs code", "spotify", "chrome"},)))  # saved already


def test_confidence_learns_from_answers():
    habit = Habit("k", "time", ("app:code",), 4, 5, minute=540, weekend=False)
    assert habits.confidence(habit, {}) == pytest.approx(0.8)
    assert habits.confidence(habit, {"declined": 2}) == pytest.approx(0.8 / 3)
    assert habits.confidence(habit, {"accepted": 3, "declined": 1}) == pytest.approx(0.8 * 4 / 5)


def test_suggests_once_per_habit_and_records_the_example(log):
    tuesday_night = DAYS[1].replace(hour=22, minute=10)
    now_ctx = ctx(tuesday_night)
    s = habits.next_suggestion(log, tuesday_night, now_ctx)
    assert s.text == "You usually work on catjang around 10:12 PM on weekdays. Resume it?"
    assert s.buttons == "habit_project"
    assert habits.next_suggestion(log, tuesday_night + timedelta(minutes=1), now_ctx) is None  # once a day

    [line] = [json.loads(x) for x in habits.examples_path.read_text().splitlines()]
    assert line["habit"] == "time:project:catjang:weekday"
    assert line["features"]["support"] == 1.0 and line["features"]["minutes_from_usual"] == -2
    assert "Because you work on catjang around 10:12 PM on 5 of the last 5 weekdays" in habits.run({"action": "why_habit"}, log)


def test_unanswered_counts_as_ignored(log):
    night = DAYS[1].replace(hour=22, minute=10)
    habits.next_suggestion(log, night, ctx(night))
    habits.next_suggestion(log, night + timedelta(hours=3), ctx(night + timedelta(hours=3)))
    assert habits.load_state()["habits"]["time:project:catjang:weekday"]["ignored"] == 1
    assert json.loads(habits.examples_path.read_text().splitlines()[-1])["answer"] == "ignored"


def test_not_now_three_times_pauses_it_and_stop_mutes_it():
    about = {"habit": "time:app:code:weekday", "id": "x"}
    assert habits.answer(about, "later", MONDAY) == "Okay, not now."
    habits.answer(about, "later", MONDAY)
    assert habits.answer(about, "later", MONDAY) == "Okay — I'll leave that one for 7 days."
    record = habits.load_state()["habits"]["time:app:code:weekday"]
    assert record["paused_until"] == (MONDAY + timedelta(days=7)).timestamp() and record["declined"] == 3

    assert habits.answer(about, "never", MONDAY) == "Okay, I won't suggest that again."
    assert habits.load_state()["habits"]["time:app:code:weekday"]["muted"] is True


def test_do_it_opens_apps_and_sites_and_saves_routines(monkeypatch):
    opened = []
    monkeypatch.setattr("services.automation.system_control.system.open_app", lambda a: opened.append(a) or "ok")
    monkeypatch.setattr("services.automation.system_control.system.open_url", lambda u: opened.append(u) or "ok")
    habits.answer({"habit": "chain:app:code>app:spotify", "id": "1"}, "do")
    habits.answer({"habit": "time:site:github.com:weekday", "id": "2"}, "do")
    assert opened == ["spotify", "https://github.com"]
    assert habits.load_state()["habits"]["chain:app:code>app:spotify"]["accepted"] == 1

    reply = habits.answer({"habit": "routine:code+spotify", "id": "3", "minute": 9 * 60}, "do")
    assert reply == 'Saved the routine "morning setup": open VS Code and spotify. Say "run morning setup" to use it.'
    assert routines.load()["morning setup"] == ["open vs code", "open spotify"]


def test_process_names_become_app_names(monkeypatch):
    opened = []
    monkeypatch.setattr("services.automation.system_control.system.open_app", lambda a: opened.append(a) or "ok")
    habits.answer({"habit": "time:app:windowsterminal:weekday", "id": "1"}, "do")
    assert opened == ["windows terminal"]
    habit = Habit("time:app:windowsterminal:weekday", "time", ("app:windowsterminal",), 3, 4, minute=534, weekend=False)
    assert habits.text_for(habit) == "You usually open Windows Terminal around 8:54 AM on weekdays. Open it?"


def test_daily_limit(log, monkeypatch):
    monkeypatch.setattr(habits, "DAILY_LIMIT", 1)
    morning = DAYS[1].replace(hour=9, minute=2)
    assert habits.next_suggestion(log, morning, ctx(morning, running=frozenset({"code"}))).buttons == "habit_routine"
    night = DAYS[1].replace(hour=22, minute=10)
    assert habits.next_suggestion(log, night, ctx(night)) is None


@pytest.mark.parametrize("text, action", [
    ("what are my habits", "list_habits"), ("why did you suggest that", "why_habit"),
    ("forget the spotify habit", "forget_habit"), ("stop suggesting spotify", "forget_habit"),
    ("pause habit suggestions", "pause_habits"), ("resume habit suggestions", "resume_habits"),
])
def test_commands(text, action):
    assert habits.match_habit_command(text)["action"] == action


def test_list_forget_and_pause(log):
    listed = habits.run({"action": "list_habits"}, log, DAYS[4])
    assert "Weekdays around 10:12 PM: work on catjang (5 of 5 days)" in listed
    assert "After VS Code: open obsidian (5 days)" in listed and "Together: VS Code, spotify and whatsapp (5 days)" in listed

    assert habits.run({"action": "forget_habit", "name": "obsidian"}, log, DAYS[4]) == "Okay, I won't suggest obsidian any more."
    assert "obsidian" not in habits.run({"action": "list_habits"}, log, DAYS[4])
    assert habits.run({"action": "forget_habit", "name": "zoom"}, log, DAYS[4]) == "I don't have a habit about zoom."

    habits.run({"action": "pause_habits"}, log)
    night = DAYS[4].replace(hour=22, minute=10)
    assert habits.next_suggestion(log, night, ctx(night)) is None


def test_no_habits_yet(tmp_path):
    empty = ActivityLog(str(tmp_path / "e.db"))
    assert habits.run({"action": "list_habits"}, empty, MONDAY).startswith("No habits yet")
