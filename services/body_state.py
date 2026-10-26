"""
services/body_state.py

What FRIDAY's body (interfaces/body/, the desktop robot) shows about her mind, read by GET /api/v1/body:
  - speaking / listening / thinking right now (TTS, the microphone, AI calls in flight or Claude Code working)
  - events since the body last asked: "say" (a speech bubble: her own questions, reminders), "done"
    (Claude Code finished — a happy jump), "permission" (Claude Code is waiting on you), "laugh" (you
    laughed at her joke — hearts), "roast" (a game during study mode — side-eye)
  - "study_gaming": a game in the foreground while study mode is on
Events are a small ring buffer with increasing ids; the body passes the last id it saw.
"""

import threading
import time
from collections import deque

MAX_EVENTS = 50
CLAUDE_STALE_SECONDS = 30 * 60  # a Claude reply "working" longer than this is assumed abandoned

_lock = threading.Lock()
_events: deque = deque(maxlen=MAX_EVENTS)
_next_id = 1
_ai_calls = 0
_claude_working: dict[str, float] = {}  # session → when the prompt was sent


def push(kind: str, text: str = "") -> None:
    global _next_id
    with _lock:
        _events.append({"id": _next_id, "kind": kind, "text": text, "at": time.time()})
        _next_id += 1


def last_id() -> int:
    with _lock:
        return _next_id - 1


def events_since(last_id: int) -> list[dict]:
    with _lock:
        return [e for e in _events if e["id"] > last_id]


class thinking:
    """`with body_state.thinking():` around an AI call — the body shows thinking dots meanwhile."""

    def __enter__(self):
        global _ai_calls
        with _lock:
            _ai_calls += 1

    def __exit__(self, *exc):
        global _ai_calls
        with _lock:
            _ai_calls = max(0, _ai_calls - 1)


def claude(payload: dict, now: float | None = None) -> None:
    """A Claude Code hook call: working between a prompt and Stop; a jump when it's done."""
    now = time.time() if now is None else now
    event, session = payload.get("hook_event_name"), str(payload.get("session_id", ""))
    with _lock:
        if event == "UserPromptSubmit":
            _claude_working[session] = now
        elif event in ("Stop", "StopFailure", "SessionEnd"):
            was_working = _claude_working.pop(session, None) is not None
        else:
            was_working = False
    if event == "Stop" and was_working:
        push("done")
    elif event == "PermissionRequest":
        push("permission")


def snapshot(now: float | None = None) -> dict:
    """speaking / listening / thinking right now (the heavy imports are late: the body only asks a few times a second)."""
    from services.voice.recorder import recorder
    from services.voice.tts import tts

    now = time.time() if now is None else now
    with _lock:
        for session, since in list(_claude_working.items()):
            if now - since > CLAUDE_STALE_SECONDS:
                del _claude_working[session]
        thinking_now = _ai_calls > 0 or bool(_claude_working)
    return {"speaking": tts.is_speaking, "listening": recorder.is_recording, "thinking": thinking_now,
            "study_gaming": _study_gaming()}


def _study_gaming() -> bool:
    try:
        from services.activity.categories import categorize
        from services.activity.log import activity_log
        from services.automation import modes

        state = modes.active()
        return bool(state and state.get("name") == "study" and activity_log.app
                    and categorize("app", activity_log.app) == "gaming")
    except Exception:
        return False
