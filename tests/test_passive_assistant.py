import asyncio
from datetime import datetime

import pytest

from core.config import config
from providers.base_provider import Message
from services.screen_watch import companion, service


@pytest.fixture
def aware(monkeypatch):
    watch = service.ScreenWatch()
    monkeypatch.setattr(service, "watch", watch)
    monkeypatch.setattr(watch, "visible", lambda: True)
    watch.control("start")
    watch.store.save(epoch=watch.store.settings()["epoch"], session=watch.session, scope={"hwnd": 42},
                     app="reader", summary="PRIVATE_SYNTHETIC_LECTURE is visible.",
                     activity="May be reading.", subject="graph theory", kind="reading",
                     source="accessible_text", at=datetime.now())
    calls = []
    async def local(messages, **kwargs):
        assert kwargs["guard"]()
        calls.append(messages)
        return {"message": {"content": "We can continue with PRIVATE_GRAPH_NOTES."}, "eval_count": 12}
    monkeypatch.setattr(companion.inference, "local_chat", local)
    return watch, calls


def test_ordinary_conversation_automatically_uses_passive_learning(aware):
    watch, calls = aware
    result = asyncio.run(companion.answer("Hey, let's carry on."))
    assert "PRIVATE_GRAPH" in result.content and result.provider == "ollama"
    assert "PRIVATE_SYNTHETIC_LECTURE" in calls[0][0]["content"]
    assert "graph theory" in calls[0][0]["content"]
    assert "do not" in calls[0][0]["content"].lower()
    assert "PRIVATE_SYNTHETIC" not in config.SYSTEM_PROMPT
    assert watch.dialogue[-1]["content"] == result.content


def test_private_followup_continuity_is_local_and_cleared_by_controls(aware):
    watch, calls = aware
    asyncio.run(companion.answer("Hello."))
    asyncio.run(companion.answer("Tell me more."))
    assert any("PRIVATE_GRAPH" in m["content"] for m in calls[-1][1:])
    watch.control("pause")
    assert watch.dialogue == []
    assert asyncio.run(companion.answer("Hello again.")) is None


@pytest.mark.parametrize("action", ["pause", "forget"])
def test_late_private_reply_is_dropped_after_context_is_revoked(aware, monkeypatch, action):
    watch, calls = aware
    async def late(*args, **kwargs):
        watch.control("pause") if action == "pause" else watch.store.forget()
        return {"message": {"content": "PRIVATE_LATE_RESULT"}}
    monkeypatch.setattr(companion.inference, "local_chat", late)
    result = asyncio.run(companion.answer("Hello."))
    assert "PRIVATE_LATE" not in result.content and not watch.dialogue


def test_remote_and_hidden_badge_never_read_passive_context(aware, monkeypatch):
    watch, calls = aware
    assert asyncio.run(companion.answer("Hello.", remote=True)) is None
    monkeypatch.setattr(watch, "visible", lambda: False)
    assert asyncio.run(companion.answer("Hello.")) is None
    assert not calls


def test_local_failure_never_uses_cloud_or_saves_a_partial_thread(aware, monkeypatch):
    watch, calls = aware
    async def unavailable(*args, **kwargs):
        raise ValueError("untrusted private exception")
    monkeypatch.setattr(companion.inference, "local_chat", unavailable)
    monkeypatch.setattr("providers.failover.complete_with_failover", lambda *a, **k: pytest.fail("Cloud fallback"))
    result = asyncio.run(companion.answer("Hello."))
    assert result.model == "friday" and "unavailable" in result.content and not watch.dialogue


@pytest.mark.parametrize("channel", ["chat", "voice"])
@pytest.mark.parametrize("assist_only", [True, False])
def test_real_ordinary_reply_paths_use_private_context_without_shared_learning(aware, monkeypatch, channel, assist_only):
    from interfaces.api.routes import chat as chat_route, voice
    from services.mind.cognition import cognition
    watch, calls = aware
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    async def no_action(*args):
        return None
    monkeypatch.setattr(chat_route, "try_system_action", no_action)
    monkeypatch.setattr(voice, "try_system_action", no_action)
    def forbidden(*args, **kwargs):
        pytest.fail("Private context reached shared history, learning, or ordinary model")
    monkeypatch.setattr(chat_route._memory, "save_message", forbidden)
    monkeypatch.setattr(voice._memory, "save_message", forbidden)
    monkeypatch.setattr("services.mind.brain_memory.brain_memory.remember", forbidden)
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    monkeypatch.setattr("services.mind.language.answer", forbidden)
    spoken = []
    monkeypatch.setattr(chat_route, "_speak_in_background", lambda text, **kw: spoken.append(kw))
    monkeypatch.setattr(voice, "_speak_in_background", lambda text, **kw: spoken.append(kw))
    result = asyncio.run(chat_route.chat(chat_route.ChatRequest(message="Hello Friday.", speak=True))) if channel == "chat" else asyncio.run(
        voice._reply("Hello Friday.", voice.VoiceRequest(speak=True)))
    assert result.private and result.provider == "ollama" and calls
    assert spoken == [{"cache": False, "local_only": True}]
    with cognition._connect() as conn:
        assert "PRIVATE_GRAPH" not in str(conn.execute("SELECT text FROM events").fetchall())


def test_explicit_command_keeps_priority_over_passive_conversation(aware, monkeypatch):
    from interfaces.api.routes import chat as chat_route
    from services.automation.results import ActionResult
    async def clock(*args):
        return ActionResult(True, "It is 6 PM.")
    monkeypatch.setattr(chat_route, "try_system_action", clock)
    monkeypatch.setattr(companion.inference, "local_chat", lambda *a, **k: pytest.fail("Command became conversation"))
    result = asyncio.run(chat_route.chat(chat_route.ChatRequest(message="what time is it", speak=False)))
    assert result.model == "system_control" and "6 PM" in result.response


@pytest.mark.parametrize("channel", ["chat", "voice"])
@pytest.mark.parametrize("proposal", ["search google for the topic I was viewing", "give a topic suggestion",
                                     "search_chrome then search google for suggestion for topic",
                                     "mute then search google for topic suggestions"])
def test_suggestion_reaches_private_conversation_after_a_wrong_proposal(aware, monkeypatch, channel, proposal):
    from interfaces.api.routes import chat as chat_route, voice
    from services.automation import intent
    from services.mind import language
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    async def wrong_command(*args):
        return proposal
    monkeypatch.setattr(language, "understand", wrong_command)
    monkeypatch.setattr(intent.system, "search_chrome", lambda *a: pytest.fail("Conversation became browser action"))
    monkeypatch.setattr(intent.system, "set_mute", lambda *a: pytest.fail("Invented batch partially ran"))
    message = "Give me one small suggestion for the topic I was just viewing."
    result = asyncio.run(chat_route.chat(chat_route.ChatRequest(message=message))) if channel == "chat" else asyncio.run(
        voice._reply(message, voice.VoiceRequest(speak=False)))
    assert result.private and result.provider == "ollama" and aware[1]
