import json
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import voice as voice_route
from services.automation import intent
from services.voice import wake
from services.voice.recorder import CHUNK_SAMPLES
from services.voice.wake import Wake, WakeListener, WakeTimeout, match_wake

LOCAL = "http://127.0.0.1:8000"


# ── Wake phrases ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("heard, command", [
    ("Hey Friday, work mode.", "work mode."),
    ("Hey, Friday. What's the weather?", "What's the weather?"),
    ("hey friday", ""),
    ("Okay Friday brief me", "brief me"),
    ("Hi Fri day, mute", "mute"),
    ("Hey Friday!", ""),
    ("K Friday, work mode.", "work mode."),  # Parakeet hearing a quick "hey"
    ("See you on Friday.", None),        # the wake phrase has to come first
    ("Friday night we're going out", None),
    ("Hey Fridays are the best", None),
    ("they friday", None),
    ("", None),
])
def test_match_wake(heard, command):
    assert match_wake(heard) == command


# ── The listening loop ────────────────────────────────────────────────────────

SPEECH, QUIET = np.full(CHUNK_SAMPLES, 0.5, dtype=np.float32), np.zeros(CHUNK_SAMPLES, dtype=np.float32)


@pytest.fixture
def mic(monkeypatch):
    """The fake mic plays `script`: a list of (chunk, times) — then stays quiet. Speech = non-zero samples."""
    def speech_segments(audio):
        loud = np.flatnonzero(audio)
        return [(int(loud[0]), int(loud[-1]) + 1)] if len(loud) else []
    monkeypatch.setattr(wake, "_speech_segments", speech_segments)

    state = SimpleNamespace(script=[], heard=[], reads=0)

    def read_chunk():
        state.reads += 1
        for step in state.script:
            if step[1]:
                step[1] -= 1
                return step[0]
        return QUIET
    state.read_chunk = read_chunk
    return state


def listen(mic, texts, timeout=60, paused=lambda: False, cancelled=lambda: False, saying=list, interrupt=None):
    replies = iter(texts)

    def transcribe(audio):
        mic.heard.append(len(audio) // CHUNK_SAMPLES)
        return next(replies)
    result = WakeListener(transcribe)._listen(
        mic.read_chunk, cancelled, timeout, paused, saying, interrupt or (lambda: None),
    )
    return result.command if result and not result.interrupted else result


def test_utterances_are_transcribed_after_they_end_and_only_a_wake_phrase_returns(mic):
    mic.script = [[QUIET, 6], [SPEECH, 12], [QUIET, 12], [SPEECH, 15]]
    assert listen(mic, ["what's for dinner", "Hey Friday, work mode"]) == "work mode"
    assert len(mic.heard) == 2  # two utterances, each transcribed once


def test_command_after_a_breath_is_heard_without_reopening_the_mic(mic):
    mic.script = [[QUIET, 3], [SPEECH, 8], [QUIET, 9], [SPEECH, 12]]  # "Hey Friday" … "open Notepad"
    assert listen(mic, ["Hey Friday.", "Open Notepad."]) == "Open Notepad."


def test_bare_wake_phrase_then_silence_asks_for_the_command(mic):
    mic.script = [[QUIET, 3], [SPEECH, 8]]
    assert listen(mic, ["Hey Friday."]) == ""
    assert len(mic.heard) == 1


def test_switching_off_stops_the_wait(mic):
    calls = []
    assert listen(mic, [], cancelled=lambda: calls.append(1) or len(calls) > 5) is None


def test_gives_up_after_the_auto_off_time(mic):
    with pytest.raises(WakeTimeout):
        listen(mic, [], timeout=-1)


def test_audio_is_ignored_while_the_voice_hotkey_is_listening(mic):
    mic.script = [[SPEECH, 20], [QUIET, 12], [SPEECH, 12]]
    hotkey_listening = lambda: mic.reads <= 30
    assert listen(mic, ["hey friday what time is it"], paused=hotkey_listening) == "what time is it"
    assert len(mic.heard) == 1


# ── Interrupting FRIDAY ───────────────────────────────────────────────────────

@pytest.mark.parametrize("heard, saying, command", [
    ("the forecast for today is sunny hey friday stop", [], "stop"),
    ("rain later on. Hey, Friday, what time is it", [], "what time is it"),
    ("it's going to be a warm day and", [], None),
    ("hi I'm Friday, hey friday, how can I help", ["Hi! I'm Friday — hey Friday, how can I help?"], None),
    ("see you on friday", [], None),
])
def test_wake_phrase_said_over_friday(heard, saying, command):
    assert match_wake(heard, anywhere=True, friday_is_saying=saying) == command


def test_hey_friday_over_friday_stops_it_and_takes_the_command(mic):
    stopped = []
    mic.script = [[SPEECH, 40], [QUIET, 12]]
    friday_talking = lambda: [] if stopped else ["The weather today is sunny with a light breeze."]
    result = listen(mic, [
        "The weather today is",                                    # a check: only FRIDAY so far
        "is sunny with a light hey friday what's",                 # the user cuts in
        "sunny with a light breeze hey friday what's the time",    # the whole utterance, once they finish
    ], saying=friday_talking, interrupt=lambda: stopped.append(mic.reads))
    assert result == Wake("what's the time", interrupted=True)
    assert stopped == [20]  # stopped as soon as it heard "hey friday", not at the end


def test_friday_saying_its_own_name_does_not_interrupt_it(mic):
    mic.script = [[SPEECH, 30]]
    saying = ["Hey Friday is how you wake me up."]
    stopped = []
    result = listen(mic, ["hey friday is how you wake"] * 3, cancelled=lambda: mic.reads > 30,
                    saying=lambda: saying, interrupt=lambda: stopped.append(1))
    assert result is None and stopped == []


def test_long_speech_is_cut_into_pieces(mic):
    mic.script = [[SPEECH, 200]]
    assert listen(mic, ["blah " * 50, "hey friday mute"]) == "mute"
    assert max(mic.heard) <= wake.MAX_UTTERANCE_SECONDS * 10 + 3


def test_only_one_wait_at_a_time(monkeypatch):
    monkeypatch.setattr(wake, "TAKEOVER_SECONDS", 0.01)
    listener = WakeListener(lambda audio: "")
    listener._busy.acquire()  # another wait has the mic
    with pytest.raises(wake.FridayError) as error:
        listener.wait(lambda: True, 1, lambda: False)
    assert error.value.status_code == 409


# ── The endpoint ──────────────────────────────────────────────────────────────

@pytest.fixture
def wake_api(monkeypatch):
    state = SimpleNamespace(command="set volume to 40", spoken=[], recorded=0, sessions=[])

    def fake_wait(cancelled, timeout_seconds, paused, friday_speech, interrupt):
        state.sessions.append(cancelled())
        if isinstance(state.command, Exception):
            raise state.command
        if cancelled():
            return None
        return state.command if isinstance(state.command, Wake) else Wake(state.command, False)
    monkeypatch.setattr(voice_route.wake_listener, "wait", fake_wait)
    monkeypatch.setattr(voice_route.recorder, "record", lambda: setattr(state, "recorded", state.recorded + 1) or b"")
    monkeypatch.setattr(voice_route.stt, "transcribe", lambda audio, log=True: "take a screenshot")
    monkeypatch.setattr(voice_route, "_speak_in_background", lambda text, cache=False: state.spoken.append(text))
    monkeypatch.setattr(voice_route, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda role, content: None,
    ))
    monkeypatch.setattr(intent.system, "set_volume", lambda level: f"Volume set to {level}%.")
    monkeypatch.setattr(intent.system, "take_screenshot", lambda: "Screenshot saved.")
    state.client = TestClient(create_app(), base_url=LOCAL)
    return state


