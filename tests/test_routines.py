import asyncio
import json

import pytest

from services.automation import intent, routines
from services.automation.intent import ActionResult, try_system_action


@pytest.fixture
def ran(monkeypatch):
    """Records the actions routine steps would run; routine edits really run (on a temp file)."""
    actions = []
    real_run_action = intent._run_action

    def fake_run_action(parsed, confirmed=False):
        if parsed["action"] in routines.EDIT_ACTIONS:
            return real_run_action(parsed, confirmed)
        if parsed["action"] == "organise_folder":  # asks for a yes, like the real one
            intent._ask_first(parsed, "Organise it? Reply yes.")
            return ActionResult(True, "Organise it? Reply yes.")
        actions.append(parsed["action"])
        if parsed["action"] == "close_app":
            return ActionResult(False, "Chrome isn't open.")
        return ActionResult(True, f"Did {parsed['action']}.")

    async def no_ai(message, provider_name):
        return None

    intent.cancel_pending_confirmation()
    monkeypatch.setattr(intent.media, "has_player", lambda: False)
    monkeypatch.setattr(intent, "_run_action", fake_run_action)
    monkeypatch.setattr(intent, "_classify_with_ai", no_ai)
    return actions


def say(message):
    return asyncio.run(try_system_action(message, "openrouter"))


@pytest.mark.parametrize("message, name, steps", [
    ("create a routine called work mode to open chrome, take a screenshot and then mute",
     "work mode", ["open chrome", "take a screenshot", "mute"]),
    ("hey friday, create routine Study: open notepad; set volume to 30.",
     "study", ["open notepad", "set volume to 30"]),
    ("make a new routine named bedtime that mutes and sets brightness to 10",
     "bedtime", ["mute", "set brightness to 10"]),
])
def test_creating_a_routine(ran, message, name, steps):
    reply = say(message)
    assert reply.success and reply.message.startswith(f'Saved the "{name}" routine: 1. {steps[0]}')
    assert routines.load() == {name: steps}


def test_running_a_routine_runs_every_step_even_after_a_failure(ran):
    say("create routine work mode: open chrome, close chrome and take a screenshot")
    for phrase in ("start work mode", "run the work mode routine", "work mode"):
        ran.clear()
        reply = say(phrase)
        assert ran == ["open_app", "close_app", "take_screenshot"]
        assert not reply.success
        assert reply.message == "Work mode: Did open_app. Chrome isn't open. Did take_screenshot."


def test_unknown_steps_and_confirmation_steps_are_skipped(ran):
    routines._save({"tidy": ["what is the meaning of life", "organise downloads", "mute"]})
    reply = say("start tidy")
    assert ran == ["set_mute"]  # organise asked for a yes and was skipped, never run
    assert 'I couldn\'t do "what is the meaning of life"' in reply.message
    assert 'Skipped "organise downloads"' in reply.message
    assert not intent.is_awaiting_confirmation()


def test_routines_cannot_run_each_other(ran):
    routines._save({"a": ["b", "mute"], "b": ["a"]})
    reply = say("run a")
    assert ran == ["set_mute"]
    assert "can't start another routine" in reply.message


def test_hand_edits_count_straight_away(ran):
    routines.path.write_text(json.dumps({"Focus": ["mute"]}), encoding="utf-8")
    say("start focus")
    assert ran == ["set_mute"]


def test_a_broken_file_is_reported_not_overwritten(ran):
    routines.path.write_text("{oops", encoding="utf-8")
    assert not say("list my routines").success
    assert not say("create routine x: mute").success
    assert routines.path.read_text(encoding="utf-8") == "{oops"


def test_list_and_delete(ran):
    assert "don't have any routines" in say("list my routines").message
    say("create routine work mode: open chrome and mute")
    assert say("what routines do i have").message == "Your routines: work mode (2 steps)."
    assert say("delete the work mode routine").message == 'Deleted the "work mode" routine.'
    assert not say("delete routine work mode").success
    assert routines.load() == {}


def test_other_commands_are_untouched(ran):
    routines._save({"work mode": ["mute"]})
    say("start chrome")
    assert ran == ["open_app"]
    assert routines.match_routine_command("start my morning run") is None
    assert routines.match_routine_command("make my morning routine easier") is None
    assert not say("create a routine called gym").success  # no steps: asks for them


def test_a_routine_can_pause_between_steps(ran, monkeypatch):
    waited = []

    async def fake_sleep(seconds):
        waited.append(seconds)
    monkeypatch.setattr(intent.asyncio, "sleep", fake_sleep)
    routines._save({"study": ["mute", "wait 5 seconds", "pause 2 minutes", "wait a moment", "take a screenshot"]})
    reply = say("start study")
    assert ran == ["set_mute", "take_screenshot"] and waited == [5, 120, 3]
    assert reply.success and "wait" not in reply.message.lower()
    assert routines.pause_seconds("wait 3 hours") is None and routines.pause_seconds("wait 99 minutes") == 600
