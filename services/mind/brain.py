"""
services/mind/brain.py

FRIDAY's brain: it watches every move the Boss makes and thinks about it by itself — no AI model anywhere
in this file. It runs with the activity tracker (services/activity/log.py), every few seconds:

  senses   sense(): each time the window in front changes, the app and what it's about (its cleaned
           title) are filed in her knowledge (services/mind/knowledge.py) and compared with what she
           knows: never seen before? back after weeks? at an hour it's never used? lots of flicking about?
  past     episodes(): the day cut into stretches of one thing ("9:10–9:50 working on friday"), with quick
           glances elsewhere folded in
  present  the episode going on now
  next     what was started and not come back to (dropped), which regular hasn't shown up (skipped), and
           the next app — her own counts against the trained model, verified by the Boss
           (services/mind/foresight.py)
  why      every thing that doesn't fit becomes a thought (services/mind/thoughts.py) carrying the raw
           facts and her own guess at the reason — the Boss's earlier answer for that pattern if there is
           one. What the Boss answers is kept as the reason, and teaches her what unknown things are.

think() runs once a minute (services/proactive/watcher.py) for what needs time to show, and
learn_something() is her curiosity: one lookup at a time for things she can't place (knowledge.look_up —
the only place a model is asked anything, and only "what is <name>?").

"what am I doing" / "where did I leave off" → timeline(): past, present and what's next.
"""

import re
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core.logger import logger
from services.activity.categories import app_category, categorize
from services.activity.log import _duration
from services.mind import foresight, knowledge, life, thoughts
from services.mind.cognition import cognition

GAP = timedelta(minutes=10)          # this long away from a thing ends its episode
GLANCE_SECONDS = 90                  # a shorter visit elsewhere is a glance, not a new episode
INTERLUDE = {"other", "system", "files", "communication", "music", "search"}  # a short spell of these between two
INTERLUDE_SECONDS = 600              # parts of the same thing doesn't split it (a reply, the desktop, a song)
MIN_EPISODE_SECONDS = 180
LOOKBACK = timedelta(hours=14)       # "today" for the timeline (a late night counts as the same day)
FOCUS = {"coding", "study", "documents", "ai"}  # plus anything in a saved project
LOOKUP_RETRY = timedelta(minutes=30)
LEISURE = {"entertainment", "gaming", "social", "shopping"}
DOING = {"coding": "coding", "study": "studying", "documents": "on documents", "ai": "talking to an AI",
         "gaming": "gaming", "entertainment": "watching things", "social": "on social media", "shopping": "shopping",
         "communication": "chatting", "music": "on music", "browsing": "browsing", "search": "searching",
         "files": "in File Explorer", "media": "on photos and media", "system": "in system windows"}
JUMP_FOCUS_MINUTES = 25              # leaving this much focused work for leisure makes her wonder
DROPPED_MINUTES = 20                 # a focused episode at least this long …
DROPPED_AFTER_MINUTES = 45           # … not come back to for this long
RETURN_DAYS = 14
REGULAR_DAYS = 5                     # seen on this many days = she knows its hours
REGULAR_SHARE = 0.6                  # there by this hour on this share of days = a regular
SETTLED_MINUTES = 30                 # nothing counts as missing until the Boss has been at it this long
RESTLESS_SWITCHES, RESTLESS_MINUTES = 12, 5
# Her first guess at why, until the Boss has told her (thoughts.reason_for)
GUESSES = {"entertainment": "taking a break", "gaming": "done for now, or dodging it", "social": "a quick scroll",
           "shopping": "something caught their eye"}
BRAIN_ACTIONS = {"brain_timeline", "brain_thing"}

_NOW = re.compile(r"^(?:what am i (?:doing|working on|up to)(?: right now| now)?|what was i (?:doing|working on|up to)"
                  r"(?: before| earlier| today)?|where (?:did i leave off|was i)|what(?:'s| is| has) my day (?:been )?like"
                  r"(?: so far)?|what (?:have i|did i) (?:left|leave) (?:hanging|unfinished))$", re.I)
