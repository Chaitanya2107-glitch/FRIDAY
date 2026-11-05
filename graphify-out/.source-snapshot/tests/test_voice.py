import asyncio
import io
import sys
import time
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from interfaces.api.routes import voice as voice_route
from services.automation import intent
from services.voice import recorder as recorder_module
from services.voice import stt as stt_module
from services.voice import tts as tts_module
from services.voice.recorder import Recorder, RecorderError

SR = recorder_module.SAMPLE_RATE
CHUNK = recorder_module.CHUNK_SAMPLES
LOCAL = "http://127.0.0.1:8000"


# ── Recorder ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_mic(monkeypatch):
    """
    A microphone that never runs out, and a stand-in for the speech detector:
    set `speech = (start_s, end_s)` for when the user is talking, relative to
    the start of the recording. `on_read(n)` runs as chunk n is read.
    """
    state = SimpleNamespace(chunks_read=0, speech=None, on_read=None)

    @contextmanager
    def open_microphone():
        def read_chunk():
            state.chunks_read += 1
            if state.on_read:
                state.on_read(state.chunks_read)
            return np.zeros(CHUNK, dtype=np.float32)
        yield read_chunk

    def speech_segments(window):
        if state.speech is None:
            return []
        window_end = state.chunks_read * CHUNK
        window_start = window_end - len(window)
        start = max(int(state.speech[0] * SR), window_start)
        end = min(int(state.speech[1] * SR), window_end)
        return [(start - window_start, end - window_start)] if start < end else []

    monkeypatch.setattr(recorder_module, "_open_microphone", open_microphone)
    monkeypatch.setattr(recorder_module, "_speech_segments", speech_segments)
    monkeypatch.setattr(recorder_module, "_beep", lambda tone: None)
    return state


def seconds(audio):
    return len(audio) / SR


def test_stops_once_the_speaker_goes_quiet(fake_mic):
    fake_mic.speech = (0.5, 2.0)
    audio = Recorder().record()
    quiet_from = 2.0 + recorder_module.SILENCE_SECONDS
    assert quiet_from <= seconds(audio) <= quiet_from + 0.4


def test_keeps_listening_while_the_speaker_talks(fake_mic):
    fake_mic.speech = (0.3, 6.0)
    assert seconds(Recorder().record()) >= 6.0 + recorder_module.SILENCE_SECONDS


def test_pressing_the_hotkey_again_stops_immediately(fake_mic):
    recorder = Recorder()
    fake_mic.speech = (0.0, 999)  # still talking
    fake_mic.on_read = lambda n: n == 10 and recorder.stop()
    assert len(recorder.record()) == 10 * CHUNK


def test_gives_up_when_nothing_is_said(fake_mic):
    assert seconds(Recorder().record()) == pytest.approx(recorder_module.NO_SPEECH_SECONDS, abs=0.35)


def test_time_limit_stops_a_very_long_recording(fake_mic, monkeypatch):
    monkeypatch.setattr(recorder_module, "MAX_SECONDS", 2)
    fake_mic.speech = (0.0, 999)
    assert len(Recorder().record()) == 2 * SR


def test_second_listen_while_listening_is_refused(fake_mic):
    recorder = Recorder()

    def listen_again(n):
        if n == 1:
            with pytest.raises(RecorderError, match="already listening"):
                recorder.record()
            recorder.stop()
    fake_mic.on_read = listen_again

    recorder.record()
    assert not recorder.is_recording


def test_stop_when_not_listening_does_nothing():
    assert Recorder().stop() is False


# ── Speech-to-text ────────────────────────────────────────────────────────────

class FakeWhisperModel:
    fail_on_gpu = False
    devices = []

    def __init__(self, name, device, compute_type):
        if device == "cuda" and FakeWhisperModel.fail_on_gpu:
            raise RuntimeError("cuDNN not found")
        FakeWhisperModel.devices.append((device, compute_type))

    def transcribe(self, audio, language, beam_size=5, vad_filter=False):
        return iter([SimpleNamespace(text=" Remind me"), SimpleNamespace(text=" to stretch. ")]), None


def no_parakeet():
    raise RuntimeError("no model")


