"""Render facts in FRIDAY's voice using local and owner-approved templates."""

from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import random
import re
import sqlite3
import unicodedata

from core.config import config
from core.logger import logger

COOLDOWN = timedelta(days=3)
BANDS = ("calm", "focused", "neutral", "bright")


def _bands(calm, focused, neutral, bright):
    return dict(zip(BANDS, (calm, focused, neutral, bright)))


HEADS = {
    "greeting": _bands(
        ("Hello{boss}.", "I'm here{boss}.", "Hi{boss}."),
        ("Ready{boss}.", "I'm here{boss}.", "Hello{boss}."),
        ("I'm here{boss}.", "Hello{boss}.", "Hi there{boss}."),
        ("Ready whenever you are{boss}.", "Hey{boss}.", "Hello there{boss}."),
    ),
    "thanks": _bands(
        ("You're welcome{boss}.", "Of course{boss}.", "Anytime{boss}."),
        ("You're welcome{boss}.", "Glad to help{boss}.", "Of course{boss}."),
        ("Anytime{boss}.", "You're welcome{boss}.", "Happy to help{boss}."),
        ("My pleasure{boss}.", "Glad that helped{boss}.", "Always welcome{boss}."),
    ),
    "goodbye": _bands(
        ("Talk later{boss}.", "Take care{boss}.", "See you later{boss}."),
        ("Until next time{boss}.", "See you later{boss}.", "Talk soon{boss}."),
        ("Talk later{boss}.", "Until next time{boss}.", "See you around{boss}."),
        ("Catch you later{boss}.", "See you soon{boss}.", "Till next time{boss}."),
    ),
    "start": _bands(
        ("I'm here{boss}.", "Ready when you are{boss}.", "Hello{boss}."),
        ("Online{boss}.", "Ready to help{boss}.", "I'm ready{boss}."),
        ("Online{boss}.", "I'm here{boss}.", "Ready when you are{boss}."),
        ("Hello there{boss}.", "Back online{boss}.", "Ready to go{boss}."),
    ),
    "back": _bands(
        ("Welcome back{boss}.", "Hello again{boss}.", "I'm here{boss}.", "Good to have you back{boss}."),
        ("Ready when you are{boss}.", "Welcome back{boss}.", "I'm here to help{boss}.", "Hello again{boss}."),
        ("Welcome back{boss}.", "Hello again{boss}.", "Good to have you back{boss}.",
         "Good to see you again{boss}.", "I'm here{boss}.", "Ready when you are{boss}.",
         "Nice to have you back{boss}.", "Hi again{boss}.", "Back with you{boss}."),
        ("Good to see you again{boss}!", "Welcome back{boss}!", "Hello again{boss}!", "Hi there again{boss}."),
    ),
    "checkin": _bands(
        ("Checking in{boss}.", "How are things{boss}?", "How's it going{boss}?"),
        ("How's it going{boss}?", "How's the work going{boss}?", "How are things coming along{boss}?"),
        ("How's it going{boss}?", "How are things{boss}?", "A quick check-in{boss}."),
        ("How are we getting on{boss}?", "How's it shaping up{boss}?", "How are things looking{boss}?"),
    ),
    "stress_ack": _bands(
        ("Understood{boss}. I'll keep it brief.", "I'll keep this short{boss}.", "I hear you{boss}."),
        ("I'll keep it brief{boss}.", "Understood{boss}.", "I'll keep this short{boss}."),
        ("Understood{boss}. I'll keep it brief.", "I hear you{boss}.", "We can take it one step at a time{boss}."),
        ("I hear you{boss}.", "I'll keep it brief{boss}.", "Understood{boss}."),
    ),
    "task_done": _bands(
        ("{name} is complete.", "Finished {name}.", "Done with {name}."),
        ("{name} is complete.", "Completed {name}.", "{name} is done."),
        ("{name} is done{boss}.", "Finished {name}{boss}.", "Done with {name}{boss}."),
        ("{name} is done{boss}!", "All done with {name}{boss}.", "That's {name} finished{boss}."),
    ),
    "exam_soon": _bands(
        ("{subject} is {when}.", "{subject} is scheduled {when}.", "{subject}{boss}, {when}."),
        ("{subject} is {when}.", "{subject} is scheduled {when}.", "A heads-up{boss}, {subject} is {when}."),
        ("{subject} is {when}{boss}.", "Reminder{boss}, {subject} is {when}.", "{subject} is scheduled {when}."),
        ("Reminder{boss}, {subject} is {when}.", "{subject} is {when}{boss}.", "{subject} is scheduled {when}."),
    ),
    "new": _bands(
        ("What is {program}{window}?", "What's {program}{window} used for?", "Can you place {program}{window}?"),
        ("What is {program}{window}?", "What's {program}{window} used for?", "What sort of app is {program}{window}?"),
        ("That's new{boss}. What is {program}{window}?", "What do you use {program}{window} for?", "What's {program}{window}?"),
        ("New one{boss}. What is {program}{window}?", "What's {program}{window} used for?", "What sort of app is {program}{window}?"),
    ),
    "unknown": _bands(
        ("What is {name}{window}?", "Can you place {name}{window}?", "What's {name}{window}?"),
        ("What is {name}{window}?", "What's {name}{window} used for?", "Can you identify {name}{window}?"),
        ("What is {name}{window}{boss}?", "What's {name}{window} used for?", "Can you place {name}{window}?"),
        ("New to me{boss}. What's {name}{window}?", "Can you place {name}{window}?", "What's {name}{window} used for?"),
    ),
    "feeling": _bands(
        ("Feeling {mood}, Boss.", "Feeling {mood}, Boss, for now.", "Feeling {mood}, Boss. Here if you need me."),
        ("Feeling {mood}, Boss.", "Feeling {mood}, Boss. Ready when you are.", "Feeling {mood}, Boss, this moment."),
        ("Feeling {mood}, Boss.", "Feeling {mood}, Boss, at the moment.", "Feeling {mood}, Boss, just now."),
        ("Feeling {mood}, Boss.", "Feeling {mood}, Boss. Ready to get going.", "Feeling {mood}, Boss, right now."),
    ),
    "joke": {
        "neutral": (
            "I tried to organise my thoughts, Boss. They asked for another folder.",
            "I asked the calculator to keep it simple. It said that wasn't a function.",
            "I told the taskbar to take a break. It said it was pinned down.",
            "The clock said it would take a minute. Technically, it kept its word.",
            "I tried to tidy the desktop. The recycling bin offered to supervise.",
            "I asked the keyboard for a little space. It was ready for that one.",
        ),
    },
}

