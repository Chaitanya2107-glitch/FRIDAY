"""
services/proactive/deadlines.py

Deadlines, apart from reminders: something due at a time, counted down.
  "DBMS assignment due Friday 11:59pm", "add deadline OS lab record due 5 Oct",
  "project report is due tomorrow", "what's due", "done with the DBMS assignment",
  "remove deadline 2", "clear my deadlines"
Silent notifications 3 days, 1 day and 3 hours before (also on Telegram when away; from
services/proactive/watcher.py). The briefing lists what's due within 3 days, and a class
warning adds a deadline for that subject. Kept in memory/deadlines.json.
A time without am/pm counts as evening ("11:59" → 11:59 PM); none at all means 11:59 PM.
"""

import json
import re
from datetime import date, datetime, timedelta

from core.config import config
from services.automation.system_control import AutomationError
from services.proactive import deadline_store

path = config.MEMORY_DIR / "deadlines.json"  # tests point this elsewhere
DEADLINE_ACTIONS = {"add_deadline", "list_deadlines", "finish_deadline", "remove_deadline", "clear_deadlines"}
STAGES = [("3d", timedelta(days=3)), ("1d", timedelta(days=1)), ("3h", timedelta(hours=3))]  # longest first
SOON = timedelta(days=3)
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_QUESTION = re.compile(r"^(?:what|why|when|how|is|are|was|do|does|did|can|could|should|who|which|whose|will|if)\b", re.I)
_ADD = re.compile(r"^(?:add (?:a )?deadline(?: for)?:?\s+)?(?P<what>.+?)\s+(?:is\s+|are\s+)?due\s+(?:on\s+|by\s+)?(?P<when>.+)$", re.I)
_LIST = re.compile(r"^(?:what(?:'s|s| is| are)? (?:due|my deadlines)(?: soon| this week)?|(?:list|show)(?: me)? (?:all )?(?:my |the )?"
                   r"deadlines|(?:any|my) deadlines|what do i have due)$", re.I)
_FINISH = re.compile(r"^(?:done with|finished|i finished|i've finished|i have finished|submitted|i submitted|i've submitted)"
                     r"\s+(?:the |my )?(?P<what>.+)$|^(?:mark )?(?:the |my )?(?P<what2>.+?) (?:as )?(?:done|submitted|finished)$", re.I)
_REMOVE = re.compile(r"^(?:remove|delete|cancel) (?:the )?deadline (?:number )?(?P<n>\d+)$", re.I)
_CLEAR = re.compile(r"^(?:clear|delete|remove) (?:all )?(?:of )?(?:my |the )?deadlines$", re.I)
_MOVE = re.compile(r"^(?:(?:actually[, ]+)?(?:my |the )?(?P<what>.+?) deadline (?:has )?(?:moved|changed|was moved)"
                   r"|(?:move|change|reschedule) (?:the |my )?deadline (?P<name>.+?))"
                   r"(?: from (?P<old>.+?))? to (?P<when>.+)$", re.I)
_RECALL = re.compile(r"^(?:when is|what is the due date for) (?:my |the )?(?P<what>.+?) deadline$", re.I)
_HISTORY = re.compile(r"^(?:show |list )?deadline history for (?P<what>.+)$", re.I)
_LINK = re.compile(r"^link reminder (?P<number>\d+) to (?:the |my )?deadline (?P<what>.+)$", re.I)
_UPDATES = re.compile(r"^(?P<verb>review|apply|reject) (?:the )?reminder updates for (?P<what>.+)$", re.I)

_DATE_DM = re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m>{'|'.join(MONTHS)})[a-z]*\b")
_DATE_MD = re.compile(rf"\b(?P<m>{'|'.join(MONTHS)})[a-z]*\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b")
_DATE_NUM = re.compile(r"\b(?P<d>\d{1,2})[/-](?P<m>\d{1,2})(?:[/-](?P<y>\d{2,4}))?\b")  # day/month, as written in India
_WEEKDAY = re.compile(rf"\b(?:this\s+|next\s+|on\s+|coming\s+)?(?P<day>{'|'.join(DAYS)})\b")
_TIME = re.compile(r"\b(?:at\s+|by\s+)?(?:(?P<noon>noon|midnight)|(?P<h>\d{1,2})(?:[:.](?P<min>\d{2}))?\s*(?P<half>am|pm|a\.m\.|p\.m\.)?)\b")


# ── Parsing ───────────────────────────────────────────────────────────────────

def _time(text: str) -> tuple[int, int] | None:
    m = _TIME.fullmatch(text.strip())
    if not m:
        return None
    if m["noon"]:
        return (12, 0) if m["noon"] == "noon" else (23, 59)
    hour, minute, half = int(m["h"]), int(m["min"] or 0), (m["half"] or "").replace(".", "")
    if half == "pm" and hour < 12 or not half and 1 <= hour <= 11:  # ponytail: no am/pm = evening; say "am" for mornings
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    return (hour, minute) if hour <= 23 and minute <= 59 else None


