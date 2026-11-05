"""
services/activity/habits.py

The habit engine (1.0): learns what the user does at the same time of day, what they open after
what, and which apps they open together — from the activity log, by counting (no AI, all local) —
and suggests it at the right moment. Learns from the answers.

What it learns (services/activity/habit_patterns.py; the last LOOKBACK_DAYS days, weekdays and weekends apart):
  - time habits: a thing (an app, a website or a saved project) started around the same time
                 on MIN_DAYS+ days — "weekdays around 10:15 PM: catjang"
  - chains:      Y started within CHAIN_MINUTES after X, on MIN_DAYS+ days and in CHAIN_SHARE+ of
                 X's starts — "after code: spotify"
  - routines:    2–MAX_ROUTINE apps launched together (within BURST_MINUTES) on MIN_DAYS+ days →
                 "save them as a routine?"
A "start" is using a thing again after START_GAP_MINUTES without it (time in front; sites: a visit).

Suggesting (services/proactive/watcher.py, once a minute): only while the user is active and not
busy or in quiet hours, only things that aren't open already, each habit once a day, at most
DAILY_LIMIT a day. Buttons: Open it / Resume it / Save it, Not now, Stop suggesting (buttons.py).
Confidence = how often the pattern held × how the user answered; "Not now" LATER_LIMIT times in a
row pauses a habit for PAUSE_DAYS days; "Stop suggesting" mutes it.

Every suggestion is saved with its features, and every answer (or "ignored"), in
memory/habit_examples.jsonl — the labelled data a trained model (2.0) can learn from.

Commands: "what are my habits", "why did you suggest that", "forget the spotify habit",
"pause habit suggestions", "resume habit suggestions". State: memory/habits.json.
"""

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import NamedTuple

from core.config import config
from core.logger import logger
from services.activity.categories import categorize
from services.activity.habit_patterns import (  # the learning half
    APP_NAMES, APP_OPEN_AS, CHAIN_MINUTES, LOOKBACK_DAYS, MIN_DAYS, Habit, learn, prune, starts,
)

state_path = config.MEMORY_DIR / "habits.json"  # tests point these elsewhere
examples_path = config.MEMORY_DIR / "habit_examples.jsonl"

SUGGEST_EARLY, SUGGEST_LATE = 5, 20  # minutes before/after a habit's usual time when it may be suggested
DAILY_LIMIT = 3
MIN_CONFIDENCE = 0.3
LATER_LIMIT = 3
PAUSE_DAYS = 7
PENDING_HOURS = 2                 # not answered by then: counted as ignored
RECENT_HOURS = 2                  # a site / project used this recently counts as open
RELEARN_MINUTES = 15
MAX_LISTED = 8
BUTTONS = {"app": "habit", "site": "habit", "project": "habit_project", "routine": "habit_routine"}

HABIT_ACTIONS = {"list_habits", "why_habit", "forget_habit", "pause_habits", "resume_habits"}
_LIST = re.compile(r"^(?:(?:what are|show(?: me)?|list|tell me)(?: all)? my habits|my habits"
                   r"|what habits (?:do i have|have you (?:learned|found|noticed)))$", re.I)
_WHY = re.compile(r"^why (?:did|do) you suggest (?:that|this|it)$|^why that suggestion$", re.I)
_FORGET = re.compile(r"^(?:forget|delete|remove)(?: the| my)? (?P<a>.+?) habits?$|^(?:stop|don't|do not) suggesting (?P<b>.+)$", re.I)
_PAUSE = re.compile(r"^(?:pause|stop|turn off|disable) (?:the |my |all )?habit suggestions$", re.I)
_RESUME = re.compile(r"^(?:resume|start|turn on|enable|unpause) (?:the |my )?habit suggestions$", re.I)


class Context(NamedTuple):
    """What's going on right now, for deciding what to suggest."""
    now: datetime
    app: str | None = None             # in front
    app_since: datetime | None = None
    project: str | None = None
    running: frozenset = frozenset()   # program names running
    recent_sites: frozenset = frozenset()
    recent_projects: frozenset = frozenset()
    routines: tuple = ()               # saved routines, as sets of the apps they open


