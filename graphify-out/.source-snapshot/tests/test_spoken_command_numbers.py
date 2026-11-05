"""Spoken quantities only become digits inside explicit command slots."""
from datetime import datetime, timedelta

import pytest

from services.automation.spoken_numbers import normalize_command_numbers


@pytest.mark.parametrize("phrase,expected", [
    ("remind me in twenty five minutes to Buy Twenty One Pilots tickets", "remind me in 25 minutes to Buy Twenty One Pilots tickets"),
    ("remind me in one hundred and five seconds to type thirty", "remind me in 105 seconds to type thirty"),
    ("set a reminder for forty-five minutes to Call Mom", "set a reminder in 45 minutes to Call Mom"),
    ("wait five seconds", "wait 5 seconds"),
    ("pause for two minutes", "pause for 2 minutes"),
    ("shutdown in thirty minutes", "shutdown in 30 minutes"),
    ("restart my laptop in an hour", "restart my laptop in 1 hour"),
    ("pause nudges for an hour", "pause nudges for 1 hour"),
    ("snooze my nudges for ninety nine minutes", "snooze my nudges for 99 minutes"),
    ("wait a hundred seconds", "wait 100 seconds"),
    ("remind me in nine hundred and ninety nine minutes to call", "remind me in 999 minutes to call"),
    ("limit Twenty One Pilots to forty minutes a day", "limit Twenty One Pilots to 40 minutes a day"),
    ("set a daily limit of two hours for Formula One", "set a daily limit of 2 hours for Formula One"),
    ("open result two", "open result 2"),
    ("open search result twenty first", "open search result 21"),
    ("show result twenty-two in folder", "show result 22 in folder"),
    ("open reading list item three", "open reading list item 3"),
    ("done with reading list number seventh", "done with reading list number 7"),
    ("open item eleven from my reading list", "open item 11 from my reading list"),
    ("open saved reading item eight", "open saved reading item 8"),
    ("mark reading item sixth as read", "mark reading item 6 as read"),
    ("cancel reminder number four", "cancel reminder number 4"),
    ("delete reminder twenty third", "delete reminder 23"),
    ("restore clipboard item nine", "restore clipboard item 9"),
])
def test_explicit_number_slots(phrase, expected):
    assert normalize_command_numbers(phrase) == expected


@pytest.mark.parametrize("phrase", [
    "type wait five seconds", "note: open result two", "search for twenty one pilots",
    "message Mom: remind me in twenty minutes to call", "save contact two 1234567890",
    "open Twenty One Pilots", "open six", "cancel reminder for Twenty One Pilots",
    "don't shutdown in thirty minutes", "do not wait five seconds",
    "shutdown in zero seconds", "wait zero seconds", "open result zero",
    "wait twenty thirteen seconds", "wait one two seconds", "wait one and two seconds",
    "wait one hundred hundred seconds", "wait twenty 5 seconds", "wait five point two seconds",
    "wait five seconds and close chrome", "shutdown in five minutes and ten seconds",
    "remind me in two hours and thirty minutes to call Mom",
    "remind me to buy twenty oranges in five minutes", "remind me at five pm to call Mom",
    "remind me on twenty first October to call Mom", "today is twenty first October",
    "open result two and delete it", "cancel reminder four or five", "cancel all reminders except two",
    "limit Formula One to twenty five minutes and ten seconds", "pause nudges for five seconds",
    "restart in twenty seconds", "wait one thousand seconds",
    "wait twenty--five seconds", "wait hundred seconds", "wait ten hundred seconds",
    "shutdown in minus thirty minutes", "copy item two", "wait five seconds tomorrow",
    "remind me in first minutes to call", "open result one hundred zero",
])
def test_literal_ambiguous_and_unsupported_numbers_stay_untouched(phrase):
    assert normalize_command_numbers(phrase) == phrase


def test_normalized_reminder_preserves_task_and_due_time():
    from services.automation.intent import _match_reminder_command
    from services.reminders.parser import parse_reminder

    now = datetime(2030, 1, 2, 10)
    text = normalize_command_numbers("remind me in twenty five minutes to Buy Twenty One Pilots tickets")
    task, due = parse_reminder(text, now)
    assert task == "Buy Twenty One Pilots tickets"
    assert due == now + timedelta(minutes=25)
    wrapped = normalize_command_numbers("set a reminder for forty-five minutes to Call Mom")
    parsed = _match_reminder_command(wrapped)
    assert parse_reminder(parsed["message"], now) == ("Call Mom", now + timedelta(minutes=45))


def test_normalized_numbers_reach_existing_matchers():
    from services.activity.limits import match_limit_command
    from services.automation.power import match_power_command
    from services.automation.routines import pause_seconds
    from services.memory.reading_list import match_reading_command
    from services.proactive.watcher import match_proactive_command

    assert pause_seconds(normalize_command_numbers("wait five seconds")) == 5
    assert match_power_command(normalize_command_numbers("shutdown in thirty minutes"))["seconds"] == 1800
    assert match_proactive_command(normalize_command_numbers("pause nudges for an hour"))["minutes"] == 60
    assert match_limit_command(normalize_command_numbers("limit Formula One to twenty five minutes a day")) == {
        "type": "system", "action": "set_limit", "app": "formula one", "minutes": 25,
    }
    assert match_reading_command(normalize_command_numbers("open reading list item three"))["number"] == 3


def test_normalized_indices_reach_existing_matchers(tmp_path):
    from services.automation.command_words import rephrase_command
    from services.automation.device_commands import match_device_command
    from services.automation.intent import _match_reminder_command
    from services.files.assistant import last_results, match_file_command
    from services.files.search import FileHit

    last_results.set([FileHit(str(tmp_path / "notes.txt"), "notes.txt")])
    assert match_file_command(normalize_command_numbers("open result two"))["number"] == 2
    assert match_file_command(rephrase_command(normalize_command_numbers("open search result twenty first")))["number"] == 21
    assert _match_reminder_command(normalize_command_numbers("cancel reminder number four"))["number"] == 4
    assert match_device_command(normalize_command_numbers("restore clipboard item nine"))["number"] == 9


def test_routine_wait_accepts_spoken_numbers_without_router():
    from services.automation.routines import MAX_PAUSE_SECONDS, pause_seconds

    assert pause_seconds("wait five seconds") == 5
    assert pause_seconds("pause for twenty five minutes") == MAX_PAUSE_SECONDS
    assert pause_seconds("wait twenty thirteen seconds") is None