@pytest.fixture
def fake_whisper(monkeypatch):
    """Parakeet unavailable, so these exercise the Whisper fallback."""
    FakeWhisperModel.fail_on_gpu, FakeWhisperModel.devices = False, []
    monkeypatch.setattr(stt_module, "_load_parakeet", no_parakeet)
    monkeypatch.setattr("faster_whisper.WhisperModel", FakeWhisperModel)
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    return FakeWhisperModel


def test_parakeet_is_used_first(fake_whisper, monkeypatch):
    monkeypatch.setattr(stt_module, "_load_parakeet", lambda: lambda audio: " Hey Friday, work mode. ")
    speech = stt_module.SpeechToText()
    assert speech.transcribe(np.zeros(SR, dtype=np.float32)) == "Hey Friday, work mode."
    assert fake_whisper.devices == []


def test_transcribe_joins_segments_and_loads_on_gpu(fake_whisper):
    speech = stt_module.SpeechToText()
    assert speech.transcribe(np.zeros(SR, dtype=np.float32)) == "Remind me to stretch."
    assert fake_whisper.devices == [("cuda", "float16")]


def test_falls_back_to_cpu_when_the_gpu_fails(fake_whisper):
    fake_whisper.fail_on_gpu = True
    speech = stt_module.SpeechToText()
    speech.load()
    assert fake_whisper.devices == [("cpu", "int8")]


# ── Text-to-speech: streaming, cache, voices ──────────────────────────────────

class FakeCommunicate:
    """edge-tts stand-in: streams `chunks`, raises a network error at index `fail_at`, calls `on_chunk(i)`."""
    chunks = [b"a", b"b", b"c"]
    fail_at = None
    on_chunk = None
    requests = []

    @classmethod
    def reset(cls):
        cls.chunks, cls.fail_at, cls.on_chunk, cls.requests = [b"a", b"b", b"c"], None, None, []

    def __init__(self, text, voice, connect_timeout):
        FakeCommunicate.requests.append((text, voice))

    async def stream(self):
        for i, chunk in enumerate(FakeCommunicate.chunks):
            if FakeCommunicate.fail_at == i:
                raise ConnectionError("network down")
            if FakeCommunicate.on_chunk:
                FakeCommunicate.on_chunk(i)
            yield {"type": "audio", "data": chunk}


def requested_texts():
    return [text for text, _ in FakeCommunicate.requests]


@pytest.fixture
def speaker(monkeypatch):
    FakeCommunicate.reset()
    monkeypatch.setattr("edge_tts.Communicate", FakeCommunicate)
    state = SimpleNamespace(tts=tts_module.TextToSpeech(), played=[], offline=[])
    monkeypatch.setattr(state.tts, "_play", lambda chunks, generation: state.played.append(b"".join(chunks)))
    monkeypatch.setattr(state.tts, "_speak_offline", lambda text, generation: state.offline.append(text))
    return state


def test_speech_streams_straight_into_playback(speaker):
    asyncio.run(speaker.tts.speak("hello there"))
    assert speaker.played == [b"abc"]
    assert speaker.offline == []


def test_hindi_replies_use_the_hindi_voice(speaker):
    asyncio.run(speaker.tts.speak("नमस्ते, मैं फ्राइडे हूँ।"))
    asyncio.run(speaker.tts.speak("Hello, I'm Friday."))
    assert [voice for _, voice in FakeCommunicate.requests] == [config.EDGE_TTS_HINDI_VOICE, config.EDGE_TTS_VOICE]


def test_cached_confirmation_replays_without_synthesising_again(speaker):
    asyncio.run(speaker.tts.speak("Volume set to 40%.", cache=True))
    asyncio.run(speaker.tts.speak("Volume set to 40%.", cache=True))
    assert requested_texts() == ["Volume set to 40%."]
    assert speaker.played == [b"abc", b"abc"]


def test_uncached_replies_are_not_kept(speaker):
    asyncio.run(speaker.tts.speak("an AI reply"))
    asyncio.run(speaker.tts.speak("an AI reply"))
    assert requested_texts() == ["an AI reply", "an AI reply"]


def test_offline_voice_is_used_when_edge_tts_cannot_connect(speaker):
    FakeCommunicate.fail_at = 0
    asyncio.run(speaker.tts.speak("hello"))
    assert speaker.offline == ["hello"]