_THING = re.compile(r"^what (?:do|did) you (?:know|learn|find out) about (?P<name>[\w .+\-']{2,60})$", re.I)

_cur: dict | None = None             # the stretch going on: app, topic, since
_switches: deque = deque(maxlen=60)  # when the app in front changed, lately
_away_since: datetime | None = None
_next_lookup: datetime | None = None  # after a lookup no model answered: when to try again
_started = False


@dataclass
class Episode:
    thread: str                      # the saved project, else the category
    category: str
    start: datetime
    end: datetime
    seconds: float = 0
    things: Counter = field(default_factory=Counter)  # what it was about (topics) → seconds
    apps: Counter = field(default_factory=Counter)

    @property
    def focus(self) -> bool:
        return self.category in FOCUS or self.category == "project"

    def label(self) -> str:
        doing = f"working on {self.thread}" if self.category == "project" else DOING.get(self.category, self.category)
        about = [name for name, _ in self.things.most_common(2)] or [name for name, _ in self.apps.most_common(1)]
        return doing + (f" ({', '.join(about)})" if about else "")


# ── Senses ────────────────────────────────────────────────────────────────────

def start(log) -> None:
    """Once, when the tracker starts: load what she's learned, and the first time ever, go through
    everything already in the activity log so she starts out knowing the Boss's past."""
    global _started
    _started = True
    knowledge.refresh_learned()
    if not knowledge.is_empty():
        return
    rows = log.moves(datetime.min, datetime.max)
    with knowledge.db() as conn:
        for at, app, title, seconds, category, _project in rows:
            when = datetime.fromisoformat(at)
            knowledge.see(conn, "app", app, app_category(app), when, knowledge.topic_of(app, title))
            knowledge.spend(conn, "app", app, seconds or 0)
            if topic := knowledge.topic_of(app, title):
                knowledge.see(conn, "topic", topic, category or "other", when)
                knowledge.spend(conn, "topic", topic, seconds or 0)
    logger.info(f"Brain: went through {len(rows)} past moves")


def sense(log, now: datetime | None = None) -> None:
    """One look at what's in front (every tick of the tracker). Does nothing unless it changed."""
    global _cur, _away_since
    now = now or datetime.now()
    if not _started:
        start(log)
    app = log.app
    topic = knowledge.topic_of(app, log.title)
    if _cur and (_cur["app"], _cur["topic"]) == (app, topic):
        with knowledge.db() as conn:
            seconds = max(0, (now - _cur.get("accounted", _cur["since"])).total_seconds())
            if getattr(log, "last_observed_at", None) and seconds > 20:
                seconds = 0
            knowledge.spend(conn, "app", app, seconds)
            if topic:
                knowledge.spend(conn, "topic", topic, seconds)
        _cur["accounted"] = now
        return
    before = _cur
    with knowledge.db() as conn:
        if before:  # the stretch that just ended
            seconds = max(0, (now - before.get("accounted", before["since"])).total_seconds())
            if getattr(log, "last_observed_at", None) and seconds > 20:
                seconds = 0
            knowledge.spend(conn, "app", before["app"], seconds)
            if before["topic"]:
                knowledge.spend(conn, "topic", before["topic"], seconds)
        if not app:  # idle / away
            if before:
                cognition.record("observation", "activity", "Boss is away or idle", public=True)
            _cur, _away_since = None, _away_since or now
            return
        category = "project" if log.project else categorize("app", app, title=log.title)
        knew_app = knowledge.see(conn, "app", app, app_category(app), now, topic)
        if topic:
            knowledge.see(conn, "topic", topic, category, now)
    _away_since = None
    if not before or before["app"] != app:
        cognition.record("observation", "activity", f"Boss's current activity: {app_category(app)}", public=True)
        _switches.append(now)
        foresight.moved(log, app, now)  # both predictors are scored on this move, and guess the next one
    _cur = {"app": app, "topic": topic, "since": now, "accounted": now}
    _notice(now, app, topic, app_category(app, log.title), knew_app)


