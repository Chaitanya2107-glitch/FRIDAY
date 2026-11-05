import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from core.errors import FridayError
from interfaces.api.routes import voice
from services.voice import conversation_input as module, recorder as recording
from services.voice.tts import TextToSpeech


@pytest.mark.parametrize("text, own, expected", [
    ("Wait, change that to tomorrow.", [], "change that to tomorrow."),
    ("The forecast is sunny wait change that to tomorrow", [], "change that to tomorrow"),
    ("Hey Friday, stop.", [], "stop."),
    ("Friday, actually use ten minutes.", [], "actually use ten minutes."),
    ("We meet next Friday at noon", [], None),
    ("The music is nice", [], None),
    ("Wait for the page to load", ["Please wait for the page to load."], None),
    ("Hey Friday, anything", ["Say hey Friday to begin."], None),
    ("Hold on", [], ""),
])
def test_explicit_interruptions_and_own_speech_rejection(text, own, expected):
    assert module.interruption(text, own) == expected


def microphone(monkeypatch, speech_until=15):
    state = SimpleNamespace(reads=0)

    def read():
        state.reads += 1
        return np.full(recording.CHUNK_SAMPLES, state.reads <= speech_until, dtype=np.float32)

    def segments(audio):
        positions = np.flatnonzero(audio)
        return [(int(positions[0]), int(positions[-1]) + 1)] if len(positions) else []

    monkeypatch.setattr(recording, "_speech_segments", segments)
    return state, read


def test_interrupt_stops_speech_and_preserves_full_correction(monkeypatch):
    state, read = microphone(monkeypatch)
    capture = module.Capture()
    capture.replying.set()
    stopped = []
    text = module.capture_turn(capture, read, lambda: state.reads > 100,
                               lambda _: "Sunny forecast wait change that to tomorrow.",
                               lambda: ["Here is the forecast."], lambda: stopped.append(state.reads))
    assert capture.interrupted and stopped == [10]
    assert text == "change that to tomorrow."
    assert state.reads > stopped[0]


def test_normal_turn_does_not_need_a_wake_phrase(monkeypatch):
    state, read = microphone(monkeypatch)
    capture = module.Capture()
    text = module.capture_turn(capture, read, lambda: state.reads > 100,
                               lambda _: "What is on my schedule?", list,
                               lambda: pytest.fail("Quiet turn stopped speech"))
    assert text == "What is on my schedule?" and not capture.interrupted


def test_cancellation_during_stt_cannot_stop_newer_speech(monkeypatch):
    state, read = microphone(monkeypatch)
    capture = module.Capture()
    capture.replying.set()
    def transcribe(_):
        capture.cancelled.set()
        return "Wait, change that to tomorrow"
    with pytest.raises(FridayError, match="Stopped"):
        module.capture_turn(capture, read, capture.cancelled.is_set, transcribe, lambda: ["A reply"],
                            lambda: pytest.fail("Cancelled monitor stopped newer speech"))


def test_self_speech_does_not_interrupt_and_silence_times_out(monkeypatch):
    state, read = microphone(monkeypatch, speech_until=20)
    with pytest.raises(FridayError, match="No speech"):
        module.capture_turn(module.Capture(), read, lambda: state.reads > 200,
                            lambda _: "Please wait for the page.",
                            lambda: ["Please wait for the page."] if state.reads < 21 else [],
                            lambda: pytest.fail("Friday interrupted herself"))


def test_capture_shares_recorder_ownership_and_stop(monkeypatch):
    recorder = recording.Recorder()
    @contextmanager
    def mic():
        yield lambda: np.zeros(recording.CHUNK_SAMPLES)
    monkeypatch.setattr(recording, "_open_microphone", mic)
    with recorder.conversation_capture(lambda: False) as (_, stopped):
        assert recorder.is_recording
        with pytest.raises(recording.RecorderError):
            recorder.record()
        assert recorder.stop() and stopped()
    assert not recorder.is_recording


def test_stop_epoch_prevents_old_capture_rearming(monkeypatch):
    service = module.ConversationInput()
    def run(capture):
        capture.text = "A captured turn"
        capture.ready.set()
    monkeypatch.setattr(service, "_run", run)
    captured = service.take()
    service.stop()
    with pytest.raises(FridayError, match="Stopped"):
        service.start(replying=True, expected_epoch=captured.epoch)
    assert service.active is None


def test_cancelling_route_releases_pending_capture(monkeypatch):
    released = threading.Event()
    service = SimpleNamespace(take=lambda: released.wait(3), stop=released.set)
    monkeypatch.setattr(voice, "conversation_input", service)
    async def scenario():
        task = asyncio.create_task(voice.voice(voice.VoiceRequest(barge_in=True)))
        await asyncio.sleep(.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert released.is_set()


def test_scheduled_old_speech_is_not_revived_after_stop(monkeypatch):
    calls = []
    async def speak(text, **kwargs):
        calls.append(text)
    monkeypatch.setattr(voice.tts, "speak", speak)
    async def scenario():
        voice._speak_in_background("Old queued reply")
        voice.tts.stop()
        await asyncio.gather(*voice._speech_tasks)
    asyncio.run(scenario())
    assert calls == []


def test_tts_carries_generation_across_cognition_setup(monkeypatch):
    from services.mind.cognition import cognition
    speaker = TextToSpeech()
    @contextmanager
    def operation(*args, **kwargs):
        speaker.stop()  # interruption after public entry, before synthesis
        yield SimpleNamespace(finish=lambda _: None)
    monkeypatch.setattr(cognition, "operation", operation)
    monkeypatch.setattr(speaker, "_cached", lambda _: pytest.fail("Cancelled speech reached audio synthesis"))
    asyncio.run(speaker.speak("Old speech", expected_generation=speaker.generation))


def test_windows_fallback_stops_on_its_own_audio_thread(monkeypatch):
    speaker = TextToSpeech()
    callbacks, calls = {}, []
    def connect(topic, callback):
        callbacks[topic] = callback
        return topic
    def run():
        speaker.stop()
        callbacks["started-word"](name="voice", location=0, length=3)
    engine = SimpleNamespace(connect=connect, disconnect=lambda token: calls.append("disconnect"),
                             setProperty=lambda *a: None, say=lambda text: calls.append("say"),
                             runAndWait=run, stop=lambda: calls.append("stop"))
    monkeypatch.setattr(speaker, "_get_offline_engine", lambda: engine)
    speaker._speak_offline("नमस्ते", speaker.generation)
    assert calls == ["say", "stop", "disconnect"]


def test_voice_intake_transcripts_are_not_logged(monkeypatch):
    flags = []
    monkeypatch.setattr(voice.recorder, "record", lambda: b"synthetic")
    monkeypatch.setattr(voice.stt, "transcribe", lambda audio, *, log: flags.append(log) or "reply that private")
    assert asyncio.run(voice._record_command()) == "reply that private"
    assert flags == [False]


def test_explicit_conversation_stop_fences_speech_but_cleanup_preserves_goodbye(monkeypatch):
    calls = []
    monkeypatch.setattr(voice, "conversation_input", SimpleNamespace(stop=lambda: calls.append("stop")))
    generation = voice.tts.generation
    asyncio.run(voice.stop_conversation_input(silence=False))
    assert voice.tts.generation == generation
    asyncio.run(voice.stop_conversation_input())
    assert voice.tts.generation != generation and calls == ["stop", "stop"]
