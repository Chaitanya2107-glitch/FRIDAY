"""Conversation-only, single-turn microphone handoff with spoken interruption.

One capture can span reply generation/playback and the next HTTP request. It
uses the recorder's lock, bounded RAM audio, private STT and cancellation epochs.
This is lexical echo rejection, not acoustic echo cancellation.
"""

from dataclasses import dataclass, field
import re
import threading
import time

import numpy as np

from core.errors import FridayError
from services.voice import recorder as recording

_CUE = re.compile(r"(?P<name>\bhey[ ,]+friday\b|(?:^|[.!?]\s*)friday(?=[,:!?]|$))"
                  r"|\b(?P<short>wait|hold on|one second)\b", re.I)


def interruption(text, own_speech=()):
    """Return words after the last explicit cue; None means unrelated/self speech."""
    for found in reversed(list(_CUE.finditer(text))):
        cue = found["name"] or found["short"]
        if any(re.search(r"\b" + re.escape(cue) + r"\b", said, re.I) for said in own_speech):
            continue
        return text[found.end():].lstrip(" ,.!?:;-").strip()
    return None


@dataclass
class Capture:
    epoch: int = 0
    cancelled: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)
    replying: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    text: str = ""
    interrupted: bool = False
    error: BaseException | None = None


def capture_turn(capture, read_chunk, stopped, transcribe, speech, interrupt):
    chunks, over_speech = [], []
    speaking = False
    idle_chunks = count = 0
    per_second = recording.SAMPLE_RATE // recording.CHUNK_SAMPLES
    max_chunks = 12 * per_second
    started = time.monotonic()
    while not stopped():
        if time.monotonic() - started > recording.MAX_SECONDS:
            raise FridayError("Conversation listening timed out.", status_code=422)
        chunk = read_chunk()
        if stopped():
            raise FridayError("Stopped listening.", status_code=409)
        count += 1
        own = [] if capture.interrupted else speech()
        guarded = not capture.interrupted and (capture.replying.is_set() or bool(own))
        if guarded:
            over_speech = (over_speech + [chunk])[-3 * per_second:]
            chunks, speaking, idle_chunks = [], False, 0
            if count % per_second or not recording._speech_segments(np.concatenate(over_speech)):
                continue
            heard = transcribe(np.concatenate(over_speech))
            if stopped():
                raise FridayError("Stopped listening.", status_code=409)
            if interruption(heard, own) is None:
                continue
            interrupt()
            capture.interrupted = True
            chunks, over_speech, speaking = over_speech, [], True
            continue
        over_speech = []
        chunks.append(chunk)
        if count % recording.CHECKS_EVERY_CHUNKS:
            continue
        recent = np.concatenate(chunks[-per_second:])
        segments = recording._speech_segments(recent)
        quiet = (len(recent) - segments[-1][1]) / recording.SAMPLE_RATE if segments else 1
        speaking = speaking or bool(segments)
        if not speaking:
            idle_chunks += recording.CHECKS_EVERY_CHUNKS
            chunks = chunks[-per_second // 2:]
            if idle_chunks >= recording.NO_SPEECH_SECONDS * per_second:
                raise FridayError("No speech detected. Please try again.", status_code=422)
            continue
        if quiet < .7 and len(chunks) < max_chunks:
            continue
        text = transcribe(np.concatenate(chunks))
        if stopped():
            raise FridayError("Stopped listening.", status_code=409)
        if capture.interrupted:
            return interruption(text) or ""
        if not text.strip():
            raise FridayError("No speech detected. Please try again.", status_code=422)
        return text.strip()
    raise FridayError("Stopped listening.", status_code=409)


class ConversationInput:
    def __init__(self, recorder=None, transcribe=None, speech=None, interrupt=None):
        self.recorder = recorder or recording.recorder
        self.transcribe, self.speech, self.interrupt = transcribe, speech, interrupt
        self.lock = threading.RLock()
        self.active = None
        self.epoch = 0

    def start(self, replying=False, expected_epoch=None):
        with self.lock:
            if expected_epoch is not None and expected_epoch != self.epoch:
                raise FridayError("Stopped listening.", status_code=409)
            if self.active is not None:
                return self.active
            capture = Capture(epoch=self.epoch)
            if replying:
                capture.replying.set()
            self.active = capture
            capture.thread = threading.Thread(target=self._run, args=(capture,), name="friday-conversation-input", daemon=True)
            capture.thread.start()
            return capture

    def _run(self, capture):
        from services.voice.stt import stt
        from services.voice.tts import tts
        try:
            with self.recorder.conversation_capture(capture.cancelled.is_set) as (read_chunk, stopped):
                capture.text = capture_turn(capture, read_chunk, stopped,
                                            self.transcribe or (lambda audio: stt.transcribe(audio, log=False)),
                                            self.speech or (lambda: tts.saying), self.interrupt or tts.stop)
        except BaseException as error:
            capture.error = error
        finally:
            capture.ready.set()

    def take(self):
        capture = self.start()
        capture.ready.wait()
        with self.lock:
            if capture.cancelled.is_set() or self.active is not capture:
                raise FridayError("Stopped listening.", status_code=409)
            self.active = None
        if capture.error:
            raise capture.error
        return capture

    def stop(self):
        with self.lock:
            self.epoch += 1
            capture, self.active = self.active, None
            if capture:
                capture.cancelled.set()
        if capture and capture.thread and capture.thread is not threading.current_thread():
            capture.thread.join(timeout=2)


conversation_input = ConversationInput()
