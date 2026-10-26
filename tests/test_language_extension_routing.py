"""Shared language hooks preserve parameters before routing chat or voice commands."""
import asyncio

import pytest

from core.config import config
from services.automation import intent
from services.automation.command_words import rephrase_command
from services.automation.results import ActionResult
from services.mind import workspace_commands
from test_task_phrase_variants import CASES


@pytest.mark.parametrize("phrase,expected", [
    ("Friday, please schedule a DBMS class on monday from 9am to 10am", "add class DBMS on monday from 9am to 10am"),
    ("record 18 out of 25 for DBMS CIE 1", "scored 18/25 in DBMS CIE 1"),
    ("watch Server.log for text: READY and Listening!", "tell me when Server.log says READY and Listening!"),
    ("report completed step for task current: Tests passed!", "finish task step current: Tests passed!"),
    ("please remind me in twenty five minutes to Buy Twenty One Pilots tickets!", "remind me in 25 minutes to Buy Twenty One Pilots tickets!"),
    ("open reading list item three", "open reading list item 3"),
    ("set a reminder for forty-five minutes to Call Mom", "set a reminder in 45 minutes to Call Mom"),
])
def test_shared_rephrasing_hooks(phrase, expected):
    assert rephrase_command(phrase) == expected


@pytest.mark.parametrize("phrase", [
    "type remind me in twenty five minutes to Call Mom!",
    "note: open result two", "please explain twenty five minutes",
    "don't schedule a DBMS class on monday from 9am to 10am",
    '"report completed step for task current: Tests passed!"',
])
def test_noncommand_and_literal_bodies_remain_unchanged(phrase):
    assert rephrase_command(phrase) == phrase


@pytest.mark.parametrize("family,phrase,canonical", CASES)
@pytest.mark.parametrize("prefix", ["", "Friday, could you please "])
def test_every_new_task_example_reaches_its_native_handler(monkeypatch, family, phrase, canonical, prefix):
    calls = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.projects, "load", lambda: {"friday": {"path": "C:/Friday"}})

    def execute(parsed, **kwargs):
        calls.append(("system", parsed))
        return ActionResult(True, "Done.")

    def workspace(parsed, **kwargs):
        calls.append(("workspace", parsed))
        return ActionResult(True, "Done.")

    async def forbidden(*args, **kwargs):
        pytest.fail("Equivalent native wording must not call an AI model")

    monkeypatch.setattr(intent, "_execute", execute)
    monkeypatch.setattr(workspace_commands, "run", workspace)
    monkeypatch.setattr(intent, "_run_ai_tools", forbidden)
    intent.cancel_pending_confirmation()
    result = asyncio.run(intent.try_system_action(canonical, "openrouter"))
    assert result and result.success and calls
    expected = calls.copy()
    calls.clear()
    result = asyncio.run(intent.try_system_action(prefix + phrase, "openrouter"))
    assert result and result.success
    assert calls == expected


@pytest.mark.parametrize("phrase", [
    "report progress for task current: Still investigating the bug",
    "record progress for task current: Tests are not passing yet",
    "watch https://example.com/battery for changes",
    "watch https://example.com/charged?battery=20 for changes",
])
def test_ambiguous_reports_and_watch_conditions_do_not_change_meaning(phrase):
    assert rephrase_command(phrase) == phrase


def test_task_cursor_advances_only_after_an_explicit_completion_report(monkeypatch):
    from services.mind.workspace import workspace

    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    task = workspace.start_task("Verify command language")
    workspace.plan(task, ["Run tests", "Review results"])
    workspace.focus("task", task)
    intent.cancel_pending_confirmation()

    for report in (
        "report progress for task current: Still investigating the bug",
        "record progress for task current: Tests are not passing yet",
    ):
        asyncio.run(intent.try_system_action(report, "openrouter"))
    assert workspace.tasks()[0]["cursor"] == 0
    result = asyncio.run(intent.try_system_action(
        "report completed step for task current: Tests passed!", "openrouter"))
    assert result.success
    saved = workspace.tasks()[0]
    assert saved["cursor"] == 1
    assert saved["evidence"][-1]["text"] == "Tests passed!"


@pytest.mark.parametrize("phrase,action", [
    ("play album Mute and Pause", "play_collection"),
    ("play Mute and Pause", "play_song"),
    ("queue Mute and Pause", "queue_song"),
])
def test_command_words_inside_music_titles_remain_one_request(monkeypatch, phrase, action):
    captured = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.media, "has_player", lambda: True)
    monkeypatch.setattr(intent, "_execute", lambda parsed, **kw:
                        captured.append(parsed) or ActionResult(True, "Playing."))
    result = asyncio.run(intent.try_system_action(phrase, "openrouter"))
    assert result and result.success
    assert len(captured) == 1
    assert captured[0]["action"] == action
    assert captured[0]["query"] == "mute and pause"


@pytest.mark.parametrize("prefix", ["", "mute then "])
def test_journal_search_keeps_its_native_feature_and_query(monkeypatch, prefix):
    captured = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent, "_execute", lambda parsed, **kw:
                        captured.append(parsed) or ActionResult(True, "Found."))
    result = asyncio.run(intent.try_system_action(prefix + "search my journal for Cats and Dogs", "openrouter"))
    assert result and result.success
    assert [step["action"] for step in captured] == (["set_mute", "search_journal"] if prefix else ["search_journal"])
    assert captured[-1]["query"] == "Cats and Dogs"
