import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from core.errors import ProviderError
from interfaces.api.app import create_app
from interfaces.api.routes import chat
from providers import failover
from providers.base_provider import Message
from providers.failover import complete_with_failover, provider_chain


@pytest.fixture(autouse=True)
def providers_set_up(monkeypatch):
    """OpenRouter and OpenAI have keys, Anthropic doesn't, Ollama has its defaults."""
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "oa-key")
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "gemma3:4b")


# ── Which providers get tried ─────────────────────────────────────────────────

@pytest.mark.parametrize("setting, primary, expected", [
    ("", "openrouter", ["openrouter", "openai", "ollama"]),
    ("", "anthropic", ["anthropic", "openrouter", "openai", "ollama"]),
    ("ollama, openrouter", "openrouter", ["openrouter", "ollama"]),
    ("none", "openrouter", ["openrouter"]),
    ("NONE", "ollama", ["ollama"]),
])
def test_provider_chain(monkeypatch, setting, primary, expected):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", setting)
    assert provider_chain(primary) == expected


@pytest.mark.parametrize("setting, error", [
    ("anthropic", "FALLBACK_PROVIDERS lists anthropic, but it isn't set up"),
    ("gemini", "FALLBACK_PROVIDERS has 'gemini'"),
])
def test_config_rejects_bad_fallback_settings(monkeypatch, setting, error):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", setting)
    assert any(error in message for message in config.validate())


@pytest.mark.parametrize("setting", ["", "none", "openai, ollama"])
def test_config_accepts_valid_fallback_settings(monkeypatch, setting):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", setting)
    assert not any("FALLBACK_PROVIDERS" in message for message in config.validate())


# ── Failing over ──────────────────────────────────────────────────────────────

@pytest.fixture
def fake_providers(monkeypatch):
    """behaviour[name] = reply text or an exception to raise; unbuildable = names get_provider rejects."""
    state = SimpleNamespace(calls=[], behaviour={}, unbuildable=set())

    def fake_get_provider(name):
        if name in state.unbuildable:
            raise RuntimeError(f"{name} client could not be created")

        async def complete(messages, system_prompt, max_tokens):
            state.calls.append(name)
            outcome = state.behaviour.get(name, f"reply from {name}")
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(content=outcome, provider=name, model=f"{name}-model", tokens_used=7)

        return SimpleNamespace(complete=complete)

    monkeypatch.setattr(failover, "get_provider", fake_get_provider)
    return state


def run(provider="openrouter"):
    return asyncio.run(complete_with_failover(provider, [Message("user", "hi")], "system prompt", 100))


def test_working_provider_answers_without_trying_others(fake_providers):
    assert run().provider == "openrouter"
    assert fake_providers.calls == ["openrouter"]


def test_falls_back_when_the_provider_errors(fake_providers):
    fake_providers.behaviour["openrouter"] = ProviderError("OpenRouter rate limit hit")

    response = run()

    assert (response.provider, response.content) == ("openai", "reply from openai")
    assert fake_providers.calls == ["openrouter", "openai"]


def test_provider_whose_client_cannot_be_created_is_skipped(fake_providers):
    fake_providers.unbuildable.add("openrouter")
    assert run().provider == "openai"


def test_every_provider_failing_lists_each_error(fake_providers):
    fake_providers.behaviour.update(
        openrouter=ProviderError("rate limit"),
        openai=ProviderError("bad key"),
        ollama=ProviderError("not running"),
    )

    with pytest.raises(ProviderError) as error:
        run()

    for detail in ("openrouter: rate limit", "openai: bad key", "ollama: not running"):
        assert detail in error.value.message


def test_none_setting_never_falls_back(fake_providers, monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "none")
    fake_providers.behaviour["openrouter"] = ProviderError("down")

    with pytest.raises(ProviderError):
        run()
    assert fake_providers.calls == ["openrouter"]