def awareness() -> dict:
    """The brain's shared view of what FRIDAY said/did as well as what she sensed."""
    from services.mind.cognition_context import live_state
    from services.memory import schedule
    from services.mind.workspace import workspace
    from services.mind.reasoning_store import reasoning_store

    return {"live": live_state(), "events": cognition.recent(), "dated_facts": schedule.active(datetime.now()),
            "workspace": workspace.context(), "reasoning": reasoning_store.context()}


def away_minutes(now: datetime) -> float:
    return (now - _away_since).total_seconds() / 60 if _away_since else 0.0


def _wonder(kind: str, subject: str, data: dict, strength: float, now: datetime) -> None:
    if thoughts.add(kind, subject, data, strength, now):
        life.feel("noticed", now.timestamp())
        from services import body_state
        body_state.push("wonder")  # a "?" over her head
        logger.info(f"Brain: {kind} — {subject}")


def _hour(hour: int) -> str:
    return f"{(hour % 12) or 12} {'AM' if hour % 24 < 12 else 'PM'}"


def _notice(now: datetime, app: str, topic: str | None, category: str, knew: "knowledge.Thing | None") -> None:
    """A move just happened: does it fit what she knows?"""
    key = knowledge.key_for("app", app)
    if category != "system":
        if knew is None:
            _wonder("new", key, {"noticed": "a program I have never seen the Boss use before", "program": app,
                                 "its_window": topic, "i_file_it_under": category, "pattern": f"new:{app}"}, 0.9, now)
        elif (now - knew.last_seen).days >= RETURN_DAYS and knew.times >= 3:
            _wonder("returned", key, {"noticed": "the Boss is back on something they hadn't touched in a long time",
                                      "program": app, "what_it_is": knew.about or knew.category,
                                      "days_since_last_time": (now - knew.last_seen).days,
                                      "pattern": f"returned:{app}"}, 0.8, now)
        elif knew.days >= REGULAR_DAYS and not any(knew.hours[(now.hour + d) % 24] for d in (-1, 0, 1)):
            usual = sorted(range(24), key=lambda h: -knew.hours[h])[:3]
            _wonder("odd_hour", key, {"noticed": "the Boss is using something at a time of day they never do",
                                      "program": app, "what_it_is": knew.about or knew.category, "time_now": _hour(now.hour),
                                      "usual_times": [_hour(h) for h in sorted(usual)],
                                      "pattern": f"odd_hour:{app}"}, 0.6, now)
    recent = [t for t in _switches if now - t <= timedelta(minutes=RESTLESS_MINUTES)]
    if len(recent) >= RESTLESS_SWITCHES:
        pattern = "restless"
        _wonder("restless", pattern, {"noticed": "the Boss keeps flicking between windows without settling",
                                      "window_switches": len(recent), "in_minutes": RESTLESS_MINUTES,
                                      "my_guess": "looking for something, waiting on something, or bored",
                                      "last_time_the_boss_said": thoughts.reason_for(pattern), "pattern": pattern}, 0.5, now)


# ── Past and present ──────────────────────────────────────────────────────────

def episodes(log, now: datetime, since: datetime | None = None) -> list[Episode]:
    """The stretch from `since` (default: the last LOOKBACK) to now, cut into episodes, oldest first."""
    rows = list(log.moves(since or now - LOOKBACK, now))
    if log.app and log.title_since:  # the stretch going on isn't saved as a row yet
        category = "project" if log.project else categorize("app", log.app, title=log.title)
        rows.append((log.title_since.isoformat(), log.app, log.title, (now - log.title_since).total_seconds(),
                     category, log.project))
    runs: list[Episode] = []
    for at, app, title, seconds, category, project in rows:
        if not seconds:
            continue
        begin = datetime.fromisoformat(at)
        end = begin + timedelta(seconds=seconds)
        category = category or "other"
        thread = project or category
        if not (runs and runs[-1].thread == thread and begin - runs[-1].end <= GAP):
            runs.append(Episode(thread, category, begin, end))
        run = runs[-1]
        run.end = max(run.end, end)
        run.seconds += seconds
        run.apps["the desktop" if app == "explorer" and not title else app] += seconds
        if topic := knowledge.topic_of(app, title):
            run.things[topic] += seconds
    found: list[Episode] = []

    def carry_on(run: Episode) -> None:
        found[-1].end, found[-1].seconds = run.end, found[-1].seconds + run.seconds
        found[-1].things.update(run.things)
        found[-1].apps.update(run.apps)

    for run in runs:
        close = bool(found) and run.start - found[-1].end <= GAP
        if close and found[-1].thread == run.thread:  # the same thing, after a glance elsewhere
            carry_on(run)
        elif close and run.seconds < GLANCE_SECONDS:  # a glance: time passes, the episode goes on
            found[-1].end = run.end
        elif (close and len(found) >= 2 and found[-2].thread == run.thread and found[-1].category in INTERLUDE
              and found[-1].seconds < INTERLUDE_SECONDS and found[-1].start - found[-2].end <= GAP):
            found.pop()  # back to it after an interlude: one episode
            carry_on(run)
        else:
            found.append(run)
    return [e for e in found if e.seconds >= MIN_EPISODE_SECONDS]