def parse_due(text: str, now: datetime) -> datetime:
    """ "Friday 11:59pm", "tomorrow", "5 Oct at 5", "5/10", "tonight" → when it's due. Raises AutomationError."""
    text = " ".join(text.lower().replace(",", " ").split())
    day: date | None = None
    by_weekday = False
    for pattern in (_DATE_DM, _DATE_MD, _DATE_NUM):
        if m := pattern.search(text):
            month = MONTHS.index(m["m"][:3]) + 1 if not m["m"].isdigit() else int(m["m"])
            year = int(m["y"]) + (2000 if len(m["y"]) == 2 else 0) if pattern is _DATE_NUM and m["y"] else now.year
            try:
                day = date(year, month, int(m["d"]))
            except ValueError:
                raise AutomationError(f"There's no date {m.group(0)!r}.") from None
            if day < now.date() - timedelta(days=1) and not (pattern is _DATE_NUM and m["y"]):
                day = day.replace(year=year + 1)  # "5 Jan" said in December
            text = (text[:m.start()] + text[m.end():]).strip()
            break
    if day is None:
        if m := re.search(r"\b(?:today|tonight)\b", text):
            day, text = now.date(), (text[:m.start()] + text[m.end():]).strip()
        elif m := re.search(r"\btomorrow\b", text):
            day, text = now.date() + timedelta(days=1), (text[:m.start()] + text[m.end():]).strip()
        elif m := _WEEKDAY.search(text):
            ahead = (DAYS.index(m["day"]) - now.weekday()) % 7
            day, text = now.date() + timedelta(days=ahead), (text[:m.start()] + text[m.end():]).strip()
            by_weekday = True
    clock = _time(text) if text else (23, 59)
    if day is None and clock and text:
        day = now.date()  # "due at 5pm": today
    if day is None or clock is None:
        raise AutomationError("I couldn't tell when that's due. Try \"due Friday 11:59pm\" or \"due 5 Oct\".")
    due = datetime.combine(day, datetime.min.time()).replace(hour=clock[0], minute=clock[1])
    if due <= now and by_weekday:
        due += timedelta(days=7)  # "due Friday 5pm", said on Friday evening: next week's
    return due


# ── The file ──────────────────────────────────────────────────────────────────

def load(*, include_done: bool = False) -> list[dict]:
    rows = deadline_store.read(path)
    return rows if include_done else [row for row in rows if row.get('done') is not True]


def _save(deadlines: list[dict], *, include_done: bool = False) -> None:
    if not include_done:
        ids = {row.get('id') for row in deadlines}
        deadlines = deadlines + [row for row in deadline_store.read(path)
                                if row.get('done') is True and row.get('id') not in ids]
    deadline_store.save(path, deadlines)


def edit():
    return deadline_store.edit(path)


def when(due: datetime, now: datetime) -> str:
    """ "today at 11:59 PM", "tomorrow at 5:00 PM", "Friday 3 Oct at 11:59 PM" """
    clock = due.strftime("%I:%M %p").lstrip("0")
    days = (due.date() - now.date()).days
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    return f"{due:%A} {due.day} {due:%b} at {clock}"


def _left(due: datetime, now: datetime) -> str:
    seconds = (due - now).total_seconds()
    if seconds < 0:
        return "overdue"
    hours = seconds / 3600
    return f"in {round(hours)} hour{'s' if round(hours) != 1 else ''}" if hours < 36 else f"in {round(hours / 24)} days"


def add(what: str, due: datetime, now: datetime) -> str:
    if due <= now:
        raise AutomationError(f"That's already past ({when(due, now)}). Say the date too, like \"due 5 Oct\".")
    # stages already inside their window when added: no instant alert, the confirmation says it
    alerted = [name for name, before in STAGES if due - before <= now]
    with edit():
        _save(load() + [{"what": what, "due": due.isoformat(timespec="minutes"), "alerted": alerted}])
    return f"Deadline added: {what} — due {when(due, now)} ({_left(due, now)})."


def _find(what: str) -> int | None:
    words = set(re.findall(r"[a-z0-9]+", what.lower())) - {"the", "my", "a", "an"}
    best, best_score = None, 0
    for i, d in enumerate(load()):
        score = len(words & set(re.findall(r"[a-z0-9]+", d["what"].lower())))
        if score > best_score:
            best, best_score = i, score
    return best


def list_message(now: datetime) -> str:
    deadlines = load()
    if not deadlines:
        return "No deadlines."
    return "\n".join(f"{i}. {d['what']} — {when(datetime.fromisoformat(d['due']), now)} "
                     f"({_left(datetime.fromisoformat(d['due']), now)})" for i, d in enumerate(deadlines, 1))


