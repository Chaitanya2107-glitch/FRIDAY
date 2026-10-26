"""
services/activity/fun.py

Numbers about yourself, from the activity log — locally, no AI:
  "how many hours did I game this week" / "game hours today" — gaming time, per game
  "what's my study streak" — days in a row with STREAK_MINUTES+ of study (and the best run)
  "semester wrap-up" / "how was my semester" — a Markdown page in Documents\\FRIDAY Journal:
      active time, time per kind, study per subject, attendance, games, projects + commits,
      the best study streak, and top Spotify artists/songs when Spotify is connected.
      The semester starts at SEMESTER_START (.env), or when FRIDAY started logging.
"""

import os
import re
from datetime import date, datetime, timedelta

from core.config import config
from core.logger import logger
from services.activity import ask, journal, study
from services.activity.log import _duration

FUN_ACTIONS = {"game_hours", "study_streak", "semester_wrap"}
STREAK_MINUTES = 30
STREAK_LOOKBACK_DAYS = 180
TOP_GAMES = 4

_GAME = re.compile(r"^(?:how (?:many hours|much time|long) (?:did|have) i (?:game|gamed|play(?:ed)?(?: games)?|spen[dt] gaming)"
                   r"|(?:my )?(?:game|gaming) (?:hours|time))\b(?P<rest>.*)$", re.I)
_STREAK = re.compile(r"^(?:what(?:'s| is) )?(?:my )?study streak$|^how many days (?:in a row )?have i studied(?: in a row)?$", re.I)
_SEMESTER = re.compile(r"^(?:(?:my |the |show (?:me )?my )?semester (?:wrap[- ]?up|wrapped|review|summary)|how was my semester)$", re.I)


def match_fun_command(text: str) -> dict | None:
    text = text.strip().rstrip("?.!")
    if m := _GAME.match(text):
        return {"type": "system", "action": "game_hours", "question": text}
    if _STREAK.match(text):
        return {"type": "system", "action": "study_streak"}
    if _SEMESTER.match(text):
        return {"type": "system", "action": "semester_wrap"}
    return None


# ── Games ─────────────────────────────────────────────────────────────────────

def games(log, start: datetime, end: datetime) -> dict[str, float]:
    """Seconds per game (≥ a minute), most first."""
    rows = log.search("kind = 'app' AND category = 'gaming' AND at >= ? AND at < ?", [start.isoformat(), end.isoformat()])
    found: dict[str, float] = {}
    for row in rows:
        found[row["app"]] = found.get(row["app"], 0) + (row["duration_s"] or 0)
    return dict(sorted(((g, s) for g, s in found.items() if s >= 60), key=lambda i: -i[1]))


def game_hours(question: str, log, now: datetime | None = None) -> str:
    start, end, label = ask.time_window(question, now or datetime.now())
    found = games(log, start, end)
    if not found:
        return f"No gaming {label}. Suspicious, but well done."
    top = ", ".join(f"{g} {_duration(s)}" for g, s in list(found.items())[:TOP_GAMES])
    return f"You gamed {_duration(sum(found.values()))} {label} — {top}."


# ── Study streak ──────────────────────────────────────────────────────────────

def _studied_minutes(log, day: date) -> float:
    start = datetime.combine(day, datetime.min.time())
    return sum(study.totals(log.study_rows(start, start + timedelta(days=1))).values()) / 60


def streaks(log, today: date) -> tuple[int, int, bool]:
    """(current streak, best streak, today already counts). Today not counting yet doesn't break it."""
    days = [today - timedelta(days=i) for i in range(STREAK_LOOKBACK_DAYS)]
    done = [_studied_minutes(log, d) >= STREAK_MINUTES for d in days]  # newest first
    current = 0
    for i, ok in enumerate(done):
        if ok:
            current += 1
        elif i > 0:  # today not yet: the streak can still continue tonight
            break
    best = run = 0
    for ok in done:
        run = run + 1 if ok else 0
        best = max(best, run)
    return current, best, done[0]


