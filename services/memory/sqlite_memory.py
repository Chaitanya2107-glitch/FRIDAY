"""
services/memory/sqlite_memory.py

Phase 1 memory service — stores conversation history and user facts in SQLite.
SQLite = a single local file. No database server needed. No setup required.

WHAT IT STORES:
  - conversations: full message history (role + content + timestamp)
  - user_facts:    long-term key/value facts about the user

PHASE 1 SCOPE:
  - save messages
  - retrieve recent history
  - save/retrieve user facts
  - clear history

FUTURE (Phase 4):
  - semantic search over memory (vector embeddings)
  - memory summarisation (compress old history)
  - memory categories (work / personal / code)
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from core.config import config
from core.logger import logger
from core.errors import MemoryError


class MemoryService:
    """Handles all memory operations for F.R.I.D.A.Y."""

    def __init__(self, db_path: str = None):
        # Allow overriding the db path (useful for tests)
        self.db_path = db_path or config.MEMORY_DB_PATH
        self._ensure_db()

    @contextmanager
    def _connect(self):
        """
        Context manager that opens a SQLite connection, yields it, then CLOSES it.

        Why this matters: sqlite3's built-in context manager handles commit/rollback
        but does NOT close the connection. Over time, unclosed connections pile up
        and cause resource leaks. This wrapper ensures connections are always closed.

        Usage:
            with self._connect() as conn:
                conn.execute(...)
            # connection is closed here — guaranteed
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # lets us access columns by name
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()  # always closes, even if an exception occurred

    def _now(self) -> str:
        """
        Return the current UTC time as an ISO string.
        Uses timezone-aware datetime (Python 3.12+ compatible).
        datetime.utcnow() is deprecated — this is the correct replacement.
        """
        return datetime.now(timezone.utc).isoformat()

    def _ensure_db(self):
        """Create the database file and tables if they don't exist yet."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            with self._connect() as conn:
                conn.executescript("""
                    -- One row per message in the conversation
                    CREATE TABLE IF NOT EXISTS conversations (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        role      TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
                        content   TEXT    NOT NULL,
                        timestamp TEXT    NOT NULL
                    );

                    -- Long-term facts about the user, stored as key/value pairs
                    -- e.g. key="name" value="Alex", key="preferred_language" value="Python"
                    CREATE TABLE IF NOT EXISTS user_facts (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        key        TEXT    UNIQUE NOT NULL,
                        value      TEXT    NOT NULL,
                        updated_at TEXT    NOT NULL
                    );
                """)
            logger.debug(f"Memory DB ready at: {self.db_path}")
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to initialise memory database: {str(e)}")

    # ── Conversation history ──────────────────────────────────────────────────

    def save_message(self, role: str, content: str):
        """
        Save a single message to history.
        Call this after every user message and every assistant response.
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO conversations (role, content, timestamp) VALUES (?, ?, ?)",
                    (role, content, self._now())
                )
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to save message to memory: {str(e)}")

    def get_recent_history(self, limit: int = None) -> list[dict]:
        """
        Get the most recent N messages.
        Returns them in chronological order (oldest first) so they
        can be passed directly to the AI as conversation context.
        """
        limit = limit or config.MAX_HISTORY_MESSAGES

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to retrieve conversation history: {str(e)}")

        # Reverse because we fetched DESC (newest first) but need oldest first
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def get_last_assistant_message(self) -> str | None:
        """Read the latest saved reply verbatim, independent of the history window."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT content FROM conversations WHERE role = 'assistant' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return row["content"] if row else None
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to retrieve the last reply: {str(e)}")

    def get_history_count(self) -> int:
        """Return total number of messages stored."""
        try:
            with self._connect() as conn:
                result = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
                return result[0] if result else 0
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to count conversation history: {str(e)}")

    def clear_history(self):
        """
        Delete all conversation history.
        User facts are preserved — only the chat log is wiped.
        """
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM conversations")
            logger.info("Conversation history cleared")
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to clear conversation history: {str(e)}")

    # ── User facts ────────────────────────────────────────────────────────────

    def save_fact(self, key: str, value: str):
        """
        Store a long-term fact about the user.
        If the key already exists, its value is updated (upsert).
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO user_facts (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE
                    SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, value, self._now())
                )
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to save fact '{key}': {str(e)}")

    def get_fact(self, key: str) -> str | None:
        """Retrieve a stored fact by key. Returns None if not found."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM user_facts WHERE key = ?", (key,)
                ).fetchone()
            return row["value"] if row else None
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to retrieve fact '{key}': {str(e)}")

    def get_all_facts(self) -> dict:
        """Return all stored user facts as a dictionary."""
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT key, value FROM user_facts").fetchall()
            return {row["key"]: row["value"] for row in rows}
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to retrieve all facts: {str(e)}")

    def delete_fact(self, key: str):
        """Remove a specific fact."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM user_facts WHERE key = ?", (key,))
        except sqlite3.Error as e:
            raise MemoryError(f"Failed to delete fact '{key}': {str(e)}")
