"""Creation/editing paraphrases resolve through existing parsers without actions."""
from datetime import datetime
import re

import pytest

from services.automation import intent
from services.automation.task_phrases import rephrase_task_command
from services.mind import workspace_commands
from services.reminders.parser import parse_reminder


CASES = [
    ("timetable", "schedule a DBMS class on monday from 9am to 10am", "add class DBMS on monday from 9am to 10am"),
    ("timetable", "put Data Structures on my timetable for tuesday from 14:00 to 15:00 in room B-12", "add class Data Structures on tuesday from 14:00 to 15:00 in room B-12"),
    ("timetable", "take DBMS off my timetable on monday", "remove class DBMS on monday"),
    ("timetable", "remove Data Structures from my schedule", "remove class Data Structures"),
    ("marks", "record 18 out of 25 for DBMS CIE 1", "scored 18/25 in DBMS CIE 1"),
    ("marks", "update my marks for DBMS CIE 1 to 19.5/25", "scored 19.5/25 in DBMS CIE 1"),
    ("marks", "save my score for Data Structures quiz 2 as 8 out of 10", "scored 8/10 in Data Structures quiz 2"),
    ("limits", "set Chrome's daily limit to 45 minutes", "limit Chrome to 45 minutes a day"),
    ("limits", "change the daily limit for Visual Studio Code to 1.5 hours", "limit Visual Studio Code to 1.5 hours a day"),
    ("limits", "give Valorant a daily limit of 2 hours", "limit Valorant to 2 hours a day"),
    ("limits", "stop limiting Chrome", "remove the limit on Chrome"),
    ("watches", "watch https://Example.com/Results?q=Case for changes", "tell me when https://Example.com/Results?q=Case changes"),
    ("watches", "watch Blender until it closes", "tell me when Blender closes"),
    ("watches", "alert me at 85% battery", "tell me when battery reaches 85%"),
    ("watches", "watch Server.log for text: READY and Listening!", "tell me when Server.log says READY and Listening!"),
    ("watches", "watch Friday for errors", "tell me when Friday logs an error"),
    ("watches", "cancel the watch on Blender", "stop watching Blender"),
    ("reminders", "in 20 minutes remind me to Call Mom and check Version 2!", "remind me in 20 minutes to Call Mom and check Version 2!"),
    ("reminders", "at 5:30pm tomorrow remind me to Call Mom", "remind me at 5:30pm tomorrow to Call Mom"),
    ("reminders", "reminder in 2 hours: Pay 250 and save Receipt.pdf!", "remind me in 2 hours to Pay 250 and save Receipt.pdf!"),
    ("projects", "replace startup steps for project Friday with run npm run Dev and open VS Code", "set resume steps for Friday: run npm run Dev and open VS Code"),
    ("projects", "when I return to project Friday do: run npm run Dev and open VS Code", "set resume steps for Friday: run npm run Dev and open VS Code"),
    ("workspace", "set a high priority goal: Build FRIDAY and test Version 2!", "add goal high: Build FRIDAY and test Version 2!"),
    ("workspace", "track a new task: Fix CaseSensitive.py!", "start task: Fix CaseSensitive.py!"),
    ("workspace", "create a task for goal Build Friday: Test the API", "start task for goal Build Friday: Test the API"),
    ("workspace", "set the steps for task current to: Read docs; Implement; Verify!", "plan task current: Read docs; Implement; Verify!"),
    ("workspace", "report completed step for task current: Tests passed and Report.pdf saved!", "finish task step current: Tests passed and Report.pdf saved!"),
    ("workspace", "mark goal Build Friday as done", "complete goal Build Friday"),
    ("workspace", "put goal Build Friday on hold", "pause goal Build Friday"),
    ("workspace", "mark goal Build Friday as cancelled", "cancel goal Build Friday"),
    ("workspace", "continue goal Build Friday", "resume goal Build Friday"),
    ("workspace", "change the priority of goal Build Friday to high", "set goal Build Friday priority high"),
    ("workspace", "mark task current as blocked: Waiting for API key!", "block task current: Waiting for API key!"),
    ("workspace", "mark task current as done: API tests passed!", "complete task current: API tests passed!"),
    ("workspace", "put task current on hold: Waiting for Review!", "pause task current: Waiting for Review!"),
    ("workspace", "continue task current", "resume task current"),
    ("workspace", "mark task current as cancelled: Requirements Changed!", "cancel task current: Requirements Changed!"),
    ("workspace", "show my task progress", "task progress"),
]

MATCHERS = {
    "timetable": intent.timetable.match_timetable_command,
    "marks": intent.attendance.match_attendance_command,
    "limits": intent.limits.match_limit_command,
    "watches": intent.watches.match_watch_command,
    "projects": intent.projects.match_project_command,
    "workspace": workspace_commands.match_command,
    "reminders": lambda text: parse_reminder(text, datetime(2026, 10, 16, 10)),
}


@pytest.mark.parametrize("family,phrase,canonical", CASES)
def test_variants_keep_fields_and_reach_existing_parser(monkeypatch, family, phrase, canonical):
    monkeypatch.setattr(intent.projects, "load", lambda: {"friday": {"path": "C:/Friday"}})
    rewritten = rephrase_task_command(phrase)
    assert rewritten == canonical
    expected = MATCHERS[family](canonical)
    assert expected
    assert MATCHERS[family](rewritten) == expected


@pytest.mark.parametrize("family,phrase,canonical", CASES)
@pytest.mark.parametrize("wrapper", ["don't {}", "never {}", "type {}", "note {}", "search for {}", "how do I {}", '"{}"', "remind me tomorrow to {}"])
def test_examples_negation_and_literal_payloads_are_not_commands(family, phrase, canonical, wrapper):
    assert rephrase_task_command(wrapper.format(phrase)) is None


@pytest.mark.parametrize("phrase", [
    "schedule a DBMS class on someday from 9am to 10am",
    "set Chrome's daily limit to unlimited",
    "record great marks for DBMS CIE 1",
    "mark goal Build Friday as maybe done",
    "watch this",
    "reminder tomorrow: something",
    "schedule a DBMS class on monday from 9am to 10am and open Chrome",
    "watch Server.log for text: battery is ready",
    "watch battery.log for errors",
    "watch Server.log for text: https://example.com changes",
    "watch battery until it closes",
    "watch Downloads until it closes",
])
def test_incomplete_or_ambiguous_paraphrases_do_not_guess(phrase):
    assert rephrase_task_command(phrase) is None


def test_payload_quoted_commands_are_preserved():
    phrase = 'track a new task: Explain "mark goal Friday as done" and Don\'t run it!'
    assert rephrase_task_command(phrase) == 'start task: Explain "mark goal Friday as done" and Don\'t run it!'


def test_watch_log_text_is_still_literal():
    rewritten = rephrase_task_command('watch Server.log for text: "Ready?" [v2] and x+y!')
    parsed = intent.watches.match_watch_command(rewritten)
    assert parsed["pattern"] == re.escape('"Ready?" [v2] and x+y!')


def test_unknown_project_is_not_created_by_step_rewrite(monkeypatch):
    monkeypatch.setattr(intent.projects, "load", lambda: {})
    rewritten = rephrase_task_command("replace startup steps for project Unknown with run npm test")
    assert intent.projects.match_project_command(rewritten) is None
