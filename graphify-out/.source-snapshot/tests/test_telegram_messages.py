import asyncio

import pytest

from core.config import config
from interfaces.api.routes import chat, voice
from services.automation import intent
from services.files.search import FileHit
from services.memory.sqlite_memory import MemoryService
from services.telegram import capabilities, client, commands


@pytest.fixture
def delivery(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    memory = MemoryService()
    monkeypatch.setattr(chat, "_memory", memory)
    monkeypatch.setattr(voice, "_memory", memory)
    sent, uploaded = [], []
    monkeypatch.setattr(client, "send", lambda recipient, text: sent.append((recipient, text)))
    monkeypatch.setattr(client, "send_file", lambda recipient, path: uploaded.append((recipient, path)))
    monkeypatch.setattr(commands, "find_files", lambda query: pytest.fail("A text message searched for files"))
    return sent, uploaded


@pytest.mark.parametrize("phrase,payload", [
    ('send me a "hi" through telegram', "hi"),
    ('send me "Hi. Are you there?" through telegram', "Hi. Are you there?"),
    ("send me hi through telegram", "hi"),
    ("please send me a message saying Hi, Boss! through Telegram", "Hi, Boss!"),
    ("send me the text Hello there via telegram bot", "Hello there"),
    ('send me the text "notes.pdf" on telegram', "notes.pdf"),
    ('send me a message on telegram saying "Hi!!!"', "Hi!!!"),
    ("send me a message through telegram saying Hi!!!", "Hi!!!"),
    ('Hey Friday, can you send me "dont change this\nI’m ready!!!" through telegram please?',
     "dont change this\nI’m ready!!!"),
])
def test_message_phrases_preserve_literal_text(phrase, payload):
    assert commands.match_command(phrase) == {"action": "telegram_message", "text": payload}


@pytest.mark.parametrize("interface", ["chat", "voice"])
@pytest.mark.parametrize("assist_only", [False, True])
@pytest.mark.parametrize("phrase,payload", [
    ('send me a message through telegram saying "dont change this\nI’m ready!!!"', "dont change this\nI’m ready!!!"),
    ('forward the message "What is on my screen? Keep CAPS!" via telegram', "What is on my screen? Keep CAPS!"),
])
def test_message_is_sent_through_real_router_without_ai(delivery, monkeypatch, interface, assist_only, phrase, payload):
    sent, uploaded = delivery
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)

    async def forbidden(*args, **kwargs):
        pytest.fail("Sending literal Telegram text invoked AI or search")

    route = chat if interface == "chat" else voice
    for name in ("build_file_context", "build_search_context", "complete_with_failover"):
        monkeypatch.setattr(route, name, forbidden)
    if interface == "chat":
        result = asyncio.run(chat.chat(chat.ChatRequest(message=phrase)))
    else:
        result = asyncio.run(voice._reply(phrase, voice.VoiceRequest(speak=False)))
    assert result.action_success is True
    assert sent == [(42, payload)]
    assert not uploaded


def test_explicit_file_label_resolves_filename(delivery, monkeypatch, tmp_path):
    sent, uploaded = delivery
    file = tmp_path / "notes.pdf"
    file.write_bytes(b"test document")
    queries = []

    def find(query):
        queries.append(query)
        return [FileHit(str(file), file.name)]

    monkeypatch.setattr(config, "FILE_SEARCH_ENABLED", True)
    monkeypatch.setattr(commands, "find_files", find)
    result = asyncio.run(intent.try_system_action("send me the file notes.pdf through telegram", "openrouter"))
    assert result.success
    assert queries == ["notes.pdf"]
    assert uploaded == [(42, file)] and not sent


def test_unspecified_file_asks_for_selection_without_searching(delivery):
    sent, uploaded = delivery
    result = asyncio.run(intent.try_system_action("send me a file through telegram", "openrouter"))
    assert not result.success and "which file" in result.message.lower()
    assert not sent and not uploaded


def test_message_failure_never_claims_delivery_or_logs_secrets(delivery, monkeypatch, caplog):
    def fail(*args):
        raise client.TelegramError("test-token private payload")

    monkeypatch.setattr(client, "send", fail)
    result = asyncio.run(intent.try_system_action('send me "hi" through telegram', "openrouter"))
    assert not result.success
    assert "test-token" not in result.message + caplog.text


def test_empty_message_and_missing_config_never_send(delivery, monkeypatch):
    sent, uploaded = delivery
    result = asyncio.run(intent.try_system_action('send me "" through telegram', "openrouter"))
    assert not result.success and "text" in result.message.lower()
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    result = asyncio.run(intent.try_system_action('send me "hi" through telegram', "openrouter"))
    assert not result.success and "configured" in result.message
    assert not sent and not uploaded


def test_runtime_capability_explains_literal_messages(delivery):
    assert 'send me "hi" through telegram' in capabilities.prompt_section()


@pytest.mark.parametrize("interface", ["chat", "voice"])
@pytest.mark.parametrize("followup", ["send the file notes.pdf", "notes.pdf"])
def test_file_clarification_accepts_followup_without_repeating_channel(delivery, monkeypatch, tmp_path, interface, followup):
    sent, uploaded = delivery
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", False)
    monkeypatch.setattr(config, "FILE_SEARCH_ENABLED", True)
    first = asyncio.run(chat.chat(chat.ChatRequest(message="send me a file through telegram")))
    assert first.action_success is False and "which file" in first.response.lower()
    file = tmp_path / "notes.pdf"
    file.write_bytes(b"test document")
    monkeypatch.setattr(commands, "find_files", lambda query: [FileHit(str(file), file.name)] if query == file.name else [])
    if interface == "chat":
        result = asyncio.run(chat.chat(chat.ChatRequest(message=followup)))
    else:
        result = asyncio.run(voice._reply(followup, voice.VoiceRequest(speak=False)))
    assert result.action_success is True
    assert uploaded == [(42, file)] and not sent
    assert commands.match_command("send the file notes.pdf") is None


@pytest.mark.parametrize("interruption", ["expire", "unrelated", "remote"])
def test_file_followup_is_bounded_to_current_conversation(delivery, monkeypatch, interruption):
    asyncio.run(commands.try_handle("send me a file through telegram"))
    if interruption == "expire":
        monkeypatch.setattr(commands.time, "monotonic", lambda: float("inf"))
    elif interruption == "unrelated":
        assert asyncio.run(commands.try_handle("what time is it")) is None
    token = intent.remote_request.set(interruption == "remote")
    try:
        assert commands.match_command("send the file notes.pdf") is None
    finally:
        intent.remote_request.reset(token)


def test_quoted_filename_remains_a_file_and_literal_message_is_not_uploaded():
    assert commands.match_command('send me "notes.pdf" through telegram') == {
        "action": "telegram_file", "reference": '"notes.pdf"'}
    assert commands.match_command('send me the file "my notes.pdf" through telegram') == {
        "action": "telegram_file", "reference": '"my notes.pdf"'}


def test_unrelated_early_command_ends_file_clarification(delivery):
    asyncio.run(chat.chat(chat.ChatRequest(message="send me a file through telegram")))
    result = asyncio.run(chat.chat(chat.ChatRequest(message="type hello")))
    assert result.action_success is True
    assert commands.match_command("send the file notes.pdf") is None
