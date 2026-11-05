"""
services/activity/journal.py

A daily journal, written from the day's activity — locally, no AI (the titles are private):
your own entries ("journal: …", services/memory/notes.py), time per kind of thing and per project, sessions, study time per subject, classes, commits, videos watched, songs,
searches, files opened and the apps used most.

Saved as Markdown in Documents\\FRIDAY Journal\\<date>.md. Written automatically at
JOURNAL_HOUR (services/proactive/watcher.py, with a notification), or on request:
  "write my journal" (today), "open my journal", "open yesterday's journal",
  "open my journal for Monday".
"""

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from core.logger import logger
from services.activity import ask, git_status, projects, sessions, study
from services.memory import notes
from services.automation.system_control import AutomationError

JOURNAL_DIR = Path.home() / "Documents" / "FRIDAY Journal"  # tests point this elsewhere
JOURNAL_ACTIONS = {"write_journal", "open_journal", "search_journal"}
SEARCH_HITS = 8
MAX_ITEMS = 12
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_WRITE = re.compile(r"^(?:write|make|create|save|update)(?: me)? (?:my |the |today's )?(?:daily )?journal(?: for today)?$", re.I)
_OPEN = re.compile(
    rf"^(?:open|show|read)(?: me)? (?:my |the )?(?:(?P<pre>today's|yesterday's) )?(?:daily )?journal"
    rf"(?: (?:for |from |of )?(?P<day>today|yesterday|(?:last )?(?:{'|'.join(WEEKDAYS)})))?$", re.I,
)
_SEARCH = re.compile(r"^(?:search|find|look (?:up|through)|grep)(?: in)? (?:my |the )?(?:journals?|diary)(?: entries)? for (?P<q>.+)$"
                     r"|^what did i write about (?P<q2>.+?)(?: in my (?:journal|diary))?$", re.I)


def match_journal_command(text: str) -> dict | None:
    text = text.strip()
    if _WRITE.match(text):
        return {"type": "system", "action": "write_journal"}
    if m := _OPEN.match(text):
        which = (m["pre"] or m["day"] or "today").lower().removesuffix("'s").removeprefix("last ")
        return {"type": "system", "action": "open_journal", "day": which}
    if m := _SEARCH.match(text):
        return {"type": "system", "action": "search_journal", "query": (m["q"] or m["q2"]).strip(" .?\"'")}
    return None


def search(query: str) -> str:
    """Lines mentioning `query` in the saved journals and diary entries, newest first."""
    hits: list[tuple[str, str]] = []  # (ISO day, line)
    for file in sorted(JOURNAL_DIR.glob("*.md"), reverse=True) if JOURNAL_DIR.exists() else []:
        for line in file.read_text(encoding="utf-8").splitlines():
            if query.lower() in line.lower() and not line.startswith("#"):
                hits.append((file.stem, line.strip("- ").strip()))
    for entry in notes.load(notes.diary_path):  # today's entries aren't in a written journal yet
        line = f"{entry['at'][11:16]} — {entry['text']}"
        if query.lower() in entry["text"].lower() and (entry["at"][:10], line) not in hits:
            hits.append((entry["at"][:10], line))
    if not hits:
        return f"Nothing about \"{query}\" in your journals."
    hits.sort(key=lambda hit: hit[0], reverse=True)
    shown = [f"{date.fromisoformat(day):%a %d %b}: {line}" for day, line in hits[:SEARCH_HITS]]
    more = f"\n…and {len(hits) - SEARCH_HITS} more." if len(hits) > SEARCH_HITS else ""
    return f"\"{query}\" in your journals:\n" + "\n".join(shown) + more


def _day_for(which: str, today: date) -> date:
    if which == "today":
        return today
    if which == "yesterday":
        return today - timedelta(days=1)
    back = (today.weekday() - WEEKDAYS.index(which)) % 7 or 7  # the most recent past one
    return today - timedelta(days=back)


def journal_path(day: date) -> Path:
    return JOURNAL_DIR / f"{day.isoformat()}.md"


def run(parsed: dict, log, today: date | None = None) -> str:
    today = today or date.today()
    if parsed["action"] == "search_journal":
        return search(parsed["query"])
    if parsed["action"] == "write_journal":
        file = write(today, log)
        return f"Wrote today's journal: {file}."
    day = _day_for(parsed["day"], today)
    file = journal_path(day)
    if not file.exists():
        if day == today or day == today - timedelta(days=1):
            file = write(day, log)  # not written yet: write it now
        else:
            raise AutomationError(f"There's no journal for {day:%A, %d %B}.")
    os.startfile(file)
    return f"Opening your journal for {day:%A, %d %B}."


# ── Writing ───────────────────────────────────────────────────────────────────

def write(day: date, log) -> Path:
    text = build(day, log)
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    file = journal_path(day)
    file.write_text(text, encoding="utf-8")
    logger.info(f"Journal written: {file}")
    return file


