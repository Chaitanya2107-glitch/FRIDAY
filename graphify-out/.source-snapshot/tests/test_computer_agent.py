import asyncio
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from services.computer import agent, desktop
from services.computer.actions import parse_action
from core.errors import ProviderError


def frame(color="white", hwnd=17, bounds=(-1920, 0, 0, 1080), focus=19):
    return desktop.Frame(Image.new("RGB", (960, 540), color), bounds, hwnd, focus)


@pytest.fixture
def computer(monkeypatch):
    instance = agent.ComputerAgent()
    calls, executions = [], []
    images = [frame()]
    replies = [{"action": "click", "x": 100, "y": 200, "reason": "Open the menu"},
               {"action": "done", "reason": "The menu is now open"}]

    async def complete(provider, messages, system_prompt, max_tokens, **kwargs):
        calls.append((messages, system_prompt, kwargs))
        return SimpleNamespace(content=json.dumps(replies.pop(0)), provider=provider,
                               model="vision", tokens_used=20)

    monkeypatch.setattr(agent, "complete_with_failover", complete)
    monkeypatch.setattr(desktop, "capture", lambda bounds=None: images[0])
    monkeypatch.setattr(desktop, "execute", lambda action, captured: executions.append(action))
    return SimpleNamespace(agent=instance, calls=calls, executions=executions, images=images, replies=replies)


def run(computer, command):
    return asyncio.run(computer.agent.handle(command, "openrouter"))


def test_action_is_proposed_then_approved_and_verified(computer):
    result = run(computer, "\\c open the menu")
    assert result.awaiting_reply and "100" in result.message
    assert computer.executions == []
    assert computer.calls[0][0][-1].images
    result = run(computer, "\\c yes")
    assert result.success and not result.awaiting_reply
    assert len(computer.executions) == 1
    assert len(computer.calls) == 2  # completion came from a fresh screen
    assert computer.agent.session is None


@pytest.mark.parametrize("command", ["\\c no", "\\c stop"])
def test_cancel_never_executes(computer, command):
    run(computer, "\\c open the menu")
    assert not run(computer, command).awaiting_reply
    assert not computer.executions
    assert computer.agent.session is None


def test_yes_without_proposal_cannot_act(computer):
    result = run(computer, "\\c yes")
    assert not result.success
    assert not computer.calls and not computer.executions


def test_changed_window_requires_new_approval(computer):
    run(computer, "\\c open the menu")
    computer.images[0] = frame(hwnd=18)
    computer.replies[:] = [{"action": "keys", "keys": "esc", "reason": "Close the new menu"}]
    result = run(computer, "\\c yes")
    assert result.awaiting_reply
    assert not computer.executions
    assert "changed" in result.message.lower()


def test_changed_screen_requires_new_approval(computer):
    run(computer, "\\c open the menu")
    computer.images[0] = frame("black")
    computer.replies[:] = [{"action": "blocked", "reason": "Cannot see the menu"}]
    assert not run(computer, "\\c yes").success
    assert not computer.executions


def test_expired_approval_cannot_act(computer):
    run(computer, "\\c open the menu")
    computer.agent.session.expires = agent.time.monotonic() - 1
    assert not run(computer, "\\c yes").success
    assert not computer.executions


@pytest.mark.parametrize("payload", [
    {"action": "shell", "command": "calc"},
    {"action": "click", "x": -1, "y": 5, "reason": "Click"},
    {"action": "click", "x": True, "y": 5, "reason": "Click"},
    {"action": "click", "x": 960, "y": 5, "reason": "Click"},
    {"action": "keys", "keys": "unknown", "reason": "Press"},
    {"action": "scroll", "x": 5, "y": 5, "amount": 50, "reason": "Scroll"},
    {"action": "type", "text": "", "reason": "Type"},
    {"action": "type", "text": "x" * 1001, "reason": "Type"},
    {"action": "done", "reason": "Done", "command": "calc"},
])
def test_bad_model_output_is_rejected(payload):
    with pytest.raises(ValueError):
        parse_action(json.dumps(payload), (960, 540))


def test_coordinates_account_for_scaling_and_negative_monitor_origin():
    assert frame().point(100, 200) == (-1720, 400)
    assert frame().point(959, 539) == (-2, 1078)


def test_malformed_output_clears_session_and_does_not_execute(computer):
    computer.replies[:] = [{"action": "shell", "command": "calc"}]
    result = run(computer, "\\c open calculator")
    assert not result.success and computer.agent.session is None
    assert not computer.executions


