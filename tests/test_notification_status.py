"""Owner-visible decisions and recoverable reminder controls."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from interfaces.api.routes import chat, voice
from services.automation.intent import remote_request
from services.mind.cognition import cognition
from services.reminders import service


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", False)
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", False)
    store = service.ReminderService(str(tmp_path / "reminders.db"))
    monkeypatch.setattr(service.reminders, "db_path", store.db_path)
    memory = SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *args: None)
    monkeypatch.setattr(chat, "_memory", memory)
    monkeypatch.setattr(voice, "_memory", memory)
    return store


def test_status_api_reads_existing_state_without_migrating_reminders(state):
    with sqlite3.connect(state.db_path) as conn:
        before = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.get("/api/v1/mind/notifications")
    assert result.status_code == 200
    assert result.json()["review_enabled"] is True
    assert result.json()["reminders"] == []
    with sqlite3.connect(state.db_path) as conn:
        after = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    assert before == after
    assert client.get("/api/v1/mind/notifications", headers={"Origin": "https://example.com"}).status_code == 403


@pytest.mark.parametrize("interface", ["chat", "voice"])
def test_owner_can_explain_brain_decisions_without_model(state, monkeypatch, interface):
    cognition.record("notification_decision", "reminders", json.dumps({"action": "suppress",
        "reason": "A current owner fact cancels this class.", "evidence": ["dated:schedule:1"]}), status="suppressed")

    async def forbidden(*args, **kwargs):
        pytest.fail("Introspection invoked a model or search")

    route = chat if interface == "chat" else voice
    for name in ("build_file_context", "build_search_context", "complete_with_failover"):
        monkeypatch.setattr(route, name, forbidden)
    if interface == "chat":
        result = asyncio.run(chat.chat(chat.ChatRequest(message="why did you not send that notification")))
    else:
        result = asyncio.run(voice._reply("why did you not send that notification", voice.VoiceRequest(speak=False)))
    assert result.action_success
    assert "current owner fact" in result.response
    assert "dated:schedule:1" in result.response


def test_private_notification_status_cannot_be_read_from_other_channel(state):
    cognition.record("notification_decision", "reminders", json.dumps({"reason": "SENTINEL_LOCAL_REASON"}),
                     status="deferred")
    token = remote_request.set(True)
    try:
        result = asyncio.run(chat.chat(chat.ChatRequest(message="notification status")))
    finally:
        remote_request.reset(token)
    assert result.action_success is False
    assert "SENTINEL_LOCAL_REASON" not in result.response


def test_retry_command_queues_a_fresh_review_without_sending(state, monkeypatch):
    from services.reminders import delivery_state
    monkeypatch.setattr(delivery_state, "MAX_ATTEMPTS", 1)
    calls = []
    monkeypatch.setattr(service, "show_toast", lambda *args, **kwargs: calls.append(args) or False)
    state.add_from_message("remind me in 1 minute to stretch", datetime.now() - timedelta(minutes=2))
    asyncio.run(service.deliver_due(state))
    assert state.delivery_status()[0]["status"] == "failed"

    result = asyncio.run(chat.chat(chat.ChatRequest(message="retry failed reminders")))

    assert result.action_success
    assert "fresh brain review" in result.response
    assert len(calls) == 1
    row = state.delivery_status()[0]
    assert row["status"] == "retry" and row["attempts"] == 0
    assert len(state.pending()) == 1
