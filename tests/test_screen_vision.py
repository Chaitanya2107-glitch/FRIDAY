import asyncio
import base64
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from core.config import config
from interfaces.api.app import create_app
from interfaces.api.routes import chat
from interfaces.api.routes import voice as voice_route
from providers import failover
from providers.anthropic.client import _content as anthropic_content
from providers.base_provider import Message
from providers.failover import complete_with_failover
from services.vision import screen
from services.vision.screen import extract_screen_question

LOCAL = "http://127.0.0.1:8000"
FAKE_JPEG = b"\xff\xd8fake-jpeg"


# ── Which messages are screen questions ───────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("what's on my screen?", "what's on my screen?"),
    ("What’s on my screen", "What’s on my screen"),
    ("explain the error on my screen", "explain the error on my screen"),
    ("translate the text on this screen", "translate the text on this screen"),
    ("look at my screen and tell me what's wrong", "look at my screen and tell me what's wrong"),
    ("read my screen", "read my screen"),
    ("can you see my screen?", "can you see my screen?"),
    ("summarize the screen", "summarize the screen"),
    ("what am I looking at", "what am I looking at"),
    ("\\v what does this chart say", "what does this chart say"),
    ("\\v", screen.DEFAULT_QUESTION),
    ("  \\V   ", screen.DEFAULT_QUESTION),
])
def test_screen_questions_are_recognised(message, expected):
    assert extract_screen_question(message) == expected


@pytest.mark.parametrize("message", [
    "take a screenshot",
    "capture my screen",
    "set the brightness on my screen to 50",
    "my screen is flickering, why?",
    "what's a good screen size for a laptop",
    "open screen recorder",
    "look up screen protectors",
    "\\vanilla",
    "",
])
def test_other_messages_are_not_screen_questions(message):
    assert extract_screen_question(message) is None


# ── Capturing ─────────────────────────────────────────────────────────────────

def test_capture_shrinks_the_screen_to_a_jpeg(monkeypatch):
    grabbed = {}

    def grab(bbox=None, all_screens=False):
        grabbed.update(bbox=bbox, all_screens=all_screens)
        return Image.new("RGBA", (3840, 2160), "white")

    monkeypatch.setattr(screen, "_monitor_under_cursor", lambda: (1920, 0, 5760, 2160))
    monkeypatch.setattr(screen.ImageGrab, "grab", grab)

    image = Image.open(io.BytesIO(screen.capture_screen()))

    assert grabbed == {"bbox": (1920, 0, 5760, 2160), "all_screens": True}
    assert image.format == "JPEG"
    assert max(image.size) == screen.MAX_IMAGE_SIDE


def test_capture_failure_raises_vision_error(monkeypatch):
    def broken(**kwargs):
        raise OSError("screen grab failed")
    monkeypatch.setattr(screen.ImageGrab, "grab", broken)
    with pytest.raises(screen.VisionError):
        screen.capture_screen()


def test_monitor_lookup_returns_real_bounds():
    bounds = screen._monitor_under_cursor()
    assert bounds is None or (bounds[2] > bounds[0] and bounds[3] > bounds[1])


# ── Providers get the image ───────────────────────────────────────────────────

def test_openai_format_attaches_image_as_data_url():
    content = Message(role="user", content="what's this?", images=[FAKE_JPEG]).openai_content()
    encoded = base64.b64encode(FAKE_JPEG).decode()
    assert content == [
        {"type": "text", "text": "what's this?"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
    ]


def test_messages_without_images_stay_plain_text():
    message = Message(role="user", content="hi")
    assert message.openai_content() == "hi"
    assert anthropic_content(message) == "hi"


def test_anthropic_format_puts_image_before_the_question():
    content = anthropic_content(Message(role="user", content="what's this?", images=[FAKE_JPEG]))
    assert content[0]["type"] == "image"
    assert content[0]["source"] == {
        "type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(FAKE_JPEG).decode(),
    }
    assert content[1] == {"type": "text", "text": "what's this?"}


# ── Which model answers ───────────────────────────────────────────────────────

@pytest.fixture
def vision_settings(monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "")
    monkeypatch.setattr(config, "VISION_MODEL", "")
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "none")
    monkeypatch.setattr(config, "ACTIVE_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "or-key")


def test_vision_model_defaults_per_provider(vision_settings):
    assert config.vision_model_for("openrouter") == "openai/gpt-4o-mini"
    assert config.vision_model_for("anthropic") == "claude-haiku-4-5"
    assert config.vision_model_for("ollama") is None  # uses OLLAMA_MODEL


def test_configured_vision_model_applies_only_to_its_provider(vision_settings, monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "ollama")
    monkeypatch.setattr(config, "VISION_MODEL", "llava:7b")
    assert config.vision_model_for("ollama") == "llava:7b"
    assert config.vision_model_for("openai") == "gpt-4o-mini"


@pytest.mark.parametrize("provider, model, error", [
    ("gemini", "", "VISION_PROVIDER='gemini' is not valid"),
    ("", "llava:7b", "VISION_MODEL is set but VISION_PROVIDER isn't"),
    ("anthropic", "", "VISION_PROVIDER=anthropic needs its API key"),
])
def test_bad_vision_settings_are_reported(vision_settings, monkeypatch, provider, model, error):
    monkeypatch.setattr(config, "VISION_PROVIDER", provider)
    monkeypatch.setattr(config, "VISION_MODEL", model)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    assert any(error in e for e in config.validate())


def test_failover_asks_each_provider_for_its_model(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "openai")
    requested = []

    class Failing:
        async def complete(self, **kwargs):
            raise RuntimeError("down")

    class Working:
        async def complete(self, **kwargs):
            return SimpleNamespace(content="ok")

    def get_provider(name, model=None):
        requested.append((name, model))
        return Failing() if name == "openrouter" else Working()

    monkeypatch.setattr(failover, "get_provider", get_provider)
    models = {"openrouter": "vision-a", "openai": "vision-b"}
    result = asyncio.run(complete_with_failover("openrouter", [], "", 100, model_for=models.get))

    assert result.content == "ok"
    assert requested == [("openrouter", "vision-a"), ("openai", "vision-b")]


# ── Routes ────────────────────────────────────────────────────────────────────

class FakeMemory:
    def __init__(self):
        self.saved = []

    def get_recent_history(self):
        return [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]

    def save_message(self, role, content):
        self.saved.append((role, content))


class FakeProvider:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, system_prompt, max_tokens):
        self.calls.append(SimpleNamespace(messages=messages, system_prompt=system_prompt))
        return SimpleNamespace(content="A code editor with an error.", provider="openrouter",
                               model="openai/gpt-4o-mini", tokens_used=900)


