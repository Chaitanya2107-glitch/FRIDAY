"""Explicit, low-risk command typos for use after normal routing fails.

This returns a candidate, not permission to execute it: the caller must send it
through the usual native command parser and confirmation rules. Leading filler
is stripped by the caller. Names and every character after the first word stay
unchanged; there is deliberately no general fuzzy matching.
"""
import re


_COMMAND_TYPOS = {
    "opne": "open", "launhc": "launch", "serach": "search", "seach": "search",
    "remnid": "remind", "remidn": "remind", "voluem": "volume",
    "brighness": "brightness", "brightnes": "brightness",
    "screenshto": "screenshot", "screnshot": "screenshot", "shwo": "show",
    "paus": "pause", "resuem": "resume",
}
_FIRST_WORD = re.compile(r"[a-z]+(?=\s|$)", re.I)


def correct_command_typo(message: str) -> str | None:
    """Return one known starter correction, or None when no safe mapping exists."""
    if match := _FIRST_WORD.match(message):
        if corrected := _COMMAND_TYPOS.get(match[0].casefold()):
            return corrected + message[match.end():]
    return None
