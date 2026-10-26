"""Real laptop/Telegram entrypoints keep temporary action context separate."""

import asyncio
from types import SimpleNamespace

import pytest

from core.config import config
from interfaces.api.routes import chat, voice
from services.automation import intent
from services.computer.agent import Session
from services.files import assistant
from services.files.search import FileHit
from services.telegram import bot, client


@pytest.fixture
def channels(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", False)
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", False)
    monkeypatch.setattr(config, "FILE_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    monkeypatch.setattr(bot, "_pending", None)
    memory = SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *args: None)
    monkeypatch.setattr(chat, "_memory", memory)
    monkeypatch.setattr(voice, "_memory", memory)
    sent, uploaded, opened = [], [], []
    monkeypatch.setattr(client, "send", lambda recipient, text, links=None: sent.append(text))
    monkeypatch.setattr(client, "send_file", lambda recipient, path: uploaded.append(path))
    monkeypatch.setattr(assistant.os, "startfile", opened.append)
    hits = {}
    for scope in ("laptop", "phone"):
        hits[scope] = []
        for number in (1, 2):
            path = tmp_path / f"{scope}-{number}.txt"
            path.write_text(f"Synthetic {scope} file {number}", encoding="utf-8")
            hits[scope].append(FileHit(str(path), path.name))
    monkeypatch.setattr(assistant, "find_files", lambda query: hits[query])
    return SimpleNamespace(sent=sent, uploaded=uploaded, opened=opened, hits=hits)


def laptop(message, interface="chat"):
    if interface == "voice":
        return asyncio.run(voice._reply(message, voice.VoiceRequest(speak=False)))
    return asyncio.run(chat.chat(chat.ChatRequest(message=message)))


def telegram(message):
    asyncio.run(bot._run(42, message))
    assert intent.remote_request.get() is False


@pytest.mark.parametrize("assist_only", [True, False])
def test_telegram_turn_preserves_laptop_computer_proposal(channels, monkeypatch, assist_only):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    session = Session("Synthetic pending desktop task", "openrouter")
    monkeypatch.setattr(chat.computer_agent, "session", session)

    telegram("what time is it")

    assert chat.computer_agent.session is session
    assert channels.sent


def test_laptop_turn_still_cancels_its_computer_proposal(channels, monkeypatch):
    monkeypatch.setattr(chat.computer_agent, "session", Session("Old local task", "openrouter"))

    laptop("what time is it")

    assert chat.computer_agent.session is None


@pytest.mark.parametrize("assist_only", [True, False])
@pytest.mark.parametrize("interface", ["chat", "voice"])
def test_interleaved_search_open_and_send_use_their_own_files(channels, monkeypatch, assist_only, interface):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    assert laptop("find my laptop").action_success
    telegram("find my phone")

    # The laptop's spoken and typed commands share a selection, even while the
    # real bot-to-chat path uses another result list in the threadpool.
    assert laptop("open 2", interface).action_success
    telegram("open 1")
    assert channels.opened == [channels.hits["laptop"][1].path, channels.hits["phone"][0].path]

    assert laptop("send me that file through telegram", interface).action_success
    telegram("send me that file through telegram")
    assert [str(path) for path in channels.uploaded] == channels.opened
    assert assistant.last_results.selected == channels.hits["laptop"][1]


@pytest.mark.parametrize("shortcut", ["copy synthetic text", "https://example.com", "/send phone-1.txt"])
def test_bot_shortcuts_drop_only_their_own_older_confirmation(channels, monkeypatch, shortcut):
    from services.telegram import commands

    executed = []
    monkeypatch.setattr(intent, "_execute", lambda parsed, confirmed=False: executed.append(parsed))
    monkeypatch.setattr(bot.system, "open_url", lambda url: "Opened")
    monkeypatch.setattr(bot.system, "write_clipboard", lambda text: "Copied")
    monkeypatch.setattr(bot, "_find_file", lambda query: channels.hits["phone"][0])
    intent._ask_first({"action": "shutdown"}, "Local question")
    token = intent.remote_request.set(True)
    try:
        intent._ask_first({"action": "restart"}, "Remote question")
        commands._pending_files[True] = float("inf")
        commands._pending_files[False] = float("inf")
    finally:
        intent.remote_request.reset(token)

    telegram(shortcut)

    token = intent.remote_request.set(True)
    try:
        assert not intent.is_awaiting_confirmation()
        assert True not in commands._pending_files
    finally:
        intent.remote_request.reset(token)
    assert intent.is_awaiting_confirmation()
    assert False in commands._pending_files
    telegram("yes")  # upload confirmation, if present, belongs to the bot only
    telegram("yes")  # an extra yes must never revive the old restart
    assert not executed
    assert intent.is_awaiting_confirmation()


@pytest.mark.parametrize("reply", ["yes", "no"])
def test_bot_owned_confirmation_cannot_leave_an_older_remote_action(channels, monkeypatch, reply):
    intent._ask_first({"action": "shutdown"}, "Local question")
    token = intent.remote_request.set(True)
    try:
        intent._ask_first({"action": "restart"}, "Old remote question")
    finally:
        intent.remote_request.reset(token)
    bot._ask("Synthetic upload?", lambda: "Uploaded")

    telegram(reply)

    token = intent.remote_request.set(True)
    try:
        assert not intent.is_awaiting_confirmation()
    finally:
        intent.remote_request.reset(token)
    assert intent.is_awaiting_confirmation()


def test_laptop_voice_can_confirm_typed_action_while_telegram_waits(channels, monkeypatch):
    executed = []
    monkeypatch.setattr(intent.power, "run", lambda parsed: executed.append(parsed["action"]) or "Done.")
    assert laptop("shut down the laptop").awaiting_reply
    telegram("restart the laptop")

    result = laptop("yes", "voice")

    assert result.action_success and not result.awaiting_reply
    assert executed == ["shutdown_pc"]
    telegram("yes")
    assert executed == ["shutdown_pc", "restart_pc"]


@pytest.mark.parametrize("failure", ["shortcut", "chat"])
def test_telegram_context_is_restored_after_failure(channels, monkeypatch, failure):
    from core.errors import FridayError

    intent._ask_first({"action": "shutdown_pc"}, "Local question")
    if failure == "shortcut":
        def fail(text):
            assert intent.remote_request.get() is True
            raise FridayError("Synthetic clipboard failure")

        monkeypatch.setattr(bot.system, "write_clipboard", fail)
        telegram("copy synthetic text")
        assert "Synthetic clipboard failure" in channels.sent[-1]
    else:
        async def fail(request):
            assert intent.remote_request.get() is True
            raise RuntimeError("Synthetic route failure")

        monkeypatch.setattr(chat, "chat", fail)
        with pytest.raises(RuntimeError, match="Synthetic route failure"):
            telegram("what time is it")
    assert intent.remote_request.get() is False
    assert intent.is_awaiting_confirmation()