# ── Commands ──────────────────────────────────────────────────────────────────

def match_deadline_change(text):
    text = text.strip()
    if m := _MOVE.fullmatch(text):
        return {"action": "move_deadline", "reference": m["what"] or m["name"], "when": m["when"], "old": m["old"], "quote": text}
    if m := _RECALL.fullmatch(text):
        return {"action": "recall_deadline", "reference": m["what"]}
    if m := _HISTORY.fullmatch(text):
        return {"action": "deadline_history", "reference": m["what"]}
    if m := _LINK.fullmatch(text):
        return {"action": "link_deadline_reminder", "reference": m["what"], "number": int(m["number"])}
    if m := _UPDATES.fullmatch(text):
        return {"action": "deadline_reminder_updates", "reference": m["what"], "verb": m["verb"].lower()}
    return None


def match_deadline_command(text: str, now: datetime | None = None) -> dict | None:
    """`text` has been through normalize_command() (letter case kept)."""
    text = text.strip()
    if change := match_deadline_change(text):
        return change
    if _LIST.match(text):
        return {"type": "system", "action": "list_deadlines"}
    if _CLEAR.match(text):
        return {"type": "system", "action": "clear_deadlines"}
    if m := _REMOVE.match(text):
        return {"type": "system", "action": "remove_deadline", "number": int(m["n"])}
    if (m := _FINISH.match(text)) and load() and _find(m["what"] or m["what2"]) is not None:
        return {"type": "system", "action": "finish_deadline", "what": m["what"] or m["what2"]}
    if (m := _ADD.match(text)) and not _QUESTION.match(text):
        explicit = text.lower().startswith("add")
        try:
            due = parse_due(m["when"], now or datetime.now())
        except AutomationError:
            if not explicit:
                return None  # "the rent is due whenever" — not a deadline command
            raise
        return {"type": "system", "action": "add_deadline", "what": m["what"].strip(" :"), "due": due.isoformat()}
    return None


def run(parsed: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    action = parsed["action"]
    if action == "add_deadline":
        return add(parsed["what"], datetime.fromisoformat(parsed["due"]), now)
    if action == "list_deadlines":
        return list_message(now)
    with edit():
        return _run_mutation(parsed, now)


def _run_mutation(parsed, now):
    action = parsed["action"]
    if action == "clear_deadlines":
        count = len(load())
        _save([], include_done=True)
        return f"Cleared {count} deadline{'s' if count != 1 else ''}." if count else "No deadlines to clear."
    deadlines = load()
    index = _find(parsed["what"]) if action == "finish_deadline" else int(parsed["number"]) - 1
    if index is None or not 0 <= index < len(deadlines):
        raise AutomationError("I don't have that deadline." + (f" You have {len(deadlines)}." if deadlines else ""))
    removed = deadlines.pop(index)
    if action == 'finish_deadline':
        from services.proactive.deadline_changes import complete
        complete(removed)
        deadlines.append(removed)
    _save(deadlines)
    return f"Nice — {removed['what']} is off the list." if action == "finish_deadline" else f"Removed: {removed['what']}"


# ── Alerts, briefing, class warnings ──────────────────────────────────────────

def due_alerts(now: datetime) -> list[str]:
    with edit():
        return _due_alerts(now)


def _due_alerts(now: datetime) -> list[str]:
    """The countdown notifications due now. After a long gap (FRIDAY off), only the most urgent one is shown."""
    deadlines, alerts, changed = load(), [], False
    for d in deadlines:
        due = datetime.fromisoformat(d["due"])
        reached = [name for name, before in STAGES if due - before <= now < due and name not in d["alerted"]]
        if reached:
            d["alerted"] += reached
            changed = True
            alerts.append(f"{d['what']} is due {when(due, now)} ({_left(due, now)}).")
    if changed:
        _save(deadlines)
    return alerts


def briefing_line(now: datetime) -> str:
    soon = [d for d in load() if datetime.fromisoformat(d["due"]) - now <= SOON]
    if not soon:
        return ""
    return "Due soon: " + "; ".join(f"{d['what']} {when(datetime.fromisoformat(d['due']), now)}"
                                    + (" (overdue)" if datetime.fromisoformat(d["due"]) < now else "") for d in soon) + "."


def for_subject(subject: str, now: datetime) -> str:
    """For a class warning: " DBMS assignment is due tomorrow at 11:59 PM." or ""."""
    from services.proactive.timetable import aliases, mentions_subject

    forms = aliases(subject)
    found = [d for d in load() if mentions_subject(d["what"], forms) and datetime.fromisoformat(d["due"]) > now]
    return "".join(f" {d['what']} is due {when(datetime.fromisoformat(d['due']), now)}." for d in found)
