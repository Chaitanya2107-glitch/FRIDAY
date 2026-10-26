"""
services/memory/notes.py

A notes inbox: "note buy a new charger", "idea: FRIDAY could …" — typed, spoken or sent from
Telegram — is saved with the time in memory/notes.json. Notes show up in that day's journal
(services/activity/journal.py) and in the morning briefing until cleared.
  "read my notes", "delete note 2", "clear my notes"

Journal entries — "journal: rough lab today", "dear diary …", "add to my journal …" — are kept
apart in memory/diary.json: they go only into that day's journal (a Diary section), never the
notes inbox or the briefing.
"""

import json
import re
from datetime import date, datetime

from core.config import config
from services.automation.command_words import normalize_command
from services.automation.system_control import AutomationError

NOTE_ACTIONS = {"add_note", "list_notes", "delete_note", "clear_notes", "add_diary"}
path = config.MEMORY_DIR / "notes.json"  # tests point these elsewhere
diary_path = config.MEMORY_DIR / "diary.json"
BRIEFING_NOTES = 3

_ADD = re.compile(r"^(?:(?:make|take|save|add|create) a note|note down|jot down|note|idea)(?:\s*[:,\-–]\s*|\s+)(?:that\s+)?(?P<text>\S.*)$", re.I | re.S)
_DIARY = re.compile(r"^(?:dear diary|diary|journal|add (?:this )?to (?:my |the |today's )?(?:journal|diary))"
                    r"(?:\s*[:,\-–]\s*|\s+)(?:that\s+)?(?P<text>\S.*)$", re.I | re.S)
_LIST = re.compile(r"^(?:read|show|list|what are)(?: me)? (?:all )?(?:my |the )?notes$|^my notes$", re.I)
_DELETE = re.compile(r"^(?:delete|remove|done with|clear|cross off) note (?:number )?(?P<n>\d+)$", re.I)
_CLEAR = re.compile(r"^(?:clear|delete|remove|empty)(?: all)?(?: of)? (?:my |the )?notes(?: inbox)?$", re.I)


def match_note_command(text: str) -> dict | None:
    """`text` has already been through normalize_command() (letter case kept)."""
    text = text.strip()
    if _LIST.match(text):
        return {"type": "system", "action": "list_notes"}
    if _CLEAR.match(text):
        return {"type": "system", "action": "clear_notes"}
    if m := _DELETE.match(text):
        return {"type": "system", "action": "delete_note", "number": int(m["n"])}
    if m := _DIARY.match(text):
        return {"type": "system", "action": "add_diary", "text": m["text"].strip()}
    if m := _ADD.match(text):
        return {"type": "system", "action": "add_note", "text": m["text"].strip()}
    return None


def is_note(message: str) -> bool:
    """For chat/voice: a note is saved as it is, never taken as a web, file or screen question."""
    text = normalize_command(message)
    return bool(_ADD.match(text) or _DIARY.match(text))


def load(file=None) -> list[dict]:
    try:
        return json.loads((file or path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(notes: list[dict], file=None) -> None:
    (file or path).write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")


def add(text: str, now: datetime | None = None) -> str:
    notes = load()
    notes.append({"text": text, "at": (now or datetime.now()).isoformat(timespec="seconds")})
    _save(notes)
    return f"Noted. You have {len(notes)} note{'s' if len(notes) != 1 else ''}."


def add_diary(text: str, now: datetime | None = None) -> str:
    entries = load(diary_path)
    entries.append({"text": text, "at": (now or datetime.now()).isoformat(timespec="seconds")})
    _save(entries, diary_path)
    return "Added to today's journal."


def list_message() -> str:
    notes = load()
    if not notes:
        return "No notes."
    return "\n".join(f"{i}. {n['text']} ({datetime.fromisoformat(n['at']):%d %b, %H:%M})" for i, n in enumerate(notes, 1))


def delete(number: int) -> str:
    notes = load()
    if not 1 <= number <= len(notes):
        raise AutomationError(f"There's no note {number}." + (f" You have {len(notes)}." if notes else ""))
    removed = notes.pop(number - 1)
    _save(notes)
    return f"Deleted: {removed['text']}"


def clear() -> str:
    count = len(load())
    _save([])
    return f"Cleared {count} note{'s' if count != 1 else ''}." if count else "No notes to clear."


def run(parsed: dict) -> str:
    action = parsed["action"]
    if action == "add_note":
        return add(str(parsed["text"]))
    if action == "add_diary":
        return add_diary(str(parsed["text"]))
    if action == "list_notes":
        return list_message()
    if action == "delete_note":
        return delete(int(parsed["number"]))
    return clear()


def on_day(day: date, file=None) -> list[str]:
    """For the journal: "14:05 — buy a new charger" (file=diary_path: the journal entries)."""
    lines = []
    for note in load(file):
        at = datetime.fromisoformat(note["at"])
        if at.date() == day:
            lines.append(f"{at:%H:%M} — {note['text']}")
    return lines


def briefing_line() -> str:
    notes = load()
    if not notes:
        return ""
    shown = "; ".join(n["text"] for n in notes[:BRIEFING_NOTES])
    more = len(notes) - BRIEFING_NOTES
    return f"You have {len(notes)} note{'s' if len(notes) != 1 else ''}: {shown}" + (f"; and {more} more." if more > 0 else ".")
