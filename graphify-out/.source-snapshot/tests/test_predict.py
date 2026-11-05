import asyncio
from datetime import datetime, timedelta

import pytest

from services.activity import predict
from services.automation import intent

MONDAY = datetime(2026, 9, 28, 9, 0)


def day_of(pattern, start=MONDAY, days=7, gap_minutes=5):
    """The same app pattern every day, a switch every gap_minutes: [(at, app)]."""
    rows = []
    for d in range(days):
        at = start + timedelta(days=d)
        for app in pattern:
            rows.append((at.isoformat(), app))
            at += timedelta(minutes=gap_minutes)
    return rows


def test_a_title_change_in_the_same_app_is_not_a_switch():
    rows = [(MONDAY.isoformat(), "chrome"), ((MONDAY + timedelta(minutes=1)).isoformat(), "chrome"),
            ((MONDAY + timedelta(minutes=2)).isoformat(), "code")]
    assert [(a, b) for _, a, b, _ in predict.switches(rows)] == [("chrome", "code")]


def test_a_routine_is_learned_and_scored_without_peeking():
    _, weeks = predict.replay(day_of(["windowsterminal", "chrome", "spotify", "code"] * 5))
    week = weeks[MONDAY.date()]
    assert week["n"] > 100 and week["top1"] / week["n"] > 0.9  # a fixed routine is easy
    first_day = predict.replay(day_of(["a", "b", "c"], days=1))[1][MONDAY.date()]
    assert first_day["top1"] == 0  # the very first switches have nothing earlier to learn from


def test_going_back_is_learned_as_a_habit():
    # alt-tab between an editor and whatever else is open
    rows = day_of(["code", "chrome", "code", "spotify", "code", "chrome", "code", "discord"] * 4)
    predictor, weeks = predict.replay(rows)
    assert predictor.top("chrome", MONDAY, before="code")[0] == "code"
    assert predictor.top("discord", MONDAY, before="code")[0] == "code"
    week = weeks[MONDAY.date()]
    assert week["top1"] >= week["naive"]


def test_week_line_needs_enough_switches():
    assert predict.week_line({"n": 5, "top1": 5, "top3": 5, "naive": 5}) is None
    assert predict.week_line({"n": 200, "top1": 90, "top3": 170, "naive": 80}) == \
        "45% right first guess, 85% in the top 3 (naive guess 40%; 200 app switches)"


class FakeLog:
    def __init__(self, rows):
        self.rows = rows

    def app_sequence(self):
        return self.rows


def test_answers():
    log = FakeLog(day_of(["windowsterminal", "chrome", "spotify"] * 6))
    assert predict.accuracy(log).startswith("My app predictions, checked against what you actually did:\nWeek of 28 Sep: ")
    assert predict.predict_next(log, MONDAY).startswith("After spotify, my guess is windowsterminal")
    assert predict.accuracy(FakeLog([])) == "Not enough activity yet to score my predictions."
    assert predict.predict_next(FakeLog([])) == "I haven't seen enough of your activity yet."


@pytest.mark.parametrize("text, action", [
    ("how good are your predictions", "prediction_accuracy"),
    ("how accurate are your predictions", "prediction_accuracy"),
    ("prediction accuracy", "prediction_accuracy"),
    ("what will I open next", "predict_next"),
    ("what do you think I'll open next", "predict_next"),
    ("predict the weather", None),
])
def test_commands(text, action):
    match = predict.match_predict_command(text)
    assert (match and match["action"]) == action


def test_through_the_command_path():
    result = asyncio.run(intent.try_system_action("hey friday, how good are your predictions?", "openai"))
    assert result.success and result.message == "Not enough activity yet to score my predictions."
