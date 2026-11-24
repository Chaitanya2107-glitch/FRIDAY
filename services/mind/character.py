"""Owner-shaped expression preferences and their local change history."""

from datetime import datetime
import json
import math
import re
import time

from core.config import config
from core.logger import logger
from services import settings_store

DEFAULTS = {"humour": .40, "warmth": .65, "sass": .50, "formality": .40, "verbosity": .45}
VALUES = (
    "Tell the Boss the truth kindly.",
    "Ask before risky actions.",
    "Respect quiet and welcome the Boss back without pressure.",
)
WEEK = 7 * 24 * 60 * 60
WEEKLY_DRIFT = .10
_FORMAL = re.compile(r"^(?:good (?:morning|afternoon|evening)|thank you(?: very much)?|could you please|i would appreciate)\b", re.I)
_CASUAL = re.compile(r"^(?:hey|yo|cheers|nice one|all good|yep|nah)\b", re.I)
_BRIEF = re.compile(r"^(?:yes|no|ok(?:ay)?|yep|nah|got it|sounds good|thanks|cheers|all good)$", re.I)
_STYLE = {
    "keep it short": ("verbosity", 0), "be brief": ("verbosity", 0), "more detail please": ("verbosity", 1),
    "be more detailed": ("verbosity", 1), "be more formal": ("formality", 1), "be more casual": ("formality", 0),
    "be gentler": ("warmth", 1), "less sass": ("sass", 0), "more sass": ("sass", 1),
}


def storage_path():
    return config.MEMORY_DIR / "mind" / "character.json"


def _load():
    try:
        state = json.loads(storage_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    saved = state.get("traits")
    saved = saved if isinstance(saved, dict) else {}
    traits = {}
    for name, default in DEFAULTS.items():
        value = saved.get(name)
        traits[name] = float(value) if type(value) in (int, float) and 0 <= value <= 1 else default
    history = state.get("history")
    return traits, history if isinstance(history, list) else []


def snapshot(now=None):
    traits, _ = _load()
    return {"traits": traits, "values": VALUES}


def _stamp(now):
    if isinstance(now, datetime):
        return now.timestamp()
    return time.time() if now is None else float(now)


def _change(targets, source, now=None, *, reset=False):
    stamp = _stamp(now)
    with settings_store.lock:
        traits, history = _load()
        changes = {}
        for name, (target, step) in targets.items():
            old = traits[name]
            spent = 0.0
            # An explicit reset changes the sheet but preserves the recent drift budget.
            for event in reversed(history):
                if (not isinstance(event, dict) or event.get("source") == "owner_reset"
                        or type(event.get("at")) not in (int, float)
                        or not stamp - WEEK < event["at"] <= stamp):
                    continue
                edited = event.get("changes")
                pair = edited.get(name) if isinstance(edited, dict) else None
                if isinstance(pair, list) and len(pair) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in pair):
                    spent += abs(pair[1] - pair[0])
            remaining = max(0.0, round(WEEKLY_DRIFT - spent, 6))
            shift = target - old
            new = target if reset else round(old + math.copysign(min(abs(shift), step, remaining), shift), 6)
            if old != new:
                changes[name] = [old, new]
                traits[name] = new
        if changes or reset:
            history.append({"at": stamp, "source": source, "changes": changes})
            settings_store.save(storage_path(), {"traits": traits, "values": VALUES, "history": history})
    return traits


def observe(message, reaction=None, now=None):
    """Learn from narrow style cues. Store only the cue and numeric changes."""
    from services.mind import humour

    text = message.strip(" .!?").casefold()
    targets = {}
    source = "owner_wording"
    if text in _STYLE:
        name, target = _STYLE[text]
        targets[name] = (target, .05)
        source = "explicit_style"
    if _FORMAL.match(text):
        targets.setdefault("formality", (1, .015))
    if _CASUAL.match(text):
        targets.setdefault("formality", (0, .015))
    if _BRIEF.fullmatch(text):
        targets.setdefault("verbosity", (0, .01))
    if reaction in {"liked", "disliked", "ignored"}:
        targets["humour"] = (humour.learned_dial(), .025)
        source = "humour_" + reaction
    if reaction == "liked":
        targets["warmth"] = (1, .015)
        targets["formality"] = (0, .01)
    if not targets:
        return
    try:
        _change(targets, source, now)
    except (OSError, ValueError, TypeError) as error:
        logger.debug("Character cue unavailable (%s)", type(error).__name__)


def serious(on, now=None):
    from services.mind import humour

    try:
        _change({"humour": (0 if on else humour.learned_dial(), .05),
                 "sass": (0 if on else DEFAULTS["sass"], .04)}, "explicit_serious", now)
    except (OSError, ValueError, TypeError) as error:
        logger.debug("Character preference unavailable (%s)", type(error).__name__)


def show():
    sheet = snapshot()
    traits = ", ".join(f"{name} {value:.2f}" for name, value in sheet["traits"].items())
    return f"Character traits — {traits}.\nValues\n" + "\n".join(sheet["values"])


def reset(now=None):
    _change({name: (value, 1) for name, value in DEFAULTS.items()}, "owner_reset", now, reset=True)
    return "Character traits reset to their defaults, Boss."
