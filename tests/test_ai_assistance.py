import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from core.errors import ProviderError
from interfaces.api.app import create_app
from interfaces.api.routes import chat, voice
from providers import failover
from providers.base_provider import Message, ProviderResponse


@pytest.fixture(autouse=True)
def assist_only(monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", False)
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", False)


def test_no_models_needed_for_chat_voice_or_clock(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Core replies attempted a model call")
    monkeypatch.setattr(failover, "complete_with_failover", forbidden)
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda *args: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    for message, expected in [("hello", "Boss"), ("what time is it", "It's"),
                              ("make something up", "commands")]:
        result = client.post("/api/v1/chat", json={"message": message})
        assert result.status_code == 200
        assert expected in result.json()["response"]
    result = asyncio.run(voice._reply("hello", voice.VoiceRequest(speak=False)))
    assert "Boss" in result.response


def test_general_generation_and_direct_routing_are_blocked():
    from providers.registry import get_provider
    with pytest.raises(ProviderError):
        asyncio.run(failover.complete_with_failover("openrouter", [Message("user", "hi")], "", 100))
    with pytest.raises(ProviderError):
        get_provider("ollama")


def test_polishing_failure_retains_original(monkeypatch):
    from services.mind import wording
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    async def down(*args, **kwargs):
        raise ProviderError("offline")
    monkeypatch.setattr(failover, "complete_with_failover", down)
    assert asyncio.run(wording.enhance("Opening Chrome, Boss.")) == "Opening Chrome, Boss."


def test_polishing_rejects_changed_numbers_or_failure(monkeypatch):
    from services.mind import wording
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    async def unfaithful(*args, **kwargs):
        return ProviderResponse(content="Volume is 90%.", provider="ollama", model="local")
    monkeypatch.setattr(failover, "complete_with_failover", unfaithful)
    assert asyncio.run(wording.enhance("Volume is 20%.")) == "Volume is 20%."


def test_unknown_knowledge_is_cached_and_used_without_models(monkeypatch):
    from services.mind import replies
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", True)
    async def lookup(*args, **kwargs):
        assert kwargs["purpose"] == "knowledge"
        return ProviderResponse(content='{"known":true,"what":"A code editor.","category":"coding"}',
                                provider="ollama", model="local")
    monkeypatch.setattr(failover, "complete_with_failover", lookup)
    assert "A code editor" in asyncio.run(replies.answer("what is Zed")).content
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", False)
    assert "A code editor" in asyncio.run(replies.answer("what is Zed")).content


def test_startup_does_not_require_cloud_key(monkeypatch):
    monkeypatch.setattr(config, "ACTIVE_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    assert not any("OPENROUTER_API_KEY is missing" in e for e in config.validate())


def test_assistance_uses_openrouter_then_ollama_and_skips_cloud_offline(monkeypatch):
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    calls = []
    def provider(name, **kwargs):
        async def complete(**params):
            calls.append(name)
            if name == "openrouter":
                raise ProviderError("unavailable")
            return ProviderResponse(content="Boss, opening Chrome.", provider=name, model="local")
        return SimpleNamespace(complete=complete)
    monkeypatch.setattr(failover, "get_provider", provider)
    from services.mind.wording import enhance
    assert asyncio.run(enhance("Opening Chrome, Boss.")).startswith("Boss")
    assert calls == ["openrouter", "ollama"]
    calls.clear()
    monkeypatch.setattr(failover.network, "online", False)
    asyncio.run(enhance("Opening Chrome, Boss."))
    assert calls == ["ollama"]


def test_system_endpoint_and_multiple_commands_use_local_matchers(monkeypatch):
    from services.automation import intent
    monkeypatch.setattr(intent.system, "open_app", lambda name: "Opening " + name)
    monkeypatch.setattr(intent.system, "set_mute", lambda mute: "Muted.")
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/system", json={"command": "what time is it", "speak": False})
    assert result.status_code == 200
    assert "It's" in result.json()["result"]
    result = asyncio.run(intent.try_system_action("mute and open chrome", "openrouter"))
    assert result.success
    assert "Opening" in result.message


def test_local_watchers_do_not_skip_the_notification_brain(monkeypatch):
    from datetime import datetime
    from services.mind import notifications
    calls = []
    async def decide(*args):
        calls.append(args)
        return [notifications.Choice(id="0", send=False, reason="Current context does not justify this notice.")]
    monkeypatch.setattr(notifications, "_reason", decide)
    choices = asyncio.run(notifications.consider([notifications.Candidate("Battery is low.")], datetime.now()))
    assert calls and not choices["0"][0]


def test_ollama_starts_once_stops_idle_and_restarts(monkeypatch):
    from providers.ollama import runtime as module
    server = module.OllamaRuntime()
    starts, stops = [], []
    monkeypatch.setattr(module.shutil, "which", lambda name: "ollama")
    def spawn(args, **kwargs):
        starts.append((args, kwargs))
        return SimpleNamespace(pid=123, poll=lambda: None)
    async def ready(url):
        return server.process is not None
    async def stop():
        stops.append(server.process)
        server.process = None
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(server, "ready", ready)
    monkeypatch.setattr(server, "stop_owned", stop)
    monkeypatch.setattr(config, "OLLAMA_IDLE_SECONDS", 1)
    async def run():
        async with server.use("http://localhost:11434"):
            async with server.use("http://localhost:11434"):
                server.last_used = 0
                await server.check_idle()
                assert not stops  # in-flight generations are protected
        assert len(starts) == 1
        server.last_used = 0
        await server.check_idle()
        assert len(stops) == 1
        async with server.use("http://localhost:11434"):
            pass
        assert len(starts) == 2
        await server.close()
    asyncio.run(run())
    assert starts[0][0] == ["ollama", "serve"]
    if module.os.name == "nt":
        assert starts[0][1]["creationflags"] == module.subprocess.CREATE_NO_WINDOW


def test_existing_ollama_and_remote_endpoints_are_never_launched_or_killed(monkeypatch):
    from providers.ollama import runtime as module
    server = module.OllamaRuntime()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Unexpected process launch"))
    async def ready(url):
        return True
    monkeypatch.setattr(server, "ready", ready)
    async def run():
        async with server.use("http://localhost:11434"):
            pass
        assert server.process is None
        await server.close()
        async def unavailable(url):
            return False
        monkeypatch.setattr(server, "ready", unavailable)
        with pytest.raises(ProviderError):
            async with server.use("http://192.0.2.1:11434"):
                pass
    asyncio.run(run())


def test_model_tools_are_not_allowed_even_with_a_wording_purpose(monkeypatch):
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    with pytest.raises(ProviderError):
        asyncio.run(failover.complete_with_failover("ollama", [Message("user", "hi")], "", 100,
                                                  purpose="wording", tools=[object()]))


def test_stalled_cloud_provider_does_not_prevent_ollama_fallback(monkeypatch):
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    def provider(name, **kwargs):
        async def complete(**params):
            if name == "openrouter":
                await asyncio.Event().wait()
            return ProviderResponse(content="Opening Chrome.", provider=name, model="local")
        return SimpleNamespace(complete=complete)
    monkeypatch.setattr(failover, "get_provider", provider)
    result = asyncio.run(failover.complete_with_failover("openrouter", [Message("user", "Opening Chrome.")],
                         "Polish only", 100, purpose="wording", attempt_timeout=0.01))
    assert result.provider == "ollama"


def test_offline_search_returns_remark_without_network_call(monkeypatch):
    from services.search import web_search
    monkeypatch.setattr(failover.network, "online", False)
    monkeypatch.setattr(web_search, "_search", lambda query: pytest.fail("Offline search reached network"))
    result = asyncio.run(web_search.build_search_context("look up Zed"))
    assert "internet connection" in result


def test_unavailable_ollama_is_optional_and_retries_are_cooled_down(monkeypatch):
    from providers.ollama import runtime as module
    server = module.OllamaRuntime()
    probes = []
    async def ready(url):
        probes.append(url)
        return False
    monkeypatch.setattr(server, "ready", ready)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module.Path, "is_file", lambda path: False)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Missing Ollama was launched"))
    async def run():
        for _ in range(2):
            with pytest.raises(ProviderError):
                async with server.use("http://localhost:11434"):
                    pass
        assert len(probes) == 1
        assert server.active == 0
        await server.close()
    asyncio.run(run())
