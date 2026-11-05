import asyncio

import pytest

from core.config import config
from core.errors import MemoryError
from interfaces.api.routes import chat, voice
from providers.base_provider import ProviderResponse
from services.automation import intent
from services.memory.sqlite_memory import MemoryService
from services.telegram import client, commands


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_DB_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    memory = MemoryService()
    monkeypatch.setattr(chat, "_memory", memory)
    monkeypatch.setattr(voice, "_memory", memory)
    sent = []
    monkeypatch.setattr(client, "send", lambda recipient, text: sent.append((recipient, text)))
    return memory, sent


@pytest.mark.parametrize("phrase", [
    "send me the answer in telegram", "send your last answer through telegram bot",
    "please share that reply on telgram", "send me this response via Telegram",
])
def test_answer_phrases_are_explicit_commands(phrase):
    assert commands.match_command(phrase) == {"action": "telegram_answer"}


@pytest.mark.parametrize("source,target", [("chat", "chat"), ("voice", "voice"), ("voice", "chat"), ("chat", "voice")])
def test_generated_answer_is_forwarded_verbatim_and_repeatable(delivery, monkeypatch, source, target):
    memory, sent = delivery
    answer = "  **Answer**\nUnicode: नमस्ते 🌙\n[Source](https://example.com/?a=1&b=2)\n```python\nx = 1\n```\n" + "Detail.\n" * 900
    calls = []

    async def no_context(*a, **kw):
        return None

    async def complete(provider, *a, **kw):
        calls.append(provider)
        return ProviderResponse(content=answer, provider=provider, model="test")

    for route in (chat, voice):
        monkeypatch.setattr(route, "build_file_context", no_context)
        monkeypatch.setattr(route, "build_search_context", no_context)
        monkeypatch.setattr(route, "complete_with_failover", complete)
    # A normal question creates the saved answer through the real interface.
    if source == "chat":
        asyncio.run(chat.chat(chat.ChatRequest(message="Explain a rainbow")))
    else:
        asyncio.run(voice._reply("Explain a rainbow", voice.VoiceRequest(speak=False)))

    async def forbidden(*a, **kw):
        pytest.fail("Forwarding the saved answer invoked search or regenerated it")

    for route in (chat, voice):
        for name in ("build_file_context", "build_search_context", "complete_with_failover"):
            monkeypatch.setattr(route, name, forbidden)
    for _ in range(2):
        sent.clear()
        if target == "chat":
            result = asyncio.run(chat.chat(chat.ChatRequest(message="send me the answer in telegram")))
        else:
            result = asyncio.run(voice._reply("send me the answer in telegram", voice.VoiceRequest(speak=False)))
        assert result.action_success is True
        assert "".join(text for _, text in sent) == answer
        assert all(recipient == 42 and len(text) <= client.TEXT_LIMIT for recipient, text in sent)
        assert memory.get_recent_history()[-1]["content"] == answer
    assert len(calls) == 1


def test_no_saved_answer_does_not_send(delivery):
    memory, sent = delivery
    memory.save_message("user", "A question without an answer")
    result = asyncio.run(intent.try_system_action("send me the answer in telegram", "openrouter"))
    assert result is not None and not result.success and "answer" in result.message.lower()
    assert not sent


def test_latest_answer_is_used_even_after_many_user_messages(delivery):
    memory, sent = delivery
    memory.save_message("assistant", "Older answer")
    memory.save_message("assistant", "Newest answer\nhttps://example.com/source")
    for _ in range(config.MAX_HISTORY_MESSAGES + 1):
        memory.save_message("user", "User text must not be sent as the answer")
    result = commands.run({"action": "telegram_answer"})
    assert result.success
    assert sent == [(42, "Newest answer\nhttps://example.com/source")]


def test_shared_prompt_explains_answer_forwarding(delivery):
    assert "send me the answer in telegram" in config.SYSTEM_PROMPT


def test_failed_delivery_does_not_claim_success_or_replace_answer(delivery, monkeypatch, caplog):
    memory, sent = delivery
    memory.save_message("assistant", "The original answer")

    def fail(*a, **kw):
        raise client.TelegramError("test-token failure")

    monkeypatch.setattr(client, "send", fail)
    reply = asyncio.run(chat.chat(chat.ChatRequest(message="send me the answer in telegram")))
    assert reply.action_success is False and not sent
    assert "test-token" not in reply.response + caplog.text
    assert memory.get_recent_history()[-1]["content"] == "The original answer"


def test_unconfigured_bot_cannot_forward(delivery, monkeypatch):
    memory, sent = delivery
    memory.save_message("assistant", "The original answer")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    result = commands.run({"action": "telegram_answer"})
    assert not result.success and not sent


def test_unreadable_memory_is_reported_without_private_details(delivery, monkeypatch, caplog):
    _, sent = delivery

    def fail(self):
        raise MemoryError("private database details")

    monkeypatch.setattr(MemoryService, "get_last_assistant_message", fail)
    result = commands.run({"action": "telegram_answer"})
    assert not result.success and not sent
    assert "private database details" not in result.message + caplog.text


def test_file_named_answer_is_still_a_file():
    assert commands.match_command("send me answer.txt in telegram") == {
        "action": "telegram_file", "reference": "answer.txt"}