@pytest.fixture
def screen_setup(monkeypatch, vision_settings):
    provider, memory = FakeProvider(), FakeMemory()
    requested = []

    def get_provider(name, model=None):
        requested.append((name, model))
        return provider

    monkeypatch.setattr(failover, "get_provider", get_provider)
    monkeypatch.setattr(screen, "capture_screen", lambda: FAKE_JPEG)

    async def no_system_action(message, provider_name):
        raise AssertionError("screen questions must not reach system-command matching")

    async def no_search(message, cite=True):
        raise AssertionError("screen questions must not trigger a web search")

    for route in (chat, voice_route):
        monkeypatch.setattr(route, "_memory", memory)
        monkeypatch.setattr(route, "try_system_action", no_system_action)
        monkeypatch.setattr(route, "build_search_context", no_search)

    return SimpleNamespace(provider=provider, memory=memory, requested=requested,
                           client=TestClient(create_app(), base_url=LOCAL))


def test_chat_answers_screen_questions_with_a_screenshot(screen_setup):
    resp = screen_setup.client.post("/api/v1/chat", json={"message": "what's on my screen?"})

    assert resp.status_code == 200
    assert resp.json()["response"] == "A code editor with an error."
    assert screen_setup.requested == [("openrouter", "openai/gpt-4o-mini")]

    call = screen_setup.provider.calls[0]
    assert [m.content for m in call.messages] == ["earlier", "reply", "what's on my screen?"]
    assert call.messages[-1].images == [FAKE_JPEG]
    assert all(not m.images for m in call.messages[:-1])
    assert screen.SCREEN_PROMPT in call.system_prompt
    assert screen.SPOKEN_PROMPT not in call.system_prompt

    # Only the text is remembered, never the screenshot
    assert screen_setup.memory.saved == [
        ("user", "what's on my screen?"), ("assistant", "A code editor with an error."),
    ]


def test_screen_question_uses_the_configured_vision_provider(screen_setup, monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "ollama")
    monkeypatch.setattr(config, "VISION_MODEL", "llava:7b")
    screen_setup.client.post("/api/v1/chat", json={"message": "\\v what is this"})
    assert screen_setup.requested == [("ollama", "llava:7b")]
    assert screen_setup.provider.calls[0].messages[-1].content == "what is this"


def test_capture_failure_returns_an_error_and_saves_nothing(screen_setup, monkeypatch):
    def broken():
        raise screen.VisionError("Couldn't capture the screen.")
    monkeypatch.setattr(screen, "capture_screen", broken)

    resp = screen_setup.client.post("/api/v1/chat", json={"message": "read my screen"})

    assert resp.status_code == 500
    assert resp.json()["message"] == "Couldn't capture the screen."
    assert screen_setup.memory.saved == []


def test_voice_screen_question_asks_for_a_spoken_reply(screen_setup, monkeypatch):
    spoken = []

    async def speak(text, cache=False):
        spoken.append(text)

    monkeypatch.setattr(voice_route.recorder, "record", lambda: b"audio")
    monkeypatch.setattr(voice_route.stt, "transcribe", lambda audio: "explain the error on my screen")
    monkeypatch.setattr(voice_route.tts, "speak", speak)
    monkeypatch.setattr(voice_route.tts, "stop", lambda: None)

    resp = screen_setup.client.post("/api/v1/voice", json={})

    assert resp.status_code == 200
    assert resp.json()["action"] == "chat"
    call = screen_setup.provider.calls[0]
    assert call.messages[-1].images == [FAKE_JPEG]
    assert call.messages[-1].content == "explain the error on my screen"
    assert screen.SPOKEN_PROMPT in call.system_prompt
    assert spoken == ["A code editor with an error."]
