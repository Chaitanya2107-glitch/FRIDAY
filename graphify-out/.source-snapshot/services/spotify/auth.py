"""
services/spotify/auth.py

Logging in to Spotify, once. Uses the Authorization Code flow with PKCE, so
only SPOTIFY_CLIENT_ID is needed (no client secret in .env):

  1. "connect Spotify" → start_login() opens Spotify's consent page in the browser
  2. Spotify sends the browser back to /api/v1/spotify/callback
     (interfaces/api/routes/spotify.py) → finish_login() swaps the code for tokens
  3. The tokens are kept in memory/spotify_token.json and refreshed automatically

The token file only lets FRIDAY control playback and read/save your library
(see SCOPES). "disconnect Spotify" deletes it.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from core.config import config
from core.logger import logger
from services.automation.system_control import AutomationError

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = " ".join((
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-read",
    "user-library-modify",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-top-read",  # "my Spotify wrapped"
))
TOKEN_PATH: Path = config.MEMORY_DIR / "spotify_token.json"
LOGIN_TIMEOUT_SECONDS = 600
REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10

NOT_SET_UP = (
    "To control Spotify, create an app at developer.spotify.com, add its Client ID to .env "
    "as SPOTIFY_CLIENT_ID (see .env.example) and restart me. Then say \"connect Spotify\"."
)
NOT_CONNECTED = "Spotify isn't connected yet. Say \"connect Spotify\" and log in once."


class SpotifyError(AutomationError):
    """Something went wrong talking to Spotify. The message is user-facing."""


_lock = threading.Lock()
_pending_login: dict | None = None  # {"state", "verifier", "started"} while the browser is open


def is_configured() -> bool:
    return bool(config.SPOTIFY_CLIENT_ID)


def is_connected() -> bool:
    return is_configured() and _load() is not None


def missing_scopes() -> set[str]:
    """Permissions FRIDAY now asks for that the saved login didn't grant (e.g. top tracks, added later)."""
    token = _load() or {}
    return set(SCOPES.split()) - set(str(token.get("scope", "")).split())


# ── Logging in ────────────────────────────────────────────────────────────────

def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def start_login() -> str:
    """Remember a fresh PKCE verifier and state, and return Spotify's consent page URL."""
    global _pending_login
    if not is_configured():
        raise SpotifyError(NOT_SET_UP)
    verifier = secrets.token_urlsafe(64)  # 86 characters; Spotify allows 43–128
    state = secrets.token_urlsafe(16)
    with _lock:
        _pending_login = {"state": state, "verifier": verifier, "started": time.monotonic()}
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": config.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.SPOTIFY_REDIRECT_URI,
        "code_challenge_method": "S256",
        "code_challenge": _challenge(verifier),
        "scope": SCOPES,
        "state": state,
    })


def finish_login(code: str, state: str) -> None:
    """Swap the code Spotify sent back for tokens. The state must match the login FRIDAY started."""
    global _pending_login
    with _lock:
        pending, _pending_login = _pending_login, None
    if pending is None or not secrets.compare_digest(state, pending["state"]):
        raise SpotifyError("That Spotify login wasn't started by FRIDAY. Say \"connect Spotify\" to try again.")
    if time.monotonic() - pending["started"] > LOGIN_TIMEOUT_SECONDS:
        raise SpotifyError("That Spotify login took too long. Say \"connect Spotify\" to try again.")
    _save(_token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.SPOTIFY_REDIRECT_URI,
        "client_id": config.SPOTIFY_CLIENT_ID,
        "code_verifier": pending["verifier"],
    }))
    logger.info("Spotify connected")


def disconnect() -> None:
    with _lock:
        TOKEN_PATH.unlink(missing_ok=True)


# ── Tokens ────────────────────────────────────────────────────────────────────

def access_token(force_refresh: bool = False) -> str:
    """A valid access token, refreshed first if it's (nearly) expired."""
    if not is_configured():
        raise SpotifyError(NOT_SET_UP)
    with _lock:
        token = _load()
        if token is None:
            raise SpotifyError(NOT_CONNECTED)
        if force_refresh or token["expires_at"] - time.time() < REFRESH_MARGIN_SECONDS:
            token = _refresh(token)
        return token["access_token"]


def _refresh(token: dict) -> dict:
    try:
        fresh = _token_request({
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": config.SPOTIFY_CLIENT_ID,
        })
    except SpotifyError as e:
        if "invalid_grant" in str(e):  # revoked in Spotify's settings, or the app changed
            TOKEN_PATH.unlink(missing_ok=True)
            raise SpotifyError("Spotify logged me out. Say \"connect Spotify\" to log in again.")
        raise
    # Spotify may or may not send a new refresh token; keep the old one if not
    fresh.setdefault("refresh_token", token["refresh_token"])
    return _save(fresh)


def _token_request(data: dict) -> dict:
    try:
        response = httpx.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        logger.warning(f"Spotify token request failed: {e}")
        raise SpotifyError("Couldn't reach Spotify — check the internet connection.")
    if response.is_error:
        try:
            error = response.json().get("error", "")
        except ValueError:
            error = ""
        logger.warning(f"Spotify token request rejected: HTTP {response.status_code} {error}")
        raise SpotifyError(f"Spotify refused the login ({error or response.status_code}).")
    return response.json()


def _save(payload: dict) -> dict:
    token = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", ""),  # what was allowed: a new feature's scope means logging in again
    }
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    return token


def _load() -> dict | None:
    try:
        token = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning(f"Couldn't read the Spotify token file: {e}")
        return None
    if not all(key in token for key in ("access_token", "refresh_token", "expires_at")):
        return None
    return token