# Each tail is a complete optional sentence. Combining it with a head creates its own template.
TAILS = {
    "greeting": (
        ("What are we doing today?", "How can I help?", "What would you like to do?"),
        ("Let me know what you'd like to start with.", "Tell me what's on the agenda when you're ready."),
    ),
    "start": (
        ("What's on the agenda?", "What are we doing this session?", "Where shall we start?"),
        ("Tell me what you'd like to work on first.", "Let me know what you want to tackle this session."),
    ),
    "task_done": (
        ("",),
        ("Ready for the next item whenever you are.", "We can move on whenever you're ready."),
    ),
    "back": (
        (
            "We can pick up whenever you're ready.", "What would you like to do next?",
            "I'm here if you need a hand.", "We can carry on when you're ready.",
            "Say the word when you want to continue.", "Where shall we pick up?",
            "Let me know what's next.", "We can start fresh or carry on.",
            "I'm here if you'd like to resume.", "Tell me where you'd like to start.",
        ),
        (
            "Tell me what you'd like to pick up, and we can take it from there.",
            "We can return to what you were doing or start something new whenever you're ready.",
            "If you'd like to carry on, tell me what you want to work on first.",
        ),
    ),
}

SUPPORTED = frozenset(HEADS) | {"command", "graph_answer"}
REQUIRED = {
    "task_done": ("name",), "exam_soon": ("subject", "when"), "new": ("program",),
    "unknown": ("name",), "feeling": ("mood",),
}


def _clock(now):
    if now is None:
        return datetime.now()
    return now if isinstance(now, datetime) else datetime.fromtimestamp(now)


def _word_key(line):
    text = unicodedata.normalize("NFKC", line).casefold().replace("’", "'")
    return " ".join(re.findall(r"\w+(?:'\w+)*", text))


