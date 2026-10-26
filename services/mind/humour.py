"""
services/mind/humour.py

FRIDAY's sense of when a joke lands — learned, not a fixed "1 in 3".

For each situation (studying, deadline close, late night, gaming, coding, everything else) FRIDAY keeps
a belief about how welcome a joke is: a Beta(liked, disliked) count. Deciding to joke is Thompson
sampling: draw a plausible "how much the Boss likes jokes here" from that belief and joke with that
chance — so it keeps trying a little where it's unsure, and settles where it has learned.

What it learns from — the Boss's next message after a joke (within REACTION_MINUTES):
  laughing ("lol", "haha", 😂, "good one") → liked;  "be serious", "not now", "stop", "not funny" → disliked
  (counts more);  anything else → a small nudge towards fewer jokes (ignored jokes fade out).
Every night (services/mind/reflection.py) old evidence is faded (DECAY), so FRIDAY keeps adapting
when the Boss's mood about jokes changes.

State: memory/mind/humour.json. The chat persona gets a matching "humour right now" line (dial()).
"""

import json
import random
import re
import time
from datetime import datetime

from core.config import config
from core.logger import logger

path = config.MEMORY_DIR / "mind" / "humour.json"  # tests point this elsewhere
PRIOR = (2.0, 3.0)          # before any evidence: jokes welcome ~40% of the time
REACTION_MINUTES = 5
DECAY = 0.97                # nightly: yesterday's evidence counts 97%, a month ago ~40%
LIKED, DISLIKED = 1.0, 1.5  # a complaint teaches more than a laugh
IGNORED = (0.1, 0.25)       # (liked, disliked) for a reply that neither laughed nor complained
SITUATIONS = ("study", "deadline", "late", "gaming", "coding", "chill")

_LAUGH = re.compile(r"(?:\b(?:lol+|lmao+|lmfao|rofl|haha\w*|hehe\w*|ha ha|good one|nice one|funny|hilarious|i'm dead"
                    r"|that was good|savage|touch[eé])\b|😂|🤣|😆|😹|💀)", re.I)
_ANNOYED = re.compile(r"\b(?:be serious|not now|not funny|stop (?:it|joking|that)|shut up|enough|annoying|cringe|"
                      r"no jokes?|don'?t joke|serious(?:ly)?,? friday|not the time|i'?m serious)\b|😐|😑|🙄", re.I)


def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def situation(now: datetime | None = None) -> str:
    """What the Boss is doing right now, as one of SITUATIONS."""
    from services.activity.categories import categorize
    from services.activity.log import activity_log
    from services.automation import personality  # its study / class / deadline checks (imported late: no cycle)

    now = now or datetime.now()
    try:
        if personality._study_mode() or personality._class_now(now):
            return "study"
        if personality._deadline_soon(now):
            return "deadline"
    except Exception as e:
        logger.info(f"Humour situation check skipped: {e}")
    if 1 <= now.hour < 5:
        return "late"
    kind = categorize("app", activity_log.app) if activity_log.app else "other"
    return "gaming" if kind == "gaming" else "coding" if kind in ("coding", "project") else "chill"


def _belief(state: dict, where: str) -> tuple[float, float]:
    liked, disliked = state.get("beliefs", {}).get(where, PRIOR)
    return float(liked), float(disliked)


def welcome(where: str, state: dict | None = None) -> float:
    """How welcome jokes are here, 0..1 (the belief's average)."""
    liked, disliked = _belief(load() if state is None else state, where)
    return liked / (liked + disliked)


def should_joke(where: str, weight: float = 1.0, rng: random.Random = random) -> bool:
    """Thompson sampling: joke with a chance drawn from the belief. weight > 1 for obvious openings (a game in study mode)."""
    liked, disliked = _belief(load(), where)
    return rng.random() < min(1.0, rng.betavariate(liked, disliked) * weight)


def told(where: str, kind: str, now: float | None = None) -> None:
    """A joke was just made: the Boss's next message tells whether it landed."""
    state = load()
    state["pending"] = {"where": where, "kind": kind, "at": time.time() if now is None else now}
    _save(state)