def present(found: list[Episode], now: datetime) -> Episode | None:
    return found[-1] if found and now - found[-1].end <= GAP else None


def dropped(found: list[Episode], now: datetime) -> Episode | None:
    """The latest focused episode the Boss left a while ago and hasn't come back to."""
    for i in range(len(found) - 2, -1, -1):
        e = found[i]
        if (e.focus and e.seconds >= DROPPED_MINUTES * 60 and now - e.end >= timedelta(minutes=DROPPED_AFTER_MINUTES)
                and not any(later.thread == e.thread for later in found[i + 1:])):
            return e
    return None


# ── Thinking, once a minute ───────────────────────────────────────────────────

def think(log, now: datetime, busy: bool = False) -> None:
    """What only shows with time: a guess at what's next, a jump out of focused work, something left hanging,
    a regular that's missing."""
    try:
        for kind, subject, data, strength in foresight.think(log, now, busy):
            _wonder(kind, subject, data, strength, now)
    except Exception as e:  # a guess must never stop the rest of her thinking
        logger.warning(f"Foresight skipped: {e}")
    found = episodes(log, now)
    here = present(found, now)
    if not here:
        return
    before = found[-2] if len(found) >= 2 else None
    if (before and before.focus and before.seconds >= JUMP_FOCUS_MINUTES * 60 and here.category in LEISURE
            and here.start - before.end <= GAP):
        pattern = f"jump:{before.category}>{here.category}"
        _wonder("jump", pattern, {"noticed": "the Boss dropped focused work for something else",
                                  "was": before.label(), "for_minutes": round(before.seconds / 60), "now": here.label(),
                                  "my_guess": GUESSES.get(here.category),
                                  "last_time_the_boss_said": thoughts.reason_for(pattern), "pattern": pattern}, 0.7, now)
    left = dropped(found, now)
    if left and not here.focus:
        pattern = f"dropped:{left.thread}"
        _wonder("dropped", pattern, {"noticed": "the Boss started something and hasn't come back to it",
                                     "left": left.label(), "left_at": f"{left.end:%I:%M %p}".lstrip("0"),
                                     "minutes_ago": round((now - left.end).total_seconds() / 60), "now": here.label(),
                                     "last_time_the_boss_said": thoughts.reason_for(pattern), "pattern": pattern}, 0.6, now)
    if now - here.start < timedelta(minutes=SETTLED_MINUTES) or now.hour < 1:
        return  # the Boss has only just sat down: nothing is "missing" yet
    watched = knowledge.days_watched()
    by_hour, today = now.hour - 1, now.date().isoformat()
    missing = [t for t in knowledge.regulars(REGULAR_DAYS) if t.category != "system" and t.last_day != today
               and t.hours[by_hour] / watched >= REGULAR_SHARE]
    if missing:  # one at a time: the most regular of them
        thing = max(missing, key=lambda t: t.hours[by_hour])
        pattern = f"skipped:{thing.name}"
        _wonder("skipped", pattern, {"noticed": "a regular of the Boss's hasn't shown up today",
                                     "program": thing.name, "what_it_is": thing.about or thing.category,
                                     "usually_open_by": _hour(now.hour),
                                     "on_days": f"{thing.hours[by_hour]} of the {watched} days I've watched",
                                     "last_time_the_boss_said": thoughts.reason_for(pattern), "pattern": pattern}, 0.5, now)


