import json
from datetime import datetime, timedelta

import pytest

from services.activity import habits, insights
from services.activity.log import ActivityLog
from services.proactive import deadlines, timetable

NOW = datetime(2026, 9, 30, 12, 0)


@pytest.fixture
def log(tmp_path):
    return ActivityLog(str(tmp_path / "a.db"))


def test_suggestion_scoreboard():
    lines = [{"id": "1", "at": "2026-09-28T09:00:00", "habit": "time:app:code:weekday"},
             {"id": "1", "answer": "do"},
             {"id": "2", "at": "2026-09-28T22:00:00", "habit": "chain:app:code>app:spotify"},
             {"id": "2", "answer": "later"},
             {"id": "3", "at": "2026-09-29T09:05:00", "habit": "time:app:code:weekday"},
             {"id": "3", "answer": "ignored"}]
    habits.examples_path.write_text("\n".join(json.dumps(x) for x in lines))
    assert insights.suggestion_score() == ("Habit suggestions: 3 shown, 1 used (33%), 1 not now, 0 stopped, 1 ignored. "
                                           "By kind: time 1/2, chain 0/1. Best in the mornings (1/2).")


def test_usual_start_and_stop_crossing_midnight(log):
    for d in range(3):
        day = datetime(2026, 9, 26 + d)
        log._insert(at=day.replace(hour=9, minute=10).isoformat(), kind="app", app="code", duration_s=3600)
        log._insert(at=(day + timedelta(days=1)).replace(hour=1).isoformat(), kind="app", app="code", duration_s=1800)
    assert insights.day_hours(log, NOW) == "Over the last 2 weeks you usually started around 9:10 AM and stopped around 1:30 AM."


def test_best_study_time_and_forecast(log):
    for d in range(4):
        day = datetime(2026, 9, 25 + d)
        log._insert(at=day.replace(hour=22).isoformat(), kind="app", app="chrome", title="Arrays - GeeksforGeeks",
                    duration_s=3000)
        log._insert(at=day.replace(hour=15).isoformat(), kind="app", app="chrome", title="Arrays - GeeksforGeeks",
                    duration_s=900)
    assert insights.best_study(log, NOW) == ("Your longest study sessions are in the nights: 4 sessions, 50m on average; "
                                             "the shortest in the afternoons (15m).")
    now = datetime(2026, 9, 30, 22, 20)
    log._insert(at=now.replace(minute=0).isoformat(), kind="app", app="chrome", title="Arrays - GeeksforGeeks", duration_s=1200)
    assert insights.session_forecast(log, now) == \
        "You've been studying for 20m; around this time it usually lasts 50m — about 30m to go."


def test_deadline_risk(log):
    timetable._save([{"day": "monday", "start": "09:00", "end": "10:00", "subject": "DBMS", "room": None}])
    deadlines._save([{"what": "DBMS assignment", "due": (NOW + timedelta(days=2)).isoformat(), "alerted": []}])
    assert insights.deadline_risk_line(log, NOW) == \
        "Heads up: DBMS assignment is due in 2 days with 0 min of DBMS in the last 3 days."
    log._insert(at=(NOW - timedelta(hours=5)).isoformat(), kind="app", app="acrobat", title="DBMS unit 3.pdf", duration_s=3600)
    assert insights.deadline_risk_line(log, NOW) == ""


def test_command_dataset(log):
    log.log_command({"action": "open_app", "app_name": "spotify"}, True)
    log.log_command({"action": "volume_up"}, True)
    assert insights.write_command_dataset(log) == 2
    rows = [json.loads(x) for x in insights.commands_path.read_text().splitlines()]
    assert rows[1]["previous_action"] == "open_app" and rows[1]["action"] == "volume_up"
    assert insights.match_insight_command("when do I study best")["action"] == "best_study"
    assert insights.match_insight_command("how long will this session last")["action"] == "session_forecast"
