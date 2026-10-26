import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import REPLY_RULES, config
from services.automation import intent, media_control as media
from services.automation.app_commands import match_media_command
from services.automation.intent import ActionResult, try_system_action
from services.automation.system_control import AutomationError
from services.voice.tts import spoken_text

PLAYING, PAUSED = media.PlaybackStatus.PLAYING, media.PlaybackStatus.PAUSED


# ── Recognising music commands ────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("play", {"action": "media_play"}),
    ("resume the music please", {"action": "media_play"}),
    ("hey friday, pause", {"action": "media_pause"}),
    ("stop the music", {"action": "media_pause"}),
    ("pause spotify", {"action": "media_pause"}),
    ("next song", {"action": "media_next"}),
    ("skip this song on spotify", {"action": "media_next"}),
    ("previous track", {"action": "media_previous"}),
    ("what's playing?", {"action": "now_playing"}),
    ("what song is this", {"action": "now_playing"}),
    ("play some music", {"action": "play_music"}),
    ("play spotify", {"action": "play_music"}),
    ("play dilbara by pritam", {"action": "play_song", "query": "dilbara by pritam"}),
    ("play the song believer on spotify", {"action": "play_song", "query": "believer"}),
])
def test_music_commands_are_recognised(message, expected):
    assert match_media_command(message, has_player=lambda: True) == {"type": "system", **expected}


@pytest.mark.parametrize("message", [
    "play a game with me",
    "play chess",
    "play despacito on youtube",  # a YouTube search, handled by the app matcher
    "I love this song",
    "stop spotify",  # closes the app
    "next week is busy",
])
def test_other_messages_are_not_music_commands(message):
    assert match_media_command(message, has_player=lambda: True) is None


@pytest.mark.parametrize("message", ["next", "skip", "go back", "back"])
def test_short_words_need_an_open_player(message):
    assert match_media_command(message, has_player=lambda: False) is None
    assert match_media_command(message, has_player=lambda: True) is not None


def test_play_song_falls_back_to_youtube_without_spotify(monkeypatch):
    opened = []
    monkeypatch.setattr(intent.system, "list_apps", lambda: ["chrome"])
    monkeypatch.setattr(intent.system, "open_url", lambda url: opened.append(url) or "ok")

    result = asyncio.run(try_system_action("play dilbara", "openrouter"))

    assert opened == ["https://www.youtube.com/results?search_query=dilbara"]
    assert result == ActionResult(
        True, 'Opened YouTube results for "dilbara". Pick the video to play it.', repeatable=False
    )


def test_play_song_opens_spotify_search(monkeypatch):
    opened = []
    monkeypatch.setattr(media.os, "startfile", opened.append)
    assert media.search_spotify("dilbara by pritam") == (
        'Opened Spotify search for "dilbara by pritam". Pick the song to play it.'
    )
    assert opened == ["spotify:search:dilbara%20by%20pritam"]


# ── Controlling the player ────────────────────────────────────────────────────

class FakeSession:
    def __init__(self, tracks, status=PLAYING, allowed=True):
        self.tracks, self.status, self.allowed, self.calls = list(tracks), status, allowed, []

    def get_playback_info(self):
        return SimpleNamespace(playback_status=self.status)

    async def try_get_media_properties_async(self):
        title, artist = self.tracks[0]
        return SimpleNamespace(title=title, artist=artist)

    async def try_play_async(self):
        self.calls.append("play")
        self.status = PLAYING if self.allowed else self.status
        return self.allowed

    async def try_pause_async(self):
        self.calls.append("pause")
        self.status = PAUSED
        return self.allowed

    async def _skip(self, name):
        self.calls.append(name)
        if len(self.tracks) > 1:
            self.tracks.pop(0)
        return self.allowed

    async def try_skip_next_async(self):
        return await self._skip("next")

    async def try_skip_previous_async(self):
        return await self._skip("previous")


@pytest.fixture
def player(monkeypatch):
    state = SimpleNamespace(session=None)

    class FakeManager:
        @staticmethod
        async def request_async():
            return FakeManager

        @staticmethod
        def get_current_session():
            return state.session

    monkeypatch.setattr(media, "SessionManager", FakeManager)
    monkeypatch.setattr(media, "TRACK_CHANGE_WAIT_SECONDS", 0.3)
    return state


def test_play_resumes_and_names_the_track(player):
    player.session = FakeSession([("Dilbara", "Pritam")], status=PAUSED)
    assert media.play() == "Playing Dilbara by Pritam."
    assert player.session.calls == ["play"]


