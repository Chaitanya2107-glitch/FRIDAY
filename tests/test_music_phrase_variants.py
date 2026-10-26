"""Natural music phrasing keeps collection names and queue intent intact."""
import asyncio

import pytest

from core.config import config
from services.automation import intent
from services.automation.app_commands import match_app_command, match_media_command


@pytest.mark.parametrize("name", ["Night Drive", "On and On", "Don't Stop Me Now", "AC/DC", "Blue Friday"])
@pytest.mark.parametrize("template,kind,shuffle", [
    ("put playlist {name} on", "playlist", False),
    ("put my {name} playlist on", "playlist", False),
    ("start playing the playlist {name}", "playlist", False),
    ("listen to the playlist named {name}", "playlist", False),
    ("shuffle the playlist called {name}", "playlist", True),
    ("put the album {name} on", "album", False),
    ("start playing the album named {name}", "album", False),
    ("listen to the album called {name}", "album", False),
    ("shuffle songs from artist {name}", "artist", True),
    ("play music from artist {name}", "artist", False),
    ("put on music by the artist {name}", "artist", False),
    ("listen to tracks by artist {name}", "artist", False),
    ("start playing songs by {name}", "artist", False),
])
def test_collection_variants_keep_named_targets(name, template, kind, shuffle):
    assert match_media_command(template.format(name=name), lambda: False) == {
        "type": "system", "action": "play_collection", "kind": kind,
        "query": name.lower(), "shuffle": shuffle,
    }


@pytest.mark.parametrize("template", [
    "add track {name} to play next", "put the song {name} on next",
    "add the song {name} to the queue", "queue the track {name}",
    "play track {name} after this song", "enqueue {name}",
    "add {name} to my play queue", "put {name} after the current track",
])
@pytest.mark.parametrize("name", ["Believer", "On and On by Erykah Badu", "Don't Stop Me Now", "Music"])
def test_queue_variants_keep_track_names(template, name):
    assert match_media_command(template.format(name=name), lambda: True) == {
        "type": "system", "action": "queue_song", "query": name.lower(),
    }


@pytest.mark.parametrize("template,shuffle", [
    ("put my liked songs on", False), ("start playing my saved tracks", False),
    ("listen to my favorite songs", False), ("shuffle my liked tracks", True),
])
def test_liked_song_variants(template, shuffle):
    assert match_media_command(template, lambda: False) == {
        "type": "system", "action": "play_liked", "shuffle": shuffle,
    }


def test_album_artist_qualifier_remains_in_search_query():
    assert match_media_command("put the album Divide by Ed Sheeran on Spotify", lambda: False) == {
        "type": "system", "action": "play_collection", "kind": "album",
        "query": "divide by ed sheeran", "shuffle": False,
    }


@pytest.mark.parametrize("name", ["Don't Stop Me Now", "Blue Friday", "Music", "Help!"])
def test_wake_words_and_politeness_do_not_truncate_album_titles(name):
    assert match_media_command(f"Hey Friday, could you put the album {name} on please", lambda: False) == {
        "type": "system", "action": "play_collection", "kind": "album",
        "query": name.lower(), "shuffle": False,
    }


@pytest.mark.parametrize("name", ["Don't Stop Me Now", "Blue Friday", "Help!"])
@pytest.mark.parametrize("template", ["play the song {name}", "listen to the song {name}"])
def test_song_titles_keep_literal_trailing_words(template, name):
    assert match_media_command(template.format(name=name), lambda: False) == {
        "type": "system", "action": "play_song", "query": name.lower(),
    }


@pytest.mark.parametrize("message", [
    "don't put playlist Night Drive on", "do not add track Believer to play next",
    "I want to know how to queue Believer", "put playlist on", "play playlist",
    "play music from artist", "add track to play next", "queue the song",
    "enqueue", "put this playlist on", "start playing that album",
])
def test_incomplete_or_noncommand_requests_do_not_guess_targets(message):
    assert match_media_command(message, lambda: True) is None


@pytest.mark.parametrize("message", ["play next", "next song", "play the next song"])
def test_next_controls_are_not_queue_requests(message):
    assert match_media_command(message, lambda: True) == {"type": "system", "action": "media_next"}


def test_short_next_still_needs_a_player():
    assert match_media_command("next", lambda: False) is None


def test_youtube_keeps_its_original_router():
    message = "play playlist Night Drive on youtube"
    assert match_media_command(message, lambda: True) is None
    assert match_app_command(message) == {
        "type": "system", "action": "open_url",
        "url": "https://www.youtube.com/results?search_query=playlist%20night%20drive",
    }


@pytest.mark.parametrize("name", ["Don't Stop Me Now", "Blue Friday", "Help!"])
def test_named_album_reaches_spotify_without_losing_title_words(monkeypatch, name):
    played = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.spotify_auth, "is_connected", lambda: True)
    monkeypatch.setattr(intent.spotify, "play_named", lambda kind, query, open_player, shuffle:
                        played.append((kind, query, shuffle)) or "Playing it.")
    result = asyncio.run(intent.try_system_action(f"put the album {name} on", "openrouter"))
    assert result.success
    assert played == [("album", name.lower(), False)]


@pytest.mark.parametrize("name", ["Don't Stop Me Now", "Blue Friday", "Help!"])
def test_named_song_reaches_spotify_without_losing_title_words(monkeypatch, name):
    played = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.spotify_auth, "is_connected", lambda: True)
    monkeypatch.setattr(intent.spotify, "play_search", lambda query, open_player:
                        played.append(query) or "Playing it.")
    result = asyncio.run(intent.try_system_action(f"play the song {name}", "openrouter"))
    assert result.success
    assert played == [name.lower()]


@pytest.mark.parametrize("command,kind,name", [
    ("play album On and On", "album", "on and on"),
    ("shuffle playlist Rock and Roll", "playlist", "rock and roll"),
])
def test_collection_title_conjunctions_stay_intact_in_batches(monkeypatch, command, kind, name):
    executed = []
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent, "_execute", lambda parsed:
                        executed.append(parsed) or intent.ActionResult(True, "Done."))
    result = asyncio.run(intent.try_system_action(f"{command} then mute", "openrouter"))
    assert result.success
    assert executed[0] == {"type": "system", "action": "play_collection", "kind": kind,
                           "query": name, "shuffle": command.startswith("shuffle")}
    assert [item["action"] for item in executed] == ["play_collection", "set_mute"]
