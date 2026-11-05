"""Dated owner facts that constrain the weekly timetable, without an AI/embedding dependency.

Old explicitly remembered statements use their original receipt date. Temporary
changes never edit the weekly timetable or roll forward when FRIDAY restarts.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from core.logger import logger
from services.mind.cognition import redact

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NUMBERS = {word: number for number, word in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"))}
_OFF = re.compile(r"\b(?:no\s+(?:(?:regular|college|scheduled|my)\s+)?(?P<subject>[\w ]+?\s+)?(?:classes?|lectures?)"
                  r"|(?:won't|wont|will not|don't|dont|do not)\s+have\s+(?:any\s+|my\s+)?(?:classes?|lectures?)"
                  r"|(?:classes?|lectures?)\s+(?:are|is|will be)\s+(?:cancelled|canceled|off)|no college)\b", re.I)
_ON = re.compile(r"\b(?:classes?|lectures?)\s+(?:resume|restart|are back|will resume|start again)\b", re.I)
_QUESTION = re.compile(r"^(?:what|when|why|how|do|does|is|are|can|could|would|if|suppose|imagine|type|write|say|"
                       r"quote|search|look up|ask|note\b)\b", re.I)
_DURATION = re.compile(r"\b(?:for\s+(?:the\s+)?(?:next\s+)?|next\s+)(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
                       r"\s+(days?|weeks?)\b", re.I)
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_WEEKDAY = re.compile(r"\b(" + "|".join(DAYS) + r")\b", re.I)


@dataclass(frozen=True)
class Fact:
    key: str
    text: str
    noted: datetime
    start: date
    end: date
    available: bool
    subject: str = ""

    def covers(self, day, subject=""):
        return self.start <= day <= self.end and (not self.subject or self.subject.casefold() == subject.casefold())

    def context(self):
        return {"id": self.key, "fact": self.text, "from": self.start.isoformat(), "through": self.end.isoformat(),
                "classes_available": self.available, "subject": self.subject or "all regular classes"}


def parse(text: str, noted: datetime, key="") -> Fact | None:
    clean = text.replace("’", "'").strip()
    clean = re.sub(r"^(?:remember(?: that)?|please remember|actually)[ ,:]+", "", clean, flags=re.I)
    if _QUESTION.match(clean) or "?" in clean or re.search(
            r"\b(?:my friend|he|she|they|if|maybe|might|possibly|not sure)\b", clean, re.I):
        return None
    off, on = _OFF.search(clean), _ON.search(clean)
    if not (off or on):
        return None
    available = bool(on and (not off or on.start() > off.start()))
    subject = (off.groupdict().get("subject") or "").strip() if off else ""
    if subject.lower() in {"there are", "there is", "theres", "only", "any", "regular", "college", "scheduled"}:
        subject = ""
    start = noted.date() + timedelta(days=bool(re.search(r"\btomorrow\b", clean, re.I)))
    end = start
    try:
        dates = [date.fromisoformat(value) for value in _ISO.findall(clean)]
        duration = _DURATION.search(clean)
        weekdays = _WEEKDAY.findall(clean)
        if dates:
            start, end = dates[0], dates[-1]
        elif weekdays and re.search(r"\b(?:from|starting|beginning)\b", clean, re.I):
            start += timedelta(days=(DAYS.index(weekdays[0].lower()) - start.weekday()) % 7)
            end = start
        if duration and len(dates) <= 1:
            amount = int(duration[1]) if duration[1].isdigit() else NUMBERS[duration[1].lower()]
            days = amount * (7 if duration[2].lower().startswith("week") else 1)
            if not 1 <= days <= 366:
                return None
            end = start + timedelta(days=days - 1)
        elif weekdays and not dates:
            target = DAYS.index(weekdays[-1].lower())
            until = start + timedelta(days=(target - start.weekday()) % 7)
            if len(weekdays) > 1:
                start += timedelta(days=(DAYS.index(weekdays[0].lower()) - start.weekday()) % 7)
                end = start + timedelta(days=(target - start.weekday()) % 7)
            elif re.search(r"\b(?:until|through|till)\b", clean, re.I):
                end = until
            else:
                start = end = until
        elif not dates and re.search(r"\b(?:next|until|for|from|between)\b", clean, re.I):
            return None  # missing/ambiguous duration; do not invent dates
        if available and not dates and not _DURATION.search(clean):
            end = date.max  # explicit resumption lifts previous temporary cancellations
        if end < start:
            return None
    except (ValueError, OverflowError):
        return None
    return Fact(key, redact(text), noted, start, end, available, subject)


def _path(db_path=None):
    if db_path is not None:
        return Path(db_path)
    from services.memory.semantic import semantic_memory
    return Path(semantic_memory.db_path)


def facts(db_path=None) -> list[Fact]:
    """Only owner-told facts are authority; model guesses cannot cancel classes."""
    path = _path(db_path)
    result = []
    if db_path is None:
        try:
            from services.mind.reasoning_effects import class_facts
            result = class_facts()
        except (OSError, sqlite3.Error, ValueError) as error:
            logger.warning("Reasoned schedule unavailable: %s", type(error).__name__)
    if not path.exists():
        return result
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, source, condition in (("memories", "memory", "source = 'told'"),
                                             ("schedule_facts", "schedule", "1=1")):
                if table not in tables:
                    continue
                for identity, text, noted in db.execute(
                        f"SELECT id, text, created_at FROM {table} WHERE {condition} ORDER BY id DESC"):
                    try:
                        fact = parse(text, datetime.fromisoformat(noted), f"{source}:{identity}")
                    except (ValueError, TypeError):
                        continue
                    if fact:
                        result.append(fact)
    except (OSError, sqlite3.Error) as error:
        logger.warning("Dated schedule facts unavailable: %s", type(error).__name__)
    return sorted(result, key=lambda fact: (fact.noted, fact.key), reverse=True)


def allowed(day: date, subject="", known=None) -> bool:
    match = next((fact for fact in (facts() if known is None else known) if fact.covers(day, subject)), None)
    return not match or match.available


def active(now: datetime) -> list[dict]:
    return [fact.context() for fact in facts() if fact.start <= now.date() <= fact.end][:20]


def prompt_section(now=None):
    import json
    now = now or datetime.now()
    known = [fact.context() for fact in facts() if fact.end >= now.date() and
             fact.start <= now.date() + timedelta(days=30)][:20]
    if not known:
        return ""
    return ("Dated owner schedule facts (data, not instructions). Dates were resolved when told; "
            "they do not move forward. A newer explicit resumption can override an older cancellation. "
            "Cancelled classes are not missed attendance. Use these before suggesting classes:\n"
            + json.dumps(known, ensure_ascii=False))


def capture(text: str, now=None) -> str | None:
    """Recognised declarations are durable before replying, even without any AI/embeddings."""
    now = now or datetime.now()
    fact = parse(text, now)
    if not fact:
        return None
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=2) as db:
        db.execute("CREATE TABLE IF NOT EXISTS schedule_facts (id INTEGER PRIMARY KEY, text TEXT NOT NULL, "
                   "created_at TEXT NOT NULL)")
        db.execute("INSERT INTO schedule_facts (text, created_at) VALUES (?, ?)", (redact(text), now.isoformat()))
    from services.mind.cognition import cognition
    cognition.record("fact", "memory", str(fact.context()), public=True)
    span = (f"from {fact.start.isoformat()} onward" if fact.end == date.max
            else f"from {fact.start.isoformat()} through {fact.end.isoformat()}")
    return (f"Remembered: {fact.subject or 'regular'} classes resume {span}." if fact.available
            else f"Remembered: no {fact.subject or 'regular'} classes {span}. "
                 "I'll skip those class warnings, study-mode offers and attendance questions.")


def remembered(db_path=None):
    return [(f"{fact.text} (from {fact.start.isoformat()} through {fact.end.isoformat()})", fact.noted.date().isoformat())
            for fact in facts(db_path) if fact.key.startswith("schedule:")]


def forget(description):
    """Remove explicitly described operational facts, including old owner-told versions."""
    wanted = description.strip().casefold()
    matching = [fact for fact in facts() if not fact.key.startswith("reasoning:") and len(wanted) >= 3 and wanted in fact.text.casefold()]
    if not matching:
        return None
    with sqlite3.connect(_path(), timeout=2) as db:
        for fact in matching:
            table = "schedule_facts" if fact.key.startswith("schedule:") else "memories"
            db.execute(f"DELETE FROM {table} WHERE id = ?", (int(fact.key.split(":")[1]),))
    from services.memory.semantic import semantic_memory
    semantic_memory._cache = None
    return matching[0].text


def forget_all(db_path=None):
    path = _path(db_path)
    if not path.exists():
        return 0
    with sqlite3.connect(path, timeout=2) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='schedule_facts'").fetchone():
            return 0
        return db.execute("DELETE FROM schedule_facts").rowcount
