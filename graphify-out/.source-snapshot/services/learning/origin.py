"""Mark known Friday opens so observations do not reinforce autonomous choices."""

import contextvars
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta

from core.config import config

_actor = contextvars.ContextVar("learning_actor", default="requested")
_lock = threading.Lock()
_opens: deque[tuple[datetime, str, str | None]] = deque(maxlen=100)


@contextmanager
def action_scope(actor: str):
    token = _actor.set(actor)
    try:
        yield
    finally:
        _actor.reset(token)


def current_actor() -> str:
    return _actor.get()


def note_open(now: datetime | None = None, app: str | None = None) -> None:
    with _lock:
        _opens.append((now or datetime.now(), current_actor(), app.lower() if app else None))


def observed_actor(now: datetime, app: str | None = None) -> str | None:
    with _lock:
        marked = list(_opens)
    for at, actor, target in reversed(marked):
        if timedelta(0) <= now - at <= timedelta(seconds=config.LEARNING_AUTOMATION_WINDOW_SECONDS):
            if target is None or app and (app.lower() == target or app.lower().startswith(target + ".")):
                return actor
    return None


def reset() -> None:
    with _lock:
        _opens.clear()
