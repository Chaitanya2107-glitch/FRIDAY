"""
services/activity/log.py

A local record of what the user does, as data for FRIDAY to learn habits from
later ("you usually open VS Code around 9 — want me to?").

Rows in the activity table of MEMORY_DB_PATH (kind):
  - app:     which app + window title was in the foreground, from when, for how
             long. Sampled every few seconds; idle time (no keyboard/mouse input)
             and FRIDAY's own windows aren't counted.
  - command: every command FRIDAY ran (action, target like the app or song,
             success), plus the app the user was in when they asked.
  - launch:  an app that started running (checked once a minute).
  - web:     a page visited in Chrome/Edge — domain + page title, from the browser history.
  - file:    a file opened in Windows (file name only, no folder, no contents).

Every row also gets a category (coding, study, ai, music, …) from
services/activity/categories.py when it's saved; all rows are re-sorted each
time FRIDAY starts, so editing that list relabels old data too. Rows that
belong to a project the user saved (services/activity/projects.py) get that
project and the category "project".

Never recorded: keystrokes, typed text, clipboard contents, screenshots, URL
paths. Password managers are skipped entirely; window titles are dropped for
private/incognito windows and banking/login pages. Nothing leaves this PC.
"what have I been doing today" summarises the day, "clear my activity log"
deletes everything, ACTIVITY_LOG_ENABLED=false turns it off.
"""

import asyncio
import ctypes
import itertools
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
from contextlib import closing
from contextvars import ContextVar
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import psutil

from core.config import config
from core.logger import logger
from services.activity import projects
from services.activity.categories import categorize, clean_title

# Set per request by intent.try_system_action: the commands it ran (services/automation/personality.py reads them)
commands_run: ContextVar[list | None] = ContextVar("commands_run", default=None)

POLL_SECONDS = 5
# No input for this long = away, unless the app in front is playing media (a lecture video).
# ponytail: a call with no media session (Zoom, Meet) still counts as away
IDLE_SECONDS = 300
# FRIDAY's own windows (tray, command bar) and the lock screen say nothing about what the user is doing
IGNORED_PROCESSES = {"python", "pythonw", "lockapp", "searchhost", "shellexperiencehost"}
PASSWORD_MANAGERS = {"keepass", "keepassxc", "bitwarden", "1password", "lastpass", "dashlane", "enpass", "nordpass"}
# Titles/domains that are logged as "app only" (titles) or not at all (sites)
PRIVATE_TITLE = re.compile(r"incognito|inprivate|private browsing|bank|paypal|password|sign in|log ?in\b", re.I)
PRIVATE_SITE = re.compile(r"bank|paypal|netbanking|hdfc|icici|sbi\.co|axis|paytm|password|accounts\.google|login", re.I)
SLOW_EVERY = 12  # ticks of POLL_SECONDS: launches, browser history and recent files once a minute
BROWSER_HISTORIES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data/Default/History",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data/Default/History",
]
RECENT_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Recent"
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
# Only these parts of a command are kept — never typed text, clipboard or memory contents
NO_ACTIVITY = "I haven't recorded any activity today yet."
TARGET_KEYS = ("app_name", "query", "url", "path", "part", "routine", "project", "contact")  # never message text

_SUMMARY = re.compile(
    r"^(?:what (?:have|did) i (?:been )?(?:do|doing|done)(?: on my (?:pc|computer|laptop))?"
    r"|how (?:have|did) i spen[dt] my (?:day|time)|(?:show|give)(?: me)? my (?:activity|day)(?: summary)?"
    r"|my activity(?: today)?)(?: today)?$",
    re.IGNORECASE,
)
_CLEAR = re.compile(r"^(?:clear|delete|wipe|erase|reset)(?: my| the)? activity(?: log| history)?$", re.IGNORECASE)
ACTIVITY_ACTIONS = {"activity_summary", "clear_activity"}


