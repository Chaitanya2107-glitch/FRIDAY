import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from interfaces.api.routes import chat, voice
from services.automation import intent
from services.automation.command_words import split_steps
from services.automation.results import ActionResult


@pytest.fixture
def local(monkeypatch):
    actions = []
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 10, 15, 21, 5)
    monkeypatch.setattr(intent, "datetime", Clock)
    monkeypatch.setattr(intent.media, "has_player", lambda: False)
    def execute(action, confirmed=False):
        actions.append(action)
        return ActionResult(True, action["action"])
    async def forbidden(*a, **kw):
        pytest.fail("A recognized local batch called the AI")
    monkeypatch.setattr(intent, "_execute", execute)
    monkeypatch.setattr(intent, "_classify_with_ai", forbidden)
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    intent.cancel_pending_confirmation()
    return actions


def run(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


@pytest.mark.parametrize("text", [
    "whats the date and time", "what's the time and date?", "tell me the current date & time",
    "Friday, what is the date and the time right now?", "date, day and time",
])
def test_combined_clock_question_uses_the_laptop_clock(local, text):
    result = run(text)
    assert result and result.success
    assert "October 15, 2026" in result.message and "9:05 PM" in result.message
    assert not result.repeatable and not local


@pytest.mark.parametrize("assist_only", [True, False])
@pytest.mark.parametrize("text", [
    "mute and open chrome", "mute, then open chrome", "mute; open chrome",
    "mute and also open chrome", "please mute, open chrome and take a screenshot",
])
def test_local_batches_run_in_order_without_ai(local, monkeypatch, text, assist_only):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    result = run(text)
    assert result.success
    assert [a["action"] for a in local] == (["set_mute", "open_app", "take_screenshot"]
        if "screenshot" in text else ["set_mute", "open_app"])


def test_batch_can_mix_clock_questions_with_actions(local):
    result = run("what's the date and mute and open chrome")
    assert result.success and "October 15, 2026" in result.message
    assert [a["action"] for a in local] == ["set_mute", "open_app"]
    assert not result.repeatable


def test_repeated_open_verb_can_be_omitted(local):
    result = run("open chrome and notepad")
    assert result.success
    assert [(a["action"], a["app_name"]) for a in local] == [
        ("open_app", "chrome"), ("open_app", "notepad")]


@pytest.mark.parametrize("text", [
    "mute and set volume to bananas", "set volume to 20 and fly to the moon",
    "open chrome and dance for me",
])
def test_an_unrecognized_step_prevents_partial_execution(local, monkeypatch, text):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    result = run(text)
    assert result and not result.success
    assert local == []


@pytest.mark.parametrize("text, action, field, value", [
    ("search cats and dogs", "search_chrome", "query", "cats and dogs"),
    ('search "mute and open chrome"', "search_chrome", "query", '"mute and open chrome"'),
    ("copy salt and pepper to clipboard", "write_clipboard", "text", "salt and pepper"),
    ("type mute and open chrome", "type_text", "text", "mute and open chrome"),
    ("remind me in 5 minutes to open chrome and close spotify", "set_reminder", "message",
     "remind me in 5 minutes to open chrome and close spotify"),
])
def test_payload_conjunctions_stay_in_one_command(local, text, action, field, value):
    assert run(text).success
    assert len(local) == 1 and local[0]["action"] == action and local[0][field] == value


def test_splitter_preserves_quoted_separators():
    assert split_steps('mute and search "cats, dogs and birds"') == [
        "mute", 'search "cats, dogs and birds"']


def test_batch_pauses_at_confirmation_without_overwriting_it(local, monkeypatch):
    def execute(action, confirmed=False):
        local.append(action)
        if action["action"] == "organise_folder":
            return intent._ask_first(action, "Organise Downloads?")
        return ActionResult(True, "Done.")
    monkeypatch.setattr(intent, "_execute", execute)
    result = run("mute and organise downloads and open chrome")
    assert [a["action"] for a in local] == ["set_mute", "organise_folder"]
    assert intent.is_awaiting_confirmation()
    assert "Organise Downloads?" in result.message and "remaining" in result.message.lower()
    run("yes")
    assert local[-1]["action"] == "organise_folder"
    intent.cancel_pending_confirmation()


@pytest.mark.parametrize("assist_only", [True, False])
def test_system_endpoint_answers_date_and_time(local, monkeypatch, assist_only):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", assist_only)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    response = client.post("/api/v1/system", json={"command": "whats the date and time", "speak": False})
    assert response.status_code == 200
    assert response.json()["success"]
    assert "9:05 PM" in response.json()["result"] and "October 15" in response.json()["result"]


def test_chat_and_voice_answer_combined_clock_questions_locally(local, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    response = client.post("/api/v1/chat", json={"message": "whats the date and time"})
    assert response.status_code == 200 and "9:05 PM" in response.json()["response"]
    result = asyncio.run(voice._reply("whats the date and time", voice.VoiceRequest(speak=False)))
    assert "9:05 PM" in result.response and "October 15" in result.response
