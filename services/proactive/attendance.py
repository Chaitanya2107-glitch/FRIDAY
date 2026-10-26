"""
services/proactive/attendance.py

Attendance and internal marks, for the 75% rule and "what do I need in the exam".

Attendance:
  - after each timetable class ends, one silent toast: "DBMS (9:30–10:30 AM): attended?"
    [Attended] [Missed] (buttons.py; reaches Telegram when the laptop is idle — i.e. at college)
  - "I attended DBMS", "bunked PE today", "missed DS yesterday", "attended all classes today",
    "bunked all classes today", "no college today" (a holiday: no questions that day)
  - "my attendance", "attendance in DBMS", "how many DBMS classes can I skip"
  Under WARN_BELOW% you're told; under MIN_PERCENT%, how many in a row it takes to get back.

Internal marks:
  - "I got 18 out of 25 in DBMS CIE 1", "scored 8/10 in DS quiz 2"
  - "my marks", "my DBMS marks"
  - "what do I need in the DBMS exam for an A" — assumes internals count INTERNAL_SHARE and the
    semester-end exam the rest, with GRADES (edit them if REVA's scheme differs)

Kept in memory/attendance.json (editable by hand).
"""

import json
import math
import re
from datetime import date, datetime, timedelta

from core.config import config
from core.logger import logger
from services.automation.system_control import AutomationError
from services.proactive import timetable

path = config.MEMORY_DIR / "attendance.json"  # tests point this elsewhere
MIN_PERCENT = 75
WARN_BELOW = 80
ASK_WITHIN_MINUTES = 60   # a class that ended longer ago than this isn't asked about any more
INTERNAL_SHARE = 50       # of 100: internals (CIE) — the exam is the other 50, marked out of 100
GRADES = {"o": 90, "a+": 80, "a": 70, "b+": 60, "b": 55, "c": 50, "p": 40, "pass": 40}
ATTENDANCE_ACTIONS = {"mark_class", "mark_all", "holiday", "show_attendance", "can_skip", "add_marks", "show_marks",
                      "exam_needed"}

_CLASS = r"(?:\s+(?:class|classes|lecture|lab|period))?"
_DAY = r"(?:\s+(?P<day>today|yesterday))?"
_MARK = re.compile(rf"^(?:i\s+)?(?P<verb>attended|went to|was in|was at|missed|skipped|bunked|didn't attend|didn't go to"
                   rf"|did not attend)\s+(?:the\s+|my\s+)?(?P<subject>.+?){_CLASS}{_DAY}$", re.I)
_ALL = re.compile(rf"^(?:i\s+)?(?P<verb>attended|went to|missed|skipped|bunked)\s+(?:all|every)\s+(?:my\s+|of my\s+|today's\s+)?"
                  rf"classes{_DAY}$", re.I)
_HOLIDAY = re.compile(r"^(?:no college|holiday|college is (?:off|closed)|no classes)(?: today)?$|^today is a holiday$", re.I)
_SHOW = re.compile(r"^(?:what(?:'s| is) |show(?: me)? |check )?my attendance(?:\s+(?:in|for|of)\s+(?P<subject>.+))?$"
                   r"|^attendance(?:\s+(?:in|for|of)\s+(?P<s2>.+))?$", re.I)
_SKIP = re.compile(r"^how many (?P<subject>.+?) (?:classes|lectures) can i (?:skip|miss|bunk)$"
                   r"|^can i (?:skip|miss|bunk) (?P<s2>.+?)(?: class| today)*$", re.I)
_ADD_MARKS = re.compile(r"^(?:i\s+)?(?:got|scored)\s+(?P<got>\d+(?:\.\d+)?)\s*(?:out of|/)\s*(?P<out>\d+(?:\.\d+)?)\s+in\s+"
                        r"(?:the\s+|my\s+)?(?P<subject>.+?)\s+(?P<exam>(?:cie|ia|internal|quiz|assignment|test|lab|mid)"
                        r"[\w ]*)$", re.I)
_SHOW_MARKS = re.compile(r"^(?:what are |show(?: me)? )?my (?:(?P<subject>.+?) )?(?:marks|internals|internal marks)$", re.I)
_NEEDED = re.compile(r"^what do i need (?:in|on) (?:the\s+)?(?P<subject>.+?)\s+(?:final|see|exam|end sem|semester)[\w ]*?\s+"
                     r"(?:for|to get) (?:an? )?(?P<grade>o|a\+|a|b\+|b|c|p|pass)(?: grade)?$", re.I)
