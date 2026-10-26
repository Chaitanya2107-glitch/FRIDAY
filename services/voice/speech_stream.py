"""
services/voice/speech_stream.py

Starts speaking a streamed AI reply early: the first sentence is spoken as soon
as it's complete, and everything after it in one go once the reply is done.

Two pieces rather than one per sentence: once the first words arrive the rest of
the reply follows within about a second, so it's ready by the time the first
sentence has been said — and two speech calls can't play out of order or leave
gaps between sentences.
"""

import re
from collections.abc import Callable

MIN_WORDS = 3  # "Sure!" alone is too short to be worth its own speech call
# Words whose full stop doesn't end a sentence
ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "st", "no", "approx"}
_SENTENCE_END = re.compile(r"[.!?।](?=\s)|\n")


def first_sentence_end(text: str) -> int | None:
    """Where the first speakable sentence of `text` ends, or None if it isn't complete yet."""
    for match in _SENTENCE_END.finditer(text):
        piece = text[:match.end()]
        words = piece.split()
        last = words[-1].rstrip(".!?।").lower() if words else ""
        if len(words) >= MIN_WORDS and last not in ABBREVIATIONS and not re.fullmatch(r"\w", last):
            return match.end()
    return None


class FirstSentenceSpeaker:
    """
    feed() it the reply as it streams in; call finish() when it's done.
    speak(text) should start speech in the background. stopped() is True once the
    user cut FRIDAY off — nothing more is said after that.
    """

    def __init__(self, speak: Callable[[str], None], stopped: Callable[[], bool]):
        self._speak = speak
        self._stopped = stopped
        self._text = ""
        self._spoken_up_to = 0

    def feed(self, text: str) -> None:
        self._text += text
        if self._spoken_up_to == 0 and not self._stopped():
            end = first_sentence_end(self._text)
            if end is not None:
                self._spoken_up_to = end
                self._speak(self._text[:end].strip())

    def finish(self) -> None:
        rest = self._text[self._spoken_up_to:].strip()
        if rest and not self._stopped():
            self._speak(rest)
