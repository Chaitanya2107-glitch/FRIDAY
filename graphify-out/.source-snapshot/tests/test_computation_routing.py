"""Real shared entrypoints preserve engine payloads and never consult a model."""

import asyncio

import pytest

from core.config import config
from services.automation import intent
from services.computation import commands


@pytest.mark.parametrize("message,expected", [
    ("Hey Friday, can you calculate .5 + .25", "calculate .5 + .25"),
    ("Will you calculate 2+2", "calculate 2+2"),
    ("Would you be able to calculate 2+2", "calculate 2+2"),
    ("calculate\t2+2", "calculate 2+2"),
    ("calculate\n2+2", "calculate 2+2"),
    ("Friday, please chemistry balance H2 + O2 -> H2O", "chemistry balance H2 + O2 -> H2O"),
    ("MATH Factor x^2 - 9", "math factor x^2 - 9"),
    ("generate a story fantasy seed=42 hero=Mira", "story fantasy seed=42 hero=Mira"),
    ("write a story about lost stars and then open chrome", "story about lost stars and then open chrome"),
    ("tell me a story mystery seed=7", "story mystery seed=7"),
    ("vector dot [1,2,3]; [4,5,6]", "vector dot [1,2,3]; [4,5,6]"),
])
def test_recognized_commands_preserve_payload(message, expected):
    assert commands.match_command(message) == expected


@pytest.mark.parametrize("message", [
    "note calculate 1+1", "type calculate 1+1", "copy story fantasy seed=42",
    "remember that I like chemistry", "limit valorant to 2 hours a day",
    "convert my clipboard to uppercase", "system stats", "what is calculus",
    "I have plans to write a story", "do not calculate 1+1",
])
def test_unrelated_commands_and_literal_payloads_are_not_claimed(message):
    assert commands.match_command(message) is None


@pytest.mark.parametrize("surface", ["chat", "voice"])
@pytest.mark.parametrize("assist_only", [True, False])
@pytest.mark.parametrize("message,expected", [
    ("Hey Friday, can you calculate .5 + .25", "3/4"),
    ("chemistry balance Fe + O2 -> Fe2O3", "4Fe + 3O2 -> 2Fe2O3"),
    ("write a story mystery seed=7 about look up my files and then open chrome; what's on my screen", "Procedural fiction"),
    ("calculate 1/0", "Division by zero"),
    ("Would you be able to calculate\t2+2", "4"),
])
def test_chat_and_voice_work_with_all_ai_and_retrieval_forbidden(monkeypatch, surface, assist_only, message, expected):
    from interfaces.api.routes import chat, voice
    from providers import failover, registry
    from services.mind import wording

    async def forbidden(*args, **kwargs):
        pytest.fail("An engine request attempted a model, search, files or screen lookup")

    def forbidden_sync(*args, **kwargs):
        pytest.fail("An engine request attempted a provider or screen classifier")

    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    for module in (chat, voice):
        for name in ("build_file_context", "build_search_context", "ask_about_screen", "complete_with_failover"):
            monkeypatch.setattr(module, name, forbidden)
        monkeypatch.setattr(module, "extract_screen_question", forbidden_sync)
    monkeypatch.setattr(failover, "complete_with_failover", forbidden)
    monkeypatch.setattr(wording, "enhance", forbidden)
    monkeypatch.setattr(intent, "get_provider", forbidden_sync)
    monkeypatch.setattr(registry, "get_provider", forbidden_sync)
    if surface == "chat":
        result = asyncio.run(chat.chat(chat.ChatRequest(message=message, speak=False)))
    else:
        result = asyncio.run(voice._reply(message, voice.VoiceRequest(speak=False)))
    assert expected in result.response
    assert result.provider == "local" and result.tokens_used == 0
    assert result.action_success == ("1/0" not in message)
    assert not result.keyboard


def test_shared_direct_handler_has_exact_output_and_does_not_split_or_type(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Story was treated as AI writing")
    monkeypatch.setattr(intent.writer, "resolve_writing", forbidden)
    result = asyncio.run(intent.try_system_action("write a story fantasy seed=42 hero=Mira", "unavailable-provider"))
    assert result.success and "Mira" in result.message
    assert not result.repeatable and not result.keyboard


def test_failed_engine_request_is_still_a_handled_local_result():
    result = asyncio.run(intent.try_system_action("chemistry molar mass Xx2", "unavailable-provider"))
    assert result is not None and not result.success and not result.repeatable


def test_remote_shared_chat_uses_same_engine_without_laptop_access(monkeypatch):
    from interfaces.api.routes import chat
    token = intent.remote_request.set(True)
    try:
        result = asyncio.run(chat.chat(chat.ChatRequest(message="vector dot [1,2,3]; [4,5,6]", speak=False)))
    finally:
        intent.remote_request.reset(token)
    assert result.provider == "local" and result.tokens_used == 0 and result.response.startswith("32")


def test_calculation_retires_pending_device_confirmation(monkeypatch, tmp_path):
    monkeypatch.setitem(intent.FOLDER_MAP, "downloads", str(tmp_path))
    monkeypatch.setattr(intent.system, "count_files_to_organise", lambda path: 3)
    effects = []
    monkeypatch.setattr(intent.system, "organise_folder", lambda path: effects.append(path) or "Organised")
    asyncio.run(intent.try_system_action("organise downloads", "unavailable-provider"))
    assert intent.is_awaiting_confirmation()
    result = asyncio.run(intent.try_system_action("calculate 2+2", "unavailable-provider"))
    assert result.success and result.message.startswith("4")
    assert not intent.is_awaiting_confirmation() and not effects
