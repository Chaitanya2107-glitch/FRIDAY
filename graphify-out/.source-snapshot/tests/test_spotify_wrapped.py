import asyncio
import json
import time

import pytest

from services.automation import intent
from services.spotify import auth, player, wrapped


@pytest.mark.parametrize("text, span, kind", [
    ("my spotify wrapped", "short_term", "both"),
    ("show my spotify wrapped this semester", "medium_term", "both"),
    ("who are my top artists of all time", "long_term", "artists"),
    ("what are my top songs", "short_term", "tracks"),
])
def test_wrapped_commands(text, span, kind):
    assert wrapped.match_wrapped_command(text) == {"type": "system", "action": "spotify_wrapped", "span": span, "kind": kind}


def _login(scope):
    auth.TOKEN_PATH.write_text(json.dumps({"access_token": "a", "refresh_token": "r",
                                           "expires_at": time.time() + 3600, "scope": scope}))


def test_wrapped_from_spotifys_top_lists(monkeypatch):
    monkeypatch.setattr(auth.config, "SPOTIFY_CLIENT_ID", "id")
    _login(auth.SCOPES)
    asked = []

    def api(method, path, params=None, json=None):
        asked.append((path, params["time_range"]))
        if path.endswith("artists"):
            return {"items": [{"name": "Pritam"}, {"name": "Arijit Singh"}]}
        return {"items": [{"name": "Tu Chahiye", "artists": [{"name": "Pritam"}]}]}
    monkeypatch.setattr(player, "_api", api)
    reply = asyncio.run(intent.try_system_action("my spotify wrapped this semester", "openai"))
    assert reply.message == ("Your Spotify, the last 6 months. Top artists: Pritam, Arijit Singh. "
                             "Top songs: Tu Chahiye — Pritam.")
    assert asked == [("/me/top/artists", "medium_term"), ("/me/top/tracks", "medium_term")]


def test_an_older_login_is_asked_to_connect_again(monkeypatch):
    monkeypatch.setattr(auth.config, "SPOTIFY_CLIENT_ID", "id")
    _login("user-read-playback-state")  # from before user-top-read was added
    reply = asyncio.run(intent.try_system_action("my spotify wrapped", "openai"))
    assert not reply.success and "connect Spotify" in reply.message
    opened = []
    monkeypatch.setattr(player.webbrowser, "open", opened.append)
    monkeypatch.setattr(auth, "start_login", lambda: "https://accounts.spotify.com/authorize?x")
    assert player.connect().startswith("Opened the Spotify login") and opened