def test_failure_part_way_does_not_repeat_the_reply_offline(speaker):
    FakeCommunicate.fail_at = 2
    asyncio.run(speaker.tts.speak("hello", cache=True))
    assert speaker.played == [b"ab"]
    assert speaker.offline == []
    assert "hello" not in speaker.tts._cache


def test_interrupted_speech_is_not_cached_or_repeated(speaker):
    FakeCommunicate.on_chunk = lambda i: i == 1 and speaker.tts.stop()
    asyncio.run(speaker.tts.speak("Volume set to 40%.", cache=True))
    assert "Volume set to 40%." not in speaker.tts._cache
    assert speaker.offline == []


def test_cache_keeps_only_the_most_recent_phrases(speaker, monkeypatch):
    monkeypatch.setattr(tts_module, "CACHE_ITEMS", 2)
    for text in ["one", "two", "three"]:
        asyncio.run(speaker.tts.speak(text, cache=True))
    assert list(speaker.tts._cache) == ["two", "three"]


def test_prewarm_loads_common_phrases(speaker):
    asyncio.run(speaker.tts.prewarm())
    assert set(speaker.tts._cache) == set(tts_module.PREWARM_PHRASES)


def test_prewarm_gives_up_quietly_when_offline(speaker):
    FakeCommunicate.fail_at = 0
    asyncio.run(speaker.tts.prewarm())
    assert len(speaker.tts._cache) == 0


def test_known_offline_goes_straight_to_the_offline_voice(speaker, monkeypatch):
    monkeypatch.setattr(tts_module.network, "online", False)
    asyncio.run(speaker.tts.speak("hello"))
    assert speaker.offline == ["hello"] and FakeCommunicate.requests == []  # no 3 s wait for edge-tts


def test_offline_uses_piper_then_the_windows_voice(monkeypatch):
    speaker = tts_module.TextToSpeech()
    used = []
    monkeypatch.setattr(speaker, "_speak_piper", lambda text, generation: used.append(("piper", text)))

    class FakeEngine:
        def connect(self, *args):
            return "callback"

        def disconnect(self, token):
            pass

        def say(self, text):
            used.append(("windows", text))

        def runAndWait(self):
            pass

        def setProperty(self, name, value):  # the speech speed, set on every use
            pass

    monkeypatch.setattr(speaker, "_get_offline_engine", lambda: FakeEngine())
    speaker._speak_offline("hello", speaker.generation)
    speaker._speak_offline("नमस्ते", speaker.generation)  # the Piper voice can't read Hindi

    def piper_missing(text, generation):
        raise tts_module.TTSError("The offline voice isn't downloaded yet")

    monkeypatch.setattr(speaker, "_speak_piper", piper_missing)
    speaker._speak_offline("bye", speaker.generation)
    assert used == [("piper", "hello"), ("windows", "नमस्ते"), ("windows", "bye")]


def test_piper_plays_sentence_by_sentence_until_stopped(monkeypatch):
    speaker = tts_module.TextToSpeech()
    chunks = [SimpleNamespace(sample_rate=22050, audio_float_array=[0.1, 0.2]) for _ in range(3)]
    stream = FakeStream(on_write=lambda n: n == 2 and speaker.stop())  # stopped during the 2nd sentence

    class FakeVoice:
        def synthesize(self, text):
            yield from chunks

    monkeypatch.setattr(speaker, "_get_piper", lambda: FakeVoice())
    monkeypatch.setitem(sys.modules, "pyaudio", SimpleNamespace(
        PyAudio=lambda: SimpleNamespace(open=lambda **kw: stream, terminate=lambda: None), paFloat32=1))
    speaker._speak_piper("One. Two. Three.", speaker.generation)
    assert stream.writes == 2 and stream.closed


def test_piper_voice_missing_is_a_tts_error():
    with pytest.raises(tts_module.TTSError, match="isn't downloaded yet"):
        tts_module.TextToSpeech()._get_piper()


# ── Text-to-speech: playback and stopping ─────────────────────────────────────

