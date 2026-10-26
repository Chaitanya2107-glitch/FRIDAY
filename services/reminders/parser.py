"""
services/reminders/parser.py

Turns "remind me at 5pm to call mom" or "remind me to stretch in 20 minutes"
into (task, due datetime). Deliberately small — no NLP dependency.

Understands:
  in 10 minutes / in 2 hours / in an hour / in half an hour / in 3 days
  at 5pm / at 5:30 p.m. / at 17:45 / at 5 (whichever of 5:00 or 17:00 comes next)
  "tomorrow" anywhere in the message
"""

import re
from datetime import datetime, timedelta

REMIND_PREFIX = re.compile(r"^\s*remind\s+me\b", re.IGNORECASE)
RELATIVE = re.compile(
    r"\bin\s+(?P<amount>\d{1,4}|an?|half\s+an?)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\b",
    re.IGNORECASE,
)
CLOCK = re.compile(
    r"\bat\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>[ap]\.?\s?m\.?)?(?![\w:])",
    re.IGNORECASE,
)
TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
UNIT_SECONDS = (("sec", 1), ("min", 60), ("hour", 3600), ("hr", 3600), ("day", 86400))

NEED_TIME = 'When should I remind you? Try "remind me at 5pm to call mom" or "remind me in 20 minutes to stretch".'
NEED_TASK = 'What should I remind you about? Try "remind me in 20 minutes to stretch".'


class ReminderParseError(ValueError):
    """A reminder request with a missing or invalid time or task. The message is user-facing."""


def is_reminder_request(message: str) -> bool:
    """
    True for "remind me <when> ..." or "remind me to ...". Other "remind me"
    questions ("remind me what the capital of France is") stay normal chat.
    """
    prefix = REMIND_PREFIX.match(message)
    if not prefix:
        return False
    body = message[prefix.end():]
    return bool(
        RELATIVE.search(body)
        or CLOCK.search(body)
        or re.match(r"\s+(?:tomorrow\s+)?to\s", body, re.IGNORECASE)
    )


def parse_reminder(message: str, now: datetime) -> tuple[str, datetime]:
    """Return (task, due). Raises ReminderParseError with a user-facing message."""
    prefix = REMIND_PREFIX.match(message)
    body = message[prefix.end():] if prefix else message
    tomorrow = bool(TOMORROW.search(body))

    relative = RELATIVE.search(body)
    clock = None if relative else CLOCK.search(body)
    if relative:
        due = now + timedelta(seconds=_relative_seconds(relative))
        start, end = relative.span()
    elif clock:
        due = _resolve_clock(clock, now, tomorrow)
        start, end = clock.span()
    else:
        raise ReminderParseError(NEED_TIME)

    task = TOMORROW.sub(" ", body[:start] + " " + body[end:])
    task = re.sub(r"\s+", " ", task).strip(" .,!?")
    task = re.sub(r"^(?:to|that|about)\s+", "", task, flags=re.IGNORECASE).strip(" .,!?")
    if not task:
        raise ReminderParseError(NEED_TASK)
    return task, due


def describe_due(due: datetime, now: datetime) -> str:
    """e.g. "5:00 PM today", "9:00 AM tomorrow", "9:00 AM on Thu 17 Sep"."""
    clock = due.strftime("%I:%M %p").lstrip("0")
    if due.date() == now.date():
        return f"{clock} today"
    if due.date() == (now + timedelta(days=1)).date():
        return f"{clock} tomorrow"
    return f"{clock} on {due:%a %d %b}"


def _relative_seconds(match: re.Match) -> float:
    amount_text = match.group("amount").lower()
    if amount_text.startswith("half"):
        amount = 0.5
    elif amount_text in ("a", "an"):
        amount = 1
    else:
        amount = int(amount_text)
    if amount <= 0:
        raise ReminderParseError("That's already now — pick a time in the future.")

    unit = match.group("unit").lower()
    seconds = next(value for prefix, value in UNIT_SECONDS if unit.startswith(prefix))
    return amount * seconds


def _resolve_clock(match: re.Match, now: datetime, tomorrow: bool) -> datetime:
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    meridiem = re.sub(r"[.\s]", "", match.group("meridiem") or "").lower()

    if minute > 59 or hour > 23 or (meridiem and not 1 <= hour <= 12):
        raise ReminderParseError("That time doesn't look right — try something like 5pm or 17:30.")
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    day = now + timedelta(days=1) if tomorrow else now
    first = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # A bare "at 5" could mean 5am or 5pm — use whichever comes next.
    options = [first, first + timedelta(hours=12)] if not meridiem and 1 <= hour <= 11 else [first]
    return next(o for o in options + [o + timedelta(days=1) for o in options] if o > now)