_MISSED = {"missed", "skipped", "bunked", "didn't attend", "didn't go to", "did not attend"}


# ── The file ──────────────────────────────────────────────────────────────────

def load() -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"records": [], "marks": [], "holidays": [], "asked": []}
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e
    for key in ("records", "marks", "holidays", "asked"):
        data.setdefault(key, [])
    return data


def _save(data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["asked"] = data["asked"][-60:]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _key(day: date, c: dict) -> str:
    return f"{day.isoformat()} {c['start']} {c['subject']}"


def record(data: dict, day: date, subject: str, start: str, attended: bool) -> None:
    """Set (or change) one class's attendance."""
    data["records"] = [r for r in data["records"] if (r["date"], r["subject"], r["start"]) != (day.isoformat(), subject, start)]
    data["records"].append({"date": day.isoformat(), "subject": subject, "start": start, "attended": attended})


# ── Numbers ───────────────────────────────────────────────────────────────────

def counts(data: dict) -> dict[str, tuple[int, int]]:
    """Subject → (attended, held)."""
    found: dict[str, list[int]] = {}
    from services.memory import schedule
    known = schedule.facts()
    for r in data["records"]:
        if not schedule.allowed(date.fromisoformat(r["date"]), r["subject"], known):
            continue
        tally = found.setdefault(r["subject"], [0, 0])
        tally[0] += bool(r["attended"])
        tally[1] += 1
    return {s: (a, t) for s, (a, t) in found.items()}


def percent(attended: int, held: int) -> float:
    return 100 * attended / held if held else 100.0


def can_skip(attended: int, held: int) -> int:
    """Classes in a row that can be missed and still stay at MIN_PERCENT."""
    return max(0, math.floor(attended * 100 / MIN_PERCENT - held + 1e-9))


def to_recover(attended: int, held: int) -> int:
    """Classes in a row it takes to get back to MIN_PERCENT."""
    share = MIN_PERCENT / 100
    return max(0, math.ceil((share * held - attended) / (1 - share) - 1e-9))


def status(subject: str, attended: int, held: int) -> str:
    """ "DBMS 7/10 (70%) — below 75%: attend the next 2 in a row to get back." """
    line = f"{subject} {attended}/{held} ({percent(attended, held):.0f}%)"
    if percent(attended, held) < MIN_PERCENT:
        return f"{line} — below {MIN_PERCENT}%: attend the next {to_recover(attended, held)} in a row to get back"
    if percent(attended, held) < WARN_BELOW:
        return f"{line} — close to {MIN_PERCENT}%"
    return line


# ── Asking after class ────────────────────────────────────────────────────────

def due_asks(now: datetime) -> list[dict]:
    """Today's classes that just ended and haven't been asked about or answered (the watcher shows each once)."""
    try:
        data, today = load(), timetable.classes_for_date(now.date())
    except AutomationError:
        return []
    if now.date().isoformat() in data["holidays"]:
        return []
    answered = {(r["date"], r["subject"], r["start"]) for r in data["records"]}
    asks = []
    for c in today:
        ended = now.replace(hour=int(c["end"][:2]), minute=int(c["end"][3:]), second=0, microsecond=0)
        key = _key(now.date(), c)
        if (timedelta(0) <= now - ended <= timedelta(minutes=ASK_WITHIN_MINUTES) and key not in data["asked"]
                and (now.date().isoformat(), c["subject"], c["start"]) not in answered):
            data["asked"].append(key)
            asks.append({"date": now.date().isoformat(), "subject": c["subject"], "start": c["start"],
                         "session_revision": c.get("session_revision"),
                         "text": f"{c['subject']} ({timetable._clock(c['start'])}–{timetable._clock(c['end'])}): attended?"})
    if asks:
        _save(data)
    return asks


def answer(about: dict, reply: str) -> str:
    """[Attended] / [Missed] on the after-class notification (buttons.py)."""
    data = load()
    from services.memory import schedule
    if about["date"] in data["holidays"] or not schedule.allowed(date.fromisoformat(about["date"]), about["subject"]):
        return "That class was cancelled; no attendance was marked."
    current = timetable.classes_for_date(date.fromisoformat(about["date"]))
    if not any(c["subject"] == about["subject"] and c["start"] == about["start"]
               and c.get("session_revision") == about.get("session_revision") for c in current):
        return "That class time changed or was removed; no attendance was marked. Check the current timetable."
    record(data, date.fromisoformat(about["date"]), about["subject"], about["start"], reply == "yes")
    _save(data)
    attended, held = counts(data)[about["subject"]]
    return f"Marked {about['subject']} {'attended' if reply == 'yes' else 'missed'}. {status(about['subject'], attended, held)}."


# ── Commands ──────────────────────────────────────────────────────────────────

def match_attendance_command(text: str) -> dict | None:
    """`text` has been through normalize_command()."""
    text = text.strip().rstrip("?.!")
    if m := _ALL.match(text):
        return {"type": "system", "action": "mark_all", "attended": m["verb"].lower() not in _MISSED,
                "day": (m["day"] or "today").lower()}
    if _HOLIDAY.match(text):
        return {"type": "system", "action": "holiday"}
    if m := _ADD_MARKS.match(text):
        return {"type": "system", "action": "add_marks", "subject": m["subject"], "exam": m["exam"].strip(),
                "got": float(m["got"]), "out_of": float(m["out"])}
    if m := _NEEDED.match(text):
        return {"type": "system", "action": "exam_needed", "subject": m["subject"], "grade": m["grade"].lower()}
    if m := _SKIP.match(text):
        return {"type": "system", "action": "can_skip", "subject": m["subject"] or m["s2"]}
    if m := _SHOW.match(text):
        return {"type": "system", "action": "show_attendance", "subject": m["subject"] or m["s2"] or ""}
    if m := _SHOW_MARKS.match(text):
        return {"type": "system", "action": "show_marks", "subject": m["subject"] or ""}
    if (m := _MARK.match(text)) and _is_subject(m["subject"]):
        return {"type": "system", "action": "mark_class", "subject": m["subject"],
                "attended": m["verb"].lower() not in _MISSED, "day": (m["day"] or "today").lower()}
    return None


def _subject(said: str, data: dict) -> str:
    """The subject meant: the timetable's name for it, else one already saved (any case), else an acronym in capitals."""
    named = timetable.subject_named(said)
    known = [*timetable.subjects(), *(r["subject"] for r in data["records"]), *(m["subject"] for m in data["marks"])]
    same = next((s for s in known if s.lower() == named.lower()), None)
    return same or (named.upper() if len(named) <= 5 and " " not in named else named)


def _is_subject(said: str) -> bool:
    """Only the user's subjects: "I missed the bus" isn't attendance."""
    named = timetable.subject_named(said)
    return named.lower() in {s.lower() for s in timetable.subjects()}


def run(parsed: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    action, data = parsed["action"], load()
    if action == "holiday":
        data["holidays"] = sorted(set(data["holidays"]) | {now.date().isoformat()})
        _save(data)
        return "Holiday noted — no attendance questions today."
    if action in ("mark_class", "mark_all"):
        day = now.date() - timedelta(days=parsed["day"] == "yesterday")
        classes = timetable.classes_for_date(day)
        if action == "mark_all":
            if not classes:
                return f"There were no classes {parsed['day']}."
            for c in classes:
                record(data, day, c["subject"], c["start"], parsed["attended"])
            _save(data)
            return f"Marked all {len(classes)} classes {parsed['day']} {'attended' if parsed['attended'] else 'missed'}."
        subject = _subject(parsed["subject"], data)
        mine = [c for c in classes if c["subject"] == subject]
        answered = {(r["subject"], r["start"]) for r in data["records"] if r["date"] == day.isoformat()}
        c = next((c for c in mine if (subject, c["start"]) not in answered), mine[-1] if mine else None)
        record(data, day, subject, c["start"] if c else "extra", parsed["attended"])
        _save(data)
        attended, held = counts(data)[subject]
        return f"Marked {subject} {'attended' if parsed['attended'] else 'missed'}. {status(subject, attended, held)}."
    if action == "show_attendance":
        found = counts(data)
        if parsed["subject"]:
            subject = _subject(parsed["subject"], data)
            return (status(subject, *found[subject]) + ".") if subject in found else f"No attendance recorded for {subject} yet."
        if not found:
            return "No attendance recorded yet. I'll ask after each class."
        return "Attendance: " + "; ".join(status(s, a, t) for s, (a, t) in sorted(found.items(), key=lambda i: percent(*i[1]))) + "."
    if action == "can_skip":
        subject = _subject(parsed["subject"], data)
        attended, held = counts(data).get(subject, (0, 0))
        if not held:
            return f"No attendance recorded for {subject} yet, so I can't tell."
        if percent(attended, held) < MIN_PERCENT:
            return f"None — {status(subject, attended, held)}."
        n = can_skip(attended, held)
        return f"{n} {subject} class{'es' if n != 1 else ''} in a row and you'd still be at {MIN_PERCENT}% ({attended}/{held} now)." \
            if n else f"None — one more miss and {subject} drops below {MIN_PERCENT}% ({attended}/{held} now)."
    return _marks(parsed, data, now)


def _marks(parsed: dict, data: dict, now: datetime) -> str:
    action = parsed["action"]
    if action == "add_marks":
        subject = _subject(parsed["subject"], data)
        if parsed["got"] > parsed["out_of"]:
            raise AutomationError(f"{parsed['got']:g} out of {parsed['out_of']:g}? I don't think so.")
        exam = re.sub(r"\b(?:cie|ia|see)\b", lambda m: m.group().upper(), parsed["exam"], flags=re.I)
        exam = exam[:1].upper() + exam[1:]  # "CIE 2", "Quiz 1"
        data["marks"] = [m for m in data["marks"] if (m["subject"], m["exam"].lower()) != (subject, exam.lower())]
        data["marks"].append({"subject": subject, "exam": exam, "got": parsed["got"], "out_of": parsed["out_of"],
                              "at": now.date().isoformat()})
        _save(data)
        return f"Saved {subject} {exam}: {parsed['got']:g}/{parsed['out_of']:g}. {_subject_total(data, subject)}"
    if action == "show_marks":
        subjects = [_subject(parsed["subject"], data)] if parsed["subject"] else \
            sorted({m["subject"] for m in data["marks"]})
        lines = [_subject_total(data, s) for s in subjects if any(m["subject"] == s for m in data["marks"])]
        return " ".join(lines) if lines else "No marks saved yet. Tell me like \"I got 18 out of 25 in DBMS CIE 1\"."
    subject = _subject(parsed["subject"], data)  # exam_needed
    mine = [m for m in data["marks"] if m["subject"] == subject]
    if not mine:
        return f"I don't have any {subject} internal marks yet."
    internal = INTERNAL_SHARE * sum(m["got"] for m in mine) / sum(m["out_of"] for m in mine)
    target = GRADES[parsed["grade"]]
    exam_share = 100 - INTERNAL_SHARE
    needed = (target - internal) / exam_share * 100
    grade = parsed["grade"].upper()
    if needed <= 0:
        return f"You already have {internal:.1f}/{INTERNAL_SHARE} from internals — {grade} is yours unless you skip the exam."
    if needed > 100:
        return f"Even 100/100 in the exam won't reach {grade} ({target}) — internals give {internal:.1f}/{INTERNAL_SHARE}."
    return (f"About {math.ceil(needed)}/100 in the {subject} exam for {grade} ({target}+ overall), with internals at "
            f"{internal:.1f}/{INTERNAL_SHARE}. Assumes internals {INTERNAL_SHARE} + exam {exam_share}.")


def _subject_total(data: dict, subject: str) -> str:
    mine = [m for m in data["marks"] if m["subject"] == subject]
    got, out_of = sum(m["got"] for m in mine), sum(m["out_of"] for m in mine)
    parts = ", ".join(f"{m['exam']} {m['got']:g}/{m['out_of']:g}" for m in mine)
    return f"{subject}: {parts} — {got:g}/{out_of:g} ({100 * got / out_of:.0f}%)."


def evening_line(now: datetime) -> str:
    """For the journal / briefing: subjects under WARN_BELOW%, or ""."""
    try:
        low = [status(s, a, t) for s, (a, t) in counts(load()).items() if percent(a, t) < WARN_BELOW]
    except AutomationError:
        return ""
    if low:
        logger.info(f"Attendance low: {low}")
    return ("Attendance: " + "; ".join(low) + ".") if low else ""