class FakeStream:
    def __init__(self, on_write):
        self.writes, self.on_write, self.stopped, self.closed = 0, on_write, False, False

    def write(self, data):
        self.writes += 1
        self.on_write(self.writes)

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_speakers(monkeypatch):
    """Five decoded audio frames per clip, played into fake speaker streams."""
    state = SimpleNamespace(streams=[], on_write=lambda n: None)

    class FakePyAudio:
        def open(self, **kwargs):
            stream = FakeStream(lambda n: state.on_write(n))
            state.streams.append(stream)
            return stream

        def terminate(self):
            pass

    monkeypatch.setattr("pyaudio.PyAudio", FakePyAudio)
    monkeypatch.setattr(
        tts_module, "_decode_mp3", lambda chunks: ((np.zeros(576, dtype=np.float32), 24000) for _ in range(5))
    )
    return state


def test_speech_that_finishes_normally_plays_to_the_end(fake_speakers):
    speaker = tts_module.TextToSpeech()
    speaker._play([b"mp3"], speaker._generation)
    stream = fake_speakers.streams[0]
    assert stream.writes == 5 and stream.stopped and stream.closed


def test_stop_cuts_speech_off_mid_sentence(fake_speakers):
    speaker = tts_module.TextToSpeech()
    fake_speakers.on_write = lambda n: n == 2 and speaker.stop()

    speaker._play([b"mp3"], speaker._generation)

    stream = fake_speakers.streams[0]
    assert stream.writes == 2
    assert stream.closed and not stream.stopped  # closed at once, not played out


def test_speech_queued_before_stop_never_starts(fake_speakers):
    speaker = tts_module.TextToSpeech()
    queued = speaker._generation
    speaker.stop()
    speaker._play([b"mp3"], queued)
    assert fake_speakers.streams == []


def _mp3_tone(samples, rate=24000):
    import av

    buffer = io.BytesIO()
    # No ID3/Xing header frames: edge-tts streams bare MPEG audio frames, so the test does too.
    container = av.open(buffer, "w", format="mp3", options={"id3v2_version": "0", "write_xing": "0"})
    stream = container.add_stream("mp3", rate=rate, layout="mono")
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(samples) / rate)).astype(np.float32)
    for start in range(0, samples, 1152):
        frame = av.AudioFrame.from_ndarray(tone[start:start + 1152].reshape(1, -1), format="fltp", layout="mono")
        frame.sample_rate, frame.pts = rate, start
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def test_mp3_decoder_plays_audio_that_arrives_in_small_pieces():
    samples = 1152 * 10
    mp3 = _mp3_tone(samples)
    pieces = [mp3[i:i + 700] for i in range(0, len(mp3), 700)]

    decoded = list(tts_module._decode_mp3(pieces))

    assert {rate for _, rate in decoded} == {24000}
    assert all(chunk.dtype == np.float32 and chunk.ndim == 1 for chunk, _ in decoded)
    assert abs(sum(len(chunk) for chunk, _ in decoded) - samples) <= 3 * 1152  # MP3 adds a little padding
    # The 0.2-amplitude tone must come back at its real level — raw 16-bit values would clip badly.
    assert 0.1 < np.abs(np.concatenate([chunk for chunk, _ in decoded])).max() < 0.35


# ── Voice route: background speech ────────────────────────────────────────────

def test_reply_is_not_held_up_by_speech(monkeypatch):
    order = []

    async def slow_speak(text, cache=False, expected_generation=None):
        await asyncio.sleep(0.05)
        order.append(f"spoke: {text}")
    monkeypatch.setattr(voice_route.tts, "speak", slow_speak)

    async def handle_request():
        voice_route._speak_in_background("hello")
        order.append("replied")
        await asyncio.sleep(0.1)

    asyncio.run(handle_request())
    assert order == ["replied", "spoke: hello"]


def test_speech_failures_are_logged_not_raised(monkeypatch):
    async def broken_speak(text, cache=False, expected_generation=None):
        raise RuntimeError("no audio device")
    monkeypatch.setattr(voice_route.tts, "speak", broken_speak)

    async def handle_request():
        voice_route._speak_in_background("hello")
        await asyncio.sleep(0.05)

    asyncio.run(handle_request())


