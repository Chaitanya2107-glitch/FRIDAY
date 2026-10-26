"""
services/telegram/client.py

The Telegram Bot API calls FRIDAY uses (plain HTTPS, outbound only — nothing on
the laptop is exposed), plus what other modules need without importing the bot:
  - mirror(): a notification also goes to Telegram while the user is away
  - the lockdown switch: "/lockdown" from Telegram, "unlock telegram" at the laptop

The token is part of every URL, so errors are logged by method name only.
"""

import json
import contextvars
import time
from urllib.parse import parse_qs, urlparse

import httpx

from core.config import config
from core.logger import logger

API = "https://api.telegram.org"
TEXT_LIMIT = 4096  # Telegram's longest message
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
state_path = config.MEMORY_DIR / "telegram.json"  # tests point this elsewhere
_chunked = contextvars.ContextVar("telegram_chunked", default=False)


class TelegramError(Exception):
    pass


class TelegramSubmissionUncertain(TelegramError):
    """The send may have arrived, but no trustworthy response was received."""


def enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN)


def call(method: str, http_timeout: float = 20, files: dict | None = None, **params):
    """One Bot API call (blocking). Returns its result; raises TelegramError without the token in it."""
    try:
        response = httpx.post(f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
                              data=params if files else None, json=None if files else params,
                              files=files, timeout=http_timeout)
        body = response.json()
    except (httpx.HTTPError, ValueError) as e:
        if method.startswith("send") and isinstance(e, (ValueError, httpx.ReadTimeout, httpx.WriteTimeout,
                                                       httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
            raise TelegramSubmissionUncertain(f"{method} outcome unknown: {type(e).__name__}") from None
        raise TelegramError(f"{method} failed: {type(e).__name__}") from None
    if not body.get("ok"):
        raise TelegramError(f"{method} failed: {body.get('description', response.status_code)}")
    return body["result"]


def send(chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
    """Text, optionally with inline buttons as (label, callback data)."""
    params = {"chat_id": chat_id, "text": text[:TEXT_LIMIT] or "(empty)"}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": data}] for label, data in buttons]}
    from services.mind.cognition import cognition

    with cognition.operation("telegram_chunk" if _chunked.get() else "telegram_message", "telegram", params["text"]):
        call("sendMessage", **params)


def send_file(chat_id: int, path, photo: bool = False, caption: str = "") -> None:
    from services.mind.cognition import cognition

    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    with cognition.operation("telegram_file", "telegram", "File upload"), open(path, "rb") as f:
        call(method, http_timeout=120, files={field: (getattr(path, "name", str(path)), f)}, chat_id=chat_id, caption=caption)


def send_long(chat_id: int, text: str) -> None:
    """Deliver a whole summary, retaining text that send() would truncate.

    Telegram limits each message to 4096 characters: https://core.telegram.org/bots/api#sendmessage
    """
    from services.mind.cognition import cognition

    with cognition.operation("telegram_message", "telegram", text):
        token = _chunked.set(True)
        try:
            while text:
                end = min(len(text), TEXT_LIMIT)
                if end < len(text):
                    newline = text.rfind("\n", 0, end)
                    if newline >= end // 2:
                        end = newline + 1
                send(chat_id, text[:end])
                text = text[end:]
        finally:
            _chunked.reset(token)


def download(file_id: str) -> bytes:
    file_path = call("getFile", file_id=file_id)["file_path"]
    try:
        response = httpx.get(f"{API}/file/bot{config.TELEGRAM_BOT_TOKEN}/{file_path}", timeout=60)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise TelegramError(f"download failed: {type(e).__name__}") from None
    return response.content


# ── Notifications while away ──────────────────────────────────────────────────

def button_data(link: str) -> str | None:
    """friday://habit?token=T&answer=open → "b|T|open" (Telegram allows 64 bytes of callback data)."""
    query = parse_qs(urlparse(link).query)
    if "token" not in query or "answer" not in query:
        return None
    return f"b|{query['token'][0]}|{query['answer'][0]}"


def mirror_eligible() -> bool:
    """Read-only routing check for the configured owner's existing away policy."""
    if not (enabled() and config.TELEGRAM_USER_ID):
        return False
    from services.activity.log import idle_seconds

    idle = idle_seconds()
    return idle >= config.TELEGRAM_AWAY_MINUTES * 60 or (idle >= BACK_SECONDS and away())


def mirror(title: str, body: str, buttons: list[tuple[str, str]] | None = None,
           *, outcome: dict | None = None) -> bool | None:
    """Send a notification to Telegram too, if the bot is set up and the user is away. Never raises."""
    if not (enabled() and config.TELEGRAM_USER_ID):
        return
    from services.activity.log import idle_seconds  # avoid an import cycle at startup

    idle = idle_seconds()
    if away() and idle < BACK_SECONDS:  # "/away" ends when the user is back at the laptop
        set_away(False)
    if not mirror_eligible():
        return
    links = [(label, data) for label, link in buttons or [] if (data := button_data(link))]
    try:
        send(config.TELEGRAM_USER_ID, f"{title}\n{body}", links)
        return True
    except TelegramError as error:
        if outcome is not None and isinstance(error, TelegramSubmissionUncertain):
            outcome["uncertain"] = True
        logger.warning("Telegram notification failed: %s", type(error).__name__)
        return False


# ── Lockdown ──────────────────────────────────────────────────────────────────

def _state() -> dict:
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def locked() -> bool:
    return bool(_state().get("lockdown"))


def set_locked(on: bool) -> None:
    state_path.write_text(json.dumps(_state() | {"lockdown": on, "at": time.time()}), encoding="utf-8")
    logger.info(f"Telegram remote control {'locked' if on else 'unlocked'}")


# ── Away ("/away", "I'm going out") ───────────────────────────────────────────

BACK_SECONDS = 60  # used the laptop this recently = back


def away() -> bool:
    """Set by "/away": notifications come here at once. Cleared once the user is back (after a minute)."""
    since = _state().get("away_since")
    return bool(since) and time.time() - since > BACK_SECONDS  # the lock's own last keypress doesn't count


def set_away(on: bool) -> None:
    state_path.write_text(json.dumps(_state() | {"away_since": time.time() if on else None}), encoding="utf-8")
