"""Known command typos reuse native routing, payload rules and safety guards."""
import asyncio
from types import SimpleNamespace

import pytest

from core.config import config
from services.automation import app_finder, intent, power
from services.automation.results import ActionResult
from services.mind import workspace_commands


@pytest.fixture
def local(monkeypatch):
    actions, workspace_calls = [], []
    real_execute = intent._execute
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.media, "has_player", lambda: False)
    monkeypatch.setattr(intent.system, "list_apps", lambda: ["chrome", "spotify", "notepad"])
    monkeypatch.setattr(app_finder, "find_app", lambda target: None)

    def execute(parsed, confirmed=False):
        actions.append(parsed)
        return ActionResult(True, parsed["action"])

    def workspace_run(parsed, *, remote=False):
        workspace_calls.append((parsed, remote))
        return ActionResult(True, "Workspace result")

    async def no_ai(*args, **kwargs):
        pytest.fail("Typo routing called an AI provider")

    monkeypatch.setattr(intent, "_execute", execute)
    monkeypatch.setattr(workspace_commands, "run", workspace_run)
    monkeypatch.setattr(intent, "_classify_with_ai", no_ai)
    monkeypatch.setattr(intent, "_run_ai_tools", no_ai)
    monkeypatch.setattr("providers.failover.complete_with_failover", no_ai)
    intent.cancel_pending_confirmation()
    yield SimpleNamespace(actions=actions, workspace=workspace_calls, real_execute=real_execute)
    intent.cancel_pending_confirmation()


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


@pytest.mark.parametrize("text,expected", [
    ("opne chrome", {"type": "system", "action": "open_app", "app_name": "chrome"}),
    ("Friday, can you opne chrome", {"type": "system", "action": "open_app", "app_name": "chrome"}),
    ("serach cats and dogs", {"type": "system", "action": "search_chrome", "query": "cats and dogs"}),
    ("remnid me in twenty minutes to Call Mom!", {"type": "system", "action": "set_reminder", "message": "remind me in 20 minutes to Call Mom!"}),
])
def test_known_typo_routes_to_native_action(local, text, expected):
    result = say(text)
    assert result and result.success
    assert local.actions == [expected]


def test_typo_namespace_command_uses_its_own_runner(local):
    assert say("shwo my goals").success
    assert local.actions == []
    assert local.workspace == [({"action": "goals"}, False)]


def test_batch_corrects_each_command_word_before_execution(local):
    assert say("opne chrome and voluem 20").success
    assert local.actions == [
        {"type": "system", "action": "open_app", "app_name": "chrome"},
        {"type": "system", "action": "set_volume", "level": 20},
    ]


@pytest.mark.parametrize("text", [
    "opne chorme", "open chorme", "lunch chrome", "shop my files",
    "don't opne chrome", "do not opne chrome", "never opne chrome",
    '"opne chrome"', "'opne chrome'", "shutdwon in twenty minutes", "restatr my laptop",
])
def test_targets_real_words_negations_quotes_and_power_typos_are_not_corrected(local, text):
    assert say(text) is None
    assert not local.actions and not local.workspace
    assert not intent.is_awaiting_confirmation()


def test_typo_in_dictation_is_literal(local):
    assert say("type opne Chrome and voluem 20").success
    assert local.actions == [{"type": "system", "action": "type_text", "text": "opne Chrome and voluem 20"}]


def test_corrected_clipboard_command_keeps_remote_refusal(local, monkeypatch):
    monkeypatch.setattr(intent, "_execute", local.real_execute)

    def must_not_read():
        pytest.fail("Remote typo command read clipboard history")

    monkeypatch.setattr(intent.clipboard_history, "list_message", must_not_read)
    token = intent.remote_request.set(True)
    try:
        result = say("shwo clipboard history")
    finally:
        intent.remote_request.reset(token)
    assert result and not result.success and result.message == intent.REMOTE_REFUSAL


def test_corrected_workspace_command_keeps_remote_scope(local):
    token = intent.remote_request.set(True)
    try:
        assert say("shwo my goals").success
    finally:
        intent.remote_request.reset(token)
    assert local.workspace == [({"action": "goals"}, True)]


def test_remote_typo_batch_is_rejected_before_any_step_executes(local):
    token = intent.remote_request.set(True)
    try:
        result = say("opne chrome and shwo clipboard history")
    finally:
        intent.remote_request.reset(token)
    assert result and not result.success and result.message == intent.REMOTE_REFUSAL
    assert not local.actions


def test_native_power_still_requires_confirmation(local, monkeypatch):
    monkeypatch.setattr(intent, "_execute", local.real_execute)

    def must_not_schedule(*args, **kwargs):
        pytest.fail("Power command executed before confirmation")

    monkeypatch.setattr(power, "_later", must_not_schedule)
    result = say("shutdown in twenty minutes")
    assert result and result.success and "yes or no" in result.message
    assert intent.is_awaiting_confirmation()
