"""
services/automation/media_control.py

Controls whatever is playing — Spotify, YouTube in Chrome, any app that shows
up in Windows' media overlay — through the Windows media session API (winrt).

Replies describe what really happened: the track that is now playing, or that
nothing is playing. If winrt isn't installed, it falls back to pressing the
keyboard media keys, and says so, since it can't check the result.
"""

import asyncio
import ctypes
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from core.logger import logger
from services.automation.system_control import AutomationError


def _load_system_cpp_runtime() -> None:
    """
    winrt ships an older msvcp140.dll. Whichever copy loads first is used by the
    whole process, and torch (speech recognition) fails with the old one — so
    load Windows' own, newer copy before winrt.
    """
    try:
        ctypes.WinDLL(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "msvcp140.dll"))
    except OSError as e:
        logger.warning(f"Couldn't preload msvcp140.dll — speech recognition may fail to load: {e}")


_load_system_cpp_runtime()

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
except ImportError:  # pragma: no cover - depends on the machine
    SessionManager = PlaybackStatus = None

TIMEOUT_SECONDS = 5
TRACK_CHANGE_WAIT_SECONDS = 2
PLAYER_START_WAIT_SECONDS = 20
NOTHING_OPEN = "No music player is open. Say \"play music\" to start Spotify."

# Windows virtual-key codes for the keyboard media keys (fallback only)
MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}

# The winrt calls are async. Callers are sync and may already be on an event loop,
# so the calls run on their own thread with their own loop.
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media")


def _run(coro):
    return _worker.submit(asyncio.run, coro).result(timeout=TIMEOUT_SECONDS + 2)


async def _current_session():
    manager = await SessionManager.request_async()
    return manager.get_current_session()


async def _track(session) -> str:
    try:
        props = await session.try_get_media_properties_async()
    except OSError:
        return ""
    title, artist = (props.title or "").strip(), (props.artist or "").strip()
    return f"{title} by {artist}" if title and artist else title


def _is_playing(session) -> bool:
    return session.get_playback_info().playback_status == PlaybackStatus.PLAYING


async def _wait_for_new_track(session, old: str) -> str:
    deadline = time.monotonic() + TRACK_CHANGE_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(0.2)
        new = await _track(session)
        if new and new != old:
            return new
    return ""


def _press_media_key(key: str) -> None:
    code = MEDIA_KEYS[key]
    user32 = ctypes.WinDLL("user32")
    user32.keybd_event(code, 0, 0, 0)
    user32.keybd_event(code, 0, 2, 0)  # KEYEVENTF_KEYUP


def _fallback(key: str, message: str) -> str:
    logger.warning("winrt media controls unavailable — pressing the media key instead")
    _press_media_key(key)
    return message


# ── Actions ───────────────────────────────────────────────────────────────────

async def _play():
    session = await _current_session()
    if session is None:
        raise AutomationError(NOTHING_OPEN)
    track = await _track(session)
    if _is_playing(session):
        return f"Already playing {track}." if track else "Music is already playing."
    if not await session.try_play_async():
        raise AutomationError("The music player didn't let me resume playback.")
    return f"Playing {track}." if track else "Resumed playback."


async def _pause():
    session = await _current_session()
    if session is None or not _is_playing(session):
        return "Nothing is playing right now."
    track = await _track(session)
    if not await session.try_pause_async():
        raise AutomationError("The music player didn't let me pause.")
    return f"Paused {track}." if track else "Paused."


async def _skip(forward: bool):
    session = await _current_session()
    if session is None:
        raise AutomationError(NOTHING_OPEN)
    old = await _track(session)
    skip = session.try_skip_next_async if forward else session.try_skip_previous_async
    if not await skip():
        direction = "next" if forward else "previous"
        raise AutomationError(f"The music player didn't let me go to the {direction} track.")
    new = await _wait_for_new_track(session, old)
    if new:
        return f"Now playing {new}."
    if forward:
        return "Skipped to the next track."
    # Most players restart the current song first when you go back mid-song
    return f"Went back to the start of {old}." if old else "Went back a track."


async def _now_playing():
    session = await _current_session()
    if session is None:
        return "Nothing is playing right now."
    track = await _track(session)
    if not track:
        return "Something is open in a player, but it isn't sharing the track name."
    return f"{'Playing' if _is_playing(session) else 'Paused'}: {track}."


def play() -> str:
    if SessionManager is None:
        return _fallback("play_pause", "Pressed play/pause — I can't check whether music started.")
    return _run(_play())


def pause() -> str:
    if SessionManager is None:
        return _fallback("play_pause", "Pressed play/pause — I can't check whether music stopped.")
    return _run(_pause())


def next_track() -> str:
    if SessionManager is None:
        return _fallback("next", "Pressed the next-track key.")
    return _run(_skip(forward=True))


def previous_track() -> str:
    if SessionManager is None:
        return _fallback("previous", "Pressed the previous-track key.")
    return _run(_skip(forward=False))


def now_playing() -> str:
    if SessionManager is None:
        raise AutomationError("I can't see what's playing on this PC (the winrt packages aren't installed).")
    return _run(_now_playing())


def has_player() -> bool:
    """Is any app showing up as a media player right now?"""
    if SessionManager is None:
        return False
    try:
        return _run(_current_session()) is not None
    except Exception as e:
        logger.warning(f"Couldn't check for a media player: {e}")
        return False


async def _playing_source() -> str:
    """The app id of Windows' current media session if it's playing ("Chrome", "MSEdge", "Spotify.exe"), else ""."""
    # ponytail: only the current session (listing all needs the winrt collections package)
    session = await _current_session()
    return (session.source_app_user_model_id or "") if session and _is_playing(session) else ""


def is_playing_in(app: str) -> bool:
    """Whether the program `app` ('chrome', 'msedge') is playing media now.
    For the activity log: watching a lecture isn't being away."""
    if SessionManager is None:
        return False
    try:
        return app.lower() in _run(_playing_source()).lower()
    except Exception as e:
        logger.info(f"Couldn't check what's playing: {e}")
        return False


# ── Starting music ────────────────────────────────────────────────────────────

def _play_when_ready() -> None:
    """After opening a player, press play as soon as it shows up."""
    deadline = time.monotonic() + PLAYER_START_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            logger.info(f"Music started: {play()}")
            return
        except AutomationError:
            continue  # not open yet
        except Exception as e:
            logger.warning(f"Couldn't start the music: {e}")
            return
    logger.warning("The music player never showed up, so playback wasn't started")


def play_music(open_player) -> str:
    """Resume the open player, or open one with open_player() and start it once it's ready."""
    if has_player():
        return play()
    open_player()
    if SessionManager is not None:
        threading.Thread(target=_play_when_ready, daemon=True, name="start-music").start()
        return "Opening Spotify — your music will start in a moment."
    return "Opened Spotify. Press play to start your music."


def search_spotify(query: str) -> str:
    """Open Spotify's search for a song. Spotify can't be told to play a search result directly."""
    try:
        os.startfile(f"spotify:search:{quote(query)}")
    except OSError as e:
        logger.warning(f"Spotify search failed: {e}")
        raise AutomationError("Couldn't open Spotify search — is Spotify installed?")
    return f"Opened Spotify search for \"{query}\". Pick the song to play it."
