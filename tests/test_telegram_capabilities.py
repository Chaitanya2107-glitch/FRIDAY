import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.config import config
from services.automation import intent
from services.files import assistant
from services.files.search import FileHit
from services.telegram import capabilities, client, commands, summaries


@pytest.fixture
def tg(monkeypatch, tmp_path):
    sent, uploaded = [], []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    monkeypatch.setattr(config, "TELEGRAM_BRIEFING_HOUR", "7")
    monkeypatch.setattr(config, "TELEGRAM_NIGHTLY_HOUR", "21")
    monkeypatch.setattr(config, "TELEGRAM_WEEKLY_HOUR", "21")
    monkeypatch.setattr(config, "TELEGRAM_WEEKLY_DAY", 6)
    monkeypatch.setattr(client, "send", lambda recipient, text, *a: sent.append((recipient, text)))
    monkeypatch.setattr(client, "send_file", lambda recipient, path, *a, **kw: uploaded.append((recipient, path)))
    monkeypatch.setattr(client, "call", lambda method, **kw: {"is_bot": True})
    monkeypatch.setattr(summaries, "state_path", tmp_path / "summaries.json")
    monkeypatch.setattr(summaries, "_busy", False)
    monkeypatch.setattr(summaries, "_retry_after", {})
    monkeypatch.setattr(assistant, "last_results", assistant._LastResults())
    return SimpleNamespace(sent=sent, uploaded=uploaded, folder=tmp_path)


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


def test_bot_awareness_describes_configured_capability_without_credentials(tg):
    text = capabilities.prompt_section()
    assert "Telegram" in text and "send" in text.lower()
    assert "test-token" not in text and "42" not in text
    assert "21:00" in text and "07:00" in text
    assert text in config.SYSTEM_PROMPT


