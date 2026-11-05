import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat, voice
from services.automation.intent import remote_request
from services.browser.service import Reply, automation


@pytest.fixture
def isolated_route(monkeypatch):
    async def no_async(*args, **kwargs):
        pytest.fail("Automation reached ordinary history/search/learning")
    def no_sync(*args, **kwargs):
        pytest.fail("Automation touched history or TTS")
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=no_sync, save_message=no_sync))
    for name in ("try_system_action", "build_file_context", "build_search_context", "complete_with_failover"):
        monkeypatch.setattr(chat, name, no_async)
    monkeypatch.setattr(chat, "_speak_in_background", no_sync)
    return TestClient(create_app(), base_url="http://127.0.0.1:8000")


def test_typed_tasks_route_before_memory_search_and_language(isolated_route, monkeypatch):
    calls = []
    async def handle(message, provider, **kwargs):
        calls.append(message)
        return Reply(True, "Review this exact step", True)
    monkeypatch.setattr(automation, "handle", handle)
    response = isolated_route.post("/api/v1/chat", json={"message": "browser task read example.com", "speak": True})
    assert response.status_code == 200 and response.json()["model"] == "automation_task"
    assert response.json()["awaiting_reply"] and response.json()["keyboard"] == []
    assert calls == ["browser task read example.com"]


def test_other_website_cannot_start_tasks(isolated_route):
    response = isolated_route.post("/api/v1/chat", json={"message": "research robots"},
                                  headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_remote_service_rejection_preserves_local_confirmation(isolated_route, monkeypatch):
    monkeypatch.setattr(chat, "cancel_pending_confirmation", lambda: pytest.fail("Remote request cancelled owner approval"))
    async def scenario():
        token = remote_request.set(True)
        try:
            for message in ("research robots", "browser yes", "browser stop", "research report"):
                response = await chat.chat(chat.ChatRequest(message=message))
                assert response.action_success is False
        finally:
            remote_request.reset(token)
    asyncio.run(scenario())


def test_voice_uses_the_same_handler_without_normal_chat(isolated_route, monkeypatch):
    async def handle(message, provider, **kwargs):
        assert message == "research headless robot control"
        return Reply(True, "Started research")
    monkeypatch.setattr(automation, "handle", handle)
    response = asyncio.run(voice._reply("research headless robot control", voice.VoiceRequest(speak=False)))
    assert response.model == "automation_task" and response.response == "Started research"
    assert response.keyboard == []
