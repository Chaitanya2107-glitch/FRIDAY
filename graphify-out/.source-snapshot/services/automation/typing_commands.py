"""
services/automation/typing_commands.py

Local matcher for typing: dictation ("type see you at 5"), AI writing
("write an email asking for Friday off") and key presses ("press ctrl+s",
"select all"). The words it accepts live in services/automation/command_words.py.

Dictated text keeps its own wording, capitals and punctuation — only filler at
the front ("hey friday, can you…") is dropped.
"""

import re

from services.automation import command_words as words
from services.automation.command_words import normalize_command, strip_leading_filler
from services.automation.keyboard import parse_keys


def _action(action: str, **arguments) -> dict:
    return {"type": "system", "action": action, **arguments}


def _split_then_keys(text: str) -> tuple[str, str | None]:
    """ "hi there and send it" → ("hi there", "enter")."""
    match = words.THEN_KEYS.search(text)
    if not match:
        return text, None
    if match.group("send"):
        return text[:match.start()], "enter"
    keys = match.group("keys").strip()
    return (text[:match.start()], keys) if parse_keys(keys) else (text, None)


def _dictated(text: str) -> str:
    for spoken, value in words.DICTATION_BREAKS.items():
        text = re.sub(rf"\s*[,.]?\s*\b{spoken}\b[,.]?\s*", value, text, flags=re.IGNORECASE)
    return text


def _profile(body: str) -> str | None:
    """ "type my USN" → the saved USN ("my USN is …", services/proactive/college.py), else None."""
    match = re.fullmatch(r"\s*my\s+(.+?)[\s.]*", body, re.I)
    if not match:
        return None
    from services.proactive import college  # avoid an import cycle
    return college.profile_value(match.group(1))


def _press_command(msg: str) -> dict | None:
    phrase = words.KEY_PHRASES.get(msg)
    if phrase:
        return _action("press_keys", keys=phrase)
    match = words.PRESS.match(msg)
    if not match or not parse_keys(match.group("keys")):
        return None
    count = match.group("times") or match.group("word")
    times = int(count) if count and count.isdigit() else words.TIMES_WORDS.get(count, 1)
    return _action("press_keys", keys=match.group("keys"), times=times)


def match_typing_command(message: str) -> dict | None:
    text = strip_leading_filler(message)

    dictate = words.DICTATE.match(text)
    if dictate:
        body, then_keys = _split_then_keys(dictate.group("text"))
        body = _profile(body) or _dictated(body)
        if body.strip():
            extra = {"then_keys": then_keys} if then_keys else {}
            return _action("type_text", text=body, **extra)

    write = words.WRITE.match(text)
    if write:
        request, then_keys = _split_then_keys(write.group("request").strip())
        extra = {"then_keys": then_keys} if then_keys else {}
        return _action("write_text", request=request, **extra)

    return _press_command(re.sub(r"\s+", " ", normalize_command(message).lower()))
