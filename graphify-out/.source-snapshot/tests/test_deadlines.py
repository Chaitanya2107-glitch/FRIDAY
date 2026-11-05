import asyncio
from datetime import datetime, timedelta

import pytest

from services.automation import intent
from services.automation.system_control import AutomationError
from services.proactive import briefing, deadlines, timetable

NOW = datetime(2026, 9, 29, 15, 0)  # a Tuesday afternoon


@pytest.mark.parametrize("text, due", [
    ("Friday 11:59pm", datetime(2026, 10, 2, 23, 59)),
    ("friday 11:59", datetime(2026, 10, 2, 23, 59)),  # no am/pm: evening
    ("tomorrow", datetime(2026, 9, 30, 23, 59)),
    ("5 Oct", datetime(2026, 10, 5, 23, 59)),
    ("oct 5 at 9am", datetime(2026, 10, 5, 9, 0)),
    ("5/10", datetime(2026, 10, 5, 23, 59)),  # day/month
    ("tonight", datetime(2026, 9, 29, 23, 59)),
    ("tuesday 2pm", datetime(2026, 10, 6, 14, 0)),  # today's already past: next week
    ("noon tomorrow", datetime(2026, 9, 30, 12, 0)),
    ("5 Jan", datetime(2027, 1, 5, 23, 59)),
])
def test_parse_due(text, due):
    assert deadlines.parse_due(text, NOW) == due


def test_unreadable_dates():
    with pytest.raises(AutomationError, match="couldn't tell when"):
        deadlines.parse_due("sometime soon", NOW)
    with pytest.raises(AutomationError, match="no date"):
        deadlines.parse_due("31 feb", NOW)


@pytest.mark.parametrize("text, action", [
    ("DBMS assignment due Friday 11:59pm", "add_deadline"),
    ("add deadline OS lab record due 5 Oct", "add_deadline"),
    ("project report is due tomorrow", "add_deadline"),
    ("what's due", "list_deadlines"),
    ("whats due this week", "list_deadlines"),
    ("list my deadlines", "list_deadlines"),
    ("remove deadline 2", "remove_deadline"),
    ("clear my deadlines", "clear_deadlines"),
    ("why is the assignment due tomorrow", None),  # a question, not a deadline
    ("the rent is due whenever", None),
    ("done with the dbms assignment", None),  # nothing saved to finish yet
])
def test_commands(text, action):
    match = deadlines.match_deadline_command(text, NOW)
    assert (match and match["action"]) == action


def test_add_list_finish():
    assert deadlines.add("DBMS assignment", datetime(2026, 10, 2, 23, 59), NOW) == \
        "Deadline added: DBMS assignment — due Friday 2 Oct at 11:59 PM (in 3 days)."
    deadlines.add("OS record", datetime(2026, 9, 30, 17, 0), NOW)
    assert deadlines.list_message(NOW) == ("1. OS record — tomorrow at 5:00 PM (in 26 hours)\n"
                                           "2. DBMS assignment — Friday 2 Oct at 11:59 PM (in 3 days)")
    match = deadlines.match_deadline_command("done with the dbms assignment", NOW)
    assert deadlines.run(match, NOW) == "Nice — DBMS assignment is off the list."
    with pytest.raises(AutomationError, match="already past"):
        deadlines.add("late thing", NOW - timedelta(hours=1), NOW)


def test_countdown_alerts_fire_once_each():
    due = NOW + timedelta(days=5)
    deadlines.add("DBMS assignment", due, NOW)
    assert deadlines.due_alerts(NOW + timedelta(days=1)) == []
    assert deadlines.due_alerts(due - timedelta(days=3)) == ["DBMS assignment is due Sunday 4 Oct at 3:00 PM (in 3 days)."]
    assert deadlines.due_alerts(due - timedelta(days=3) + timedelta(minutes=1)) == []
    assert deadlines.due_alerts(due - timedelta(days=1)) == ["DBMS assignment is due tomorrow at 3:00 PM (in 24 hours)."]
    assert deadlines.due_alerts(due - timedelta(hours=3)) == ["DBMS assignment is due today at 3:00 PM (in 3 hours)."]
    assert deadlines.due_alerts(due + timedelta(hours=1)) == []  # past: no more alerts


def test_a_late_start_shows_only_the_most_urgent_alert():
    due = NOW + timedelta(days=5)
    deadlines.add("DBMS assignment", due, NOW)
    assert len(deadlines.due_alerts(due - timedelta(hours=2))) == 1  # FRIDAY was off for days


def test_adding_inside_a_window_doesnt_alert_straight_away():
    deadlines.add("OS record", NOW + timedelta(hours=20), NOW)
    assert deadlines.due_alerts(NOW + timedelta(minutes=1)) == []
    assert deadlines.due_alerts(NOW + timedelta(hours=17)) == ["OS record is due today at 11:00 AM (in 3 hours)."]


def test_briefing_and_class_warning():
    deadlines.add("DBMS assignment", NOW + timedelta(days=1), NOW)
    deadlines.add("OS record", NOW + timedelta(days=10), NOW)
    assert deadlines.briefing_line(NOW) == "Due soon: DBMS assignment tomorrow at 3:00 PM."
    timetable._save([{"day": "tuesday", "start": "15:10", "end": "16:00", "subject": "DBMS", "room": "204"}])
    assert timetable.due_warnings(NOW) == [
        "DBMS starts in 10 minutes in 204. DBMS assignment is due tomorrow at 3:00 PM."]


@pytest.mark.parametrize("now, due", [
    (NOW, datetime(2026, 10, 5, 23, 59)),
    (datetime(2026, 10, 11, 15, 0), datetime(2027, 10, 5, 23, 59)),
])
def test_through_the_command_path(monkeypatch, now, due):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return now

    # Freeze both parsing and execution; the command path otherwise uses today's date.
    monkeypatch.setattr(deadlines, "datetime", FixedDatetime)
    result = asyncio.run(intent.try_system_action("hey friday, add deadline OS lab record due 5 Oct", "openai"))
    assert result.success and result.message.startswith(f"Deadline added: OS lab record — due {deadlines.when(due, now)}")
    assert deadlines.load()[0]["due"] == due.isoformat(timespec="minutes")
    result = asyncio.run(intent.try_system_action("add deadline thesis due someday", "openai"))
    assert not result.success and "couldn't tell when" in result.message