def _choose(rows, now):
    """Atomically reserve a phrase and its template across speakers and restarts."""
    path = config.MEMORY_DIR / "mind" / "expression.db"
    stamp = now.timestamp()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=.1)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS recent (identity TEXT PRIMARY KEY, spoken_at REAL NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM recent WHERE spoken_at <= ?", (stamp - COOLDOWN.total_seconds(),))
            used = {row[0] for row in db.execute("SELECT identity FROM recent")}
            for template, line, callback in rows:
                identities = ["template:" + template, "line:" + _word_key(line)]
                if callback:
                    identities.append("callback:" + callback)
                hashes = [hashlib.sha256(identity.encode("utf-8")).hexdigest() for identity in identities]
                if used.isdisjoint(hashes):
                    db.executemany("INSERT INTO recent VALUES (?, ?)", ((key, stamp) for key in hashes))
                    return line
    except (OSError, sqlite3.Error) as error:
        logger.debug("Expression history unavailable (%s)", type(error).__name__)
    return None


def claim(template_id: str, text: str, *, now=None, joke=False) -> bool:
    """Share the recent-line check with personality's existing quips."""
    identity = ("joke:" if joke else "") + template_id
    return bool(text.strip() and _choose(((identity, text, None),), _clock(now)))


def humour_allowed(snapshot: Mapping, situation=None, *, explicit=False) -> bool:
    from services.automation import personality

    where = situation if isinstance(situation, str) else None
    emotion = snapshot.get("emotion", {})
    return bool((explicit or personality.is_on()) and not emotion.get("owner_stressed") and not snapshot.get("focus")
                and not snapshot.get("quiet") and where not in {"study", "deadline", "exam", "late"})


def _callback(kind, fields, situation, snapshot, now, rng):
    if kind != "task_done" or not humour_allowed(snapshot, situation):
        return None
    from services.mind import humour

    where = situation if isinstance(situation, str) else "chill"
    if not humour.should_joke(where, rng=rng):
        return None
    topic = fields["name"]
    temporal = situation if isinstance(situation, Mapping) else snapshot.get("situation", {})
    for row in temporal.get("closed", ()):
        quote, noted = row.get("quote", ""), row.get("source_noted", "")
        if (row.get("status") != "completed" or row.get("superseded_by")
                or row.get("subject", "").casefold() != topic.casefold()
                or not re.fullmatch(r"I (?:finished|completed) " + re.escape(topic) + r"[.!]?", quote, re.I)):
            continue
        try:
            day = datetime.fromisoformat(noted).date()
        except (TypeError, ValueError):
            continue
        if day < now.date():
            return str(row.get("id") or noted), f"On {day:%B} {day.day}, you said you'd finished it."
    return None


def _traits(snapshot, now):
    sheet = snapshot.get("character")
    if sheet is None:
        from services.mind import character
        sheet = character.snapshot(now)
    return sheet["traits"]


def render(raw: Mapping, situation, snapshot: Mapping, *, now=None) -> str | None:
    """Render only supported safe intents. None leaves the caller its literal fallback."""
    kind = raw.get("kind")
    if kind not in SUPPORTED:
        return None
    if kind == 'graph_answer':
        return str(raw['fact'])
    if now is None and snapshot.get("as_of"):
        now = datetime.fromisoformat(snapshot["as_of"])
    now = _clock(now)
    emotion = snapshot.get("emotion", {})
    band = emotion.get("band", "neutral")
    stressed = bool(emotion.get("owner_stressed"))
    if stressed:
        band = "calm"
    elif (snapshot.get("focus") or situation in ("study", "deadline", "exam")) and band != "calm":
        band = "focused"
    elif band not in BANDS:
        band = "neutral"
    if kind == "joke" and not humour_allowed(snapshot, situation, explicit=True):
        return None

    traits = _traits(snapshot, now)
    verbosity = traits.get("verbosity", .5)
    brief = stressed or verbosity < .35 or emotion.get("chatty", .5) < .25
    full = not brief and verbosity >= .7
    boss = ", Boss" if traits.get("warmth", .5) >= .4 and traits.get("formality", .5) < .72 else ""
    fields = {"boss": boss}
    for name in REQUIRED.get(kind, ()):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            return None
        fields[name] = value
    fields["window"] = f" ({raw['its_window']})" if raw.get("its_window") else ""
    detail = ""
    if kind == "back" and raw.get("before_leaving"):
        detail = f" You were {raw['before_leaving']}."
    elif kind == "checkin" and raw.get("the_boss_is"):
        detail = f" You've been {raw['the_boss_is']} for {raw['for_minutes']} minutes."
    elif kind == "feeling":
        if raw.get("because") and not brief:
            detail = f" Reason: {raw['because'].rstrip('.')}."
        if raw.get("my_day_so_far") and (raw.get("include_day") or full):
            detail += f" Today, {raw['my_day_so_far']}"

    rng = random.Random(f"{kind}:{now.timestamp()}")
    grouped = HEADS.get(kind, {})
    heads = grouped.get(band, grouped.get("neutral", ()))
    if kind == "task_done" and raw.get("owner_report"):
        heads = ("Recorded {name} as complete.", "Marked {name} complete{boss}.",
                 "Saved your completion report for {name}.")
    tails = TAILS[kind][int(full)] if not brief and kind in TAILS else ("",)
    return_marker = f"return:{raw['return_event']}" if raw.get("return_event") is not None else None
    rows = [(kind + ":" + head + tail, head.format_map(fields) + detail + (" " + tail if tail else ""), return_marker)
            for head in heads for tail in tails]
    if kind != "joke":
        rng.shuffle(rows)
    if kind == "greeting" and band == "neutral":
        rows.sort(key=lambda row: not row[1].startswith("I'm here"))

    fact = raw.get("fact", "")
    if (fact and not stressed and not snapshot.get("quiet") and "\n" not in fact and "?" not in fact
            and len(fact.split()) <= (12 if brief else 30)):
        from services.mind import writers_room

        approved = [(f"approved:{item['id']}", item["template"].replace("{fact}", fact, 1), None)
                    for item in writers_room.approved_templates(kind, band)
                    if boss or ", Boss" not in item["template"]]
        approved = [row for row in approved if len(row[1].split()) <= (12 if brief else 30)]
        rng.shuffle(approved)
        rows = approved + rows

    if not brief and (callback := _callback(kind, fields, situation, snapshot, now, rng)):
        identity, sentence = callback
        rows = [(template, line + " " + sentence, identity) for template, line, _ in rows
                if len((line + " " + sentence).split()) <= 30] + rows
    return _choose(rows, now) if rows else None
