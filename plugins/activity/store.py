"""A fixed five-column schema: no titles, URLs, payloads or arbitrary metadata."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import threading

from services import settings_store

from .policy import CATEGORIES


def bounds(period: str, now: datetime) -> tuple[float, float]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'today':
        start, end = today, now
    elif period == 'yesterday':
        start, end = today - timedelta(days=1), today
    elif period == 'this week':
        start, end = today - timedelta(days=today.weekday()), now
    elif period == 'last 7 days':
        start, end = now - timedelta(days=7), now
    else:
        raise ValueError('Use today, yesterday, this week or last 7 days.')
    return start.timestamp(), end.timestamp()


class Store:
    def __init__(self, path: Path):
        if path.resolve().is_relative_to(Path(settings_store.__file__).resolve().parents[1]):
            raise ValueError('Activity data must be stored outside the repository.')
        self.path, self.lock = path, threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions (start REAL NOT NULL, end REAL NOT NULL, '
                        'process TEXT, app_name TEXT, category TEXT NOT NULL, '
                        'CHECK(end >= start), CHECK(category != \'private\' OR (process IS NULL AND app_name IS NULL)))')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(sessions)')}
        if columns != {'start', 'end', 'process', 'app_name', 'category'}:
            self.db.close()
            raise ValueError('Unexpected activity database schema; original data was preserved.')
        self.db.execute('CREATE INDEX IF NOT EXISTS sessions_end ON sessions(end)')
        self.db.commit()

    def save(self, session: dict, rowid: int | None = None) -> int | None:
        if session['end'] - session['start'] < 3:
            return rowid
        if session['category'] not in CATEGORIES | {'private'}:
            raise ValueError('Unknown activity category')
        fields = ('start', 'end', 'process', 'app_name', 'category')
        values = tuple(session[name] for name in fields)
        with self.lock, self.db:
            if rowid is None:
                return self.db.execute('INSERT INTO sessions(start,end,process,app_name,category) VALUES (?,?,?,?,?)', values).lastrowid
            self.db.execute('UPDATE sessions SET start=?,end=?,process=?,app_name=?,category=? WHERE rowid=?', (*values, rowid))
            return rowid

    def trim_since(self, cutoff: float):
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions WHERE start >= ?', (cutoff,))
            self.db.execute('UPDATE sessions SET end=? WHERE end > ?', (cutoff, cutoff))
            self.db.execute('DELETE FROM sessions WHERE end-start < 3')

    def purge(self, cutoff: float):
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions WHERE end <= ?', (cutoff,))
            self.db.execute('UPDATE sessions SET start=? WHERE start < ?', (cutoff, cutoff))
            self.db.execute('DELETE FROM sessions WHERE end-start < 3')

    def rows(self, start: float, end: float) -> list[dict]:
        with self.lock:
            return [dict(row, start=max(row['start'], start), end=min(row['end'], end))
                    for row in self.db.execute('SELECT start,end,process,app_name,category FROM sessions '
                                              'WHERE end > ? AND start < ? ORDER BY start', (start, end))]

    def delete_all(self):
        with self.lock:
            self.db.execute('DELETE FROM sessions')
            self.db.commit()
            self.db.execute('VACUUM')

    def close(self):
        with self.lock:
            self.db.close()
