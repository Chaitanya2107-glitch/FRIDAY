"""
services/activity/study.py

Study time per subject, from the activity log (services/activity/log.py) — locally, no AI:
  - time in any app counts for a subject when the window title names it ("DBMS unit 2.pdf",
    "Data Structures lecture - YouTube") — short name or initials, the subjects from the
    timetable and "my subjects are …" (services/proactive/timetable.py)
  - "start study mode for DBMS": everything until the mode ends counts for DBMS, except
    games, chat, music and system windows (the rows carry the subject)

  "how long did I study DBMS this week", "study hours today", "how much did I study yesterday",
  "my study time last week"  (no time said = the past 7 days)
Also in the daily journal and the weekly summary.
"""

import re
from datetime import datetime

from services.activity import ask
from services.activity.log import _duration
from services.proactive import timetable

STUDY_ACTIONS = {"study_hours"}
NOT_STUDY = {"gaming", "communication", "music", "system"}  # study mode doesn't count these

_ASK = re.compile(
    r"^(?:how (?:long|much|many hours) (?:did|have) i (?:study|studied|spen[dt] studying)"
    r"|(?:what(?:'s| is| are) )?(?:my )?study (?:hours|time))\b(?P<rest>.*)$", re.I,
)
_WHEN = re.compile(
    r"\b(?:today|yesterday|tonight|last night|so far|in total|(?:this|last) (?:week|morning|afternoon|evening)"
    r"|\d+ days? ago|(?:on |last )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I,
)


def match_study_command(text: str) -> dict | None:
    """ "how long did I study DBMS this week" → {"action": "study_hours", "subject": "DBMS", "question": …}"""
    m = _ASK.match(text.strip())
    if not m:
        return None
    said = re.sub(r"^\s*(?:for|on|of)\s+", "", _WHEN.sub(" ", m["rest"])).strip(" ?.")
    return {"type": "system", "action": "study_hours", "question": text.strip(),
            "subject": timetable.subject_named(said) if said else ""}


def subject_of(title: str | None, category: str | None, stored: str | None, forms: dict[str, list[str]]) -> str | None:
    """The subject a stretch of time counts for: study mode's, else the one its title names
    (forms: each subject → its names, timetable.aliases())."""
    if stored:
        return stored if category not in NOT_STUDY else None
    return next((s for s, names in forms.items() if title and timetable.mentions_subject(title, names)), None)


def totals(rows, names: list[str] | None = None) -> dict[str, float]:
    """Seconds per subject (≥ a minute), most first, from log.study_rows()."""
    forms = {s: timetable.aliases(s) for s in (timetable.subjects() if names is None else names)}
    found: dict[str, float] = {}
    for _, seconds, title, category, stored in rows:
        if subject := subject_of(title, category, stored, forms):
            found[subject] = found.get(subject, 0) + (seconds or 0)
    return dict(sorted(((s, t) for s, t in found.items() if t >= 60), key=lambda i: -i[1]))


def line(found: dict[str, float]) -> str:
    """ "DBMS 2h 10m, DS 45m" """
    return ", ".join(f"{subject} {_duration(seconds)}" for subject, seconds in found.items())


def run(parsed: dict, log, now: datetime | None = None) -> str:
    now = now or datetime.now()
    start, end, label = ask.time_window(parsed["question"], now)
    subject = parsed["subject"]
    names = timetable.subjects()
    if subject and subject not in names:
        names = [subject, *names]  # not in the timetable: still look for it in titles
    found = totals(log.study_rows(start, end), names)
    if subject:
        if subject not in found:
            return f"You haven't studied {subject} {label}."
        return f"You studied {subject} for {_duration(found[subject])} {label}."
    if not found:
        hint = "" if names else ' Tell me your subjects first: "my subjects are …" or import your timetable.'
        return f"No study time recorded {label}.{hint}"
    return f"Study time {label}: {line(found)} — {_duration(sum(found.values()))} in all."
