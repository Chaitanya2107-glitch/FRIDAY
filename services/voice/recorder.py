"""
services/voice/recorder.py

Records one voice command from the microphone. Listening ends when:
  - stop() is called (the voice hotkey pressed a second time),
  - the user has spoken and then stayed quiet for SILENCE_SECONDS,
  - nothing was said within NO_SPEECH_SECONDS, or
  - MAX_SECONDS have passed (safety limit).

Speech is detected with the Silero voice-activity model bundled with
faster-whisper, which ignores steady background noise (fans, typing) far better
than a volume threshold. A short beep marks the start and the end of listening.
"""

import threading
import winsound
from contextlib import contextmanager

import numpy as np

from core.errors import FridayError
from core.logger import logger

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1600            # 0.1 s per microphone read
CHECKS_EVERY_CHUNKS = 3         # run speech detection every 0.3 s
SILENCE_SECONDS = 1.5
NO_SPEECH_SECONDS = 8
MAX_SECONDS = 60
VAD_WINDOW_SECONDS = 3          # how much recent audio each check looks at
MIN_SPEECH_MS = 250             # shorter sounds (the hotkey's own click) aren't speech
START_BEEP, STOP_BEEP = (880, 120), (660, 120)  # (frequency Hz, duration ms)


class RecorderError(FridayError):
    """Microphone problems, or a second listen while one is already running."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code=status_code)


def _speech_segments(audio: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) sample positions of speech within `audio`."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(min_speech_duration_ms=MIN_SPEECH_MS, min_silence_duration_ms=100, speech_pad_ms=0)
    return [(s["start"], s["end"]) for s in get_speech_timestamps(audio, options, sampling_rate=SAMPLE_RATE)]


@contextmanager
def _open_microphone():
    """Yields a function returning the next CHUNK_SAMPLES of mic audio as float32 in [-1, 1]."""
    try:
        import pyaudio
    except ImportError:
        raise RecorderError("pyaudio is not installed. Run: pip install pyaudio")

    audio = pyaudio.PyAudio()
    try:
        stream = audio.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True, frames_per_buffer=CHUNK_SAMPLES
        )
    except Exception as e:
        audio.terminate()
        raise RecorderError(f"Couldn't open the microphone: {e}")

    def read_chunk() -> np.ndarray:
        data = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
        return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768

    try:
        yield read_chunk
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()


def _beep(tone: tuple[int, int]) -> None:
    try:
        winsound.Beep(*tone)
    except RuntimeError:
        pass  # no sound device — listening still works without the cue


class Recorder:
    def __init__(self):
        self._stop = threading.Event()
        self._busy = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._busy.locked()

    def stop(self) -> bool:
        """Ask the current recording to finish. Returns False if nothing was recording."""
        if not self.is_recording:
            return False
        self._stop.set()
        return True

    def record(self) -> np.ndarray:
        """Blocks until listening ends; returns 16 kHz mono float32 audio."""
        if not self._busy.acquire(blocking=False):
            raise RecorderError("FRIDAY is already listening.", status_code=409)
        try:
            self._stop.clear()
            _beep(START_BEEP)  # before opening the mic, so the beep isn't recorded
            with _open_microphone() as read_chunk:
                audio = self._capture(read_chunk)
            _beep(STOP_BEEP)
            return audio
        finally:
            self._busy.release()

    @contextmanager
    def conversation_capture(self, cancelled):
        """Conversation input shares the ordinary microphone lock and stop control."""
        if cancelled() or not self._busy.acquire(blocking=False):
            raise RecorderError("FRIDAY is already listening or this turn was cancelled.", status_code=409)
        try:
            if cancelled():
                raise RecorderError("Stopped listening.", status_code=409)
            self._stop.clear()
            with _open_microphone() as read_chunk:
                yield read_chunk, lambda: cancelled() or self._stop.is_set()
        finally:
            self._busy.release()

    def _capture(self, read_chunk) -> np.ndarray:
        chunks: list[np.ndarray] = []
        speech_seen = False
        window_chunks = int(VAD_WINDOW_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

        while not self._stop.is_set():
            chunks.append(read_chunk())
            recorded = len(chunks) * CHUNK_SAMPLES / SAMPLE_RATE
            if recorded >= MAX_SECONDS:
                logger.info("Stopped listening: time limit reached")
                break
            if len(chunks) % CHECKS_EVERY_CHUNKS:
                continue

            window = np.concatenate(chunks[-window_chunks:])
            segments = _speech_segments(window)
            if segments:
                speech_seen = True
                if (len(window) - segments[-1][1]) / SAMPLE_RATE >= SILENCE_SECONDS:
                    logger.info("Stopped listening: speaker went quiet")
                    break
            elif speech_seen:
                logger.info("Stopped listening: speaker went quiet")
                break
            elif recorded >= NO_SPEECH_SECONDS:
                logger.info("Stopped listening: nothing was said")
                break

        if self._stop.is_set():
            logger.info("Stopped listening: hotkey pressed")
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


# ── Singleton ─────────────────────────────────────────────────────────────────
recorder = Recorder()
