"""Bounded model interpretations, kept separate from owner facts and dialogue."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json

from services.mind.cognition import cognition


class ScreenStore:
    def __init__(self, store=cognition):
        self.store = store

    @contextmanager
    def db(self):
        with self.store._lock, self.store._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS screen_settings (
                    id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, paused INTEGER NOT NULL,
                    epoch INTEGER NOT NULL);
                INSERT OR IGNORE INTO screen_settings VALUES(1,0,0,0);
                CREATE TABLE IF NOT EXISTS screen_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, epoch INTEGER NOT NULL,
                    session TEXT NOT NULL, scope TEXT NOT NULL, app TEXT NOT NULL,
                    summary TEXT NOT NULL, activity TEXT NOT NULL, source TEXT NOT NULL);
            """)
            yield conn

    def settings(self):
        with self.db() as conn:
            return dict(conn.execute("SELECT * FROM screen_settings WHERE id=1").fetchone())

    def control(self, action):
        if action not in {"start", "resume", "pause", "stop"}:
            raise ValueError("Unknown screen control")
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if action in {"start", "resume"}:
                conn.execute("UPDATE screen_settings SET enabled=1,paused=0,epoch=epoch+1 WHERE id=1")
            elif action == "pause":
                conn.execute("UPDATE screen_settings SET paused=1,epoch=epoch+1 WHERE id=1")
            else:
                conn.execute("UPDATE screen_settings SET enabled=0,paused=0,epoch=epoch+1 WHERE id=1")

    def save(self, *, epoch, session, scope, app, summary, activity, source, at):
        if source not in {"accessible_text", "vision"} or not (0 < len(summary) <= 300 and len(activity) <= 200):
            raise ValueError("Invalid screen interpretation")
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute("SELECT * FROM screen_settings WHERE id=1").fetchone()
            if state["epoch"] != epoch or not state["enabled"] or state["paused"]:
                return False
            conn.execute("INSERT INTO screen_observations(at,epoch,session,scope,app,summary,activity,source) "
                         "VALUES(?,?,?,?,?,?,?,?)", (at.isoformat(timespec="seconds"), epoch, session,
                                                   json.dumps(scope, sort_keys=True), app, summary, activity, source))
            conn.execute("DELETE FROM screen_observations WHERE at<? OR id NOT IN "
                         "(SELECT id FROM screen_observations ORDER BY id DESC LIMIT 200)",
                         ((at - timedelta(days=7)).isoformat(timespec="seconds"),))
            return True

    def latest(self, scope, session, epoch, now=None):
        now = now or datetime.now()
        with self.db() as conn:
            row = conn.execute("SELECT * FROM screen_observations WHERE scope=? AND session=? AND epoch=? "
                               "ORDER BY id DESC LIMIT 1",
                               (json.dumps(scope, sort_keys=True), session, epoch)).fetchone()
        if row and 0 <= (now - datetime.fromisoformat(row["at"])).total_seconds() <= 75:
            return dict(row)
        return None

    def history(self, limit=8, now=None):
        cutoff = ((now or datetime.now()) - timedelta(days=7)).isoformat(timespec="seconds")
        with self.db() as conn:
            conn.execute("DELETE FROM screen_observations WHERE at<?", (cutoff,))
            return [dict(row) for row in conn.execute(
                "SELECT at,app,summary,activity,source FROM screen_observations ORDER BY id DESC LIMIT ?",
                (min(max(limit, 1), 20),))]

    def prune(self, now=None):
        cutoff = ((now or datetime.now()) - timedelta(days=7)).isoformat(timespec="seconds")
        with self.db() as conn:
            conn.execute("DELETE FROM screen_observations WHERE at<?", (cutoff,))

    def forget(self, description=None):
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE screen_settings SET paused=1,epoch=epoch+1 WHERE id=1")
            where, args = ("", ()) if not description else (
                " WHERE instr(lower(summary),?) OR instr(lower(activity),?) OR instr(lower(app),?)",
                (description.lower(),) * 3)
            return conn.execute("DELETE FROM screen_observations" + where, args).rowcount
