import asyncio

import pytest

from services.automation import intent
from services.automation.app_commands import match_media_command
from services.spotify import auth, dj, player
from services.spotify.auth import SpotifyError


def track(letter, artist="artist1"):
    return {"uri": "spotify:track:" + letter * 22, "name": "Song " + letter,
            "artists": [{"id": artist, "name": "Test Artist"}]}


@pytest.mark.parametrize("text, action, mood", [
    ("play something chill", "dj_mood", "chill"),
    ("give me energetic music", "dj_mood", "energetic"),
    ("switch to a relaxed mood", "dj_mood", "chill"),
    ("more songs like this", "dj_more", None),
    ("switch the mood", "dj_mood", "next"),
    ("for chill music use my Evening Walk playlist", "dj_save", "chill"),
])
def test_dj_commands_take_precedence_over_song_titles(text, action, mood):
    parsed = match_media_command(text, lambda: False)
    assert parsed["action"] == action
    assert parsed.get("mood") == mood


def test_chat_mentions_and_named_songs_keep_existing_behaviour():
    assert dj.match_command("I feel chill") is None
    assert dj.match_command("explain music moods") is None
    assert match_media_command("play Friday I'm in Love", lambda: False)["action"] == "play_song"
    for phrase in ("play Happy", "play Work", "start study", "more like this"):
        assert dj.match_command(phrase) is None


@pytest.fixture
def music(monkeypatch):
    monkeypatch.setattr(auth, "is_connected", lambda: True)
    monkeypatch.setattr(player, "_find_my_playlist", lambda _: None)
    monkeypatch.setattr(player, "_search", lambda *a, **kw: {"track": [track("a"), track("b"), track("a")]})
    starts, queued = [], []
    monkeypatch.setattr(player, "_start", lambda body, label, open_player: starts.append(body) or "Playing " + label)
    def api(method, path, **kwargs):
        if method == "GET" and path == "/me/player/currently-playing":
            return {"item": track("a"), "currently_playing_type": "track"}
        assert method == "POST" and path == "/me/player/queue"
        queued.append(kwargs["params"]["uri"])
        return {}
    monkeypatch.setattr(player, "_api", api)
    return starts, queued


def say(text):
    return asyncio.run(intent.try_system_action(text, "openrouter"))


def test_mood_mix_reaches_real_action_router_and_deduplicates(music):
    starts, _ = music
    result = say("play something chill")
    assert result.success and "chill" in result.message
    assert starts == [{"uris": [track("a")["uri"], track("b")["uri"]]}]
    assert say("switch the mood").success
    assert dj._load()["last_requested_mood"] == "focus"


def test_preferences_survive_reload_and_can_be_forgotten_without_playback(music, monkeypatch):
    starts, _ = music
    monkeypatch.setattr(auth, "is_connected", lambda: False)
    assert say("for chill music use my Evening Walk playlist").success
    assert dj._load()["preferences"]["chill"] == {"kind": "playlist", "value": "Evening Walk"}
    assert "Evening Walk" in say("show my DJ preferences").message
    assert say("forget my chill music preference").success
    assert "chill" not in dj._load()["preferences"] and not starts


def test_saved_playlist_uses_context_without_scraping_its_tracks(music, monkeypatch):
    starts, _ = music
    say("for chill music use my Evening Walk playlist")
    uri = "spotify:playlist:" + "p" * 22
    monkeypatch.setattr(player, "_find_my_playlist", lambda name: {"uri": uri} if name == "Evening Walk" else None)
    assert say("play something chill").success
    assert starts[-1] == {"context_uri": uri}


def test_more_like_current_uses_artist_search_excludes_current_duplicates_and_other_artists(music, monkeypatch):
    _, queued = music
    monkeypatch.setattr(player, "_search", lambda *a, **kw: {"track": [track("a"), track("b"), track("b"),
                                                                 track("c", "unrelated"), {"uri": "file://bad"}]})
    result = say("more songs like this")
    assert result.success and "from Test Artist" in result.message
    assert queued == [track("b")["uri"]]


def test_partial_queue_failure_reports_count_and_stops(music, monkeypatch):
    attempts = []
    monkeypatch.setattr(player, "_search", lambda *a, **kw: {"track": [track("b"), track("c"), track("d")]})
    def api(method, path, **kwargs):
        if method == "GET":
            return {"item": track("a"), "currently_playing_type": "track"}
        attempts.append(kwargs["params"]["uri"])
        if len(attempts) == 2:
            raise SpotifyError("Rate limited")
        return {}
    monkeypatch.setattr(player, "_api", api)
    result = say("more songs like this")
    assert not result.success and "Queued 1" in result.message
    assert len(attempts) == 2


def test_disconnected_no_track_and_empty_search_fail_truthfully(music, monkeypatch):
    monkeypatch.setattr(auth, "is_connected", lambda: False)
    assert not say("play something chill").success
    monkeypatch.setattr(auth, "is_connected", lambda: True)
    monkeypatch.setattr(player, "_api", lambda *a, **kw: {})
    assert not say("more songs like this").success
    monkeypatch.setattr(player, "_search", lambda *a, **kw: {"track": []})
    assert not say("play something chill").success


def test_storage_failure_after_playback_does_not_claim_playback_failed(music, monkeypatch):
    starts, _ = music
    def fail(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(dj.settings_store, "save", fail)
    result = say("play something chill")
    assert result.success and "couldn't save" in result.message and len(starts) == 1
    assert not say("for chill music use my Evening Walk playlist").success


def test_malformed_preferences_and_unknown_actions_cannot_play(music, monkeypatch):
    import json
    starts, _ = music
    assert dj.run({"action": "dj_unrecognized", "mood": "chill"}, lambda: None)[0] is False
    path = dj.config.MEMORY_DIR / "spotify_dj.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"preferences": {"chill": None}}), encoding="utf-8")
    assert not say("show my DJ preferences").success
    assert not say("play something chill").success and not starts
