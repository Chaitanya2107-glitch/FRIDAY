"""
interfaces/tray/backend.py

Small HTTP client the tray and the Ctrl+Shift+F command bar use to talk to the
FRIDAY backend (main.py), plus the session settings they share.
"""

from dataclasses import dataclass
from typing import NamedTuple

import httpx

from core.config import config
from services.voice.recorder import MAX_SECONDS as MAX_LISTEN_SECONDS

BASE_URL = f"http://{config.API_HOST}:{config.API_PORT}"
VOICE_EXTRA_SECONDS = 120  # transcription + AI reply after listening ends


class BackendError(Exception):
    """The backend is unreachable or rejected the request. The message is user-facing."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # the HTTP status, when the backend answered


def screen_indicator(hwnd):
    return _request("POST", "/api/v1/screen-watch/indicator", timeout=2, json={"hwnd": hwnd})


class ChatReply(NamedTuple):
    text: str
    awaiting_reply: bool  # FRIDAY asked a yes/no question and is waiting for the answer
    keyboard: tuple = ()  # text/keys to type into the app the user was using
    command: bool = False  # a command ran (not an AI answer)
    automation_job: str | None = None
    private: bool = False


@dataclass
class Settings:
    provider: str | None = None  # None = the backend's ACTIVE_PROVIDER
    speak_replies: bool = True   # voice requests
    speak_typed: bool = False    # typed messages (command bar) are answered out loud too
    conversation: bool = False   # conversation mode is on: typed messages are answered out loud too


settings = Settings()


def _request(method: str, path: str, timeout: float, **kwargs) -> dict:
    try:
        response = httpx.request(method, BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.TimeoutException:
        raise BackendError("FRIDAY took too long to respond.")
    except httpx.HTTPError:
        raise BackendError("FRIDAY isn't running. Start it from the FRIDAY taskbar icon.")

    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.is_error:
        raise BackendError(
            data.get("message") or (data.get('detail') if isinstance(data.get('detail'), str) else None)
            or f"FRIDAY returned an error (HTTP {response.status_code}).", response.status_code,
        )
    return data


def is_online() -> bool:
    try:
        response = httpx.get(BASE_URL + "/health", timeout=2, trust_env=False)
        data = response.json() if response.status_code == 200 else None
        return isinstance(data, dict) and data.get("service") == "F.R.I.D.A.Y"
    except (httpx.HTTPError, ValueError):
        return False


def active_provider() -> str:
    return _request("GET", "/api/v1/providers", timeout=5)["active"]


def runtime_status() -> dict:
    return _request("GET", "/api/v1/system/status", timeout=3)


def chat(message: str) -> ChatReply:
    body = {"message": message, "provider": settings.provider, "speak": settings.speak_typed or settings.conversation}
    data = _request("POST", "/api/v1/chat", timeout=60, json=body)
    return ChatReply(data["response"], data.get("awaiting_reply", False), tuple(data.get("keyboard") or ()),
                     data.get("model") == "system_control", data.get("automation_job"), data.get("private", False))


def bar_suggestions() -> list[str]:
    """The command bar's guesses for right now ([] if FRIDAY isn't answering)."""
    try:
        return _request("GET", "/api/v1/predict/bar", timeout=3)["suggestions"]
    except (BackendError, KeyError):
        return []


def automation_status() -> dict:
    return _request("GET", "/api/v1/automation/status", timeout=3)


def bar_outcome(offered: list[str], sent: str | None) -> None:
    """Which guess was used when the bar closed (None = closed without sending)."""
    try:
        _request("POST", "/api/v1/predict/bar/outcome", timeout=3, json={"offered": offered, "sent": sent})
    except BackendError:
        pass


def voice(after_speech: bool = False, speak: bool | None = None) -> dict:
    """
    Listen until the user stops (or stop_listening() is called); returns transcription + reply.
    after_speech=True waits for FRIDAY to finish speaking first — to hear the answer to its
    question. Otherwise FRIDAY stops talking so the user can speak.
    speak=True says the reply even if spoken replies are switched off (conversation mode).
    """
    body = {"speak": settings.speak_replies if speak is None else speak, "provider": settings.provider,
            "after_speech": after_speech}
    if settings.conversation:
        body["barge_in"] = True
    return _request("POST", "/api/v1/voice", timeout=MAX_LISTEN_SECONDS + VOICE_EXTRA_SECONDS, json=body)


def wake(session: str) -> dict:
    """
    Wait for "Hey Friday", then return the transcription + reply like voice().
    BackendError status 408 = nobody said it before the auto-off time; 409 = stop_wake() was called.
    """
    body = {"speak": settings.speak_replies, "provider": settings.provider, "session": session}
    timeout = config.WAKE_AUTO_OFF_MINUTES * 60 + MAX_LISTEN_SECONDS + VOICE_EXTRA_SECONDS
    return _request("POST", "/api/v1/voice/wake", timeout=timeout, json=body)


def stop_wake(session: str) -> None:
    _request("POST", "/api/v1/voice/wake/stop", timeout=5, json={"session": session})


def stop_listening(discard: bool = False) -> None:
    _request("POST", "/api/v1/voice/stop", timeout=5, params={"discard": "true"} if discard else None)


def stop_conversation_input() -> None:
    _request("POST", "/api/v1/voice/conversation/stop", timeout=5, params={"silence": "false"})


def body_state(since: int = 0) -> dict:
    """What FRIDAY's body should show: speaking / listening / thinking, and events after `since`."""
    return _request("GET", "/api/v1/body", timeout=2, params={"since": since})


def talk_on() -> bool:
    return _request("GET", "/api/v1/mind/talk", timeout=5)["on"]


def set_talk(on: bool) -> bool:
    return _request("POST", "/api/v1/mind/talk", timeout=5, json={"on": on})["on"]


def next_ask(wait: float = 25) -> str | None:
    """Blocks until FRIDAY asks something on her own (or `wait` seconds pass)."""
    return _request("GET", "/api/v1/mind/ask", timeout=wait + 10, params={"wait": wait})["question"]


def clear_history() -> None:
    _request("DELETE", "/api/v1/history", timeout=10)


def clipboard_history() -> list[str]:
    """Recently copied text, newest first."""
    return _request("GET", "/api/v1/clipboard/history", timeout=5)["items"]


def clear_clipboard_history() -> None:
    _request("DELETE", "/api/v1/clipboard/history", timeout=5)


def file_search_status() -> dict:
    return _request("GET", "/api/v1/files/status", timeout=5)


def rescan_files() -> str:
    return _request("POST", "/api/v1/files/rescan", timeout=5)["message"]


def system_stats() -> list[str]:
    """Short system stats lines for the tray menu."""
    return _request("GET", "/api/v1/system/stats", timeout=5)["lines"]