def _update(state: dict, where: str, liked: float, disliked: float) -> None:
    a, b = _belief(state, where)
    state.setdefault("beliefs", {})[where] = [round(a + liked, 3), round(b + disliked, 3)]


def reaction(text: str) -> str:
    if _ANNOYED.search(text):
        return "disliked"
    if _LAUGH.search(text):
        return "liked"
    return "ignored"


def hear(message: str, now: float | None = None) -> str | None:
    """The Boss said something: if it answers a recent joke, learn from it. Returns the reaction, or None."""
    try:
        return _hear(message, now)
    except Exception as e:  # learning must never break a reply
        logger.info(f"Humour learning skipped: {e}")
        return None


def _hear(message: str, now: float | None) -> str | None:
    state = load()
    pending = state.get("pending")
    if not pending:
        return None
    state.pop("pending")
    if (time.time() if now is None else now) - pending["at"] > REACTION_MINUTES * 60:
        _save(state)
        return None
    felt = reaction(message)
    if felt == "ignored" and pending["kind"] == "chat":  # a chat reply may not have joked at all: only clear reactions count
        _save(state)
        return felt
    liked, disliked = {"liked": (LIKED, 0.0), "disliked": (0.0, DISLIKED), "ignored": IGNORED}[felt]
    _update(state, pending["where"], liked, disliked)
    notes = state.setdefault("recent", [])
    notes.append({"where": pending["where"], "kind": pending["kind"], "felt": felt,
                  "day": datetime.now().date().isoformat()})
    state["recent"] = notes[-50:]
    _save(state)
    logger.info(f"Humour: a {pending['kind']} joke while {pending['where']} was {felt}")
    if felt == "liked":
        from services import body_state
        body_state.push("laugh")  # hearts on her body
    return felt


def after_chat_reply() -> None:
    """A chat reply went out with humour allowed: a laugh or a complaint next tells whether it worked."""
    from services.automation import personality

    try:
        if personality.is_on() and welcome(where := situation()) >= 0.25:
            told(where, "chat")
    except Exception as e:  # learning must never break a reply
        logger.info(f"Humour bookkeeping skipped: {e}")


def fade() -> None:
    """Nightly: older evidence counts a little less, pulled gently back towards the prior."""
    state = load()
    for where, (a, b) in list(state.get("beliefs", {}).items()):
        state["beliefs"][where] = [round(PRIOR[0] + (a - PRIOR[0]) * DECAY, 3), round(PRIOR[1] + (b - PRIOR[1]) * DECAY, 3)]
    _save(state)


def dial(where: str | None = None) -> str:
    """One line for the chat persona: how much humour fits right now, from what's been learned."""
    where = where or situation()
    level = welcome(where)
    if level < 0.25:
        return f"Humour right now ({where}): the Boss hasn't enjoyed jokes in this situation lately — keep it minimal."
    if level < 0.5:
        return f"Humour right now ({where}): a light, dry touch at most."
    return f"Humour right now ({where}): the Boss has been enjoying the banter here — go for it, still one line."


def summary() -> str:
    """For "what's on your mind": where jokes land and where they don't."""
    state = load()
    beliefs = state.get("beliefs", {})
    if not beliefs:
        return "I'm still working out when you like jokes — no reactions to go on yet."
    ranked = sorted(beliefs, key=lambda w: welcome(w, state), reverse=True)
    good = [w for w in ranked if welcome(w, state) >= 0.5]
    bad = [w for w in ranked if welcome(w, state) < 0.3]
    parts = []
    if good:
        parts.append("jokes land best when " + ", ".join(_describe(w) for w in good))
    if bad:
        parts.append("I keep it quiet when " + ", ".join(_describe(w) for w in bad))
    return ("From your reactions: " + "; ".join(parts) + ".") if parts else "Your reactions to jokes are mixed so far — still learning."


def _describe(where: str) -> str:
    return {"study": "you're studying", "deadline": "a deadline is close", "late": "it's late at night",
            "gaming": "you're gaming", "coding": "you're coding", "chill": "you're just chilling"}.get(where, where)
