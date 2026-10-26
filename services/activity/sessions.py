"""
services/activity/sessions.py

Sessions: stretches of one kind of thing ("work 14:05–15:40"), worked out from the
activity log's foreground time whenever they're needed — no table of their own, so
editing categories.py relabels old sessions too.

Categories are grouped to match the default modes (GROUPS); everything else
(communication, music, files, system, other) is neutral: it neither breaks nor extends
a session, so a quick WhatsApp reply mid-coding is still the same work session.
A group's stretches are merged while they're at most GAP apart; one with at least
MIN_ACTIVE of that group's own time is a session. Two groups can overlap when they
interleave; a break longer than GAP splits the session instead.

Used by services/proactive/watcher.py (offer the matching mode; sum a session up when
it ends), the daily journal and the weekly summary.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from services.activity.categories import categorize
from services.activity.log import _duration

GROUPS = {"coding": "work", "project": "work", "ai": "work", "documents": "work",
          "study": "study", "gaming": "gaming", "entertainment": "chill"}
DOING = {"work": "working", "study": "studying", "gaming": "gaming", "chill": "chilling"}
GAP = timedelta(minutes=10)          # this long without the group ends its session
MIN_ACTIVE = 10 * 60                 # seconds of the group's own time before it counts as a session
SUMMARY_MIN = 20 * 60                # sessions at least this long get a notification when they end
SUMMARY_WITHIN = timedelta(minutes=30)  # …if they ended this recently (a restart doesn't replay old ones)
OFFER_AGAIN = 2 * 3600               # an unanswered mode suggestion isn't repeated for this long
LOOKBACK = timedelta(hours=6)        # how far back the live check reads


@dataclass
class Session:
    group: str
    start: datetime
    end: datetime                    # the last minute of the group, not when the end was noticed
    active_s: float = 0
    projects: dict[str, float] = field(default_factory=dict)


def build(rows) -> list[Session]:
    """rows: (at, seconds, category, project), oldest first → the sessions in them, by start time."""
    current: dict[str, Session] = {}
    done: list[Session] = []
    for at, seconds, category, project in rows:
        group = GROUPS.get(category)
        if not group or not seconds:
            continue
        start = at if isinstance(at, datetime) else datetime.fromisoformat(at)
        end = start + timedelta(seconds=seconds)
        s = current.get(group)
        if s is None or start - s.end > GAP:
            if s:
                done.append(s)
            s = current[group] = Session(group, start, end)
        s.end = max(s.end, end)
        s.active_s += seconds
        if project:
            s.projects[project] = s.projects.get(project, 0) + seconds
    done.extend(current.values())
    return sorted((s for s in done if s.active_s >= MIN_ACTIVE), key=lambda s: s.start)


def recent(log, now: datetime) -> list[Session]:
    """Sessions of the last few hours, counting the app in front right now (not saved as a row yet)."""
    rows = list(log.app_rows(now - LOOKBACK, now))
    if log.app and log.title_since:
        category = "project" if log.project else categorize("app", log.app, title=log.title)
        rows.append((log.title_since, (now - log.title_since).total_seconds(), category, log.project))
    return build(rows)


def on_day(log, day: date) -> list[Session]:
    start = datetime.combine(day, datetime.min.time())
    return build(log.app_rows(start, start + timedelta(days=1)))


# ── Decisions for the watcher ─────────────────────────────────────────────────

def to_suggest(found: list[Session], offers: dict, modes: set[str], now: datetime) -> Session | None:
    """
    The running session to offer its mode for, or None. offers: {group: {"day", "at", "declined"}} —
    "No" stops that group for the day; no answer waits OFFER_AGAIN.
    """
    today = now.date().isoformat()
    running = [s for s in found if now - s.end <= GAP and s.group in modes]
    for s in sorted(running, key=lambda s: -s.active_s):
        offer = offers.get(s.group, {})
        if offer.get("day") == today and (offer.get("declined") or now.timestamp() - offer.get("at", 0) < OFFER_AGAIN):
            continue
        return s
    return None


def just_ended(found: list[Session], now: datetime) -> list[Session]:
    """Long-enough sessions that are over and ended recently (worth a summary)."""
    return [s for s in found if s.active_s >= SUMMARY_MIN and GAP < now - s.end <= GAP + SUMMARY_WITHIN]


def key(s: Session) -> str:
    return f"{s.group}@{s.end:%Y-%m-%dT%H:%M}"


# ── Text ──────────────────────────────────────────────────────────────────────

def _projects(s: Session) -> list[tuple[str, float]]:
    return sorted(((p, t) for p, t in s.projects.items() if t >= 60), key=lambda i: -i[1])[:2]


def line(s: Session) -> str:
    """For the journal: "14:05–15:40 work — 1h 35m (FRIDAY)"."""
    names = ", ".join(p for p, _ in _projects(s))
    return f"{s.start:%H:%M}–{s.end:%H:%M} {s.group} — {_duration(s.active_s)}" + (f" ({names})" if names else "")


def summary(s: Session, commits: int = 0) -> str:
    """ "Work session done: 1h 35m (14:05–15:40) — FRIDAY 1h 10m, 3 commits." """
    extras = [f"{p} {_duration(t)}" for p, t in _projects(s)]
    if commits:
        extras.append(f"{commits} commit{'s' if commits != 1 else ''}")
    return (f"{s.group.title()} session done: {_duration(s.active_s)} ({s.start:%H:%M}–{s.end:%H:%M})"
            + (" — " + ", ".join(extras) if extras else "") + ".")


def commits_in(s: Session) -> int:
    """Commits made during the session in its projects (runs git; blocking)."""
    if not s.projects:
        return 0
    from services.activity import journal  # journal imports this module

    found = journal.commits_between(s.start.isoformat(timespec="seconds"), s.end.isoformat(timespec="seconds"))
    return sum(len(found.get(p, [])) for p in s.projects)
