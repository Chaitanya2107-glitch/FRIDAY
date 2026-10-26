"""One factual event record shared by the API, background services and tray.

This is working memory, not hidden model reasoning or a claim of consciousness.
Only explicitly public events enter AI context. Delivery states describe what
the transport confirmed, never whether the Boss read/heard a message.
"""

import asyncio
import contextvars
import functools
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.config import config
from core.logger import logger

_turn = contextvars.ContextVar("cognition_turn", default="")
_channel = contextvars.ContextVar("cognition_channel", default="system")
_replied = contextvars.ContextVar("cognition_replied", default=False)
_introspection = contextvars.ContextVar("cognition_introspection", default=False)


def redact(text: str) -> str:
    # Known credentials must not be duplicated into event storage or prompts.
    for name in set(vars(type(config))) | set(vars(config)):
        if name.endswith(("_KEY", "_TOKEN", "_PASSWORD", "_SECRET")):
            value = getattr(config, name)
            if isinstance(value, str) and value.strip():
                text = text.replace(value, "[credential removed]")
    return re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._-]+", "Bearer [removed]", text)


class Cognition:
    def __init__(self, path: Path):
        self.path = path
        self.runtime = f"{os.getpid()}:{uuid.uuid4().hex}"
        self._lock = threading.RLock()

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=1)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                kind TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL,
                text TEXT NOT NULL, public INTEGER NOT NULL, turn_id TEXT NOT NULL,
                runtime TEXT NOT NULL, shortened INTEGER NOT NULL DEFAULT 0)""")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(self, kind: str, channel: str, text: str = "", *, status: str = "completed",
               public: bool = False) -> int | None:
        if not config.COGNITION_ENABLED:
            return None
        try:
            if config.COGNITION_MAX_EVENTS < 1 or config.COGNITION_EVENT_CHARS < 1:
                raise ValueError("Cognition limits must be positive")
            text = redact(text)
            with self._lock, self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO events (at, kind, channel, status, text, public, turn_id, runtime, shortened) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (time.time(), kind, channel, status, text[:config.COGNITION_EVENT_CHARS], int(public),
                     _turn.get(), self.runtime, int(len(text) > config.COGNITION_EVENT_CHARS)))
                conn.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id DESC LIMIT -1 OFFSET ?)",
                             (config.COGNITION_MAX_EVENTS,))
                logger.debug("Cognition recorded %s/%s: %s", channel, kind, status)
                from services.mind.cognitive_runtime import signal
                signal(kind, status)
                return cursor.lastrowid
        except (OSError, sqlite3.Error, ValueError) as error:
            logger.warning("Cognition event unavailable: %s", type(error).__name__)
            return None

    def finish(self, event_id: int | None, status: str) -> None:
        if event_id is None:
            return
        try:
            with self._lock, self._connect() as conn:
                conn.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
                row = conn.execute('SELECT kind FROM events WHERE id=?', (event_id,)).fetchone()
                if row:
                    from services.mind.cognitive_runtime import signal
                    signal(row['kind'], status)
                logger.debug("Cognition operation %s: %s", event_id, status)
        except (OSError, sqlite3.Error) as error:
            logger.warning("Cognition event status unavailable: %s", type(error).__name__)

    def recent(self, limit: int = 20) -> list[dict]:
        if not config.COGNITION_ENABLED:
            return []
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?",
                                    (max(1, min(limit, config.COGNITION_MAX_EVENTS)),)).fetchall()
            return [dict(row) for row in reversed(rows)]
        except (OSError, sqlite3.Error) as error:
            logger.warning("Cognition history unavailable: %s", type(error).__name__)
            return []

    def latest(self, kind: str) -> dict | None:
        return next((e for e in reversed(self.recent(config.COGNITION_MAX_EVENTS)) if e["kind"] == kind), None)

    def active(self) -> list[dict]:
        # Prior-process 'started' rows are interrupted history, not live tasks.
        return [e for e in self.recent(config.COGNITION_MAX_EVENTS)
                if e["runtime"] == self.runtime and e["status"] == "started"]

    def clear(self) -> None:
        # Failure should propagate to the explicit clear-history operation.
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM events")
            from services.mind.executive import clear_derived
            clear_derived(conn)

    @contextmanager
    def operation(self, kind: str, channel: str, text: str = "", *, public: bool = False):
        event_id = self.record(kind, channel, text, status="started", public=public)
        operation = SimpleOperation(self, event_id)
        try:
            yield operation
        except BaseException as error:
            operation.finish("cancelled" if isinstance(error, asyncio.CancelledError) else "failed")
            raise
        else:
            if not operation.finished:
                operation.finish("completed")


class SimpleOperation:
    def __init__(self, store: Cognition, event_id: int | None):
        self.store, self.event_id, self.finished = store, event_id, False

    def finish(self, status: str) -> None:
        self.store.finish(self.event_id, status)
        self.finished = True


cognition = Cognition(config.MEMORY_DIR / "mind" / "cognition.db")


def reply(text: str, *, public: bool = False, safe_text: str | None = None) -> None:
    _replied.set(True)
    if _introspection.get():
        return  # recalling an event must not replace the event being recalled
    cognition.record("reply", _channel.get(), safe_text if safe_text is not None else text, public=public)


def mark_introspection() -> None:
    _introspection.set(True)


def turn(channel: str):
    """Track a request across thread offloads without storing raw user input."""
    def decorate(function):
        @functools.wraps(function)
        async def wrapped(*args, **kwargs):
            from services.automation.intent import remote_request

            tokens = [(_turn, _turn.set(uuid.uuid4().hex)),
                      (_channel, _channel.set("telegram" if remote_request.get() else channel)),
                      (_replied, _replied.set(False)), (_introspection, _introspection.set(False))]
            event_id = cognition.record("request", _channel.get(), "User request", status="started")
            try:
                result = await function(*args, **kwargs)
                if not _replied.get() and not _introspection.get():
                    # Computer tasks deliberately keep proposed text/screens ephemeral.
                    text = "Computer task response" if getattr(result, "model", "") in {"computer_agent", "automation_task"} else result.response
                    reply(text)
                if not _introspection.get() and getattr(result, 'model', '') not in {'system_control', 'computer_agent', 'automation_task'}:
                    from services.mind.brain_memory import brain_memory
                    incoming = args[0] if args else kwargs.get('transcription', kwargs.get('request'))
                    message = incoming if isinstance(incoming, str) else getattr(incoming, 'message', '')
                    from services.computer.agent import is_computer_command
                    if message and not is_computer_command(message):
                        try:
                            await asyncio.to_thread(brain_memory.remember, message, source=_turn.get(), channel=_channel.get())
                        except (OSError, sqlite3.Error, ValueError) as error:
                            logger.debug('Owner dialogue memory unavailable (%s)', type(error).__name__)
                cognition.finish(event_id, "failed" if getattr(result, "action_success", None) is False else "completed")
                return result
            except BaseException as error:
                cognition.finish(event_id, "cancelled" if isinstance(error, asyncio.CancelledError) else "failed")
                raise
            finally:
                for variable, token in reversed(tokens):
                    variable.reset(token)
        return wrapped
    return decorate
