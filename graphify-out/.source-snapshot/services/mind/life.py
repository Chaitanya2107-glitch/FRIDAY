"""
services/mind/life.py

FRIDAY's persona counters, day summary and grounded behavioral life reports.

Feelings come from what happens to her, not from a schedule. Two of them, each fading by half every
HALF_LIFE_HOURS:
  warmth     positive conversational engagement; quiet requests never reduce it
  curiosity  up with everything she notices and can't explain, down when she learns what something is
mood() provides light persona tone: quiet while away, curious, pleased or content.
Behavioral priorities/gates come from life_state, shared with local cognition.

Her day: what she noticed, said, was answered, respected quiet, and learned. "how are you feeling" / "how was
your day" tells it; every night it's written to her own diary (memory/mind/diary.jsonl).

No AI model in this file. State: memory/mind/life.json.
Feeling reports also consume the shared, locally reviewed temporal situation.
Warmth/curiosity do not grant permission to interrupt or establish facts.
"""

import json
import re
import time
from datetime import datetime

from core.config import config
from services.mind import knowledge, thoughts

path = config.MEMORY_DIR / "mind" / "life.json"       # tests point these elsewhere
diary_path = config.MEMORY_DIR / "mind" / "diary.jsonl"
HALF_LIFE_HOURS = 3
# What each thing that happens to her does to (warmth, curiosity)
EVENTS = {"answered": (1.0, 0.0), "shushed": (0.0, 0.0), "ignored": (0.0, 0.0),
          "noticed": (0.0, 0.4), "learned": (0.3, -0.5)}
PLEASED, CURIOUS, AWAY_MINUTES = 1.0, 1.5, 60
FEEL_ACTION = "friday_feeling"
_FEEL = re.compile(r"^(?:how are you feeling(?: today)?|how do you feel|how(?:'s| is| was) your day(?: going| been)?"  # plain "how are you" stays a chat
                   r"|what(?:'s| is) your mood|are you (?:bored|sulking|sulky)|what did you learn today)$", re.I)


def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _faded(state: dict, now_ts: float) -> tuple[float, float]:
    keep = 0.5 ** (max(0.0, now_ts - state.get("at", now_ts)) / 3600 / HALF_LIFE_HOURS)
    return max(0.0, state.get("warmth", 0.0)) * keep, state.get("curiosity", 0.0) * keep


def feel(event: str, now_ts: float | None = None) -> None:
    """Something happened to her (EVENTS): it moves her feelings and goes into today's count."""
    now_ts = time.time() if now_ts is None else now_ts
    state = load()
    warmth, curiosity = _faded(state, now_ts)
    d_warmth, d_curiosity = EVENTS[event]
    day = datetime.fromtimestamp(now_ts).date().isoformat()
    today = state.get("today", {}) if state.get("day") == day else {}
    today[event] = today.get(event, 0) + 1
    _save({"warmth": round(warmth + d_warmth, 3), "curiosity": round(max(0.0, curiosity + d_curiosity), 3),
           "at": now_ts, "day": day, "today": today})


def mood(now: datetime, away_minutes: float = 0) -> tuple[str, str]:
    """(one word, why) — from her feelings right now."""
    warmth, curiosity = _faded(load(), now.timestamp())
    if away_minutes >= AWAY_MINUTES:
        return "quiet", "respecting time away from the laptop"
    if curiosity >= CURIOUS:
        return "curious", "I've noticed a lot lately that I haven't figured out"
    if warmth >= PLEASED:
        return "pleased", "the Boss has been talking to me"
    return "content", "nothing much has happened to me"


def day_line(day: str) -> str:
    """Her day in a sentence: what she noticed, said and learned."""
    counts = thoughts.counts_on(day)
    state = load()
    mine = state.get("today", {}) if state.get("day") == day else {}
    learned = [t.name for t in knowledge.learned_on(day)]
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"
    parts = [f"noticed {plural(counts['noticed'], 'thing')}", f"brought up {counts['said']}",
             f"got {plural(mine.get('answered', 0), 'answer')}"]
    if mine.get("shushed"):
        parts.append(f"respected {plural(mine['shushed'], 'request')} for quiet")
    line = "I " + ", ".join(parts) + "."
    return line + (f" Learned what {', '.join(learned[:5])} {'is' if len(learned) == 1 else 'are'}." if learned else "")


def close_day(now: datetime) -> str:
    """Nightly: today goes into her diary."""
    word, _ = mood(now)
    line = day_line(now.date().isoformat())
    diary_path.parent.mkdir(parents=True, exist_ok=True)
    with diary_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"day": now.date().isoformat(), "mood": word, "text": line}, ensure_ascii=False) + "\n")
    return line


def match_life_command(text: str) -> dict | None:
    return {"type": "system", "action": FEEL_ACTION} if _FEEL.match(text.strip(" ?!.")) else None


def feeling(now: datetime, away_minutes: float = 0) -> dict:
    """The raw data behind "how are you feeling" — worded by services/mind/wording.py."""
    word, why = mood(now, away_minutes)
    from services.mind.temporal_memory import situation
    from services.mind.life_state import current
    from services.automation.intent import remote_request
    if remote_request.get():
        return {'kind': 'feeling', 'mood': word, 'because': why, 'my_day_so_far': 'I am ready to help when you ask.'}
    behavior = current(now)
    word, why = behavior.get('posture', word), behavior.get('reason', why)
    return {"kind": "feeling", "the_boss_asked": "how you feel / how your day is", "mood": word, "because": why,
            'situation': situation(now),
            'life_state': behavior,
            "my_day_so_far": day_line(now.date().isoformat()),
            "on_my_mind": [t.data.get("noticed") for t in thoughts.alive(now)[:2]]}