class Suggestion(NamedTuple):
    id: str
    key: str
    text: str
    buttons: str   # the buttons.py kind
    minute: int | None = None  # a routine's usual time (its name: "evening setup")


_cache: dict = {}


def learned(log, now: datetime) -> tuple[list[Habit], dict[str, datetime]]:
    """learn() over the last LOOKBACK_DAYS, redone at most every RELEARN_MINUTES."""
    key = (log.db_path, now.date(), (now.hour * 60 + now.minute) // RELEARN_MINUTES)
    if _cache.get("key") != key:
        _cache.update(key=key, result=learn(log.habit_rows(now - timedelta(days=LOOKBACK_DAYS))))
    return _cache["result"]


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _record(state: dict, key: str) -> dict:
    return state.setdefault("habits", {}).setdefault(key, {"accepted": 0, "declined": 0, "ignored": 0, "later_streak": 0})


def _example(line: dict) -> None:
    """One line of training data: a suggestion with its features, or an answer to one."""
    try:
        with examples_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError as e:
        logger.warning(f"Couldn't save a habit example: {e}")


def confidence(habit: Habit, record: dict) -> float:
    """How often the pattern held, lowered by "Not now" and unanswered suggestions, raised back by "Open it"."""
    accepted = record.get("accepted", 0)
    return habit.support * (accepted + 1) / (accepted + record.get("declined", 0) + 0.5 * record.get("ignored", 0) + 1)


def _muted_things(state: dict) -> set[str]:
    from services.proactive import watcher  # the old habit nudge's "Don't suggest this" still counts

    return set(state.get("muted_things", [])) | {f"app:{a}" for a in watcher.load_state().get("muted_habits", [])}


def _expire(state: dict, now: datetime) -> None:
    """Suggestions nobody answered within PENDING_HOURS count as ignored."""
    pending = state.setdefault("pending", {})
    for sid, item in list(pending.items()):
        if now.timestamp() - item["at"] > PENDING_HOURS * 3600:
            del pending[sid]
            _record(state, item["key"])["ignored"] += 1
            _example({"id": sid, "at": now.isoformat(timespec="seconds"), "answer": "ignored"})


# ── Suggesting ────────────────────────────────────────────────────────────────

def _name(thing: str) -> str:
    """What the user calls it: "Windows Terminal", "github.com", "catjang"."""
    kind, name = thing.split(":", 1)
    return APP_NAMES.get(name, name) if kind == "app" else name.removeprefix("www.")


def _clock(minute: int) -> str:
    return datetime(2000, 1, 1, minute // 60, minute % 60).strftime("%I:%M %p").lstrip("0")


def _listing(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _doing(thing: str) -> str:
    kind, name = thing.split(":", 1)[0], _name(thing)
    return {"app": f"open {name}", "site": f"go to {name}", "project": f"work on {name}"}[kind]


def command_for(thing: str) -> str:
    """The FRIDAY command that does a thing: "open vs code", "go to github.com", "resume catjang"."""
    kind, name = thing.split(":", 1)
    return {"app": f"open {APP_OPEN_AS.get(name, name)}", "site": f"go to {name}", "project": f"resume {name}"}[kind]


def due_now(log, now: datetime) -> list[Habit]:
    """Time habits and chains due right now and not muted, most confident first (for the command bar)."""
    state, (found, _) = load_state(), learned(log, now)
    if not found:
        return []
    ctx, muted = context(log, now), _muted_things(state)
    records = state.get("habits", {})
    due_ones = [h for h in found if h.kind != "routine" and not records.get(h.key, {}).get("muted")
                and not muted & set(h.things) and due(h, ctx)]
    return sorted(due_ones, key=lambda h: -confidence(h, records.get(h.key, {})))


def is_open(thing: str, ctx: Context) -> bool:
    kind, name = thing.split(":", 1)
    if kind == "app":
        return name in ctx.running
    if kind == "site":
        return name in ctx.recent_sites
    return name == ctx.project or name in ctx.recent_projects


def due(habit: Habit, ctx: Context) -> bool:
    """Whether now is the moment for this habit."""
    minute = ctx.now.hour * 60 + ctx.now.minute
    around_usual = habit.minute is not None and habit.minute - SUGGEST_EARLY <= minute <= habit.minute + SUGGEST_LATE
    if habit.kind == "time":
        return (ctx.now.weekday() >= 5) == habit.weekend and around_usual and not is_open(habit.things[0], ctx)
    if habit.kind == "chain":
        trigger, thing = habit.things
        just_started = ctx.app_since and ctx.now - ctx.app_since <= timedelta(minutes=CHAIN_MINUTES)
        return bool(just_started and trigger in (f"app:{ctx.app}", f"project:{ctx.project}") and not is_open(thing, ctx))
    apps = {APP_OPEN_AS.get(name, name) for name in (t.split(":", 1)[1] for t in habit.things)}  # as routines say it
    return around_usual and not any(apps <= saved for saved in ctx.routines)  # a routine: until it's saved


def text_for(habit: Habit) -> str:
    if habit.kind == "routine":
        return f"You often open {_listing([_name(t) for t in habit.things])} together. Save them as a routine?"
    thing = habit.things[-1]
    ask = "Resume it?" if thing.startswith("project:") else "Open it?"
    if habit.kind == "chain":
        return f"You usually {_doing(thing)} after {_name(habit.things[0])}. {ask}"
    days = "weekends" if habit.weekend else "weekdays"
    return f"You usually {_doing(thing)} around {_clock(habit.minute)} on {days}. {ask}"


def reason_for(habit: Habit, record: dict) -> str:
    """Why it was suggested, in words."""
    if habit.kind == "time":
        pattern = (f"you {_doing(habit.things[0])} around {_clock(habit.minute)} on {habit.days} of the last "
                   f"{habit.observed} {'weekend' if habit.weekend else 'week'}days I've seen")
    elif habit.kind == "chain":
        pattern = f"you {_doing(habit.things[1])} within {CHAIN_MINUTES} minutes after {_name(habit.things[0])} on {habit.days} days"
    else:
        pattern = f"you opened {_listing([_name(t) for t in habit.things])} together on {habit.days} days"
    answers = f"; you said yes {record.get('accepted', 0)} and not now {record.get('declined', 0)} times" \
        if record.get("accepted") or record.get("declined") else ""
    return f"Because {pattern}{answers}. Confidence {confidence(habit, record):.0%}."


def pick(habits: list[Habit], state: dict, ctx: Context) -> Habit | None:
    """The habit to suggest now, if any: the most confident one that's due and allowed."""
    today = state.get("today", {})
    suggested = today.get("suggested", []) if today.get("date") == ctx.now.date().isoformat() else []
    if len(suggested) >= DAILY_LIMIT:
        return None
    muted = _muted_things(state)
    options = []
    for habit in habits:
        record = state.get("habits", {}).get(habit.key, {})
        if (record.get("muted") or record.get("paused_until", 0) > ctx.now.timestamp() or habit.key in suggested
                or muted & set(habit.things) or confidence(habit, record) < MIN_CONFIDENCE or not due(habit, ctx)):
            continue
        options.append((confidence(habit, record), habit))
    return max(options, key=lambda option: option[0])[1] if options else None


def features(habit: Habit, record: dict, ctx: Context, last_seen: dict[str, datetime], suggested_today: int) -> dict:
    """What a trained model (2.0) will learn from: the moment, the habit, and the history of answers."""
    minute = ctx.now.hour * 60 + ctx.now.minute
    last = last_seen.get(habit.things[-1])
    return {
        "kind": habit.kind, "thing_type": habit.things[-1].split(":", 1)[0], "hour": ctx.now.hour,
        "minute_of_day": minute, "weekday": ctx.now.weekday(), "weekend": ctx.now.weekday() >= 5,
        "days": habit.days, "observed": habit.observed, "support": round(habit.support, 3),
        "minutes_from_usual": minute - habit.minute if habit.kind == "time" else None,
        "app_in_front": ctx.app, "category_in_front": categorize("app", ctx.app) if ctx.app else None,
        "minutes_since_last_use": round((ctx.now - last).total_seconds() / 60) if last else None,
        "accepted_before": record.get("accepted", 0), "declined_before": record.get("declined", 0),
        "ignored_before": record.get("ignored", 0), "suggested_today": suggested_today,
        "confidence": round(confidence(habit, record), 3),
    }


def context(log, now: datetime) -> Context:
    """The present moment, read from the activity log, running programs and saved routines."""
    from services.activity.log import running_apps
    from services.automation import routines

    recent = log.habit_rows(now - timedelta(hours=RECENT_HOURS))
    try:
        saved = tuple({s.split(" ", 1)[1].strip().lower() for s in steps if s.lower().startswith("open ") and " " in s}
                      for steps in routines.load().values())
    except Exception:  # a broken routines.json shouldn't stop suggestions
        saved = ()
    return Context(now, log.app, log.app_since, log.project, frozenset(running_apps()),
                   frozenset(r[3] for r in recent if r[1] == "web" and r[3]),
                   frozenset(r[6] for r in recent if r[6]), saved)


def next_suggestion(log, now: datetime, ctx: Context | None = None) -> Suggestion | None:
    """The watcher's call (blocking): a suggestion to show now, recorded as shown; None most of the time."""
    state = load_state()
    if state.get("off"):
        return None
    before = json.dumps(state, sort_keys=True)
    _expire(state, now)
    habits, last_seen = learned(log, now)
    ctx = (ctx or context(log, now)) if habits else None
    habit = pick(habits, state, ctx) if habits else None
    if habit is None:
        if json.dumps(state, sort_keys=True) != before:
            _save_state(state)
        return None
    today = state.get("today", {})
    if today.get("date") != now.date().isoformat():
        today = {"date": now.date().isoformat(), "suggested": []}
    record = _record(state, habit.key)
    sid = uuid.uuid4().hex
    text = text_for(habit)
    _example({"id": sid, "at": now.isoformat(timespec="seconds"), "habit": habit.key, "text": text,
              "features": features(habit, record, ctx, last_seen, len(today["suggested"]))})
    today["suggested"].append(habit.key)
    state.update(today=today, last={"key": habit.key, "text": text, "reason": reason_for(habit, record)})
    state["pending"][sid] = {"key": habit.key, "at": now.timestamp()}
    _save_state(state)  # before showing it, so a failure can't repeat it every minute
    logger.info(f"Habit suggestion: {text}")
    kind = "routine" if habit.kind == "routine" else habit.things[-1].split(":", 1)[0]
    return Suggestion(sid, habit.key, text, BUTTONS[kind], habit.minute)


# ── Answers ───────────────────────────────────────────────────────────────────

def answer(about: dict, reply: str, now: datetime | None = None) -> str:
    """A button on a habit suggestion (buttons.py): "do", "later" or "never". Runs in a worker thread."""
    now = now or datetime.now()
    state, key = load_state(), about["habit"]
    state.setdefault("pending", {}).pop(about["id"], None)
    record = _record(state, key)
    _example({"id": about["id"], "at": now.isoformat(timespec="seconds"), "answer": reply})
    if reply == "never":
        record["muted"] = True
        _save_state(state)
        return "Okay, I won't suggest that again."
    if reply == "later":
        record["declined"] += 1
        record["later_streak"] += 1
        paused = record["later_streak"] >= LATER_LIMIT
        if paused:
            record.update(later_streak=0, paused_until=(now + timedelta(days=PAUSE_DAYS)).timestamp())
        _save_state(state)
        return f"Okay — I'll leave that one for {PAUSE_DAYS} days." if paused else "Okay, not now."
    record["accepted"] += 1
    record["later_streak"] = 0
    _save_state(state)
    return _do(key, about)


def _do(key: str, about: dict) -> str:
    kind, _, rest = key.partition(":")
    if kind == "routine":
        return save_routine(rest.split("+"), about.get("minute"))
    thing = rest.rsplit(":", 1)[0] if kind == "time" else rest.split(">", 1)[1]
    what, name = thing.split(":", 1)
    if what == "project":
        import asyncio
        from services.automation import intent

        resumed = asyncio.run_coroutine_threadsafe(intent._resume_project(name, config.ACTIVE_PROVIDER), about["loop"])
        return resumed.result(timeout=120).message
    from services.automation.system_control import system

    return system.open_url(f"https://{name}") if what == "site" else system.open_app(APP_OPEN_AS.get(name, name))


def save_routine(apps: list[str], minute: int | None = None) -> str:
    """Save apps opened together as a routine named after the time of day ("evening setup")."""
    from services.automation import routines

    saved = routines.load()
    hour = (minute or 0) // 60
    part = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 21 else "night"
    base = f"{part} setup"
    name, n = base, 2
    while name in saved:
        name, n = f"{base} {n}", n + 1
    routines._save(saved | {name: [f"open {APP_OPEN_AS.get(app, app)}" for app in apps]})
    return f'Saved the routine "{name}": open {_listing([_name(f"app:{a}") for a in apps])}. Say "run {name}" to use it.'


# ── Commands ──────────────────────────────────────────────────────────────────

def match_habit_command(text: str) -> dict | None:
    text = text.strip()
    if _LIST.match(text):
        return {"type": "system", "action": "list_habits"}
    if _WHY.match(text):
        return {"type": "system", "action": "why_habit"}
    if _PAUSE.match(text):
        return {"type": "system", "action": "pause_habits"}
    if _RESUME.match(text):
        return {"type": "system", "action": "resume_habits"}
    if m := _FORGET.match(text):
        return {"type": "system", "action": "forget_habit", "name": (m["a"] or m["b"]).strip(" .")}
    return None


def describe(habit: Habit) -> str:
    """One line for "what are my habits"."""
    if habit.kind == "time":
        days = "Weekends" if habit.weekend else "Weekdays"
        return f"{days} around {_clock(habit.minute)}: {_doing(habit.things[0])} ({habit.days} of {habit.observed} days)"
    if habit.kind == "chain":
        return f"After {_name(habit.things[0])}: {_doing(habit.things[1])} ({habit.days} days)"
    return f"Together: {_listing([_name(t) for t in habit.things])} ({habit.days} days)"


def run(parsed: dict, log, now: datetime | None = None) -> str:
    now = now or datetime.now()
    action, state = parsed["action"], load_state()
    if action == "pause_habits":
        _save_state(state | {"off": True})
        return 'Habit suggestions are off. Say "resume habit suggestions" to get them back.'
    if action == "resume_habits":
        _save_state(state | {"off": False})
        return "Habit suggestions are back on."
    if action == "why_habit":
        last = state.get("last")
        return f'I suggested: "{last["text"]}" {last["reason"]}' if last else "I haven't suggested anything yet."
    habits, _ = learn(log.habit_rows(now - timedelta(days=LOOKBACK_DAYS)))
    muted = _muted_things(state)
    live = [h for h in habits if not state.get("habits", {}).get(h.key, {}).get("muted") and not muted & set(h.things)]
    if action == "forget_habit":
        said = parsed["name"].lower()
        things = {t for h in habits for t in h.things if said in _name(t).lower()}
        if not things:
            return f"I don't have a habit about {parsed['name']}."
        _save_state(state | {"muted_things": sorted(set(state.get("muted_things", [])) | things)})
        return f"Okay, I won't suggest {_listing(sorted(_name(t) for t in things))} any more."
    if not live:
        days = len({datetime.fromisoformat(r[0]).date() for r in log.habit_rows(now - timedelta(days=LOOKBACK_DAYS))})
        return (f"No habits yet — I need the same thing on at least {MIN_DAYS} days in the last {LOOKBACK_DAYS}. "
                f"I have {days} day{'s' if days != 1 else ''} of activity so far.")
    live.sort(key=lambda h: (-h.support, -h.days))
    lines = [describe(h) for h in live[:MAX_LISTED]]
    more = f" (and {len(live) - MAX_LISTED} more)" if len(live) > MAX_LISTED else ""
    off = " Suggestions are paused." if state.get("off") else ""
    return f"Your habits{more}: " + "; ".join(lines) + "." + off