async def learn_something(log, now: datetime) -> None:
    """Her curiosity, one thing a minute: look up what she can't place; ask the Boss when that doesn't help."""
    import asyncio
    global _next_lookup

    if _next_lookup and now < _next_lookup:
        return
    thing = await asyncio.to_thread(knowledge.due_lookup, now)
    if not thing:
        return
    known = await knowledge.look_up(thing, now)
    _next_lookup = None if known else now + LOOKUP_RETRY
    spent = _duration(thing.seconds)
    from services.mind import app_learning
    if app_learning.pending(thing.key):
        # The real question flow reads these versioned proposals. No category or personal fact changes yet.
        return
    if known and known.about and known.source in {"boss", "confirmed"}:
        life.feel("learned", now.timestamp())
        _wonder("learned", thing.key, {"noticed": "I looked up something the Boss uses, and now I know what it is",
                                       "name": thing.name, "it_is": known.about, "the_boss_has_spent": spent}, 0.6, now)
        await asyncio.to_thread(log.resort)  # old rows move to the category she just learned
    else:  # the model doesn't know it, or there's no model right now: the Boss will
        _wonder("unknown", thing.key, {"noticed": "something the Boss uses that I can't identify",
                                       "name": thing.name, "its_window": thing.hint, "the_boss_has_spent": spent,
                                       "ask": "what it is"}, 0.8, now)


def answered(thought_id: int, answer: str, now: datetime) -> None:
    """The Boss answered what she wondered: the reason is kept, and an unknown thing is no longer unknown."""
    thought = thoughts.answered(thought_id, answer, now)
    if thought and thought.kind in ("prediction", "automate"):  # yes / no: kept per pattern, and for the model
        foresight.answered(thought.kind, thought.data, answer, now)
    # Knowing a category doesn't mean she knows what it is: keep the Boss's explanation too.
    if thought and thought.kind in ("unknown", "new") and (thing := knowledge.get(thought.subject)):
        knowledge.teach(thing.key, answer)


def nightly(now: datetime) -> None:
    knowledge.prune(now)
    thoughts.forget_old(now)


# ── "What am I doing?" ────────────────────────────────────────────────────────

def match_brain_command(text: str) -> dict | None:
    text = text.strip(" ?!.")
    if _NOW.match(text):
        return {"type": "system", "action": "brain_timeline"}
    if (m := _THING.match(text)) and knowledge.find(m["name"]):  # a thing she has seen; people go to memory
        return {"type": "system", "action": "brain_thing", "name": m["name"]}
    return None


def timeline(log, now: datetime | None = None) -> str:
    """Past, present and what's next, in her own plain words."""
    from services.activity import predict

    now = now or datetime.now()
    found = episodes(log, now)
    earlier = found  # history remains useful even when no fresh foreground observation exists
    span = lambda e: f"{e.start:%H:%M}–{e.end:%H:%M}"
    from services.mind.activity_awareness import summary
    lines = [summary(log, now)]
    if earlier:
        lines.append("Recorded earlier (app/title-based categories): " + "; ".join(
            f"{span(e)} {e.label()}" for e in reversed(earlier[-5:])) + ".")
    if left := dropped(found, now):
        lines.append(f"Earlier focus: {left.label()}, last seen at {left.end:%H:%M}; completion is unknown.")
    try:
        guess = predict.predict_next(log, now)
        if guess.startswith("After"):
            lines.append("Next, going by your habits: " + guess[0].lower() + guess[1:])
    except Exception as e:  # a guess must never break the answer
        logger.info(f"Brain: no next-app guess: {e}")
    return "\n".join(lines)


def run(parsed: dict, log) -> str:
    if parsed["action"] == "brain_thing":
        thing = knowledge.find(parsed["name"])
        return knowledge.describe(thing) if thing else f"I haven't seen anything called {parsed['name']}."
    return timeline(log)
