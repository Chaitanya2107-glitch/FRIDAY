import asyncio
import json
from datetime import datetime, timedelta

import pytest

from core.config import config
from interfaces.api.routes import chat, system, voice
from providers.base_provider import ProviderResponse
from services.automation import intent, personality
from services.mind import character, emotion, humour, state
from services.mind.reviews import reviews
from services.proactive import deadlines


def typed(text, *, speak=True):
    return asyncio.run(chat.chat(chat.ChatRequest(message=text, speak=speak)))


def test_stress_before_exam_preserves_facts_and_command_authority(monkeypatch):
    now = datetime.now()
    due = now + timedelta(minutes=20)
    deadlines._save([{"what": "Applied Physics exam", "due": due.isoformat(), "alerted": []}])
    emotion.Observer().sample()
    assert state.snapshot()["emotion"]["drives"]["wanting_to_help"] > emotion.BASELINE["wanting_to_help"]
    spoken = []
    monkeypatch.setattr(chat, "_speak_in_background", lambda text, **kwargs: spoken.append(text))
    monkeypatch.setattr(humour, "should_joke", lambda *args, **kwargs: True)
    personality.path.write_text('{"off": false}', encoding="utf-8")
    monkeypatch.setattr(intent.system, "open_app", lambda app: f"Opening {app}.")
    before = state.snapshot()["life_state"]

    reply = typed("I'm stressed before my exam.")
    assert len(reply.response.split()) <= 8 and "!" not in reply.response
    assert state.snapshot()["emotion"]["owner_stressed"]
    for key in ("can_review", "can_initiate", "interruption_blocks"):
        assert state.snapshot()["life_state"][key] == before[key]
    exam = typed("When is my Applied Physics exam deadline?")
    assert exam.action_success and "Applied Physics exam" in exam.response
    assert due.strftime("%Y-%m-%dT%H:%M") in exam.response and "owner reported" in exam.response
    assert len(exam.response.split()) <= 12 and "!" not in exam.response
    joke = typed("tell me a joke")
    assert "jokes" in joke.response and "folder" not in joke.response
    assert typed("open notepad").response == "Opening notepad."
    assert spoken[-4:] == [reply.response, exam.response, joke.response, "Opening notepad."]


def test_character_drift_uses_the_learned_dial_and_respects_the_rolling_limit():
    now = datetime(2026, 11, 10, 10)
    first = state.snapshot(now)
    for index in range(20):
        at = now + timedelta(minutes=index)
        humour.told("chill", "everyday", now=at.timestamp())
        humour.hear("ha ha, good one", now=at.timestamp() + 1)
        character.observe("keep it short", now=at)
    actual = character.snapshot(now)["traits"]
    assert humour.learned_dial() > actual["humour"] > character.DEFAULTS["humour"]
    assert actual["verbosity"] == pytest.approx(character.DEFAULTS["verbosity"] - character.WEEKLY_DRIFT)
    for name, value in actual.items():
        assert 0 <= value <= 1
        assert abs(value - character.DEFAULTS[name]) <= character.WEEKLY_DRIFT + 1e-9
    assert first["character"]["traits"] == character.DEFAULTS
    assert state.snapshot(now + timedelta(minutes=20))["character"]["traits"] == actual
    character.observe("keep it short", now=now + timedelta(days=8))
    updated = character.snapshot()["traits"]
    assert updated["verbosity"] < actual["verbosity"]
    history = json.loads(character.storage_path().read_text(encoding="utf-8"))["history"]
    assert all(row["changes"] for row in history)
    assert "ha ha" not in str(history)


def test_character_commands_use_the_local_sheet_and_keep_reset_history():
    character.observe("more detail please")
    report = typed("show your character", speak=False)
    assert report.action_success and "Tell the Boss the truth kindly" in report.response
    assert "verbosity 0.50" in report.response
    reset = typed("reset your character", speak=False)
    assert reset.action_success and character.snapshot()["traits"] == character.DEFAULTS
    history = json.loads(character.storage_path().read_text(encoding="utf-8"))["history"]
    assert [row["source"] for row in history] == ["explicit_style", "owner_reset"]
    assert history[-1]["changes"]["verbosity"] == [.5, .45]


def test_working_reply_welcomes_the_owner_once_and_never_infers_blame(monkeypatch):
    now = datetime.now()
    monkeypatch.setattr(chat, "_speak_in_background", lambda *args, **kwargs: None)
    original = emotion.snapshot(now)["warmth"]
    assert emotion.note_owner("quiet, please", now) is None
    emotion.record("long_absence", now)
    assert emotion.snapshot(now)["warmth"] >= original
    first, second = typed("hello"), typed("hello")
    assert any(phrase in first.response.lower() for phrase in ("back", "again"))
    assert not any(word in first.response.lower() for word in ("finally", "ignored", "missed", "abandoned", "about time"))
    assert not any(phrase in second.response.lower() for phrase in ("back", "again"))


def test_remote_conversation_keeps_local_return_context_private():
    from services.mind import wording

    now = datetime.now()
    emotion.record("long_absence", now)
    token = intent.remote_request.set(True)
    try:
        raw = {"kind": "greeting"}
        assert wording.render(raw, now=now) == wording.plain(raw)
    finally:
        intent.remote_request.reset(token)


def test_writer_review_previews_are_private_on_every_reply_route(monkeypatch):
    line = "A quick result, Boss. {fact}"
    with reviews.db() as conn:
        item = conn.execute(
            "INSERT INTO reviews (at,kind,channel,question,context,pattern,subject) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().timestamp(), "line", "writers_room", line, '{"provider":"ollama"}', "neutral", "command"),
        ).lastrowid
    spoken = []
    monkeypatch.setattr(chat, "_speak_in_background", lambda *args, **kwargs: spoken.append(args))
    monkeypatch.setattr(voice, "_speak_in_background", lambda *args, **kwargs: spoken.append(args))
    monkeypatch.setattr(chat._memory, "save_message", lambda *args: pytest.fail("Draft persisted to chat history"))
    via_chat = typed("review lines")
    via_voice = asyncio.run(voice._reply("review lines", voice.VoiceRequest(speak=True)))
    via_system = asyncio.run(system.system_control(system.SystemRequest(command="review lines", speak=True)))
    assert via_chat.private and not via_chat.allow_speech and line in via_chat.response
    assert via_voice.private and not via_voice.allow_speech and line in via_voice.response
    assert via_system.success and line in via_system.result
    assert not spoken
    assert typed(f"approve line {item}").action_success
    from services.mind import writers_room
    assert writers_room.approved_templates("command", "neutral")[0]["template"] == line


def test_generated_chat_remains_visible_without_raw_model_speech(monkeypatch):
    generated = "Model-only draft example."
    calls, speech = [], []

    async def model(*args, **kwargs):
        calls.append(True)
        return ProviderResponse(generated, "ollama", "test-model")

    async def no_command(*args, **kwargs):
        return None

    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", True)
    monkeypatch.setattr("services.mind.language.answer", model)
    monkeypatch.setattr(chat, "try_system_action", no_command)
    monkeypatch.setattr(chat, "_speak_in_background", lambda text, **kwargs: speech.append(text))
    reply = typed("A word about octopuses")
    if config.FRIDAY_LLM == "on":
        assert calls and reply.response == generated and not reply.allow_speech
        assert not speech
    else:
        assert not calls and generated not in reply.response and reply.allow_speech
        assert speech == [reply.response]
