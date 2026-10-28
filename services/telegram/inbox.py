"""Durable inbound queue; Telegram's unseen backlog lasts at most 24 hours.

Persist before acknowledging updates. Claim before execution so an interrupted
side effect is reported as uncertain instead of being executed twice.
"""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager

from core.config import config

CURSOR_SECONDS = 24 * 60 * 60  # Telegram expires unseen updates after 24 hours.


def _owner() -> str:
    # Separate recipients and bots without persisting their credentials.
    return hashlib.sha256(f"{config.TELEGRAM_USER_ID}:{config.TELEGRAM_BOT_TOKEN}".encode()).hexdigest()


@contextmanager
def _db():
    path = config.MEMORY_DIR / "telegram_inbox.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS cursors (owner TEXT PRIMARY KEY, next_id INTEGER NOT NULL, "
                         "received_at REAL NOT NULL DEFAULT 0)")
            if "received_at" not in {row[1] for row in conn.execute("PRAGMA table_info(cursors)")}:
                conn.execute("ALTER TABLE cursors ADD COLUMN received_at REAL NOT NULL DEFAULT 0")
            conn.execute("CREATE TABLE IF NOT EXISTS inbox (owner TEXT, id INTEGER, payload TEXT NOT NULL, "
                         "running INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner, id))")
            yield conn
    finally:
        conn.close()


def offset() -> int:
    with _db() as conn:
        row = conn.execute("SELECT next_id, received_at FROM cursors WHERE owner=?", (_owner(),)).fetchone()
        # After a week without updates Telegram may pick a smaller random ID.
        # Once its entire retention window has expired, request a fresh cursor.
        return row[0] if row and time.time() - row[1] < CURSOR_SECONDS else 0


def enqueue(updates: list[dict]) -> None:
    if not updates:
        return  # Empty polls must not extend an old cursor's lifetime.
    with _db() as conn:
        owner = _owner()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT next_id, received_at FROM cursors WHERE owner=?", (owner,)).fetchone()
        previous = row[0] if row and time.time() - row[1] < CURSOR_SECONDS else 0
        next_id = previous
        for update in updates:
            ident = update["update_id"]
            next_id = max(next_id, ident + 1)
            source = update.get("message") or update.get("callback_query") or {}
            if config.TELEGRAM_USER_ID and source.get("from", {}).get("id") != config.TELEGRAM_USER_ID:
                continue
            if ident >= previous:
                conn.execute("INSERT OR IGNORE INTO inbox (owner, id, payload) VALUES (?, ?, ?)",
                             (owner, ident, json.dumps({**update, "_friday_received_at": time.time()})))
        conn.execute("INSERT INTO cursors VALUES (?, ?, ?) ON CONFLICT(owner) DO UPDATE SET "
                     "next_id=excluded.next_id, received_at=excluded.received_at", (owner, next_id, time.time()))


def pending() -> list[tuple[dict, bool]]:
    with _db() as conn:
        rows = conn.execute("SELECT payload, running FROM inbox WHERE owner=? ORDER BY id", (_owner(),)).fetchall()
        return [(json.loads(payload), bool(running)) for payload, running in rows]


def start(ident: int) -> None:
    with _db() as conn:
        conn.execute("UPDATE inbox SET running=1 WHERE owner=? AND id=?", (_owner(), ident))


def finish(ident: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM inbox WHERE owner=? AND id=?", (_owner(), ident))