def match_activity_command(text: str) -> dict | None:
    """Activity commands. `text` has already been through normalize_command()."""
    if _SUMMARY.match(text.strip()):
        return {"type": "system", "action": "activity_summary"}
    if _CLEAR.match(text.strip()):
        return {"type": "system", "action": "clear_activity"}
    return None


# ── Windows: the foreground app and idle time ─────────────────────────────────

class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def foreground_window() -> tuple[str | None, str | None]:
    """('chrome', 'Inbox - Gmail'); (None, None) for FRIDAY's own windows, password managers, the lock screen or no window."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        name = psutil.Process(pid.value).name().lower().removesuffix(".exe")
    except (psutil.Error, ValueError):
        return None, None
    if name in IGNORED_PROCESSES or name in PASSWORD_MANAGERS:
        return None, None
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    title = buf.value.strip()
    return name, (None if PRIVATE_TITLE.search(title) else title or None)


def foreground_app() -> str | None:
    return foreground_window()[0]


def foreground_ids() -> tuple[int | None, int | None]:
    """(window handle, process id) of the foreground window."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, pid.value


def running_apps() -> set[str]:
    """Names of the user's running programs ('code', 'spotify'), leaving out Windows' own."""
    names = set()
    for p in psutil.process_iter(["name", "exe"]):
        exe = (p.info["exe"] or "").lower()
        if exe and not exe.startswith("c:\\windows") and p.info["name"]:
            names.add(p.info["name"].lower().removesuffix(".exe"))
    return names - IGNORED_PROCESSES - PASSWORD_MANAGERS


def idle_seconds() -> float:
    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def media_playing_in(app: str) -> bool:
    """Whether `app` ('chrome') is playing a video or audio right now (Windows' media sessions)."""
    from services.automation import media_control  # loads winrt; only needed once the user looks idle

    return media_control.is_playing_in(app)


def study_subject() -> str | None:
    """The subject of the study mode that's on ("start study mode for DBMS"), else None."""
    from services.automation import modes  # avoid an import cycle

    return (modes.active() or {}).get("subject") or None


# ── The log ───────────────────────────────────────────────────────────────────