def test_stop_during_planning_cannot_resurrect_session(computer, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def complete(*args, **kwargs):
            entered.set()
            await release.wait()
            return SimpleNamespace(content=json.dumps({"action": "click", "x": 1, "y": 1,
                                                        "reason": "Click"}), provider="openrouter", tokens_used=20)

        monkeypatch.setattr(agent, "complete_with_failover", complete)
        task = asyncio.create_task(computer.agent.handle("\\c open the menu", "openrouter"))
        await entered.wait()
        busy = await computer.agent.handle("\\c another task", "openrouter")
        assert not busy.success
        await computer.agent.handle("\\c stop", "openrouter")
        release.set()
        await task
        assert computer.agent.session is None
        assert not computer.executions

    asyncio.run(scenario())


def test_step_limit_still_checks_the_final_screen(computer, monkeypatch):
    monkeypatch.setattr(agent, "MAX_STEPS", 1)
    computer.replies[:] = [{"action": "click", "x": 1, "y": 1, "reason": "Click"}] * 2
    run(computer, "\\c open the menu")
    result = run(computer, "\\c yes")
    assert not result.success and "1 steps" in result.message
    assert len(computer.executions) == 1 and len(computer.calls) == 2
    assert computer.agent.session is None


def test_private_task_and_text_are_not_logged(computer, caplog):
    computer.replies[:] = [{"action": "type", "text": "SENTINEL_PRIVATE_TEXT", "reason": "Enter the text"}]
    result = run(computer, "\\c SENTINEL_PRIVATE_TASK")
    assert result.awaiting_reply
    assert "SENTINEL_PRIVATE_TASK" not in caplog.text
    assert "SENTINEL_PRIVATE_TEXT" not in caplog.text


def test_failed_input_is_not_replayed(computer, monkeypatch):
    run(computer, "\\c open the menu")

    def fail(*args):
        raise RuntimeError("SENTINEL_PRIVATE_EXCEPTION")

    monkeypatch.setattr(desktop, "execute", fail)
    result = run(computer, "\\c yes")
    assert not result.success and "SENTINEL_PRIVATE_EXCEPTION" not in result.message
    assert computer.agent.session is None
    assert not run(computer, "\\c yes").success


def test_invalid_json_cannot_act(computer, monkeypatch):
    async def invalid(*args, **kwargs):
        return SimpleNamespace(content="This is not JSON")

    monkeypatch.setattr(agent, "complete_with_failover", invalid)
    assert not run(computer, "\\c open the menu").success
    assert not computer.executions and computer.agent.session is None


def test_timeout_stops_without_input(computer, monkeypatch):
    async def timeout(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(agent, "complete_with_failover", timeout)
    assert "too long" in run(computer, "\\c open the menu").message
    assert not computer.executions and computer.agent.session is None


def test_mouse_events_use_virtual_desktop_coordinates():
    action = parse_action('{"action":"click","x":0,"y":0,"reason":"Click"}', (960, 540))
    events = desktop._mouse_events(action, frame(), (-1920, 0, 3840, 1080))
    assert events[0].u.mi.dx == 8
    assert events[0].u.mi.dwFlags == 0xC001
    assert [e.u.mi.dwFlags for e in events[1:]] == [2, 4]


def test_scroll_moves_pointer_then_sends_signed_wheel_notches():
    action = parse_action('{"action":"scroll","x":1,"y":1,"amount":-2,"reason":"Scroll"}', (960, 540))
    events = desktop._mouse_events(action, frame(), (-1920, 0, 3840, 1080))
    assert events[1].u.mi.dwFlags == 0x0800
    assert events[1].u.mi.mouseData == (-240) & 0xFFFFFFFF


def test_small_change_at_click_target_is_stale_even_if_global_mean_is_small():
    original, changed = frame(), frame()
    changed.image.paste("black", (80, 180, 121, 221))
    action = parse_action('{"action":"click","x":100,"y":200,"reason":"Click"}', (960, 540))
    assert not original.same_view(changed, action)


@pytest.mark.parametrize("text, expected", [("\\c open notepad", True), (" \\C yes ", True),
                                           ("\\cat", False), ("hello", False), ("", False)])
def test_only_explicit_computer_commands_are_routed(text, expected):
    assert agent.is_computer_command(text) is expected


def test_typing_target_change_requires_new_approval(computer):
    computer.replies[:] = [{"action": "type", "text": "Hello", "reason": "Fill the name"},
                          {"action": "blocked", "reason": "The focused field changed"}]
    run(computer, "\\c fill the name")
    computer.images[0] = frame(focus=20)
    assert not run(computer, "\\c yes").success
    assert not computer.executions


def test_direct_service_calls_cannot_bypass_explicit_command(computer):
    run(computer, "\\c open the menu")
    assert not run(computer, "something yes").success
    assert not computer.executions


@pytest.mark.parametrize("after_approval, error", [
    (False, ProviderError("SENTINEL_PRIVATE_PROVIDER_ERROR")),
    (True, ProviderError("SENTINEL_PRIVATE_PROVIDER_ERROR")),
    (True, TimeoutError()),
])
def test_vision_failure_reports_whether_approved_input_ran(computer, monkeypatch, after_approval, error):
    if after_approval:
        run(computer, "\\c open the menu")

    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(agent, "complete_with_failover", fail)
    result = run(computer, "\\c yes" if after_approval else "\\c open the menu")
    assert not result.success
    assert ("approved step ran" if after_approval else "No desktop input ran") in result.message
    assert "SENTINEL_PRIVATE_PROVIDER_ERROR" not in result.message
    assert len(computer.executions) == int(after_approval)
    assert computer.agent.session is None
    assert not run(computer, "\\c yes").success


def test_focus_change_reports_input_failure_instead_of_vision_settings(computer, monkeypatch):
    run(computer, "\\c open the menu")

    def fail(*args):
        raise desktop.DesktopError("SENTINEL_PRIVATE_EXCEPTION")

    monkeypatch.setattr(desktop, "execute", fail)
    result = run(computer, "\\c yes")
    assert not result.success and "Windows input" in result.message
    assert "VISION_MODEL" not in result.message
    assert "SENTINEL_PRIVATE_EXCEPTION" not in result.message
