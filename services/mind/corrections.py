"""
services/mind/corrections.py

FRIDAY learning from being corrected. Right after a message FRIDAY got wrong, the Boss says
"no, I meant open spotify" (or "I meant …", "I said …", "no, open spotify"): FRIDAY does that,
and remembers that the missed message means those actions — next time it just does them.

"I meant X" always teaches (FRIDAY may have done the wrong thing successfully). A bare "no, X"
teaches only after a miss (a chat answer or a failed command) — otherwise it's a change of mind.
Text-carrying actions (typing, clipboard) are never learned: the wording would be replayed.

State: memory/mind/corrections.json {"<message key>": {"actions": [...], "meant": "...", "day": "..."}}.
"""

import json
import re
import time
from datetime import date

from core.config import config
from core.logger import logger
from services.automation.command_cache import NEVER_CACHED_ACTIONS, _key

path = config.MEMORY_DIR / "mind" / "corrections.json"  # tests point this elsewhere
WINDOW_SECONDS = 120  # a correction answers the message just before, not one from an hour ago
MAX_ENTRIES = 300

_MEANT = re.compile(r"^(?:no+|nope|nah|wrong)?[\s,.!]*i (?:meant(?: to say)?|said|wanted you to)[\s,:]+(.+)$", re.I)
_NO = re.compile(r"^(?:no+|nope|nah|wrong)[\s,.!]+(.+)$", re.I)

_last: dict = {}  # the message before this one: {"message", "at", "hit"}


def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def lookup(message: str) -> list[dict] | None:
    """The actions the Boss taught for this message, or None."""
    entry = load().get(_key(message))
    return entry["actions"] if entry else None


def correction(message: str, now: float | None = None) -> tuple[str, str] | None:
    """(what was missed, what was meant) if `message` corrects the one just before, else None."""
    last = _last
    if not last or (time.time() if now is None else now) - last["at"] > WINDOW_SECONDS:
        return None
    if match := _MEANT.match(message.strip()):
        return last["message"], match.group(1).strip(" .!")
    if not last["hit"] and (match := _NO.match(message.strip())):
        return last["message"], match.group(1).strip(" .!")
    return None


def note(message: str, hit: bool, now: float | None = None) -> None:
    """Every message, after it's handled: hit = it ran a command successfully."""
    _last.clear()
    _last.update(message=message, at=time.time() if now is None else now, hit=hit)


def learn(missed: str, meant: str, actions: list[dict]) -> bool:
    """Remember that `missed` means `actions` (what `meant` ran). False if there's nothing safe to learn."""
    if not actions or any(a.get("action") in NEVER_CACHED_ACTIONS for a in actions) or _key(missed) == _key(meant):
        return False
    try:
        json.dumps(actions)
    except (TypeError, ValueError):
        return False
    state = load()
    state[_key(missed)] = {"actions": actions, "meant": meant, "day": date.today().isoformat()}
    _save(dict(list(state.items())[-MAX_ENTRIES:]))
    logger.info(f"Learned a correction: {missed!r} means {meant!r}")
    return True


def forget(message: str) -> bool:
    state = load()
    if state.pop(_key(message), None) is None:
        return False
    _save(state)
    return True


def recent(days: int = 7) -> list[tuple[str, str]]:
    """(missed, meant) pairs learned in the last `days` days, newest last — for "what's on your mind"."""
    since = date.fromordinal(date.today().toordinal() - days).isoformat()
    return [(missed, e["meant"]) for missed, e in load().items() if e.get("day", "") >= since]
