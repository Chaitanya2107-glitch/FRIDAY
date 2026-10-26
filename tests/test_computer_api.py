import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat
from services.automation.intent import remote_request
from services.computer.agent import Reply


@pytest.fixture
def client(monkeypatch):
    async def must_not_call(*args, **kwargs):
        pytest.fail("computer commands reached ordinary chat, search or learning")

    def must_not_read_or_save(*args, **kwargs):
        pytest.fail("computer commands accessed chat history or speech")

    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=must_not_read_or_save,
                                                       save_message=must_not_read_or_save))
    for name in ("try_system_action", "build_file_context", "build_search_context", "complete_with_failover"):
        monkeypatch.setattr(chat, name, must_not_call)
    monkeypatch.setattr(chat, "_speak_in_background", must_not_read_or_save)
    return TestClient(create_app(), base_url="http://127.0.0.1:8000")


def test_computer_route_skips_history_search_learning_and_speech(client, monkeypatch):
    calls = []

    async def handle(message, provider):
        calls.append((message, provider))
        return Reply(True, "Review the step", True, "anthropic", 25)

    monkeypatch.setattr(chat.computer_agent, "handle", handle)
    response = client.post("/api/v1/chat", json={"message": "\\c open the menu", "speak": True})
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "computer_agent" and data["awaiting_reply"]
    assert data["provider"] == "anthropic" and data["tokens_used"] == 25
    assert data["keyboard"] == [] and len(calls) == 1


def test_telegram_cannot_start_or_approve_computer_tasks(monkeypatch):
    async def must_not_call(*args):
        pytest.fail("a remote request reached computer control")

    monkeypatch.setattr(chat.computer_agent, "handle", must_not_call)

    async def scenario():
        token = remote_request.set(True)
        try:
            for message in ("\\c open the menu", "\\c yes", "\\c stop"):
                response = await chat.chat(chat.ChatRequest(message=message))
                assert response.action_success is False
        finally:
            remote_request.reset(token)

    asyncio.run(scenario())


def test_other_website_cannot_start_computer_agent(client):
    response = client.post("/api/v1/chat", json={"message": "\\c open the menu"},
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
