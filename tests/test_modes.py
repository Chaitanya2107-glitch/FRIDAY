import asyncio

import pytest

from services.automation import intent, modes


@pytest.fixture
def pc(monkeypatch):
    """Fake volume, apps and step runner; records what happened."""
    state = {"volume": 60, "closed": [], "ran": []}
    monkeypatch.setattr(intent.system, "volume_level", lambda: state["volume"])
    monkeypatch.setattr(intent.system, "set_volume", lambda v: state.update(volume=v) or f"Volume set to {v}%.")
    monkeypatch.setattr(intent.system, "close_app", lambda app: state["closed"].append(app) or f"Closing {app}.")

    async def run_steps(steps, provider):
        state["ran"].extend(steps)
        return [intent.ActionResult(True, f"Did {s}.") for s in steps]
    monkeypatch.setattr(intent, "_run_steps", run_steps)
    return state


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


def test_start_and_end_study_mode(pc):
    say("when I start study mode, open vs code, play lofi and set volume to 20")
    reply = say("start study mode")
    assert reply.message.startswith("Study mode on — nudges will wait and I'll stay quiet until you end it.")
    assert pc["ran"] == ["open vs code", "play lofi", "set volume to 20"]
    assert modes.is_quiet_mode() and say("what mode am i in").message == "You're in study mode."

    reply = say("end study mode")
    assert reply.message == "Study mode off: closed vs code, volume back to 60%."
    assert pc["closed"] == ["vs code"] and pc["volume"] == 60
    assert not modes.is_quiet_mode() and say("what mode am i in").message == "Normal mode is active."


def test_switching_modes_ends_the_first(pc):
    say("start study mode")
    reply = say("switch to chill mode")
    assert reply.message.startswith("Chill mode on.") and "Study mode off" in reply.message
    assert modes.active()["name"] == "chill" and not modes.is_quiet_mode()  # chill isn't quiet


def test_quiet_mode_holds_nudges(pc):
    from services.proactive import watcher
    say("start gaming mode")
    assert modes.is_quiet_mode()
    say("make gaming mode not quiet")
    assert modes.load()["gaming"]["quiet"] is False


def test_unknown_modes_are_not_commands(pc):
    assert modes.match_mode_command("start party mode") is None   # not a mode: left to the AI
    assert modes.match_mode_command("start chrome") is None
    assert say("end mode").message == "Normal mode is active; no mode is on."


def test_list_and_delete(pc):
    assert say("list my modes").message.startswith("Your modes: study (quiet): set volume to 30; work (quiet)")
    assert say("delete chill mode").message == "Deleted chill mode."
    assert "chill" not in modes.load()


@pytest.mark.parametrize("text, action", [
    ("start study mode", "start_mode"), ("switch to work mode", "start_mode"), ("study mode on", "start_mode"),
    ("end study mode", "end_mode"), ("study mode off", "end_mode"), ("back to normal", "end_mode"),
    ("stop mode", "end_mode"), ("which mode am i in", "mode_status"),
])
def test_commands(text, action):
    assert modes.match_mode_command(text)["action"] == action


def test_repeating_mode_on_does_not_turn_it_off_or_rerun_steps(pc):
    say('when I start gaming mode, open notepad')
    say('turn on gaming mode')
    reply = say('turn on gaming mode')
    assert reply.success and reply.message.startswith('Gaming mode is already on.')
    assert 'off' not in reply.message.lower()
    assert pc['ran'] == ['open notepad'] and pc['closed'] == []


def test_mode_switch_leads_with_final_active_mode(pc):
    say('start work mode')
    reply = say('turn on gaming mode')
    assert reply.success and reply.message.startswith('Gaming mode on')
    assert modes.active()['name'] == 'gaming'


def test_setup_failure_does_not_hide_that_mode_is_on(pc, monkeypatch):
    async def failed(*args):
        return [intent.ActionResult(False, 'Could not open Spotify.')]
    monkeypatch.setattr(intent, '_run_steps', failed)
    reply = say('start gaming mode')
    assert not reply.success and modes.active()['name'] == 'gaming'
    assert reply.message.startswith('Gaming mode on') and 'setup' in reply.message.lower()


@pytest.mark.parametrize('text', ['is gaming mode on', 'gaming mode status', 'is gaming mode off'])
def test_named_mode_status_never_turns_it_on(pc, text):
    reply = say(text)
    assert reply.success and reply.message.startswith('Gaming mode is off.')
    assert modes.active() is None and pc['ran'] == []
    say('start gaming mode')
    assert say(text).message == 'Gaming mode is on.'