def test_command_after_the_wake_phrase_runs_straight_away(wake_api):
    body = wake_api.client.post("/api/v1/voice/wake", json={"session": "a"}).json()
    assert (body["transcription"], body["response"]) == ("set volume to 40", "Volume set to 40%.")
    assert wake_api.recorded == 0
    assert wake_api.spoken == ["Volume set to 40%."]


def test_bare_wake_phrase_listens_for_the_command(wake_api):
    wake_api.command = ""
    body = wake_api.client.post("/api/v1/voice/wake", json={"session": "a"}).json()
    assert wake_api.recorded == 1
    assert body["response"] == "Screenshot saved."


def test_stopping_a_session_ends_its_wait_even_if_it_starts_later(wake_api):
    assert wake_api.client.post("/api/v1/voice/wake/stop", json={"session": "b"}).status_code == 200
    resp = wake_api.client.post("/api/v1/voice/wake", json={"session": "b"})
    assert resp.status_code == 409
    assert wake_api.client.post("/api/v1/voice/wake", json={"session": "c"}).status_code == 200  # a new switch-on


def test_auto_off_is_a_408(wake_api):
    wake_api.command = WakeTimeout("Nobody said it.", status_code=408)
    assert wake_api.client.post("/api/v1/voice/wake", json={"session": "d"}).status_code == 408


def test_a_session_id_is_required(wake_api):
    assert wake_api.client.post("/api/v1/voice/wake", json={}).status_code == 422


def test_hey_friday_stop_over_friday_just_goes_quiet(wake_api):
    wake_api.command = Wake("stop.", interrupted=True)
    body = wake_api.client.post("/api/v1/voice/wake", json={"session": "e"}).json()
    assert (body["response"], body["action"]) == ("Okay.", "system")
    assert wake_api.spoken == [] and wake_api.recorded == 0


def test_a_new_question_over_friday_is_answered(wake_api):
    wake_api.command = Wake("set volume to 40", interrupted=True)
    body = wake_api.client.post("/api/v1/voice/wake", json={"session": "f"}).json()
    assert body["response"] == "Volume set to 40%."


def test_stop_when_friday_was_not_talking_is_a_normal_command(wake_api, monkeypatch):
    seen = []

    async def commands(message, provider_name):
        seen.append(message)
        return intent.ActionResult(True, "Paused.")
    monkeypatch.setattr(voice_route, "try_system_action", commands)
    wake_api.command = Wake("stop", interrupted=False)
    body = wake_api.client.post("/api/v1/voice/wake", json={"session": "g"}).json()
    assert seen == ["stop"] and body["response"] == "Paused."


def test_false_wakes_are_logged_and_counted(wake_api, monkeypatch):
    wake_api.client.post("/api/v1/voice/wake", json={"session": "h"})  # a real command
    wake_api.command = "I wasn't talking to you."
    body = wake_api.client.post("/api/v1/voice/wake", json={"session": "h"}).json()
    assert body["response"] == "Sorry — my mistake." and wake_api.spoken == ["Volume set to 40%."]
    wake_api.command = ""  # woke, then nothing was said
    monkeypatch.setattr(voice_route.stt, "transcribe", lambda audio, log=True: "")
    assert wake_api.client.post("/api/v1/voice/wake", json={"session": "h"}).status_code != 200
    assert [e["mistake"] for e in map(json.loads, wake.LOG_PATH.read_text().splitlines())] == [False, True, True]
    assert "woke me 3 times; 2 were mistakes (67%)" in wake.stats()
