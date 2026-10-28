"""
services/voice/wake.py

"Hey Friday" — only while the user has switched it on (tray toggle / Ctrl+Alt+H).

The microphone is read continuously; the Silero voice-activity model (the same
one the recorder uses) finds where each utterance starts and ends, and only
then is it transcribed with the speech model already loaded for voice commands.
An utterance that *starts* with a wake phrase ("hey friday", "ok friday") wakes
FRIDAY, and whatever follows it is the command — "Hey Friday, work mode" in one
breath. A bare "Hey Friday" keeps the mic open for COMMAND_WAIT_SECONDS: the next
utterance is the command ("Hey Friday … open Notepad" after a breath). Nothing else is logged or kept.

Interrupting: while FRIDAY is talking, its own voice comes back through the mic,
so utterances never end cleanly and "Hey Friday" lands mid-way through one.
Then, every second, the last few seconds are transcribed and the wake phrase is
looked for anywhere in them — unless FRIDAY itself is saying it. When found,
FRIDAY stops talking at once and listening carries on until the user finishes.

Audio is ignored while the voice hotkey is already listening.

Every wake is logged in memory/wake_log.jsonl — only when, and whether it was a mistake
(nothing said after it, or "false alarm" / "I wasn't talking to you"), never what was heard —
so false triggers can be counted ("how many false wakes").
"""

import json
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

from core.config import config
from core.errors import FridayError
from core.logger import logger
from services.voice.recorder import CHUNK_SAMPLES, SAMPLE_RATE, _open_microphone, _speech_segments

CHECKS_EVERY_CHUNKS = 3     # look for speech every 0.3 s
RECENT_SECONDS = 1.0        # how much audio each check looks at
END_SILENCE_SECONDS = 0.6   # an utterance ends after this much quiet
PREROLL_SECONDS = 0.5       # audio kept from just before speech was noticed
MAX_UTTERANCE_SECONDS = 10
INTERRUPT_WINDOW_SECONDS = 3  # while FRIDAY talks: how much recent audio each check transcribes
INTERRUPT_CHECK_SECONDS = 1
COMMAND_WAIT_SECONDS = 2.0  # after a bare "Hey Friday": how long the command may take to start
TAKEOVER_SECONDS = 2        # a wait that was just switched off takes a moment to let go of the mic
LOG_PATH = config.MEMORY_DIR / "wake_log.jsonl"  # tests point this elsewhere
STATS_DAYS = 7


class WakeTimeout(FridayError):
    """Nobody said the wake phrase before the auto-off time."""


class Wake(NamedTuple):
    command: str       # what followed the wake phrase ("" = nothing yet)
    interrupted: bool  # said over FRIDAY while it was talking (FRIDAY has already stopped)


def _phrase_pattern(phrase: str) -> str:
    words = [re.escape(w) if w != "friday" else r"fri\s?day" for w in phrase.lower().split()]
    return r"[\s,.!?:;-]*".join(words)


def match_wake(
    text: str, phrases: list[str] | None = None, anywhere: bool = False, friday_is_saying: list[str] = (),
) -> str | None:
    """
    The command after a wake phrase at the start of `text` ("" if nothing followed),
    or None if `text` doesn't start with one. "Hey, Friday. Work mode." → "Work mode."
    anywhere=True (said over FRIDAY's voice): the phrase may come anywhere; the last one
    counts. A phrase in `friday_is_saying` (FRIDAY's own words right now) never counts.
    """
    phrases = config.wake_phrases() if phrases is None else phrases
    for phrase in phrases:
        pattern = rf"{_phrase_pattern(phrase)}\b[\s,.!?:;-]*"
        if not anywhere:
            match = re.match(rf"^\W*{pattern}", text, re.IGNORECASE)
        elif any(re.search(rf"\b{pattern}", said, re.IGNORECASE) for said in friday_is_saying):
            continue
        else:
            match = next(reversed(list(re.finditer(rf"(?<!\w){pattern}", text, re.IGNORECASE))), None)
        if match:
            return text[match.end():].strip()
    return None


