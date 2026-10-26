"""
services/spotify/player.py

Real Spotify control through the Spotify Web API (Premium only): play a song,
artist, album, playlist or your liked songs, shuffle, repeat, add to the queue,
like the current song. Used by services/automation/intent.py once the user has
said "connect Spotify" (services/spotify/auth.py). Pause, skip and "what's
playing" keep using media_control.py, which works with any player.

Playback needs a Spotify device. If none is running, FRIDAY opens the desktop
app and starts the music as soon as it shows up. Once music starts, the Spotify
window is minimized so it doesn't cover what you were doing.

Every function returns a sentence to show or speak, or raises SpotifyError.
"""

import os
import random
import re
import threading
import time
import webbrowser

import httpx

from core.logger import logger
from services.automation import app_finder
from services.spotify import auth
from services.spotify.auth import SpotifyError

API_URL = "https://api.spotify.com/v1"
HTTP_TIMEOUT_SECONDS = 10
SEARCH_LIMIT = 5  # Spotify's maximum is 10
DEVICE_WAIT_SECONDS = 20
MINIMIZE_TRIES = 5  # seconds to wait for a just-opened Spotify's window to appear
LIKED_SONGS_PAGES = 2  # 50 songs a page
PLAYLIST_PAGES = 4
NOTHING_PLAYING = "Nothing is playing on Spotify right now."


class NoDevice(SpotifyError):
    """Spotify has no active device to act on."""


# ── Talking to the API ────────────────────────────────────────────────────────