def _rows(log, day: date, where: str, params: list | None = None):
    start = datetime.combine(day, datetime.min.time())
    return log.search(f"at >= ? AND at < ? AND {where}",
                      [start.isoformat(), (start + timedelta(days=1)).isoformat(), *(params or [])])


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def _totals(rows, key: str) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in rows:
        if row[key]:
            totals[row[key]] = totals.get(row[key], 0) + (row["duration_s"] or 0)
    return [(k, v) for k, v in sorted(totals.items(), key=lambda i: -i[1]) if v >= 60]


def _items(rows) -> list[str]:
    """Each thing once, oldest first (the day read in order), cleaned like activity answers."""
    return [text for _, text in reversed(ask._distinct(rows))][:MAX_ITEMS]


def build(day: date, log) -> str:
    """The journal for one day, as Markdown ("" sections are left out)."""
    apps = _rows(log, day, "kind = 'app'")
    sections = [f"# {day:%A, %d %B %Y}", ""]
    active = sum(r["duration_s"] or 0 for r in apps)
    kinds = [(k, s) for k, s in _totals(apps, "category") if k not in ("other", "system")]
    note_lines, diary_lines = notes.on_day(day), notes.on_day(day, notes.diary_path)

    def section(title: str, lines: list[str]) -> None:
        if lines:
            sections.extend(["", f"## {title}", *[f"- {line}" for line in lines]])

    if active < 60:
        sections.append("_Nothing recorded for this day._")
        section("Diary", diary_lines)
        section("Notes", note_lines)
        return "\n".join(sections) + "\n"
    sections.append(f"**Active:** {_duration(active)}" +
                    (" — " + ", ".join(f"{k} {_duration(s)}" for k, s in kinds[:6]) if kinds else ""))
    section("Diary", diary_lines)

    section("Sessions", [sessions.line(s) for s in sessions.on_day(log, day)])
    start = datetime.combine(day, datetime.min.time())
    studied = study.totals(log.study_rows(start, start + timedelta(days=1)))
    section("Study", [study.line(studied)] if studied else [])
    project_time = _totals(apps, "project")
    commits = _commits(day)
    section("Projects", [f"{name} — {_duration(secs)}" + (f" ({len(commits[name])} commit"
                         f"{'s' if len(commits[name]) != 1 else ''})" if commits.get(name) else "")
                         for name, secs in project_time])
    section("Commits", [f"{name}: {message}" for name, messages in commits.items() for message in messages][:MAX_ITEMS])
    section("Classes", _classes(day))
    section("Watched", _items(_rows(log, day, "kind = 'web' AND target LIKE '%youtube.%' AND title LIKE '% - YouTube'")))
    section("Listened to", _items(_rows(log, day, "kind = 'app' AND app = 'spotify' AND title NOT LIKE 'Spotify%'")))
    section("Searched for", _items(_rows(log, day, "kind = 'web' AND (title LIKE '% - Google Search' OR title LIKE '% - Bing')")))
    section("Files opened", _items(_rows(log, day, "kind = 'file' AND target NOT LIKE 'ms-%' AND target NOT LIKE 'http%' "
                                                  "AND target NOT LIKE '{%'")))
    section("Apps", [", ".join(f"{app} {_duration(s)}" for app, s in _totals(apps, "app")[:8])])
    section("Notes", note_lines)
    return "\n".join(sections) + "\n"


def _commits(day: date) -> dict[str, list[str]]:
    """Commit messages made that day in each saved project."""
    return commits_between(day.isoformat(), (day + timedelta(days=1)).isoformat())


def commits_between(since: str, until: str) -> dict[str, list[str]]:
    """Commit messages made between two ISO dates/times in each saved project (sessions and the week use it too)."""
    found: dict[str, list[str]] = {}
    if not projects.load():
        return found
    try:
        repos = git_status._repos()
    except AutomationError:
        return found
    for name, folder in repos.items():
        try:
            messages = git_status._git(folder, "log", f"--since={since}", f"--until={until}", "--pretty=%s").splitlines()
        except AutomationError:
            continue
        if messages:
            found[name] = list(reversed(messages))  # in the order they were made
    return found


def _classes(day: date) -> list[str]:
    from services.proactive import timetable  # avoid an import cycle at startup

    try:
        return [f"{timetable._clock(c['start'])} {c['subject']}" + (f" ({c['room']})" if c.get("room") else "")
                for c in timetable.classes_for_date(day)]
    except AutomationError:
        return []


def evening_note(day: date, log) -> str | None:
    """Write the day's journal and say so in one line (for the evening notification); None if nothing happened."""
    text = build(day, log)
    if "_Nothing recorded" in text:
        return None
    write(day, log)
    active = re.search(r"\*\*Active:\*\* ([^\n]+)", text)
    return f"Today's journal is saved — {active[1] if active else ''}. Say \"open my journal\" to read it."