def test_waits_until_friday_has_finished_speaking():
    voice_route._listen_cancelled.clear()
    order = []

    async def scenario():
        async def speech():
            await asyncio.sleep(0.15)
            order.append("finished speaking")
        task = asyncio.create_task(speech())
        voice_route._speech_tasks.add(task)
        task.add_done_callback(voice_route._speech_tasks.discard)

        assert await voice_route._wait_until_done_speaking() is True
        order.append("listening")

    asyncio.run(scenario())
    assert order == ["finished speaking", "listening"]


def test_cancelling_ends_the_wait_early():
    voice_route._listen_cancelled.clear()

    async def scenario():
        async def long_speech():
            await asyncio.sleep(5)
        task = asyncio.create_task(long_speech())
        voice_route._speech_tasks.add(task)
        asyncio.get_running_loop().call_later(0.15, voice_route._listen_cancelled.set)

        started = time.perf_counter()
        result = await voice_route._wait_until_done_speaking()
        waited = time.perf_counter() - started
        task.cancel()
        voice_route._speech_tasks.discard(task)
        return result, waited

    result, waited = asyncio.run(scenario())
    voice_route._listen_cancelled.clear()
    assert result is False and waited < 1


# ── Voice route: requests ─────────────────────────────────────────────────────

@pytest.fixture
def voice_api(monkeypatch):
    state = SimpleNamespace(heard="tell me a fun fact", spoken=[], events=[], not_cancelled=True)
    monkeypatch.setattr(
        voice_route.recorder, "record", lambda: state.events.append("record") or np.zeros(SR, dtype=np.float32)
    )
    monkeypatch.setattr(voice_route.tts, "stop", lambda: state.events.append("stop speech"))

    async def wait_until_done_speaking():
        state.events.append("waited for speech")
        return state.not_cancelled
    monkeypatch.setattr(voice_route, "_wait_until_done_speaking", wait_until_done_speaking)

    monkeypatch.setattr(voice_route.stt, "transcribe", lambda audio, log=True: state.heard)
    monkeypatch.setattr(
        voice_route, "_speak_in_background", lambda text, cache=False: state.spoken.append((text, cache))
    )
    monkeypatch.setattr(voice_route, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda role, content: None,
    ))

    async def stream(messages, system_prompt, max_tokens):
        for piece in ("Octopuses have ", "three hearts. They also ", "have blue blood."):
            state.events.append(f"streamed {piece!r}")
            yield piece

    async def complete(messages, system_prompt, max_tokens):
        return SimpleNamespace(content="Octopuses have three hearts. They also have blue blood.",
                               provider="openrouter", model="m", tokens_used=9)
    monkeypatch.setattr(
        "providers.failover.get_provider",
        lambda name: SimpleNamespace(stream=stream, complete=complete, get_model_name=lambda: "m"),
    )

    state.client = TestClient(create_app(), base_url=LOCAL)
    return state


def test_listening_starts_by_stopping_friday_mid_sentence(voice_api):
    voice_api.client.post("/api/v1/voice", json={})
    assert voice_api.events[:2] == ["stop speech", "record"]


def test_answer_listen_waits_for_friday_to_finish_asking(voice_api):
    voice_api.client.post("/api/v1/voice", json={"after_speech": True})
    assert voice_api.events[:2] == ["waited for speech", "record"]


def test_answer_listen_cancelled_while_waiting_never_records(voice_api):
    voice_api.not_cancelled = False
    resp = voice_api.client.post("/api/v1/voice", json={"after_speech": True})
    assert resp.status_code == 409
    assert "record" not in voice_api.events


def test_voice_chat_reply_is_returned_and_spoken_without_caching(voice_api):
    body = voice_api.client.post("/api/v1/voice", json={}).json()
    assert (body["transcription"], body["response"]) == (
        "tell me a fun fact", "Octopuses have three hearts. They also have blue blood."
    )
    # The first sentence is spoken while the rest is still streaming in, then the rest in one go
    assert voice_api.spoken == [("Octopuses have three hearts.", False), ("They also have blue blood.", False)]


