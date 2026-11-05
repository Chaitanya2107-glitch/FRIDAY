import asyncio
from datetime import date, datetime

import pytest

from services.activity import fun, journal
from services.activity.log import ActivityLog
from services.automation import personality
from services.proactive import timetable


@pytest.fixture
def log(tmp_path):
    timetable._save_subjects(["DBMS"])
    log = ActivityLog(str(tmp_path / "a.db"))
    add = log._insert
    for day in (26, 27, 28, 29):  # DBMS 40 min a day, Sat–Tue
        add(at=datetime(2026, 9, day, 9).isoformat(), kind="app", app="acrobat", title="DBMS unit 2.pdf", duration_s=2400)
    add(at=datetime(2026, 9, 23, 9).isoformat(), kind="app", app="acrobat", title="DBMS unit 1.pdf", duration_s=2400)
    add(at=datetime(2026, 9, 29, 21).isoformat(), kind="app", app="valorant", title="VALORANT", duration_s=7200)
    add(at=datetime(2026, 9, 30, 20).isoformat(), kind="app", app="minecraft", title="Minecraft", duration_s=1800)
    return log


@pytest.mark.parametrize("text, action", [
    ("how many hours did I game this week", "game_hours"),
    ("gaming time today", "game_hours"),
    ("what's my study streak", "study_streak"),
    ("semester wrap-up", "semester_wrap"),
    ("how was my semester", "semester_wrap"),
])
def test_fun_commands(text, action):
    assert fun.match_fun_command(text)["action"] == action


def test_game_hours_per_game(log):
    now = datetime(2026, 9, 30, 23)
    assert fun.game_hours("how many hours did I game this week", log, now) == \
        "You gamed 2h 30m this week — valorant 2h 0m, minecraft 30m."
    assert fun.game_hours("game hours yesterday", log, now) == "You gamed 2h 0m yesterday — valorant 2h 0m."
    assert fun.game_hours("game hours on sunday", log, now).startswith("No gaming")


def test_study_streak_survives_until_tonight(log):
    assert fun.streaks(log, date(2026, 9, 30)) == (4, 4, False)  # nothing yet today: still alive
    assert "keep it going" in fun.streak_message(log, date(2026, 9, 30))
    assert fun.streaks(log, date(2026, 10, 1))[0] == 0  # a whole day missed
    log._insert(at=datetime(2026, 9, 30, 10).isoformat(), kind="app", app="acrobat", title="DBMS unit 3.pdf", duration_s=1800)
    assert fun.streak_message(log, date(2026, 9, 30)) == \
        "5 days in a row with 30+ minutes of study. That's your best yet."


def test_semester_wrap_up_page(log, monkeypatch):
    monkeypatch.setattr(fun.config, "SEMESTER_START", "2026-09-20")
    opened = []
    reply = fun.semester_wrap(log, date(2026, 9, 30), open_file=opened.append)
    text = opened[0].read_text(encoding="utf-8")
    assert opened[0].parent == journal.JOURNAL_DIR
    assert text.startswith("# Semester wrap-up — 20 Sep 2026 to 30 Sep 2026")
    assert "## Study\n- DBMS 3h 20m" in text and "## Games\n- valorant 2h 0m\n- minecraft 30m" in text
    assert "Best study streak: 4 days" in text
    assert reply.startswith("Your semester so far: 5h 50m over 11 days")


def test_semester_starts_with_the_log_when_not_set(log):
    assert fun.semester_start(log) == date(2026, 9, 23)


def test_roast_my_week_uses_seven_days(monkeypatch):
    assert personality.match_personality_command("roast my week")["week"] is True
    assert personality.match_personality_command("roast me")["week"] is False
    seen = []

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kw):
        seen.append((messages[0].content, system_prompt))
        raise RuntimeError("offline")
    monkeypatch.setattr("providers.failover.complete_with_failover", fake_ai)
    monkeypatch.setattr(personality, "_minutes_today", lambda now, days=1: {"gaming": 120 * days})
    reply = asyncio.run(personality.roast_me("openai", datetime(2026, 9, 30, 22), week=True))
    assert reply.startswith("The last 7 days: 840 min gaming") and "about their week" in seen[0][1]