def _api(method: str, path: str, params: dict | None = None, json: dict | None = None,
         _retry: bool = True) -> dict:
    token = auth.access_token(force_refresh=not _retry)
    try:
        response = httpx.request(
            method, API_URL + path, params=params, json=json, timeout=HTTP_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as e:
        logger.warning(f"Spotify request {method} {path} failed: {e}")
        raise SpotifyError("Couldn't reach Spotify — check the internet connection.")
    if response.status_code == 401 and _retry:
        return _api(method, path, params, json, _retry=False)
    if response.is_error:
        raise _error(response, f"{method} {path}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}  # some playback endpoints answer with a non-JSON body


def _error(response: httpx.Response, request: str) -> SpotifyError:
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {"message": str(error)}
    reason, message = error.get("reason", ""), error.get("message", "")
    status = response.status_code
    logger.warning(f"Spotify {request} → HTTP {status} {reason} {message}")

    if reason == "NO_ACTIVE_DEVICE" or (status == 404 and "device" in message.lower()):
        return NoDevice(NOTHING_PLAYING)
    if reason == "PREMIUM_REQUIRED":
        return SpotifyError("Spotify only lets apps control playback on Premium accounts.")
    if "not registered" in message.lower() or "developer" in message.lower():
        return SpotifyError(
            "Spotify blocked your account for this app. On developer.spotify.com, open your app's "
            "User Management and add the email of your Spotify account."
        )
    if status == 429:
        return SpotifyError("Spotify is limiting how often I can ask. Try again in a minute.")
    if status == 403 and "scope" in message.lower():
        return SpotifyError("Spotify needs one more permission for that — say \"connect Spotify\" and press Agree.")
    if status == 403:
        return SpotifyError("Spotify won't allow that right now.")
    return SpotifyError(f"Spotify couldn't do that ({message or f'HTTP {status}'}).")


# ── Devices and starting playback ─────────────────────────────────────────────

def _pick_device() -> str | None:
    """The device already playing; otherwise this PC's Spotify app, if it's open."""
    devices = [d for d in _api("GET", "/me/player/devices").get("devices", [])
               if d.get("id") and not d.get("is_restricted")]
    active = [d for d in devices if d.get("is_active")]
    if active:
        return active[0]["id"]
    computers = [d for d in devices if str(d.get("type", "")).lower() == "computer"]
    here = os.environ.get("COMPUTERNAME", "").lower()
    for device in computers:
        if str(device.get("name", "")).lower() == here:
            return device["id"]
    return computers[0]["id"] if computers else None


def _play_on(device: str, body: dict, shuffle: bool) -> None:
    _api("PUT", "/me/player/play", params={"device_id": device}, json=body)
    if shuffle:
        _api("PUT", "/me/player/shuffle", params={"state": "true", "device_id": device})
    threading.Thread(target=minimize_spotify, daemon=True, name="spotify-minimize").start()


def minimize_spotify() -> None:
    """Minimize the Spotify app's window; a Spotify that just opened may take a moment to show one."""
    for attempt in range(MINIMIZE_TRIES):
        windows = app_finder.app_windows(lambda proc: proc.name().lower() == "spotify.exe")
        if windows:
            app_finder.minimize_windows(windows)
            return
        time.sleep(1)


def _start(body: dict, label: str, open_player, shuffle: bool = False) -> str:
    device = _pick_device()
    if device is None:
        open_player()
        threading.Thread(
            target=_start_when_ready, args=(body, label, shuffle), daemon=True, name="spotify-start",
        ).start()
        return f"Opening Spotify — {label} will start in a moment."
    _play_on(device, body, shuffle)
    return f"{'Shuffling' if shuffle else 'Playing'} {label}."


def _start_when_ready(body: dict, label: str, shuffle: bool) -> None:
    """After opening the desktop app, start playback as soon as it shows up as a device."""
    deadline = time.monotonic() + DEVICE_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            device = _pick_device()
            if device is None:
                continue
            _play_on(device, body, shuffle)
            logger.info(f"Spotify started {label}")
            return
        except SpotifyError as e:
            logger.warning(f"Couldn't start {label} on Spotify: {e}")
            return
    logger.warning("Spotify never showed up as a device, so playback wasn't started")


# ── Finding things ────────────────────────────────────────────────────────────

def _simplify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _search(query: str, *kinds: str, limit: int = SEARCH_LIMIT) -> dict[str, list[dict]]:
    result = _api("GET", "/search", params={"q": query, "type": ",".join(kinds), "limit": limit})
    # Spotify sometimes puts nulls in the lists (e.g. removed playlists)
    return {kind: [item for item in (result.get(kind + "s") or {}).get("items") or [] if item]
            for kind in kinds}


def _named(query: str, items: list[dict]) -> dict | None:
    wanted = _simplify(query)
    return next((item for item in items if _simplify(item.get("name", "")) == wanted), None)


def _artist_names(item: dict) -> str:
    return ", ".join(a["name"] for a in item.get("artists", [])[:2] if a.get("name"))


def _describe_track(track: dict) -> str:
    artists = _artist_names(track)
    return f"{track['name']} by {artists}" if artists else track["name"]


def _my_playlists() -> list[dict]:
    playlists, offset = [], 0
    for _ in range(PLAYLIST_PAGES):
        page = _api("GET", "/me/playlists", params={"limit": 50, "offset": offset})
        playlists += [p for p in page.get("items") or [] if p]
        if not page.get("next"):
            break
        offset += 50
    return playlists


def _find_my_playlist(query: str) -> dict | None:
    playlists = _my_playlists()
    exact = _named(query, playlists)
    if exact:
        return exact
    wanted = _simplify(query)
    return next((p for p in playlists if wanted and wanted in _simplify(p.get("name", ""))), None)


def _track_count(playlist: dict) -> int:
    # Renamed from "tracks" to "items" in Spotify's February 2026 API
    for key in ("items", "tracks"):
        info = playlist.get(key)
        if isinstance(info, dict) and isinstance(info.get("total"), int):
            return info["total"]
    return 0


# ── Actions ───────────────────────────────────────────────────────────────────

def play_search(query: str, open_player) -> str:
    """ "play <anything>": an artist whose name matches exactly, otherwise the best matching song."""
    found = _search(query, "track", "artist")
    artist = _named(query, found["artist"])
    if artist:
        return _start({"context_uri": artist["uri"]}, artist["name"], open_player)
    if not found["track"]:
        raise SpotifyError(f"I couldn't find \"{query}\" on Spotify.")
    track = found["track"][0]
    album = (track.get("album") or {}).get("uri")
    # Play it inside its album, so the music carries on afterwards
    body = {"context_uri": album, "offset": {"uri": track["uri"]}} if album else {"uris": [track["uri"]]}
    return _start(body, _describe_track(track), open_player)


def play_named(kind: str, query: str, open_player, shuffle: bool = False) -> str:
    """Play an artist, album or playlist by name. Playlists are looked for in yours first."""
    if kind == "playlist":
        mine = _find_my_playlist(query)
        if mine:
            return _play_playlist(mine, f"your {mine['name']} playlist", open_player, shuffle)
    items = _search(query, kind)[kind]
    if not items:
        raise SpotifyError(f"I couldn't find the {kind} \"{query}\" on Spotify.")
    item = _named(query, items) or items[0]
    if kind == "playlist":
        return _play_playlist(item, f"the playlist {item['name']}", open_player, shuffle)
    label = item["name"]
    if kind == "album":
        artists = _artist_names(item)
        label = f"the album {item['name']}" + (f" by {artists}" if artists else "")
    return _start({"context_uri": item["uri"]}, label, open_player, shuffle)


def _play_playlist(playlist: dict, label: str, open_player, shuffle: bool) -> str:
    body = {"context_uri": playlist["uri"]}
    total = _track_count(playlist)
    if shuffle and total > 1:
        body["offset"] = {"position": random.randrange(total)}  # don't always start on song one
    return _start(body, label, open_player, shuffle)


def play_liked(open_player, shuffle: bool = False) -> str:
    uris = []
    for page in range(LIKED_SONGS_PAGES):
        data = _api("GET", "/me/tracks", params={"limit": 50, "offset": page * 50})
        uris += [item["track"]["uri"] for item in data.get("items") or []
                 if item and item.get("track") and item["track"].get("uri")]
        if not data.get("next"):
            break
    if not uris:
        raise SpotifyError("You don't have any liked songs on Spotify yet.")
    if shuffle:
        random.shuffle(uris)
    return _start({"uris": uris}, "your liked songs", open_player, shuffle)


def set_shuffle(on: bool) -> str:
    _api("PUT", "/me/player/shuffle", params={"state": "true" if on else "false"})
    return "Shuffle is on." if on else "Shuffle is off."


REPEAT_REPLIES = {
    "track": "Repeating this song.",
    "context": "Repeat is on.",
    "off": "Repeat is off.",
}


def set_repeat(mode: str) -> str:
    if mode not in REPEAT_REPLIES:
        raise ValueError(f"Unknown repeat mode: {mode}")
    _api("PUT", "/me/player/repeat", params={"state": mode})
    return REPEAT_REPLIES[mode]


def add_to_queue(query: str) -> str:
    tracks = _search(query, "track")["track"]
    if not tracks:
        raise SpotifyError(f"I couldn't find \"{query}\" on Spotify.")
    try:
        _api("POST", "/me/player/queue", params={"uri": tracks[0]["uri"]})
    except NoDevice:
        raise SpotifyError(f"Spotify isn't playing anything, so there's no queue. Say \"play {query}\" instead.")
    return f"Added {_describe_track(tracks[0])} to the queue."


def like_current(like: bool = True) -> str:
    playing = _api("GET", "/me/player/currently-playing")
    track = playing.get("item")
    if not track or playing.get("currently_playing_type", "track") != "track":
        raise SpotifyError(NOTHING_PLAYING)
    _api("PUT" if like else "DELETE", "/me/library", params={"uris": track["uri"]})
    name = _describe_track(track)
    return f"Added {name} to your liked songs." if like else f"Removed {name} from your liked songs."


def connect() -> str:
    if auth.is_connected() and not auth.missing_scopes():
        return "Spotify is already connected. Say \"disconnect Spotify\" first to switch accounts."
    webbrowser.open(auth.start_login())
    return "Opened the Spotify login in your browser. Log in and press Agree, and you're set."


def disconnect() -> str:
    if not auth.is_connected():
        return "Spotify wasn't connected."
    auth.disconnect()
    return "Disconnected Spotify. Music commands will still control whatever player is open."
