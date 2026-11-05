import asyncio
from types import SimpleNamespace

import pytest

from core.errors import ProviderError
from providers import failover
from providers.base_provider import BaseProvider, Message, ProviderResponse
from providers.failover import complete_with_failover
from services.voice.speech_stream import FirstSentenceSpeaker, first_sentence_end


# ── Where the first sentence ends ─────────────────────────────────────────────

@pytest.mark.parametrize("text, first", [
    ("Octopuses have three hearts. They also", "Octopuses have three hearts."),
    ("Sure! Here are three names: Focus Flow, Deep Work. More", "Sure! Here are three names: Focus Flow, Deep Work."),
    ("Pi is about 3.14 which is handy. Next", "Pi is about 3.14 which is handy."),
    ("Try fruit, e.g. apples or pears. Next", "Try fruit, e.g. apples or pears."),
    ("Here are some ideas:\n- Lo-fi", "Here are some ideas:\n"),
    ("1. Open the settings app. 2. Tap", "1. Open the settings app."),
    ("मैं ठीक हूँ, धन्यवाद। आप", "मैं ठीक हूँ, धन्यवाद।"),
    ("Octopuses have three hearts.", None),  # might still continue ("hearts.5"?) — wait for more
    ("Hi.", None),
    ("It keeps going and going without an end", None),
])
def test_first_sentence_end(text, first):
    end = first_sentence_end(text)
    assert (text[:end] if end else None) == first


def test_speaker_says_the_first_sentence_early_and_the_rest_at_the_end():
    said, stopped = [], False
    speaker = FirstSentenceSpeaker(said.append, lambda: stopped)
    for piece in ("Wi-Fi sends data ", "as radio waves. Your router ", "decodes them. ", "Simple!"):
        speaker.feed(piece)
    assert said == ["Wi-Fi sends data as radio waves."]
    speaker.finish()
    assert said == ["Wi-Fi sends data as radio waves.", "Your router decodes them. Simple!"]


def test_short_replies_are_said_in_one_piece():
    said = []
    speaker = FirstSentenceSpeaker(said.append, lambda: False)
    speaker.feed("Hey! How can I help?")
    speaker.finish()
    assert said == ["Hey! How can I help?"]


def test_speaker_goes_quiet_once_stopped():
    said, state = [], SimpleNamespace(stopped=False)
    speaker = FirstSentenceSpeaker(said.append, lambda: state.stopped)
    speaker.feed("First part is here. Second")
    state.stopped = True
    speaker.feed(" part.")
    speaker.finish()
    assert said == ["First part is here."]


# ── Providers and failover ────────────────────────────────────────────────────

def test_providers_without_real_streaming_stream_the_whole_reply():
    class OneShot(BaseProvider):
        async def complete(self, messages, system_prompt="", max_tokens=1000, temperature=0.7, tools=None):
            return ProviderResponse(content="All at once.", provider="x", model="y")
        def get_provider_name(self): return "x"
        def get_model_name(self): return "y"

    async def collect():
        return [text async for text in OneShot().stream([Message("user", "hi")])]
    assert asyncio.run(collect()) == ["All at once."]


@pytest.fixture
def streams(monkeypatch):
    """behaviour[name] = list of pieces; an Exception in the list is raised at that point."""
    monkeypatch.setattr(failover.config, "ACTIVE_PROVIDER", "openai")
    monkeypatch.setattr(failover.config, "fallback_providers", lambda: ["openrouter"])
    state = SimpleNamespace(behaviour={}, heard=[])

    def fake_get_provider(name):
        async def stream(messages, system_prompt, max_tokens):
            for piece in state.behaviour.get(name, [f"reply from {name}"]):
                if isinstance(piece, Exception):
                    raise piece
                yield piece
        return SimpleNamespace(stream=stream, get_model_name=lambda: f"{name}-model")

    monkeypatch.setattr(failover, "get_provider", fake_get_provider)
    return state


def stream_reply(state):
    return asyncio.run(complete_with_failover(
        "openai", [Message("user", "hi")], "system", 100, on_text=state.heard.append,
    ))


def test_streamed_reply_is_passed_on_and_returned_whole(streams):
    streams.behaviour["openai"] = ["Hello ", "there."]
    result = stream_reply(streams)
    assert streams.heard == ["Hello ", "there."]
    assert (result.content, result.provider, result.model) == ("Hello there.", "openai", "openai-model")


def test_falls_back_when_the_provider_fails_before_saying_anything(streams):
    streams.behaviour["openai"] = [ConnectionError("gateway down")]
    result = stream_reply(streams)
    assert (result.content, result.provider) == ("reply from openrouter", "openrouter")
    assert streams.heard == ["reply from openrouter"]


def test_keeps_what_was_said_when_the_provider_fails_part_way(streams):
    streams.behaviour["openai"] = ["The first half. ", ConnectionError("dropped")]
    result = stream_reply(streams)
    assert (result.content, result.provider, result.metadata) == ("The first half. ", "openai", {"incomplete": True})
    assert streams.heard == ["The first half. "]  # never restarted on another provider


def test_every_provider_failing_to_stream_raises(streams):
    streams.behaviour = {"openai": [ConnectionError("a")], "openrouter": [ConnectionError("b")]}
    with pytest.raises(ProviderError):
        stream_reply(streams)