def test_play_when_already_playing_does_nothing(player):
    player.session = FakeSession([("Dilbara", "Pritam")])
    assert media.play() == "Already playing Dilbara by Pritam."
    assert player.session.calls == []


def test_play_without_a_player_says_so(player):
    with pytest.raises(AutomationError, match="No music player is open"):
        media.play()


def test_player_refusing_to_play_is_an_error(player):
    player.session = FakeSession([("Dilbara", "Pritam")], status=PAUSED, allowed=False)
    with pytest.raises(AutomationError, match="didn't let me resume"):
        media.play()


def test_pause(player):
    player.session = FakeSession([("Dilbara", "Pritam")])
    assert media.pause() == "Paused Dilbara by Pritam."


def test_pause_when_nothing_plays(player):
    player.session = FakeSession([("Dilbara", "Pritam")], status=PAUSED)
    assert media.pause() == "Nothing is playing right now."
    assert player.session.calls == []


def test_next_reports_the_new_track(player):
    player.session = FakeSession([("Dilbara", "Pritam"), ("Kesariya", "Arijit Singh")])
    assert media.next_track() == "Now playing Kesariya by Arijit Singh."


def test_previous_mid_song_restarts_it(player):
    player.session = FakeSession([("Dilbara", "Pritam")])
    assert media.previous_track() == "Went back to the start of Dilbara by Pritam."


def test_now_playing(player):
    player.session = FakeSession([("Dilbara", "Pritam")], status=PAUSED)
    assert media.now_playing() == "Paused: Dilbara by Pritam."
    player.session = None
    assert media.now_playing() == "Nothing is playing right now."


def test_play_music_resumes_an_open_player(player):
    player.session = FakeSession([("Dilbara", "Pritam")], status=PAUSED)
    opened = []
    assert media.play_music(lambda: opened.append("spotify")) == "Playing Dilbara by Pritam."
    assert opened == []


def test_play_music_opens_spotify_and_starts_it_when_ready(player, monkeypatch):
    opened, started = [], []
    monkeypatch.setattr(media.threading, "Thread", lambda target, **kw: SimpleNamespace(start=lambda: started.append(target)))

    reply = media.play_music(lambda: opened.append("spotify"))

    assert reply == "Opening Spotify — your music will start in a moment."
    assert opened == ["spotify"] and started == [media._play_when_ready]

    # Spotify shows up a moment later, paused
    monkeypatch.setattr(media.time, "sleep", lambda s: None)
    player.session = FakeSession([("Dilbara", "Pritam")], status=PAUSED)
    media._play_when_ready()
    assert player.session.calls == ["play"]


def test_media_keys_are_used_without_winrt(monkeypatch):
    pressed = []
    monkeypatch.setattr(media, "SessionManager", None)
    monkeypatch.setattr(media, "_press_media_key", pressed.append)
    assert media.next_track() == "Pressed the next-track key."
    assert "can't check" in media.play()
    assert pressed == ["next", "play_pause"]


def test_music_command_runs_through_intent(player, monkeypatch):
    player.session = FakeSession([("Dilbara", "Pritam"), ("Kesariya", "Arijit Singh")])
    monkeypatch.setattr(intent, "get_provider", lambda *a, **k: pytest.fail("no AI call expected"))
    # Track names change, so the spoken reply isn't cached
    assert asyncio.run(try_system_action("next", "openrouter")) == ActionResult(
        True, "Now playing Kesariya by Arijit Singh.", repeatable=False
    )


# ── The chat AI stops pretending ──────────────────────────────────────────────

def test_voice_does_not_read_markdown():
    assert spoken_text("*next song* **play** `code` [site](https://x.com)\n- item") == "next song play code site\nitem"


def test_reply_rules_are_always_in_the_system_prompt(monkeypatch):
    assert REPLY_RULES in config.SYSTEM_PROMPT
    monkeypatch.setenv("SYSTEM_PROMPT", "You are a pirate.")
    assert config.SYSTEM_PROMPT.startswith("You are a pirate.\n" + REPLY_RULES)


def test_speech_recognition_still_loads_after_the_music_code():
    # winrt ships an old msvcp140.dll that used to stop torch from loading
    root = Path(__file__).parent.parent
    code = "import services.automation.media_control, torch; print('ok')"
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                            timeout=120, env={**os.environ, "PYTHONPATH": str(root)})
    assert result.stdout.strip().endswith("ok"), result.stderr[-500:]
