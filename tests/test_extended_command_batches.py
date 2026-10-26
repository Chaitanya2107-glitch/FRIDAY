"""Mixed local batches validate before execution and keep literal tails intact."""
import asyncio
import re

import pytest

from core.config import config
from services.automation import intent
from services.automation.results import ActionResult
from services.mind import workspace_commands


@pytest.fixture
def actions(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.media, "has_player", lambda: True)
    monkeypatch.setattr(intent, "_execute", lambda parsed, confirmed=False: calls.append(parsed) or ActionResult(True, "done"))
    monkeypatch.setattr(workspace_commands, "run", lambda parsed, **kwargs: calls.append(parsed) or ActionResult(True, "saved"))
    async def no_ai(*args, **kwargs):
        pytest.fail("A local batch called the model")
    monkeypatch.setattr(intent, "_run_ai_tools", no_ai)
    intent.cancel_pending_confirmation()
    yield calls
    intent.cancel_pending_confirmation()


def run(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


@pytest.mark.parametrize("text,expected", [
    ("list my notes and mute", ["list_notes", "set_mute"]),
    ("show my app limits then battery health", ["list_limits", "battery_health"]),
    ("what are you watching and show my notes", ["list_watches", "list_notes"]),
    ("show my subjects then my marks", ["list_subjects", "show_marks"]),
    ("limit Chrome to 20 minutes a day then open chrome", ["set_limit", "open_app"]),
    ("my attendance then show my notes", ["show_attendance", "list_notes"]),
    ("show my goals and mute", ["goals", "set_mute"]),
    ("mute then show my tasks", ["set_mute", "tasks"]),
    ("put goal Friday on hold and mute", ["goal_state", "set_mute"]),
])
def test_mixed_features_execute_in_order(actions, text, expected):
    result = run(text)
    assert result and result.success
    assert [parsed["action"] for parsed in actions] == expected


@pytest.mark.parametrize("assist_only", [True, False])
@pytest.mark.parametrize("text", [
    "list my notes and fly to the moon",
    "show my goals then do something mysterious",
    "my attendance then open chrome then gibberish",
    "gibberish then mute",
    "mute then start study mode",
])
def test_any_unknown_or_unsupported_step_runs_nothing(actions, monkeypatch, text, assist_only):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    result = run(text)
    assert result and not result.success
    assert actions == []


@pytest.mark.parametrize("prefix", ["", "mute then "])
@pytest.mark.parametrize("command,action,field,body", [
    ("note Buy A and B!", "add_note", "text", "Buy A and B!"),
    ("remind me in 5 minutes to Call Mom and Save Report.pdf!", "set_reminder", "message", "remind me in 5 minutes to Call Mom and Save Report.pdf!"),
    ("type A and B!", "type_text", "text", "A and B!"),
    ("search Cats and Dogs!", "search_chrome", "query", "Cats and Dogs!"),
    ("copy A and B! to clipboard", "write_clipboard", "text", "A and B!"),
    ("add goal: Build API and Test Friday!", "add_goal", "title", "Build API and Test Friday!"),
    ("plan task current: Read Docs; Build and Test!", "plan", "steps", "Read Docs; Build and Test!"),
    ("report completed step for task current: Passed A and B!", "step", "evidence", "Passed A and B!"),
])
def test_literal_bodies_own_the_rest_of_the_sentence(actions, prefix, command, action, field, body):
    assert run(prefix + command).success
    assert len(actions) == (2 if prefix else 1)
    assert actions[-1]["action"] == action
    assert actions[-1][field] == body


@pytest.mark.parametrize("text", ["read clipboard then mute", "mute then read clipboard", "read this then mute"])
def test_remote_batch_keeps_clipboard_and_read_aloud_restrictions(actions, text):
    token = intent.remote_request.set(True)
    try:
        result = run(text)
    finally:
        intent.remote_request.reset(token)
    assert result and not result.success
    assert actions == []


def test_login_or_mode_or_routine_or_project_orchestration_is_not_dispatched_as_plain_action(actions, monkeypatch):
    monkeypatch.setattr(intent.logins, "load", lambda: {"github": {"url": "https://github.com/login"}})
    assert not run("mute then log in to github").success
    assert actions == []


def test_confirmation_pauses_every_following_feature(actions, monkeypatch):
    def execute(parsed, confirmed=False):
        actions.append(parsed)
        if parsed["action"] == "shutdown_pc" and not confirmed:
            return intent._ask_first(parsed, "Shut down?")
        return ActionResult(True, "done")
    monkeypatch.setattr(intent, "_execute", execute)
    result = run("list my notes then shut down then mute")
    assert [p["action"] for p in actions] == ["list_notes", "shutdown_pc"]
    assert intent.is_awaiting_confirmation()
    assert "remaining" in result.message.lower()
    run("yes")
    assert [p["action"] for p in actions] == ["list_notes", "shutdown_pc", "shutdown_pc"]


def test_watch_text_reaches_router_without_losing_literal_punctuation(actions):
    result = run('watch Server.log for text: "READY?" and Version 2!')
    assert result.success
    assert len(actions) == 1
    assert actions[0]["action"] == "watch_log"
    assert actions[0]["pattern"] == re.escape('"READY?" and Version 2!')


def test_spotify_collection_name_reaches_router_without_losing_friday(actions):
    result = run("play album Friday")
    assert result.success
    assert actions[0]["action"] == "play_collection"
    assert actions[0]["query"].casefold() == "friday"


@pytest.mark.parametrize("text,expected", [
    ("play album On and On then mute", ["play_collection", "set_mute"]),
    ("mute then play album On and On then battery health", ["set_mute", "play_collection", "battery_health"]),
    ('play album "Then and Now"; mute', ["play_collection", "set_mute"]),
])
def test_explicit_music_separators_keep_title_conjunctions(actions, text, expected):
    assert run(text).success
    assert [p["action"] for p in actions] == expected


@pytest.mark.parametrize("prefix", ["", "mute then "])
def test_mode_step_definition_saves_conjunctions_instead_of_running_them(actions, prefix):
    assert run(prefix + "change actions in Focus mode to open chrome and mute").success
    assert len(actions) == (2 if prefix else 1)
    assert actions[-1]["action"] == "set_mode_steps"
    assert actions[-1]["steps"] == ["open chrome", "mute"]


def test_whatsapp_literal_body_does_not_turn_into_batch(actions):
    result = run("message Mom on whatsapp: Keep CAPS and mute!")
    assert result.success
    assert len(actions) == 1
    assert actions[0]["action"] == "send_whatsapp"
    assert actions[0]["text"] == "Keep CAPS and mute!"


def test_telegram_message_keeps_native_route_and_literal_body(actions, monkeypatch):
    calls = []
    async def capture(message):
        parsed = intent.telegram_commands.match_command(message)
        if parsed:
            calls.append(parsed)
            return ActionResult(True, "sent")
    monkeypatch.setattr(intent.telegram_commands, "try_handle", capture)
    assert run("send text saying Hello and mute! through telegram").success
    assert actions == []
    assert calls == [{"action": "telegram_message", "text": "Hello and mute!"}]


def test_deadline_and_device_batch(actions):
    assert run("add deadline DBMS assignment due tomorrow then mute").success
    assert [p["action"] for p in actions] == ["add_deadline", "set_mute"]


@pytest.mark.parametrize("prefix", ["", "mute then "])
def test_routine_definition_saves_steps_instead_of_executing_them(actions, prefix):
    assert run(prefix + "create a routine called Desk: open chrome and mute").success
    assert len(actions) == (2 if prefix else 1)
    assert actions[-1]["action"] == "create_routine"
    assert actions[-1]["steps"] == ["open chrome", "mute"]


@pytest.mark.parametrize("text", [
    "play album On and On then do something mysterious",
    "mute then play album On and On then gibberish",
])
def test_unknown_explicit_music_followup_prevents_all_actions(actions, text):
    assert not run(text).success
    assert actions == []