class ActivityLog:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.MEMORY_DB_PATH
        self._ready_for = None
        self._lock = threading.Lock()
        self.runtime = uuid.uuid4().hex
        self.origin = "unknown"
        self._observed_runtime = False
        self.app = None          # app in the foreground right now (None = idle/unknown)
        self.title = None        # its window title
        self.last_observed_at = None  # freshness, distinct from the beginning of a session
        self.last_foreground = None   # recent evidence for an explicit command-bar activity label
        self.app_since = None    # when the user got into this app (survives title changes — the long-stretch nudge uses it)
        self.title_since = None  # when this app+title started (what the next saved row covers)
        self.last_app = None     # last real app the user was in — context for commands
        self.last_window = (None, None)  # its (window, process) — "this is a project" looks there
        self.project = None      # saved project the current app is running in
        self._running = None     # program names seen last minute, to spot launches

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        if self._ready_for != self.db_path:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS activity (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    at         TEXT NOT NULL,   -- local time the app session / command started
                    kind       TEXT NOT NULL,   -- app, command, launch, web or file
                    app        TEXT,            -- app session: the app; command: the app the user was in
                    action     TEXT,            -- command: e.g. open_app, play_song
                    target     TEXT,            -- command: e.g. chrome, the song, the search
                    success    INTEGER,         -- command: 1/0
                    duration_s REAL             -- app session: seconds in the foreground
                );
                CREATE INDEX IF NOT EXISTS activity_at ON activity(at);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(activity)")}
            if "title" not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN title TEXT")  # window/page title (app, web rows)
            if "category" not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN category TEXT")  # coding, study, ai, … (categories.py)
            if "project" not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN project TEXT")  # a saved project (projects.py)
            if "subject" not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN subject TEXT")  # app rows in "study mode for X" (study.py)
            if "origin" not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown'")
            if "runtime" not in columns:
                conn.execute("ALTER TABLE activity ADD COLUMN runtime TEXT")
            conn.execute("CREATE TABLE IF NOT EXISTS activity_boundaries (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                         "at TEXT NOT NULL, reason TEXT NOT NULL, runtime TEXT NOT NULL)")
            conn.execute("INSERT INTO activity_boundaries(at,reason,runtime) VALUES (?,?,?)",
                         (datetime.now().isoformat(timespec="seconds"), "restart", self.runtime))
            conn.commit()
            self._recategorize(conn)
            self._ready_for = self.db_path
        return conn

    @staticmethod
    def _recategorize(conn: sqlite3.Connection) -> None:
        """
        Re-sort every row with the current categories.py and projects (at each start, and when a project
        is saved or removed), so edits reach old data. A project found while recording (from the folder a
        program ran in) is kept while that project is still saved.
        """
        # ponytail: rescans the whole table; fine for months of rows, only-changed-since if it gets slow
        saved = projects.load()
        rows = conn.execute("SELECT id, kind, app, target, title, action, category, project FROM activity").fetchall()
        changed = []
        for row_id, kind, app, target, title, action, old_category, old_project in rows:
            project = old_project if old_project in saved else projects.project_of_row(kind, app, target, title, saved)
            category = "project" if project else categorize(kind, app, target, title, action)
            if (category, project) != (old_category, old_project):
                changed.append((category, project, row_id))
        if changed:
            with conn:
                conn.executemany("UPDATE activity SET category = ?, project = ? WHERE id = ?", changed)
            logger.info(f"Activity log: sorted {len(changed)} rows into categories")

    def resort(self) -> None:
        """Re-sort all rows now (a project was just saved or removed)."""
        with self._lock, closing(self._connect()) as conn:
            self._recategorize(conn)

    def _insert(self, **row) -> None:
        project = row.get("project") or projects.project_of_row(
            row["kind"], row.get("app"), row.get("target"), row.get("title"), projects.load())
        row["project"] = project
        row["category"] = "project" if project else categorize(
            row["kind"], row.get("app"), row.get("target"), row.get("title"), row.get("action"))
        columns = ", ".join(row)
        with self._lock, closing(self._connect()) as conn, conn:
            conn.execute(f"INSERT INTO activity ({columns}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))

    # ── App sessions ──────────────────────────────────────────────────────────

    def observe(self, app: str | None, now: datetime | None = None, title: str | None = None,
                project: str | None = None) -> None:
        """
        Record that `app` (with window `title`, running in saved `project`) is in the foreground now
        (None = idle). Closes the previous session on a change.
        """
        now = now or datetime.now()
        from services.mind import activity_awareness
        gap = self.last_observed_at and (now - self.last_observed_at).total_seconds() > activity_awareness.FRESH_SECONDS
        try:
            if gap:
                activity_awareness.end_current(now)
        except (OSError, sqlite3.Error):
            logger.debug("Optional activity label could not be closed after an observation gap")
        self.last_observed_at = now
        if app:
            self.last_foreground = {"app": app, "title": title, "at": now,
                                    "window": json.dumps(self.last_window)}
        try:
            # Check window identity even when the app and title haven't changed.
            seen = activity_awareness.snapshot(self, now)
            seen.update(app=app, title=clean_title(title)[:180])
            activity_awareness.changed(self, now, seen=seen)
        except (OSError, sqlite3.Error):
            logger.debug("Optional activity label unavailable")
        if (app, title, project) == (self.app, self.title, self.project):
            return
        self.flush(now)
        from services.learning import origin
        if app != self.app:
            self.origin = origin.observed_actor(now, app) or ("user" if self._observed_runtime else "unknown")
        if app is None and self.app is not None:
            with self._lock, closing(self._connect()) as conn, conn:
                conn.execute("INSERT INTO activity_boundaries(at,reason,runtime) VALUES (?,?,?)",
                             (now.isoformat(timespec="seconds"), "idle", self.runtime))
        if app:
            self._observed_runtime = True
        if app != self.app:
            self.app_since = now
        self.app, self.title, self.project = app, title, project
        if app:
            self.last_app = app

    def flush(self, now: datetime | None = None) -> None:
        """Save the current app session so far (on a switch, or on shutdown)."""
        now = now or datetime.now()
        if self.app and self.title_since and (now - self.title_since).total_seconds() >= POLL_SECONDS:
            self._insert(
                at=self.title_since.isoformat(timespec="seconds"), kind="app", app=self.app, title=self.title,
                duration_s=round((now - self.title_since).total_seconds(), 1), project=self.project,
                subject=study_subject(),
                origin=self.origin, runtime=self.runtime,
            )
        elif self.app and self.title_since and now > self.title_since:
            # Even an unsettled foreground observation breaks learning continuity.
            with self._lock, closing(self._connect()) as conn, conn:
                conn.execute("INSERT INTO activity_boundaries(at,reason,runtime) VALUES (?,?,?)",
                             (self.title_since.isoformat(timespec="microseconds"), "short_session", self.runtime))
        self.title_since = now

    def sample(self, tick: int = 0) -> None:
        """One tick of the tracker (blocking). Every SLOW_EVERY ticks it also collects launches, sites and files."""
        app, title = foreground_window()
        if idle_seconds() >= IDLE_SECONDS and not (app and media_playing_in(app)):  # a lecture video isn't "away"
            self.observe(None)
        else:
            project = None
            if app:
                self.last_window = foreground_ids()
                if app not in projects.BROWSERS | {"explorer"}:  # those are matched by their titles instead
                    project = projects.project_of_process(self.last_window[1])
            self.observe(app, title=title, project=project)
        if tick % SLOW_EVERY == 0:
            self.collect_slow()

    # ── Launches, websites, files ─────────────────────────────────────────────

    def collect_slow(self) -> None:
        for step in (self._launches, self._websites, self._files):
            try:
                step()
            except Exception as e:  # one source failing (locked history, no Recent folder) shouldn't stop the rest
                logger.warning(f"Activity {step.__name__.strip('_')} skipped: {e}")

    def _last_at(self, kind: str) -> datetime:
        """When the newest row of `kind` happened — where to resume reading from (today's start if none)."""
        with self._lock, closing(self._connect()) as conn:
            (at,) = conn.execute("SELECT MAX(at) FROM activity WHERE kind = ?", (kind,)).fetchone()
        return datetime.fromisoformat(at) if at else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    def _launches(self) -> None:
        # ponytail: checked once a minute, so an app opened and closed within a minute is missed; per-process watchers if that matters
        now, current = datetime.now(), running_apps()
        if self._running is not None:  # the first reading only seeds the set
            for app in sorted(current - self._running):
                self._insert(at=now.isoformat(timespec="seconds"), kind="launch", app=app)
        self._running = current

    def _websites(self) -> None:
        # ponytail: default profile of Chrome/Edge only; add profile folders if you use others
        since = self._last_at("web")
        cursor = int((since.astimezone() - _CHROME_EPOCH).total_seconds() * 1_000_000)
        servers = projects.local_servers()  # localhost port → the project whose folder serves it, right now
        for history in BROWSER_HISTORIES:
            if not history.exists():
                continue
            with tempfile.TemporaryDirectory() as tmp:  # the browser keeps the live file locked
                copy = Path(tmp) / "History"
                shutil.copy2(history, copy)
                with closing(sqlite3.connect(copy)) as conn:
                    visits = conn.execute(
                        "SELECT url, title, last_visit_time FROM urls WHERE last_visit_time > ? ORDER BY last_visit_time",
                        (cursor,),
                    ).fetchall()
            for url, title, visited in visits:
                domain = urlparse(url).netloc
                if not domain or PRIVATE_SITE.search(domain):
                    continue
                when = (_CHROME_EPOCH + timedelta(microseconds=visited)).astimezone().replace(tzinfo=None)
                self._insert(at=when.isoformat(timespec="seconds"), kind="web", target=domain, title=title or None,
                             project=servers.get(projects.port_of(domain)))

    def _files(self) -> None:
        since = self._last_at("file").timestamp()
        for shortcut in RECENT_DIR.glob("*.lnk"):
            opened = shortcut.stat().st_mtime
            if opened > since:  # the shortcut's name is the file's name; its folder and contents are never read
                self._insert(at=datetime.fromtimestamp(opened).isoformat(timespec="seconds"), kind="file", target=shortcut.stem)

    # ── Habits ────────────────────────────────────────────────────────────────

    def habit_rows(self, since: datetime) -> list[tuple]:
        """App, web and launch rows since then, oldest first — for services/activity/habits.py:
        (at, kind, app, target, duration_s, category, project)."""
        with self._lock, closing(self._connect()) as conn:
            return conn.execute("SELECT at, kind, app, target, duration_s, category, project FROM activity "
                                "WHERE kind IN ('app', 'web', 'launch') AND at >= ? ORDER BY at",
                                (since.isoformat(),)).fetchall()

    # ── Commands ──────────────────────────────────────────────────────────────

    def log_command(self, parsed: dict, success: bool) -> None:
        if (ran := commands_run.get()) is not None:  # what this request ran, for FRIDAY's quips (personality.py)
            ran.append((parsed, success))
        if not config.ACTIVITY_LOG_ENABLED:
            return
        try:
            target = next((str(parsed[k]) for k in TARGET_KEYS if parsed.get(k) not in (None, "")), None)
            if target and parsed.get("url"):
                target = urlparse(target if "//" in target else "//" + target).netloc or target  # site only, no paths/tokens
            self._insert(
                at=datetime.now().isoformat(timespec="seconds"), kind="command", app=self.last_app,
                action=parsed.get("action"), target=target, success=int(success),
                origin=parsed.get("origin", "requested"), runtime=self.runtime,
            )
        except Exception as e:  # the log must never break a command
            logger.warning(f"Could not log command: {e}")

    def log_feedback(self, app: str, answer: str) -> None:
        """A habit suggestion shown ("suggested") or answered ("open", "later", "never") — for learning habits."""
        try:
            self._insert(at=datetime.now().isoformat(timespec="seconds"), kind="feedback", app=app, action=answer)
        except Exception as e:  # never break a notification over this
            logger.warning(f"Could not log feedback: {e}")

    def search(self, where: str, params: list) -> list[sqlite3.Row]:
        """Rows matching an SQL condition, newest first (for services/activity/ask.py; params are bound, never pasted)."""
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(f"SELECT * FROM activity WHERE {where} ORDER BY at DESC LIMIT 500", params).fetchall()

    def app_rows(self, start: datetime, end: datetime) -> list[tuple[str, float, str, str | None]]:
        """Foreground time from start to end, oldest first, no limit: (at, seconds, category, project)."""
        with self._lock, closing(self._connect()) as conn:
            return conn.execute("SELECT at, duration_s, category, project FROM activity WHERE kind = 'app' "
                                "AND at >= ? AND at < ? ORDER BY at", (start.isoformat(), end.isoformat())).fetchall()

    def app_totals(self, start: datetime, end: datetime) -> dict[str, float]:
        """Foreground seconds per app between start and end, most first (no row limit)."""
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT app, SUM(duration_s) FROM activity WHERE kind = 'app' AND at >= ? AND at < ? "
                                "AND app IS NOT NULL GROUP BY app ORDER BY 2 DESC", (start.isoformat(), end.isoformat()))
            return {app: seconds or 0 for app, seconds in rows.fetchall()}

    def app_seconds(self, name: str, since: datetime, now: datetime | None = None) -> float:
        """Foreground seconds since `since` in apps whose name contains `name`, the stretch going on included."""
        with self._lock, closing(self._connect()) as conn:
            total = conn.execute("SELECT COALESCE(SUM(duration_s), 0) FROM activity WHERE kind = 'app' "
                                 "AND app LIKE ? AND at >= ?", (f"%{name}%", since.isoformat())).fetchone()[0]
        if self.app and name in self.app and self.title_since and self.title_since >= since:
            total += ((now or datetime.now()) - self.title_since).total_seconds()
        return total

    def study_rows(self, start: datetime, end: datetime) -> list[tuple[str, float, str | None, str | None, str | None]]:
        """Foreground time from start to end for study hours (study.py): (at, seconds, title, category, subject),
        plus the stretch still going on."""
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT at, duration_s, title, category, subject FROM activity WHERE kind = 'app' "
                                "AND at >= ? AND at < ? ORDER BY at", (start.isoformat(), end.isoformat())).fetchall()
        if self.app and self.title_since and start <= self.title_since < end:
            rows.append((self.title_since.isoformat(timespec="seconds"), (datetime.now() - self.title_since).total_seconds(),
                         self.title, categorize("app", self.app, None, self.title, None), study_subject()))
        return rows

    def command_rows(self) -> list[sqlite3.Row]:
        """Every command FRIDAY ran, oldest first (at, app, action, target, success) — insights.py's dataset."""
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT at, app, action, target, success FROM activity WHERE kind = 'command' "
                                "ORDER BY at").fetchall()

    def moves(self, start: datetime, end: datetime) -> list[tuple]:
        """Every foreground stretch from start to end, oldest first, titles included — for FRIDAY's brain
        (services/mind/brain.py, local only): (at, app, title, seconds, category, project)."""
        with self._lock, closing(self._connect()) as conn:
            return conn.execute("SELECT at, app, title, duration_s, category, project FROM activity WHERE kind = 'app' "
                                "AND app IS NOT NULL AND at >= ? AND at < ? ORDER BY at",
                                (start.isoformat(), end.isoformat())).fetchall()

    def app_sequence(self) -> list[tuple[str, str]]:
        """Every foreground app session, oldest first: (at, app) — for services/activity/predict.py.
        System windows (shellhost, Task Manager, "Open with"…) are left out: they aren't choices."""
        with self._lock, closing(self._connect()) as conn:
            return conn.execute("SELECT at, app FROM activity WHERE kind = 'app' AND app IS NOT NULL "
                                "AND (category IS NULL OR category != 'system') ORDER BY at").fetchall()

    # ── Projects ──────────────────────────────────────────────────────────────

    def last_project(self) -> str | None:
        """The saved project worked on most recently ("pick up where I left off")."""
        saved = projects.load()
        with self._lock, closing(self._connect()) as conn:
            for (name,) in conn.execute(
                "SELECT project FROM activity WHERE project IS NOT NULL ORDER BY at DESC LIMIT 200"
            ):
                if name in saved:
                    return name
        return None

    def project_domains(self, name: str, since: datetime) -> list[str]:
        """Websites (domains) used with the project since then, most-used first."""
        with self._lock, closing(self._connect()) as conn:
            return [domain for (domain,) in conn.execute(
                "SELECT target FROM activity WHERE kind='web' AND project = ? AND at >= ? "
                "GROUP BY target ORDER BY COUNT(*) DESC", (name, since.isoformat()),
            )]

    def project_time(self, name: str, when: str = "today") -> str:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = {
            "today": (today, today + timedelta(days=1)),
            "yesterday": (today - timedelta(days=1), today),
            "this week": (today - timedelta(days=today.weekday()), today + timedelta(days=1)),
        }[when]
        with self._lock, closing(self._connect()) as conn:
            (seconds,) = conn.execute(
                "SELECT COALESCE(SUM(duration_s), 0) FROM activity WHERE kind='app' AND project = ? AND at >= ? AND at < ?",
                (name, start.isoformat(), end.isoformat()),
            ).fetchone()
        if self.project == name and self.title_since and start <= self.title_since < end:  # the session still going
            seconds += (datetime.now() - self.title_since).total_seconds()
        if seconds < 60:
            return f"You haven't worked on {name} {when}."
        return f"You've spent {_duration(seconds)} on {name} {when}."

    # ── Reading ───────────────────────────────────────────────────────────────

    def day_summary(self, day: datetime | None = None) -> str:
        day = (day or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = day.isoformat(), (day + timedelta(days=1)).isoformat()
        with self._lock, closing(self._connect()) as conn:
            apps = conn.execute(
                "SELECT app, SUM(duration_s) FROM activity WHERE kind='app' AND at >= ? AND at < ? GROUP BY app",
                (start, end),
            ).fetchall()
            categories = conn.execute(
                "SELECT category, SUM(duration_s) FROM activity WHERE kind='app' AND at >= ? AND at < ? "
                "AND category NOT IN ('other', 'system') GROUP BY category HAVING SUM(duration_s) >= 60 "
                "ORDER BY SUM(duration_s) DESC LIMIT 4", (start, end),
            ).fetchall()
            by_project = conn.execute(
                "SELECT project, SUM(duration_s) FROM activity WHERE kind='app' AND project IS NOT NULL "
                "AND at >= ? AND at < ? GROUP BY project HAVING SUM(duration_s) >= 60 ORDER BY SUM(duration_s) DESC",
                (start, end),
            ).fetchall()
            commands = conn.execute(
                "SELECT action, COUNT(*) FROM activity WHERE kind='command' AND at >= ? AND at < ? "
                "GROUP BY action ORDER BY COUNT(*) DESC", (start, end),
            ).fetchall()
        totals = dict(apps)
        if self.app and self.title_since and start <= self.title_since.isoformat() < end:  # the session still going on
            totals[self.app] = totals.get(self.app, 0) + (datetime.now() - self.title_since).total_seconds()
        totals = {app: secs for app, secs in totals.items() if secs >= 60}
        if not totals and not commands:
            return NO_ACTIVITY

        parts = []
        if totals:
            ranked = sorted(totals.items(), key=lambda item: -item[1])
            top = ", ".join(f"{app} {_duration(secs)}" for app, secs in ranked[:6])
            when = "Today you've been" if day.date() == datetime.now().date() else "Yesterday you were"
            parts.append(f"{when} active for {_duration(sum(totals.values()))}: {top}.")
        if categories:
            parts.append("By kind: " + ", ".join(f"{category} {_duration(secs)}" for category, secs in categories) + ".")
        if by_project:
            parts.append("Projects: " + ", ".join(f"{name} {_duration(secs)}" for name, secs in by_project) + ".")
        if commands:
            count = sum(n for _, n in commands)
            usual = ", ".join(f"{action.replace('_', ' ')} ({n})" for action, n in commands[:3])
            parts.append(f"You gave me {count} command{'s' if count != 1 else ''}, mostly {usual}.")
        return " ".join(parts)

    def clear(self) -> str:
        with self._lock, closing(self._connect()) as conn, conn:
            count = conn.execute("DELETE FROM activity").rowcount
        self.app_since = self.title_since = datetime.now()
        from services.mind.activity_awareness import forget
        forget(activities_only=True)
        from services.screen_watch.store import ScreenStore
        ScreenStore().forget()
        return f"Cleared your activity log ({count} entries)." if count else "Your activity log is already empty."


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


async def watch_activity(log: "ActivityLog") -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan."""
    if not config.ACTIVITY_LOG_ENABLED:
        return
    from services.mind import brain  # she watches every move (imported late: it builds on this module)

    logger.info("Activity tracker started")
    try:
        for tick in itertools.count():
            try:
                await asyncio.to_thread(log.sample, tick)
                await asyncio.to_thread(brain.sense, log)
            except Exception as e:
                logger.error(f"Activity tracker error: {e}", exc_info=True)
            await asyncio.sleep(POLL_SECONDS)
    finally:
        log.flush()  # keep the last session when FRIDAY shuts down


activity_log = ActivityLog()
