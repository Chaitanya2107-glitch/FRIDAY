import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from services.activity import predict
from services.activity.log import ActivityLog, activity_log

MONDAY = datetime(2026, 9, 28, 9, 0)


def switches(log, day, apps):
    at = day
    for app in apps:
        log._insert(at=at.isoformat(), kind="app", app=app, title="x", duration_s=60)
        at += timedelta(minutes=2)


def test_guesses_are_commands_habits_first(tmp_path, monkeypatch):
    log = ActivityLog(str(tmp_path / "a.db"))
    for d in range(4):  # code, then spotify, then windowsterminal — every morning
        switches(log, MONDAY + timedelta(days=d), ["code", "spotify", "windowsterminal"])
    switches(log, MONDAY + timedelta(days=4), ["code"])
    monkeypatch.setattr(predict, "datetime", datetime)  # (plain datetime; no clock tricks needed)
    monkeypatch.setattr("services.activity.habits.due_now", lambda log, now: [])
    assert predict.bar_suggestions(log, MONDAY + timedelta(days=4, minutes=1)) == ["open spotify", "open windows terminal"]

    from services.activity.habits import Habit
    catjang = Habit("time:project:catjang:weekday", "time", ("project:catjang",), 4, 5, minute=540, weekend=False)
    monkeypatch.setattr("services.activity.habits.due_now", lambda log, now: [catjang])
    assert predict.bar_suggestions(log, MONDAY + timedelta(days=4, minutes=1))[0] == "resume catjang"


def test_outcomes_are_saved_and_scored():
    offered = ["resume catjang", "open spotify"]
    predict.bar_outcome(offered, "open spotify", activity_log)
    predict.bar_outcome(offered, "what's the weather", activity_log)   # typed something else: text not kept
    predict.bar_outcome(offered, None, activity_log)                   # closed
    predict.bar_outcome([], "hi", activity_log)                        # nothing shown: nothing to learn
    lines = [json.loads(x) for x in predict.bar_log_path.read_text().splitlines()]
    assert [(x["picked"], x["outcome"]) for x in lines] == [(1, "picked"), (-1, "typed"), (-1, "closed")]
    assert "weather" not in predict.bar_log_path.read_text()
    assert predict.bar_score() == "Command bar guesses: used 1 of 2 times (50%), the first guess 0 times."
    assert predict.match_predict_command("how good are your bar guesses")["action"] == "bar_score"


def test_api_endpoints():
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    assert client.get("/api/v1/predict/bar").json() == {"suggestions": []}  # an empty log: no guesses
    assert client.post("/api/v1/predict/bar/outcome", json={"offered": ["open spotify"], "sent": "open spotify"}).json() \
        == {"ok": True}
    assert json.loads(predict.bar_log_path.read_text())["outcome"] == "picked"