def test_unconfigured_bot_is_not_claimed_connected(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    assert "not configured" in capabilities.prompt_section().lower()


def test_status_checks_bot_and_explains_capabilities(tg):
    result = say("do you have a telegram bot")
    assert result.success and "connected" in result.message.lower()
    assert "summary" in result.message.lower() or "recap" in result.message.lower()


@pytest.mark.parametrize("phrase", ["send me that file through telgram bot", "send that file via Telegram",
                                   "please send me it on the telegram bot", "share that file through telegram"])
def test_recent_file_can_be_sent_from_laptop(tg, phrase):
    file = tg.folder / "notes.pdf"
    file.write_bytes(b"test-document")
    assistant.last_results.set([FileHit(str(file), file.name)])
    result = say(phrase)
    assert result.success and tg.uploaded == [(42, file)]
    assert result.memory_message and file.name not in result.memory_message


def test_ambiguous_reference_never_uploads(tg):
    assistant.last_results.set([FileHit(str(tg.folder / name), name) for name in ("a.pdf", "b.pdf")])
    result = say("send me that file through telegram")
    assert not result.success and not tg.uploaded
    assert "which" in result.message.lower()


def test_selected_result_is_used_instead_of_first_hit(tg, monkeypatch):
    files = [tg.folder / name for name in ("a.pdf", "b.pdf")]
    for file in files:
        file.write_bytes(b"test")
    assistant.last_results.set([FileHit(str(file), file.name) for file in files])
    monkeypatch.setattr(assistant.os, "startfile", lambda *a: None)
    assistant.open_result(2)
    assert say("send me that file through telegram").success
    assert tg.uploaded == [(42, files[1])]


def test_numbered_result_is_sent_without_an_ai_call(tg):
    file = tg.folder / "notes.pdf"
    file.write_bytes(b"test")
    assistant.last_results.set([FileHit(str(file), file.name)])
    assert say("send me file 1 through telegram").success
    assert tg.uploaded == [(42, file)]


def test_missing_or_expired_reference_cannot_send(tg):
    assert not say("send me that file through telegram").success
    assert not tg.uploaded


def test_daily_nightly_and_sunday_summaries_are_sent_once(tg, monkeypatch):
    monkeypatch.setattr(summaries, "build", lambda kind, now: kind + " report")
    sunday = datetime(2026, 10, 11, 6, 59)
    asyncio.run(summaries.tick(sunday))
    assert not tg.sent
    asyncio.run(summaries.tick(sunday.replace(hour=7)))
    assert tg.sent == [(42, "morning report")]
    asyncio.run(summaries.tick(sunday.replace(hour=21)))
    assert [text for _, text in tg.sent] == ["morning report", "nightly report", "weekly report"]
    asyncio.run(summaries.tick(sunday.replace(hour=22)))
    assert len(tg.sent) == 3


def test_morning_summary_is_daily_without_timetable(tg, monkeypatch):
    monkeypatch.setattr(summaries, "build", lambda kind, now: "Daily briefing")
    asyncio.run(summaries.tick(datetime(2026, 10, 12, 7)))
    assert tg.sent == [(42, "Daily briefing")]


def test_failure_is_retried_and_not_marked_delivered(tg, monkeypatch):
    monkeypatch.setattr(summaries, "build", lambda kind, now: kind)
    attempts = []

    def fail(*args):
        attempts.append(args)
        raise client.TelegramError("offline")

    monkeypatch.setattr(client, "send", fail)
    now = datetime(2026, 10, 12, 7)
    asyncio.run(summaries.tick(now))
    asyncio.run(summaries.tick(now.replace(minute=1)))
    assert len(attempts) == 1
    monkeypatch.setattr(client, "send", lambda recipient, text: tg.sent.append((recipient, text)))
    asyncio.run(summaries.tick(now.replace(minute=5)))
    assert tg.sent == [(42, "morning")]


def test_long_summary_is_split_without_losing_text(tg):
    text = "First paragraph\n" + "x" * 9000
    client.send_long(42, text)
    assert "".join(part for _, part in tg.sent) == text
    assert all(len(part) <= client.TEXT_LIMIT for _, part in tg.sent)


def test_summary_can_be_requested_from_chat(tg, monkeypatch):
    monkeypatch.setattr(summaries, "build", lambda kind, now: kind + " summary")
    assert say("send me my weekly summary through telegram").success
    assert tg.sent == [(42, "weekly summary")]


def test_disabling_an_hour_prevents_that_report(tg, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BRIEFING_HOUR", "")
    monkeypatch.setattr(config, "TELEGRAM_NIGHTLY_HOUR", "25")
    monkeypatch.setattr(config, "TELEGRAM_WEEKLY_HOUR", "bad")
    assert summaries.due(datetime(2026, 10, 11, 23)) == []


def test_file_too_large_cannot_be_uploaded(tg, monkeypatch):
    file = tg.folder / "big.pdf"
    file.write_bytes(b"12345")
    monkeypatch.setattr(client, "MAX_UPLOAD_BYTES", 4)
    assistant.last_results.set([FileHit(str(file), file.name)])
    assert not say("send me that file through telegram").success
    assert not tg.uploaded


def test_expired_search_cannot_be_used(tg):
    assistant.last_results.set([FileHit(str(tg.folder / "notes.pdf"), "notes.pdf")])
    assistant.last_results.at -= assistant.RESULTS_VALID_SECONDS + 1
    assert not say("send me that file through telegram").success
    assert not tg.uploaded


def test_named_file_search_requires_a_unique_match(tg, monkeypatch):
    files = [tg.folder / name for name in ("resume.pdf", "old_resume.pdf")]
    for file in files:
        file.write_bytes(b"test")
    hits = [FileHit(str(file), file.name) for file in files]
    monkeypatch.setattr(commands, "find_files", lambda query: hits)
    assert not say("send me my resume through telegram").success
    assert not tg.uploaded
    assert say("send me resume.pdf through telegram").success
    assert tg.uploaded == [(42, files[0])]


def test_sending_failure_does_not_claim_success_or_expose_token(tg, monkeypatch, caplog):
    file = tg.folder / "notes.pdf"
    file.write_bytes(b"test")
    assistant.last_results.set([FileHit(str(file), file.name)])

    def fail(*args):
        raise client.TelegramError("test-token failed")

    monkeypatch.setattr(client, "send_file", fail)
    result = say("send me that file through telegram")
    assert not result.success
    assert "test-token" not in result.message and "test-token" not in caplog.text


def test_delivery_markers_survive_a_restart(tg, monkeypatch):
    monkeypatch.setattr(summaries, "build", lambda kind, now: kind)
    now = datetime(2026, 10, 12, 7)
    asyncio.run(summaries.tick(now))
    summaries._delivered.clear()  # a fresh process, reading the persisted marker
    asyncio.run(summaries.tick(now.replace(minute=1)))
    assert len(tg.sent) == 1


def test_failed_state_save_does_not_resend_every_minute(tg, monkeypatch):
    monkeypatch.setattr(summaries, "build", lambda kind, now: kind)

    def fail(state):
        raise OSError("disk full")

    monkeypatch.setattr(summaries, "_save", fail)
    now = datetime(2026, 10, 12, 7)
    asyncio.run(summaries.tick(now))
    asyncio.run(summaries.tick(now.replace(minute=1)))
    assert len(tg.sent) == 1


def test_concurrent_ticks_do_not_duplicate_delivery(tg, monkeypatch):
    import threading

    entered, release = threading.Event(), threading.Event()

    def deliver(*args):
        entered.set()
        assert release.wait(5)
        tg.sent.append((42, "summary"))

    monkeypatch.setattr(summaries, "deliver", deliver)

    async def scenario():
        now = datetime(2026, 10, 12, 7)
        first = asyncio.create_task(summaries.tick(now))
        assert await asyncio.to_thread(entered.wait, 5)
        await summaries.tick(now)
        release.set()
        await first

    asyncio.run(scenario())
    assert len(tg.sent) == 1


@pytest.mark.parametrize("interface", ["chat", "voice"])
def test_chat_and_voice_providers_receive_telegram_awareness(tg, monkeypatch, interface):
    from interfaces.api.routes import chat, voice
    from providers.base_provider import ProviderResponse

    prompts = []
    route = chat if interface == "chat" else voice

    async def none(*a, **kw):
        return None

    async def complete(provider, messages, system_prompt, *a, **kw):
        prompts.append(system_prompt)
        return ProviderResponse(content="Known capability", provider=provider, model="test")

    monkeypatch.setattr(route, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    for name in ("try_system_action", "build_file_context", "build_search_context"):
        monkeypatch.setattr(route, name, none)
    monkeypatch.setattr(route, "complete_with_failover", complete)
    if interface == "chat":
        asyncio.run(chat.chat(chat.ChatRequest(message="What can you do with Telegram?")))
    else:
        asyncio.run(voice._reply("What can you do with Telegram?", voice.VoiceRequest(speak=False)))
    assert len(prompts) == 1
    assert "integrated Telegram bot configured for Boss" in prompts[0]
    assert "test-token" not in prompts[0]


@pytest.mark.parametrize("interface", ["chat", "voice"])
def test_file_delivery_skips_file_excerpts_and_ai_search(tg, monkeypatch, interface):
    from interfaces.api.routes import chat, voice

    route = chat if interface == "chat" else voice
    file = tg.folder / "private_notes.pdf"
    file.write_bytes(b"private contents must not go to an AI")
    assistant.last_results.set([FileHit(str(file), file.name)])

    async def must_not_call(*a, **kw):
        pytest.fail("Telegram file transfer sent context to search or an AI")

    monkeypatch.setattr(route, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    for name in ("build_file_context", "build_search_context", "complete_with_failover"):
        monkeypatch.setattr(route, name, must_not_call)
    message = "send me that file through telgram bot"
    if interface == "chat":
        reply = asyncio.run(chat.chat(chat.ChatRequest(message=message)))
    else:
        reply = asyncio.run(voice._reply(message, voice.VoiceRequest(speak=False)))
    assert reply.action_success is True and tg.uploaded == [(42, file)]
