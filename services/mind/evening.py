"""Explicit day-review/learning adapters and an offline training catalogue.

Live questions are generated one at a time by local cognitive inquiry. Clock times
never start a question session, answers never schedule the next question, and
persisted pre-upgrade queues are retired. collect() serves the explicit manual
Train Friday catalogue only; it does not choose live autonomous questions.
"""

import json
import re
import time
from datetime import datetime

from core.config import config
from core.logger import logger
from services.activity.log import _duration
from services.mind import brain, talk, thoughts, wonder, wording

path = config.MEMORY_DIR / "mind" / "evening.json"       # tests point these elsewhere
answers_path = config.MEMORY_DIR / "mind" / "evening.jsonl"
MAX_QUESTIONS = max(1, min(30, config.EVENING_QUESTION_LIMIT))
MAX_THOUGHTS = 3
MIN_EPISODE_MINUTES = 20       # a stretch of the day worth asking about
WHERE = "evening"              # how welcome this is, is learned like every other situation (talk.py)
EVENING_ACTION = "evening_questions"
# What no window title will tell her. The first two every evening, the rest taking turns.
DATA_WISHES = [
    "Out of 10, how was today?",
    "What's the plan for tomorrow?",
    "When did you get to sleep last night, and when were you up?",
    "Did you study or work on anything away from the laptop today?",
    "Who did you spend time with today?",
    "What did you eat today?",
    "Anything you'd like me to start keeping track of?",
]
_ASK = re.compile(r"^(?:ask me about my day|(?:start |do )?(?:the |your |my )?(?:evening|end of day|nightly|daily) questions"
                  r"|what do you want to ask me(?: today| tonight)?|ask me your questions|let'?s do the questions)$", re.I)
_LEARN = re.compile(r"^(?:start |begin |do )?(?:a |the |my )?(?:longer |extended )?learning session$|^ask me more questions$", re.I)



def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


# ── What she wants to ask ─────────────────────────────────────────────────────

def collect(log, now: datetime, extended: bool = False, *, unlimited: bool = False) -> list[dict]:
    """Tonight's questions, in order: {"raw": facts to word} plus what asking crosses off (thought, wondered)."""
    items = []
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        day = [e for e in brain.episodes(log, now, midnight) if e.seconds >= MIN_EPISODE_MINUTES * 60]
    except Exception as e:  # her questions must never depend on one source
        logger.info(f"Evening: no episodes ({e})")
        day = []
    by_thread: dict[str, list] = {}
    for e in day:
        by_thread.setdefault(e.thread, []).append(e)
    totals = sorted(by_thread.values(), key=lambda es: -sum(e.seconds for e in es))
    work = next((es for es in totals if es[0].focus), None)
    play = next((es for es in totals if es[0].category in brain.LEISURE), None)
    for stretch, ask in ((work, "how did it go, and what got done"), (play, "was it any good")):
        if stretch:
            longest = max(stretch, key=lambda e: e.seconds)
            items.append({"raw": {"kind": "day", "the_boss_spent": _duration(sum(e.seconds for e in stretch)),
                                  "on": longest.label(), "ask": ask}})
    items.append({"raw": {"kind": "question", "ask": "What did you get up to today away from the laptop?"}})
    day_items = list(items)
    unsaid = thoughts.unsaid_on(None if unlimited else now.date().isoformat())
    if not unlimited:
        unsaid = unsaid[:MAX_THOUGHTS]
    thought_items = [{"raw": {"kind": t.kind, **t.data}, "thought": t.id} for t in unsaid]
    items += thought_items
    turn = now.toordinal() % (len(DATA_WISHES) - 2)
    data_items = [{"raw": {"kind": "question", "ask": q}} for q in DATA_WISHES[:2] + [DATA_WISHES[2 + turn]]]
    limit = max(1, min(30, config.LEARNING_SESSION_QUESTIONS)) if extended else MAX_QUESTIONS
    personal = [{"raw": {"kind": "question", "ask": q}, "wondered": q}
                for q in wonder.next_questions(None if unlimited else limit if extended else 2, now=now.timestamp())]
    if unlimited:
        return day_items + thought_items + data_items + personal
    if not config.AI_ASSIST_ONLY and not extended:
        return (items + data_items + personal)[:limit]
    # Round-robin coverage: personal questions cannot be lost behind a long day/observations list.
    groups = [day_items, thought_items, data_items, personal]
    offset = now.toordinal() % len(groups)
    groups = groups[offset:] + groups[:offset]
    selected, seen = [], set()
    while any(groups) and len(selected) < limit:
        for group in groups:
            if not group or len(selected) >= limit:
                continue
            item = group.pop(0)
            identity = json.dumps(item["raw"], sort_keys=True)
            if identity not in seen:
                selected.append(item)
                seen.add(identity)
    return selected


# ── The session ───────────────────────────────────────────────────────────────

def due(now: datetime, idle: float, busy: bool) -> bool:
    """A clock time never authorizes an interview; autonomous inquiry owns timing."""
    return False


async def start(log, now: datetime, extended: bool = False) -> str | None:
    """An explicit request permits one fresh brain decision, never a saved queue."""
    stop()
    line = await talk.compose(log, 'learning' if extended else 'day_review', talk.load(), now)
    _save({'day': now.date().isoformat(), 'active': bool(line), 'queue': [],
           'total': int(bool(line)), 'session_id': time.time_ns(), 'extended': extended})
    if not line:
        return None
    talk._record(line, WHERE, now.timestamp())
    return line['say']


async def _ask_next() -> str | None:
    stop()  # persisted pre-upgrade queues must not replay
    return None


def heard(felt: str, pending: dict, message: str) -> None:
    """talk.hear's call: the Boss reacted to one of tonight's questions. Keep the answer; ask the next, or stop."""
    state = load()
    if not state.get("active") or pending.get("where") != WHERE:
        return
    if felt == "answered":
        with answers_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"day": state["day"], "question": pending.get("question"), "answer": message},
                               ensure_ascii=False) + "\n")
    _save({**state, 'active': False, 'queue': []})


async def _carry_on(more: bool, session_id=None) -> None:
    """Old callbacks cannot resume a retired fixed question sequence."""
    stop()


def stop() -> None:
    """No answer at all (talk.py): the session is over."""
    state = load()
    if state.get("active") or state.get('queue'):
        _save({**state, "active": False, "queue": []})


def match_evening_command(text: str) -> dict | None:
    if _LEARN.match(text.strip(" ?!.")):
        return {"type": "system", "action": EVENING_ACTION, "extended": True}
    return {"type": "system", "action": EVENING_ACTION} if _ASK.match(text.strip(" ?!.")) else None