def test_first_sentence_is_spoken_before_the_reply_finishes(voice_api, monkeypatch):
    monkeypatch.setattr(
        voice_route, "_speak_in_background",
        lambda text, cache=False: voice_api.events.append(f"spoke {text!r}"),
    )
    voice_api.client.post("/api/v1/voice", json={})
    assert voice_api.events[-4:] == [
        "streamed 'three hearts. They also '",
        "spoke 'Octopuses have three hearts.'",
        "streamed 'have blue blood.'",
        "spoke 'They also have blue blood.'",
    ]


def test_nothing_more_is_said_after_the_user_cuts_friday_off(voice_api, monkeypatch):
    def spoke(text, cache=False):
        voice_api.spoken.append((text, cache))
        voice_route.tts.stop()  # the user pressed the voice hotkey during the first sentence
    monkeypatch.setattr(voice_route.tts, "stop", tts_module.TextToSpeech.stop.__get__(voice_route.tts))
    monkeypatch.setattr(voice_route, "_speak_in_background", spoke)

    body = voice_api.client.post("/api/v1/voice", json={}).json()

    assert body["response"] == "Octopuses have three hearts. They also have blue blood."  # still returned and saved
    assert voice_api.spoken == [("Octopuses have three hearts.", False)]


def test_nothing_is_streamed_or_spoken_when_speech_is_off(voice_api):
    body = voice_api.client.post("/api/v1/voice", json={"speak": False}).json()
    assert body["response"] == "Octopuses have three hearts. They also have blue blood."
    assert voice_api.spoken == []
    assert not any(event.startswith("streamed") for event in voice_api.events)


def test_voice_command_confirmation_is_spoken_with_caching(voice_api, monkeypatch):
    voice_api.heard = "set volume to 40"
    monkeypatch.setattr(intent.system, "set_volume", lambda level: f"Volume set to {level}%.")

    body = voice_api.client.post("/api/v1/voice", json={}).json()

    assert (body["action"], body["response"], body["awaiting_reply"]) == ("system", "Volume set to 40%.", False)
    assert voice_api.spoken == [("Volume set to 40%.", True)]


def test_voice_reply_says_when_friday_is_waiting_for_an_answer(voice_api, monkeypatch):
    voice_api.heard = "set volume to 40"
    monkeypatch.setattr(intent.system, "set_volume", lambda level: "Set it to 40%? Reply yes or no.")
    monkeypatch.setattr(voice_route, "is_awaiting_confirmation", lambda: True)

    assert voice_api.client.post("/api/v1/voice", json={}).json()["awaiting_reply"] is True


def test_private_replies_are_never_cached(voice_api, monkeypatch):
    voice_api.heard = "read my clipboard"
    monkeypatch.setattr(intent.system, "read_clipboard", lambda: "Your clipboard says: hunter2")

    voice_api.client.post("/api/v1/voice", json={})

    assert voice_api.spoken == [("Your clipboard says: hunter2", False)]


def test_speak_false_stays_silent(voice_api):
    voice_api.client.post("/api/v1/voice", json={"speak": False})
    assert voice_api.spoken == []


def test_no_speech_is_reported(voice_api):
    voice_api.heard = ""
    resp = voice_api.client.post("/api/v1/voice", json={})
    assert resp.status_code == 422
    assert resp.json()["message"] == "No speech detected. Please try again."


def test_stop_endpoint_stops_listening_and_speech(voice_api, monkeypatch):
    monkeypatch.setattr(voice_route.recorder, "stop", lambda: True)

    assert voice_api.client.post("/api/v1/voice/stop").json() == {"stopped": True}

    assert voice_api.events == ["stop speech"]
    assert voice_route._listen_cancelled.is_set()
    voice_route._listen_cancelled.clear()


def test_lets_talk_and_bye_start_and_end_conversation_mode(voice_api):
    voice_api.heard = "Let's talk."
    started = voice_api.client.post("/api/v1/voice", json={"speak": False}).json()
    assert started["conversation"] == "start" and started["response"] == "I'm all ears, Boss."
    voice_api.heard = "Okay, bye Friday!"
    assert voice_api.client.post("/api/v1/voice", json={"speak": False}).json()["conversation"] == "end"
    voice_api.heard = "let's talk about my exam"
    assert voice_api.client.post("/api/v1/voice", json={"speak": False}).json()["conversation"] is None