def test_chat_reply_comes_from_the_fallback_provider(fake_providers, monkeypatch):
    fake_providers.behaviour["openrouter"] = ProviderError("OpenRouter is down")
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda role, content: None,
    ))

    resp = TestClient(create_app(), base_url="http://127.0.0.1:8000").post(
        "/api/v1/chat", json={"message": "tell me a joke", "provider": "openrouter"}
    )

    assert resp.status_code == 200
    assert resp.json()["provider"] == "openai"
    assert resp.json()["response"] == "reply from openai"


@pytest.mark.parametrize("message, quick", [
    ("hi friday", True),
    ("what's the capital of australia", True),
    ("explain how black holes form", False),
    ("write a python script to rename files", False),
    ("word " * 16, False),
])
def test_simple_messages_are_quick_chat(monkeypatch, message, quick):
    monkeypatch.setattr(config, "ACTIVE_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "QUICK_CHAT_LOCAL", True)
    assert failover.is_quick_chat(message, "openrouter") == quick


def test_quick_chat_skipped_when_off_or_answering_from_context(monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_PROVIDER", "openrouter")
    assert not failover.is_quick_chat("hi", "openrouter")  # QUICK_CHAT_LOCAL off
    monkeypatch.setattr(config, "QUICK_CHAT_LOCAL", True)
    assert not failover.is_quick_chat("hi", "openrouter", has_context=True)
    assert not failover.is_quick_chat("hi", "anthropic")  # a provider picked for this request


def quick(provider="openrouter"):
    return asyncio.run(complete_with_failover(provider, [Message("user", "hi")], "", 100, prefer_local=True))


def test_quick_chat_tries_the_local_model_first_then_the_rest(fake_providers):
    assert quick().provider == "ollama"
    fake_providers.behaviour["ollama"] = ProviderError("Cannot connect to Ollama")  # not running
    assert quick().provider == "openrouter"
    assert fake_providers.calls == ["ollama", "ollama", "openrouter"]  # never tried twice in one request


def test_quick_chat_offline_is_the_local_model_only(fake_providers, monkeypatch):
    monkeypatch.setattr(failover.network, "online", False)
    fake_providers.behaviour["ollama"] = ProviderError("not running")
    with pytest.raises(ProviderError):
        quick()
    assert fake_providers.calls == ["ollama"]


def test_chat_sends_quick_messages_local_and_the_rest_to_the_main_model(fake_providers, monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "QUICK_CHAT_LOCAL", True)
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda role, content: None,
    ))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    assert client.post("/api/v1/chat", json={"message": "how are you"}).json()["provider"] == "ollama"
    assert client.post("/api/v1/chat", json={"message": "explain how black holes form"}).json()["provider"] == "openrouter"


def test_openrouter_moves_to_the_next_model_when_one_is_busy(monkeypatch):
    from providers.openrouter.client import OpenRouterProvider
    monkeypatch.setattr(config, "OPENROUTER_BACKUP_MODELS", ["busy:free", "good:free"])
    provider = OpenRouterProvider(model="down:free")
    tried = []

    async def fake(model, *args):
        tried.append(model)
        if model != "good:free":
            raise ProviderError("OpenRouter returned no answer: rate-limited upstream")
        return SimpleNamespace(model=model)

    monkeypatch.setattr(provider, "_complete_with", fake)
    assert asyncio.run(provider.complete([Message(role="user", content="hi")])).model == "good:free"
    assert tried == ["down:free", "busy:free", "good:free"]

    async def bad_key(model, *args):
        tried.append(model)
        raise ProviderError("OpenRouter API key is invalid or missing.")

    tried.clear()
    monkeypatch.setattr(provider, "_complete_with", bad_key)
    with pytest.raises(ProviderError):
        asyncio.run(provider.complete([Message(role="user", content="hi")]))
    assert tried == ["down:free"]  # a bad key isn't retried on every model


def test_typed_replies_are_spoken_only_when_asked(fake_providers, monkeypatch):
    spoken = []
    monkeypatch.setattr(chat, "_speak_in_background", lambda text, cache=False: spoken.append(text))
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda role, content: None,
    ))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    client.post("/api/v1/chat", json={"message": "tell me a joke"})
    assert spoken == []
    client.post("/api/v1/chat", json={"message": "tell me a joke", "speak": True})
    assert spoken == ["reply from openrouter"]
