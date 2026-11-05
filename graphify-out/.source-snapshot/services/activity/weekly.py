"""
services/activity/weekly.py

The weekly summary, written from the week's activity — locally, no AI (like the journal):
active time, time per category and study time per subject compared with the week before, projects and commits,
sessions per kind and the longest, active time per day.

Saved as Markdown in Documents\\FRIDAY Journal\\Week of <Monday>.md. Written automatically
on Sunday at JOURNAL_HOUR (services/proactive/watcher.py, with a one-line notification), or
on request: "how was my week", "open my weekly summary", "open last week's summary".
Asking always rewrites it, so a half-finished week is up to date. (No "write my weekly
summary": "write …" is the typing command.)
"""

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from core.logger import logger
from services.activity import insights, journal, predict, sessions, study
from services.activity.log import _duration

WEEKLY_ACTIONS = {"open_weekly"}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_SHIPPED = 8  # commit messages per project in "Shipped"

_OPEN = re.compile(r"^(?:how was my week|how did my week go|(?:open|show|read)(?: me)? (?:my |the )?"
                   r"(?:(?P<which>this|last) week's (?:weekly )?|weekly )(?:summary|review))$", re.I)


def match_weekly_command(text: str) -> dict | None:
    text = text.strip()
    if m := _OPEN.match(text):
        return {"type": "system", "action": "open_weekly", "which": (m["which"] or "this").lower()}
    return None


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def summary_path(monday: date) -> Path:
    return journal.JOURNAL_DIR / f"Week of {monday.isoformat()}.md"


def run(parsed: dict, log, today: date | None = None) -> str:
    monday = monday_of(today or date.today())
    if parsed.get("which") == "last":
        monday -= timedelta(days=7)
    os.startfile(write(monday, log))
    return note(monday, log) or f"Nothing recorded for the week of {monday:%d %B}."


def write(monday: date, log) -> Path:
    journal.JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    file = summary_path(monday)
    file.write_text(build(monday, log), encoding="utf-8")
    logger.info(f"Weekly summary written: {file}")
    return file


# ── Numbers ───────────────────────────────────────────────────────────────────

def _week(log, monday: date):
    start = datetime.combine(monday, datetime.min.time())
    return log.app_rows(start, start + timedelta(days=7))


def _totals(rows, index: int) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        if row[index] and row[index] not in ("other", "system"):
            totals[row[index]] = totals.get(row[index], 0) + (row[1] or 0)
    return dict(sorted(((k, v) for k, v in totals.items() if v >= 60), key=lambda i: -i[1]))


def _change(now: float, before: float | None) -> str:
    """ "(+3h 0m)" / "(−2h 0m)" against last week; "" when last week had no data or it's within a minute."""
    if before is None or abs(now - before) < 60:
        return ""
    return f" ({'+' if now > before else '−'}{_duration(abs(now - before))})"


def _shipped(monday: date) -> dict[str, list[str]]:
    """Each saved project's commit messages that week, oldest first."""
    return journal.commits_between(monday.isoformat(), (monday + timedelta(days=7)).isoformat())


def _commits(monday: date) -> dict[str, int]:
    return {name: len(messages) for name, messages in _shipped(monday).items()}


def build(monday: date, log) -> str:
    rows, before = _week(log, monday), _week(log, monday - timedelta(days=7))
    lines = [f"# Week of {monday:%A, %d %B %Y}", ""]
    active = sum(r[1] or 0 for r in rows)
    if active < 60:
        return "\n".join(lines + ["_Nothing recorded for this week._"]) + "\n"
    had_before = sum(r[1] or 0 for r in before) >= 60
    kinds, kinds_before = _totals(rows, 2), _totals(before, 2)
    lines.append(f"**Active:** {_duration(active)}" + _change(active, sum(r[1] or 0 for r in before) if had_before else None))

    def section(title: str, items: list[str]) -> None:
        if items:
            lines.extend(["", f"## {title}", *[f"- {item}" for item in items]])

    section("Time", [f"{k} {_duration(s)}" + _change(s, kinds_before.get(k, 0) if had_before else None)
                     for k, s in kinds.items()])
    start = datetime.combine(monday, datetime.min.time())
    studied = study.totals(log.study_rows(start, start + timedelta(days=7)))
    studied_before = study.totals(log.study_rows(start - timedelta(days=7), start)) if had_before else {}
    section("Study", [f"{subject} {_duration(secs)}" + _change(secs, studied_before.get(subject, 0) if had_before else None)
                      for subject, secs in studied.items()])
    shipped = _shipped(monday)
    commits = {name: len(messages) for name, messages in shipped.items()}
    section("Shipped", [f"{name}: {message}" for name, messages in shipped.items()  # a draft changelog
                        for message in messages[-MAX_SHIPPED:]])
    section("Projects", [f"{name} — {_duration(secs)}" + (f" ({commits[name]} commit{'s' if commits[name] != 1 else ''})"
                         if commits.get(name) else "") for name, secs in _totals(rows, 3).items()])
    found = sessions.build(rows)
    section("Sessions", [f"{group}: {len(group_sessions)} session{'s' if len(group_sessions) != 1 else ''}, longest "
                         f"{_duration(longest.active_s)} ({longest.start:%a %H:%M})"
                         for group in sessions.DOING
                         if (group_sessions := [s for s in found if s.group == group])
                         and (longest := max(group_sessions, key=lambda s: s.active_s))])
    per_day = [0.0] * 7
    for at, secs, *_ in rows:
        per_day[datetime.fromisoformat(at).weekday()] += secs or 0
    section("Days", [", ".join(f"{DAYS[i]} {_duration(s)}" for i, s in enumerate(per_day) if s >= 60)])
    section("Rhythm", [f"You {line}." for line in [insights.rhythm_line(rows)] if line])
    _, weeks = predict.replay(log.app_sequence())
    section("Predictions", [line] if (line := predict.week_line(weeks.get(monday))) else [])
    return "\n".join(lines) + "\n"


def note(monday: date, log) -> str | None:
    """One line for the Sunday notification; None if nothing was recorded."""
    rows, before = _week(log, monday), _week(log, monday - timedelta(days=7))
    active, active_before = sum(r[1] or 0 for r in rows), sum(r[1] or 0 for r in before)
    if active < 60:
        return None
    had_before = active_before >= 60
    kinds_before = _totals(before, 2)
    kinds = [f"{k} {_duration(s)}" + _change(s, kinds_before.get(k, 0) if had_before else None)
             for k, s in list(_totals(rows, 2).items())[:3]]
    parts = [f"Your week: {_duration(active)} active" + (" — " + ", ".join(kinds) if kinds else "")]
    if top := next(iter(_totals(rows, 3)), None):
        parts.append(f"top project {top}")
    if commits := sum(_commits(monday).values()):
        parts.append(f"{commits} commit{'s' if commits != 1 else ''}")
    return " · ".join(parts) + '. Say "open my weekly summary" to read it.'
