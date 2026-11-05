"""Bounded live display events; reminder delivery receipts remain authoritative."""
from collections import deque
import threading
import time

_lock = threading.Lock()
_events = deque(maxlen=80)
_sequence = 0
_listeners = set()


def listen(owner, enabled):
    with _lock:
        if enabled:
            _listeners.add(owner)
        else:
            _listeners.discard(owner)


def connected():
    with _lock:
        return bool(_listeners)


def publish(kind, text, *, title='FRIDAY', buttons=None, private=False, **metadata):
    global _sequence
    if private:
        return  # Private replies travel only to their requesting surface.
    with _lock:
        _sequence += 1
        _events.append({'id': _sequence, 'kind': kind, 'text': str(text)[:4000],
                        'title': str(title)[:120], 'at': time.time(),
                        'buttons': list(buttons or [])[:6], **metadata})


def snapshot(since=None):
    with _lock:
        rows = [] if since is None else [dict(row) for row in _events if row['id'] > since and time.time() - row['at'] < 300][:6]
        return {'last': rows[-1]['id'] if rows else _sequence, 'events': rows}
