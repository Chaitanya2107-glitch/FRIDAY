"""
services/automation/routines.py

Routines: one phrase runs several commands in order. "start work mode" →
open VS Code, play the focus playlist, set the volume to 30.

A routine is a name and a list of plain command sentences, kept in
memory/routines.json so it can be edited by hand:
    {"work mode": ["open vs code", "play my focus playlist", "set volume to 30"]}
The file is read again on every use, so hand edits count straight away.

This module only matches the commands and keeps the file. intent.py runs each
step through the normal command flow, so any command FRIDAY knows is a valid step —
plus pauses: "wait 5 seconds", "pause 2 minutes" (up to MAX_PAUSE_SECONDS).
The tray's Routines menu runs them with one click.
"""

import json
import re
from pathlib import Path

from core.logger import logger
from services import settings_store
from services.automation.command_words import STEP_STARTERS, split_steps
from services.automation.system_control import AutomationError

path = Path("memory/routines.json")  # tests point this elsewhere

EDIT_ACTIONS = {"create_routine", "list_routines", "delete_routine"}
EXAMPLE = '"create a routine called work mode to open vs code, play my focus playlist and set volume to 30"'

_CREATE = re.compile(
    r"^(?:create|make|add|save|new|set up)\s+(?:(?:a|an|new|the)\s+)*routine\b(?:\s+(?:called|named|for))?\s*",
    re.I,
)
# Where the name ends and the steps begin: "work mode: open…", "work mode to open…", "…that opens…"
_NAME_END = re.compile(r"\s*:\s*|\s+(?:to|that|which|with)\s+", re.I)
_LIST = re.compile(
    r"^(?:(?:list|show)(?: me)?(?: all)?(?: of)?(?: my| the)? routines|what routines do i have|my routines)$", re.I
)
_DELETE = re.compile(r"^(?:delete|remove|forget)\s+(?:the\s+|my\s+)?(?:routine\s+(?P<a>.+)|(?P<b>.+?)\s+routine)$", re.I)
MAX_PAUSE_SECONDS = 600
_PAUSE = re.compile(r"^(?:wait|pause|sleep)(?: for)? (?:(?P<n>\d+(?:\.\d+)?) ?(?P<unit>s|secs?|seconds?|m|mins?|minutes?)"
                    r"|(?P<moment>a (?:moment|bit|second|sec)))$", re.I)
_RUN_VERB = re.compile(r"^(?:start|run|begin|do|activate|launch|enter|go into|switch to|turn on)\s+", re.I)


def load() -> dict[str, list[str]]:
    """Every routine, by lowercase name. Raises AutomationError if the file is broken."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e
    if not isinstance(data, dict):
        raise AutomationError(f"{path} should hold routine names and their steps, like {{\"work mode\": [\"open vs code\"]}}.")
    return {
        _clean_name(name): [str(step) for step in steps]
        for name, steps in data.items()
        if isinstance(steps, list)
    }


def _save(routines: dict[str, list[str]]) -> None:
    settings_store.save(path, routines)


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip(" \"'").lower())


def _base_verb(step: str) -> str:
    """ "opens vs code" → "open vs code", from "a routine that opens vs code" """
    first, _, rest = step.partition(" ")
    lowered = first.lower()
    for stem in (lowered[:-1], lowered[:-2]):  # opens → open, presses → press
        if lowered not in STEP_STARTERS and stem in STEP_STARTERS:
            return f"{stem} {rest}".strip()
    return step


def _routine_named(text: str) -> str | None:
    """The saved routine "start work mode", "run the work mode routine" or just "work mode" names."""
    name = _RUN_VERB.sub("", text.strip(), count=1)
    name = re.sub(r"^(?:my|the)\s+|^routine\s+|\s+routine$", "", name, flags=re.I)
    name = _clean_name(name)
    try:
        return name if name in load() else None
    except AutomationError as e:
        logger.warning(f"Routines unavailable: {e}")
        return None


def match_routine_command(text: str) -> dict | None:
    """Routine commands. `text` has already been through normalize_command()."""
    created = _CREATE.match(text)
    if created:
        parts = _NAME_END.split(text[created.end():], maxsplit=1)
        steps = [_base_verb(s.strip(" .")) for s in split_steps(parts[1])] if len(parts) == 2 else []
        return {"type": "system", "action": "create_routine", "routine": _clean_name(parts[0]),
                "steps": [s for s in steps if s]}
    if _LIST.match(text.strip()):
        return {"type": "system", "action": "list_routines"}
    deleted = _DELETE.match(text.strip())
    if deleted:
        return {"type": "system", "action": "delete_routine", "routine": _clean_name(deleted["a"] or deleted["b"])}
    name = _routine_named(text)
    if name:
        return {"type": "system", "action": "run_routine", "routine": name}
    return None


def pause_seconds(step: str) -> float | None:
    """ "wait 5 seconds" → 5.0; None if the step isn't a pause."""
    from services.automation.spoken_numbers import normalize_command_numbers

    m = _PAUSE.match(normalize_command_numbers(step.strip().rstrip(".")))
    if not m:
        return None
    if m["moment"]:
        return 3.0
    seconds = float(m["n"]) * (60 if m["unit"].lower().startswith("m") else 1)
    return min(seconds, MAX_PAUSE_SECONDS)


def steps(name: str) -> list[str]:
    return load().get(name, [])


@settings_store.synchronized
def run_edit(parsed: dict) -> str:
    """Create, list or delete routines (running them is in intent.py)."""
    action = parsed["action"]
    routines = load()

    if action == "list_routines":
        if not routines:
            return f"You don't have any routines yet. Try {EXAMPLE}."
        listed = ", ".join(f"{name} ({len(s)} step{'s' if len(s) != 1 else ''})" for name, s in routines.items())
        return f"Your routines: {listed}."

    name = parsed["routine"]
    if action == "delete_routine":
        if name not in routines:
            raise AutomationError(f'You don\'t have a routine called "{name}".')
        del routines[name]
        _save(routines)
        return f'Deleted the "{name}" routine.'

    new_steps = [str(s) for s in parsed["steps"]]
    if not name or not new_steps:
        raise AutomationError(f"Tell me the name and the steps together, like {EXAMPLE}.")
    verb = "Updated" if name in routines else "Saved"
    routines[name] = new_steps
    _save(routines)
    numbered = ", ".join(f"{i}. {step}" for i, step in enumerate(new_steps, 1))
    return f'{verb} the "{name}" routine: {numbered}. Say "start {name}" to run it.'
