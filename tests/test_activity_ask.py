from datetime import datetime, timedelta

import pytest

from services.activity import ask
from services.activity.log import ActivityLog

NOW = datetime(2026, 9, 28, 15, 0)  # a Monday afternoon
YESTERDAY = NOW - timedelta(days=1)


@pytest.fixture
def log(tmp_path):
    log = ActivityLog(str(tmp_path / "a.db"))
    add = log._insert
    add(at=(NOW.replace(hour=9, minute=5)).isoformat(), kind="web", target="www.youtube.com",
        title="(436) How B-Trees Work - YouTube")
    add(at=(NOW.replace(hour=9, minute=30)).isoformat(), kind="web", target="www.google.com",
        title="dbms normalization - Google Search")
    add(at=(NOW.replace(hour=10)).isoformat(), kind="file", target="DBMS Unit 2.pdf")
    add(at=(NOW.replace(hour=10, minute=1)).isoformat(), kind="file", target="ms-screenclip---source=PrintScreen")
    add(at=(NOW.replace(hour=11)).isoformat(), kind="app", app="spotify", title="Arijit Singh - Tose Naina",
        duration_s=240)
    add(at=(NOW.replace(hour=11, minute=5)).isoformat(), kind="app", app="spotify", title="Spotify Premium",
        duration_s=60)
    add(at=(NOW.replace(hour=12)).isoformat(), kind="app", app="windowsterminal", title="✳ Build next",
        duration_s=3000)
    add(at=(NOW.replace(hour=12, minute=50)).isoformat(), kind="app", app="windowsterminal", title="◐ Build next",
        duration_s=600)
    add(at=(NOW.replace(hour=13)).isoformat(), kind="app", app="chrome",
        title="How B-Trees Work - YouTube - Google Chrome", duration_s=1500)
    add(at=(YESTERDAY.replace(hour=16)).isoformat(), kind="web", target="github.com",
        title="me/catjang: a cat game")
    add(at=(YESTERDAY.replace(hour=16, minute=1)).isoformat(), kind="web", target="github.com", title="Manage access")
    add(at=(YESTERDAY.replace(hour=21)).isoformat(), kind="launch", app="b1-win64-shipping")
    return log


def say(log, question):
    match = ask.match_activity_question(question)
    assert match, f"not recognised: {question}"
    return ask.answer(match["question"], log, now=NOW)


def test_repo_yesterday(log):
    assert say(log, "what was the repo I looked at yesterday") == "Yesterday: 4:00 pm — me/catjang: a cat game (github.com)."


def test_video_this_morning(log):
    assert say(log, "what video did I watch this morning") == "This morning: 9:05 am — How B-Trees Work (youtube.com)."


def test_file_with_a_topic(log):
    assert say(log, "which file did I open today for dbms") == "Today: 10:00 am — DBMS Unit 2.pdf."
    assert "screenclip" not in say(log, "what files did I open today")


def test_songs_skip_the_paused_window(log):
    assert say(log, "what song was I listening to today") == "Today: 11:00 am — Arijit Singh - Tose Naina."


def test_searches(log):
    assert say(log, "what did i search for on google today") == "Today: 9:30 am — dbms normalization (google.com)."


def test_when_last(log):
    assert say(log, "when did I last play games") == "Last time was yesterday 9:00 pm: opened b1-win64-shipping."


def test_how_long(log):
    assert say(log, "how long did i spend on youtube today") == "You spent 25m on YouTube today."
    assert say(log, "how long did I spend on reddit yesterday").startswith("I don't see anything matching reddit")


def test_apps_are_totalled_not_listed(log):
    assert say(log, "what apps did i use today") == "Today you used: windowsterminal 1h 0m, chrome 25m, spotify 5m."


def test_same_title_with_different_spinner_marks_is_one_thing(log):
    assert say(log, "what did i work on today").count("Build next") == 1


@pytest.mark.parametrize("question", [
    "what's the weather", "what did I tell you about my birthday", "open chrome", "what time is it",
])
def test_not_activity_questions(question):
    assert ask.match_activity_question(question) is None


@pytest.mark.parametrize("question, expected", [
    ("what did i watch yesterday", ("2026-09-27T00:00:00", "2026-09-28T00:00:00", "yesterday")),
    ("what did i open this morning", ("2026-09-28T05:00:00", "2026-09-28T12:00:00", "this morning")),
    ("what did i watch last night", ("2026-09-27T18:00:00", "2026-09-28T05:00:00", "last night")),
    ("what did i open on saturday", ("2026-09-26T00:00:00", "2026-09-27T00:00:00", "on Saturday")),
    ("what did i open last monday", ("2026-09-21T00:00:00", "2026-09-22T00:00:00", "on Monday")),
    ("what did i open last week", ("2026-09-21T00:00:00", "2026-09-28T00:00:00", "last week")),
    ("hey what did friday open", ("2026-09-22T00:00:00", NOW.isoformat(), "in the past week")),  # the assistant
    ("what did i open on friday", ("2026-09-25T00:00:00", "2026-09-26T00:00:00", "on Friday")),
])
def test_time_windows(question, expected):
    start, end, label = ask.time_window(question, NOW)
    assert (start.isoformat(), end.isoformat(), label) == expected