class WakeListener:
    def __init__(self, transcribe: Callable[[np.ndarray], str] | None = None):
        self._transcribe = transcribe  # None = the shared speech model (loaded lazily)
        self._busy = threading.Lock()

    def _text(self, audio: np.ndarray) -> str:
        if self._transcribe:
            return self._transcribe(audio)
        from services.voice.stt import stt
        return stt.transcribe(audio, log=False)  # other people's speech never reaches the log

    def wait(
        self,
        cancelled: Callable[[], bool],
        timeout_seconds: float,
        paused: Callable[[], bool],
        friday_speech: Callable[[], list[str]] = list,
        interrupt: Callable[[], None] = lambda: None,
    ) -> Wake | None:
        """
        Block until someone says a wake phrase; returns what followed it. None once
        cancelled() is True. Raises WakeTimeout after `timeout_seconds` without one.
        paused() True = ignore the audio for now. friday_speech() = what FRIDAY is
        saying right now ([] = quiet); interrupt() makes it stop.
        """
        if not self._busy.acquire(timeout=TAKEOVER_SECONDS):
            raise FridayError("Already listening for 'Hey Friday'.", status_code=409)
        try:
            with _open_microphone() as read_chunk:
                return self._listen(read_chunk, cancelled, timeout_seconds, paused, friday_speech, interrupt)
        finally:
            self._busy.release()

    def _listen(
        self, read_chunk, cancelled, timeout_seconds, paused,
        friday_speech=list, interrupt=lambda: None,
    ) -> Wake | None:
        deadline = time.monotonic() + timeout_seconds
        chunks_per_second = SAMPLE_RATE / CHUNK_SAMPLES
        recent_chunks = int(RECENT_SECONDS * chunks_per_second)
        preroll_chunks = int(PREROLL_SECONDS * chunks_per_second)
        max_chunks = int(MAX_UTTERANCE_SECONDS * chunks_per_second)
        window_chunks = int(INTERRUPT_WINDOW_SECONDS * chunks_per_second)
        check_chunks = int(INTERRUPT_CHECK_SECONDS * chunks_per_second)
        command_wait = int(COMMAND_WAIT_SECONDS * chunks_per_second)
        woke_at = None  # chunk count when a bare wake phrase was heard; the next utterance is the command
        chunks: list[np.ndarray] = []
        over_friday: list[np.ndarray] = []  # recent audio while FRIDAY is talking
        speaking = interrupted = False
        count = 0

        while not cancelled():
            if time.monotonic() > deadline:
                raise WakeTimeout("Nobody said 'Hey Friday'.", status_code=408)
            chunk = read_chunk()
            if paused():
                chunks, over_friday, speaking = [], [], False
                woke_at = None
                continue

            friday_is_saying = [] if interrupted else friday_speech()
            if friday_is_saying:
                over_friday = (over_friday + [chunk])[-window_chunks:]
                chunks, speaking = [], False
                count += 1
                if count % check_chunks or not _speech_segments(np.concatenate(over_friday)):
                    continue
                heard = self._text(np.concatenate(over_friday))
                if match_wake(heard, anywhere=True, friday_is_saying=friday_is_saying) is None:
                    continue
                logger.info("Wake phrase heard over FRIDAY — stopping it")
                interrupt()
                # Keep listening from here until the user finishes what they're saying
                chunks, over_friday, speaking, interrupted = over_friday, [], True, True
                continue
            over_friday = []

            chunks.append(chunk)
            count += 1
            if count % CHECKS_EVERY_CHUNKS:
                continue

            recent = np.concatenate(chunks[-recent_chunks:])
            segments = _speech_segments(recent)
            quiet_for = (len(recent) - segments[-1][1]) / SAMPLE_RATE if segments else RECENT_SECONDS
            if not speaking:
                if segments:
                    speaking = True
                else:
                    chunks = chunks[-preroll_chunks:]
                    if woke_at is not None and count - woke_at > command_wait:
                        return self._woke("", interrupted)  # nothing followed: beep and ask for it
                continue
            if quiet_for < END_SILENCE_SECONDS and len(chunks) < max_chunks:
                continue

            utterance, chunks, speaking = np.concatenate(chunks), [], False
            text = self._text(utterance)
            if woke_at is not None:
                return self._woke(text, interrupted)
            command = match_wake(text, anywhere=interrupted)
            if interrupted and command is None:
                command = ""  # heard it a moment ago, but not in the full transcript: ask for the command
            if command == "":
                # "Hey Friday … open Notepad": people take a breath after the name. Keep the mic
                # open so the command isn't lost while it closes and the beep plays.
                woke_at = count
            elif command is not None:
                return self._woke(command, interrupted)
        return None

    @staticmethod
    def _woke(command: str, interrupted: bool) -> Wake:
        logger.info("Wake phrase heard — command captured (%s characters)", len(command))
        return Wake(command, interrupted)


def record(mistake: bool, interrupted: bool = False, now: datetime | None = None) -> None:
    """Log one wake: when, and whether it was a mistake — never what was heard."""
    entry = {"at": (now or datetime.now()).isoformat(timespec="seconds"), "mistake": mistake, "interrupted": interrupted}
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        logger.warning(f"Couldn't log the wake: {e}")


def stats(now: datetime | None = None) -> str:
    since = ((now or datetime.now()) - timedelta(days=STATS_DAYS)).isoformat()
    try:
        entries = [json.loads(line) for line in LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        entries = []
    recent = [e for e in entries if e.get("at", "") >= since]
    if not recent:
        return f"\"Hey Friday\" hasn't woken me in the last {STATS_DAYS} days."
    mistakes = sum(1 for e in recent if e.get("mistake"))
    return (f"In the last {STATS_DAYS} days \"Hey Friday\" woke me {len(recent)} time{'s' if len(recent) != 1 else ''}; "
            f"{mistakes} {'was a mistake' if mistakes == 1 else 'were mistakes'} ({round(100 * mistakes / len(recent))}%).")


wake_listener = WakeListener()