def streak_message(log, today: date | None = None) -> str:
    current, best, today_counts = streaks(log, today or date.today())
    if not current:
        return f"No study streak right now — {STREAK_MINUTES} minutes of study today starts one." + (
            f" Your best was {best} day{'s' if best != 1 else ''}." if best else "")
    text = f"{current} day{'s' if current != 1 else ''} in a row with {STREAK_MINUTES}+ minutes of study"
    text += "." if today_counts else f" — study {STREAK_MINUTES} minutes today to keep it going."
    return text + (f" Best: {best} days." if best > current else " That's your best yet.")


# ── Semester wrap-up ──────────────────────────────────────────────────────────

def semester_start(log) -> date:
    if config.SEMESTER_START:
        try:
            return date.fromisoformat(config.SEMESTER_START)
        except ValueError:
            logger.warning(f"SEMESTER_START isn't a date (YYYY-MM-DD): {config.SEMESTER_START}")
    rows = log.app_rows(datetime(2000, 1, 1), datetime.now())  # oldest first
    return datetime.fromisoformat(rows[0][0]).date() if rows else date.today()


def _spotify_lines() -> list[str]:
    from services.spotify import auth, wrapped

    if not auth.is_connected() or "user-top-read" in auth.missing_scopes():
        return []
    try:
        return [wrapped.wrapped("medium_term")]
    except Exception as e:  # offline or Spotify refused: the page is fine without it
        logger.info(f"Semester wrap-up without Spotify: {e}")
        return []


def build_semester(log, today: date | None = None) -> str:
    from services.proactive import attendance

    today = today or date.today()
    first = semester_start(log)
    start, end = datetime.combine(first, datetime.min.time()), datetime.combine(today + timedelta(days=1), datetime.min.time())
    rows = log.app_rows(start, end)
    lines = [f"# Semester wrap-up — {first:%d %b %Y} to {today:%d %b %Y}", ""]
    active = sum(r[1] or 0 for r in rows)
    lines.append(f"**Active:** {_duration(active)} over {(today - first).days + 1} days")

    def section(title: str, items: list[str]) -> None:
        if items:
            lines.extend(["", f"## {title}", *[f"- {item}" for item in items]])

    kinds: dict[str, float] = {}
    for _, secs, kind, _ in rows:
        if kind and kind not in ("other", "system"):
            kinds[kind] = kinds.get(kind, 0) + (secs or 0)
    section("Time", [f"{k} {_duration(s)}" for k, s in sorted(kinds.items(), key=lambda i: -i[1]) if s >= 60])
    studied = study.totals(log.study_rows(start, end))
    section("Study", [f"{s} {_duration(t)}" for s, t in studied.items()])
    _, best, _ = streaks(log, today)
    section("Streak", [f"Best study streak: {best} day{'s' if best != 1 else ''} in a row"] if best else [])
    try:
        counted = attendance.counts(attendance.load())
    except Exception:
        counted = {}
    section("Attendance", [attendance.status(s, a, t) for s, (a, t) in counted.items()])
    played = games(log, start, end)
    section("Games", [f"{g} {_duration(s)}" for g, s in played.items()])
    commits = journal.commits_between(first.isoformat(), (today + timedelta(days=1)).isoformat())
    projects: dict[str, float] = {}
    for _, secs, _, project in rows:
        if project:
            projects[project] = projects.get(project, 0) + (secs or 0)
    section("Projects", [f"{p} — {_duration(s)}" + (f" ({len(commits[p])} commits)" if commits.get(p) else "")
                         for p, s in sorted(projects.items(), key=lambda i: -i[1]) if s >= 60])
    section("Music", _spotify_lines())
    return "\n".join(lines) + "\n"


def semester_wrap(log, today: date | None = None, open_file=os.startfile) -> str:
    today = today or date.today()
    text = build_semester(log, today)
    journal.JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    file = journal.JOURNAL_DIR / f"Semester wrap-up {today.isoformat()}.md"
    file.write_text(text, encoding="utf-8")
    open_file(file)
    active = re.search(r"\*\*Active:\*\* ([^\n]+)", text)
    return f"Your semester so far: {active[1] if active else 'nothing yet'}. Opened the full wrap-up."


def run(parsed: dict, log) -> str:
    action = parsed["action"]
    if action == "game_hours":
        return game_hours(parsed["question"], log)
    if action == "study_streak":
        return streak_message(log)
    return semester_wrap(log)
