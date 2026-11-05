import asyncio
import base64
import hashlib
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from services.automation import intent, media_control as media
from services.automation.app_commands import match_media_command
from services.automation.intent import ActionResult, try_system_action
from services.spotify import auth, player
from services.spotify.auth import SpotifyError


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "SPOTIFY_CLIENT_ID", "client123")


@pytest.fixture
def connected(configured):
    auth._save({"access_token": "access1", "refresh_token": "refresh1", "expires_in": 3600})


# ── Recognising Spotify commands ──────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("shuffle", {"action": "set_shuffle", "on": True}),
    ("turn on shuffle please", {"action": "set_shuffle", "on": True}),
    ("turn off shuffle on spotify", {"action": "set_shuffle", "on": False}),
    ("repeat this song", {"action": "set_repeat", "mode": "track"}),
    ("repeat the playlist", {"action": "set_repeat", "mode": "context"}),
    ("stop repeating", {"action": "set_repeat", "mode": "off"}),
    ("like this song", {"action": "like_song", "like": True}),
    ("add this song to my liked songs", {"action": "like_song", "like": True}),
    ("unlike this song", {"action": "like_song", "like": False}),
    ("play my liked songs", {"action": "play_liked", "shuffle": False}),
    ("shuffle my favourite songs", {"action": "play_liked", "shuffle": True}),
    ("play my gym playlist", {"action": "play_collection", "kind": "playlist", "query": "gym", "shuffle": False}),
    ("shuffle the playlist chill vibes on spotify",
     {"action": "play_collection", "kind": "playlist", "query": "chill vibes", "shuffle": True}),
    ("play the album divide", {"action": "play_collection", "kind": "album", "query": "divide", "shuffle": False}),
    ("play songs by arijit singh",
     {"action": "play_collection", "kind": "artist", "query": "arijit singh", "shuffle": False}),
    ("add believer to the queue", {"action": "queue_song", "query": "believer"}),
    ("queue up kesariya by arijit singh", {"action": "queue_song", "query": "kesariya by arijit singh"}),
    ("play believer next", {"action": "queue_song", "query": "believer"}),
    ("connect spotify", {"action": "connect_spotify"}),
    ("hey friday, can you log in to my spotify account please", {"action": "connect_spotify"}),
    ("disconnect spotify", {"action": "disconnect_spotify"}),
    ("play some arijit singh", {"action": "play_song", "query": "arijit singh"}),
    ("play next", {"action": "media_next"}),  # still a skip, not a queue
])
def test_spotify_commands_are_recognised(message, expected):
    assert match_media_command(message, has_player=lambda: True) == {"type": "system", **expected}


@pytest.mark.parametrize("message", ["I like this song", "I love this song", "repeat after me: hello"])
def test_chat_is_not_a_spotify_command(message):
    match = match_media_command(message, has_player=lambda: True)
    assert match is None or match["action"] not in ("like_song", "set_repeat")


# ── Logging in ────────────────────────────────────────────────────────────────

def test_login_url_uses_pkce(configured):
    url = urlparse(auth.start_login())
    query = {key: values[0] for key, values in parse_qs(url.query).items()}

    assert url.netloc == "accounts.spotify.com"
    assert query["client_id"] == "client123"
    assert query["redirect_uri"] == f"http://127.0.0.1:{config.API_PORT}/api/v1/spotify/callback"
    assert query["code_challenge_method"] == "S256"
    verifier = auth._pending_login["verifier"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == expected
    assert query["state"] == auth._pending_login["state"]
    assert "user-modify-playback-state" in query["scope"]


def test_login_needs_a_client_id(monkeypatch):
    monkeypatch.setattr(config, "SPOTIFY_CLIENT_ID", "")
    with pytest.raises(SpotifyError, match="SPOTIFY_CLIENT_ID"):
        auth.start_login()


def _token_response(monkeypatch, sent, payload, status=200):
    def fake_post(url, data, timeout):
        sent.append(data)
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))
    monkeypatch.setattr(auth.httpx, "post", fake_post)


def test_finish_login_saves_the_tokens(configured, monkeypatch):
    sent = []
    _token_response(monkeypatch, sent, {"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    auth.start_login()
    state, verifier = auth._pending_login["state"], auth._pending_login["verifier"]

    auth.finish_login("the-code", state)

    assert sent[0]["code"] == "the-code" and sent[0]["code_verifier"] == verifier
    assert json.loads(auth.TOKEN_PATH.read_text())["refresh_token"] == "r"
    assert auth.is_connected()


def test_finish_login_rejects_a_login_friday_did_not_start(configured, monkeypatch):
    _token_response(monkeypatch, [], {})
    auth.start_login()
    with pytest.raises(SpotifyError, match="wasn't started by FRIDAY"):
        auth.finish_login("code", "someone-elses-state")
    assert not auth.is_connected()


def test_expired_token_is_refreshed_and_keeps_the_refresh_token(connected, monkeypatch):
    sent = []
    _token_response(monkeypatch, sent, {"access_token": "access2", "expires_in": 3600})
    token = json.loads(auth.TOKEN_PATH.read_text())
    auth.TOKEN_PATH.write_text(json.dumps({**token, "expires_at": time.time() - 1}))

    assert auth.access_token() == "access2"
    assert sent[0] == {"grant_type": "refresh_token", "refresh_token": "refresh1", "client_id": "client123"}
    assert json.loads(auth.TOKEN_PATH.read_text())["refresh_token"] == "refresh1"


def test_revoked_login_disconnects(connected, monkeypatch):
    _token_response(monkeypatch, [], {"error": "invalid_grant"}, status=400)
    with pytest.raises(SpotifyError, match="logged me out"):
        auth.access_token(force_refresh=True)
    assert not auth.is_connected()


def test_callback_page(configured, monkeypatch):
    _token_response(monkeypatch, [], {"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")

    auth.start_login()
    bad = client.get("/api/v1/spotify/callback", params={"code": "c", "state": "wrong"})
    assert bad.status_code == 400 and "wasn&#x27;t started by FRIDAY" in bad.text

    auth.start_login()
    good = client.get("/api/v1/spotify/callback", params={"code": "c", "state": auth._pending_login["state"]})
    assert good.status_code == 200 and "Spotify connected" in good.text
    assert client.get("/api/v1/spotify/status").json() == {"configured": True, "connected": True}

    denied = client.get("/api/v1/spotify/callback", params={"error": "access_denied"})
    assert denied.status_code == 400


# ── Talking to the API ────────────────────────────────────────────────────────

def _respond(monkeypatch, *responses):
    calls = []
    queue = list(responses)

    def fake_request(method, url, params=None, json=None, timeout=None, headers=None):
        calls.append((method, url, headers["Authorization"]))
        status, body = queue.pop(0)
        return httpx.Response(status, json=body, request=httpx.Request(method, url))
    monkeypatch.setattr(player.httpx, "request", fake_request)
    return calls


def test_no_active_device_error(connected, monkeypatch):
    _respond(monkeypatch, (404, {"error": {"status": 404, "message": "Player command failed: No active device found",
                                           "reason": "NO_ACTIVE_DEVICE"}}))
    with pytest.raises(player.NoDevice, match="Nothing is playing"):
        player.set_shuffle(True)


def test_premium_required_error(connected, monkeypatch):
    _respond(monkeypatch, (403, {"error": {"status": 403, "message": "Premium required", "reason": "PREMIUM_REQUIRED"}}))
    with pytest.raises(SpotifyError, match="Premium"):
        player.set_repeat("off")


def test_expired_access_token_is_retried_once(connected, monkeypatch):
    monkeypatch.setattr(auth, "_refresh", lambda token: {**token, "access_token": "fresh"})
    calls = _respond(monkeypatch, (401, {"error": {"status": 401, "message": "expired"}}), (204, None))
    assert player.set_shuffle(False) == "Shuffle is off."
    assert [c[2] for c in calls] == ["Bearer access1", "Bearer fresh"]


# ── Playing things ────────────────────────────────────────────────────────────

class FakeSpotify:
    """Stands in for player._api: canned answers per path, and a log of every call."""

    def __init__(self, devices=None, **answers):
        self.devices = devices if devices is not None else [{"id": "pc", "type": "Computer", "name": "LAPTOP"}]
        self.answers = answers
        self.calls = []

    def __call__(self, method, path, params=None, json=None):
        self.calls.append((method, path, params, json))
        if path == "/me/player/devices":
            return {"devices": self.devices}
        return self.answers.get(path, {})

    def sent(self, method, path):
        return [(params, json) for m, p, params, json in self.calls if (m, p) == (method, path)]


TRACK = {"name": "Believer", "uri": "spotify:track:1", "artists": [{"name": "Imagine Dragons"}],
         "album": {"uri": "spotify:album:9"}}


@pytest.fixture
def api(monkeypatch):
    def install(**kwargs):
        fake = FakeSpotify(**kwargs)
        monkeypatch.setattr(player, "_api", fake)
        monkeypatch.setattr(player, "minimize_spotify", lambda: fake.calls.append(("MINIMIZE", "", None, None)))
        return fake
    return install


def test_play_a_song_in_its_album(api):
    fake = api(**{"/search": {"tracks": {"items": [TRACK]}, "artists": {"items": [{"name": "Believers", "uri": "x"}]}}})

    assert player.play_search("believer", lambda: pytest.fail("Spotify is open")) == "Playing Believer by Imagine Dragons."
    assert fake.sent("PUT", "/me/player/play") == [
        ({"device_id": "pc"}, {"context_uri": "spotify:album:9", "offset": {"uri": "spotify:track:1"}})
    ]


def test_spotify_is_minimized_once_the_music_starts(api, monkeypatch):
    fake = api(**{"/search": {"tracks": {"items": [TRACK]}, "artists": {"items": []}}})
    monkeypatch.setattr(player.threading, "Thread", lambda target, **kw: SimpleNamespace(start=lambda: target()))
    player.play_search("believer", lambda: None)
    methods = [c[0] for c in fake.calls]
    assert methods.index("MINIMIZE") > methods.index("PUT")  # minimized after playback started


def test_minimize_waits_for_a_just_opened_spotify_window(monkeypatch):
    from services.automation import app_finder

    class Proc:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

    appear = iter([[], [], ["spotify window"]])  # the window shows up on the third look
    looks, minimized = [], []

    def windows(is_app):
        looks.append(1)
        found = next(appear)
        return found if all(is_app(Proc("Spotify.exe")) for _ in found) and not is_app(Proc("chrome.exe")) else []

    monkeypatch.setattr(app_finder, "app_windows", windows)
    monkeypatch.setattr(app_finder, "minimize_windows", minimized.extend)
    monkeypatch.setattr(player.time, "sleep", lambda s: None)
    player.minimize_spotify()
    assert minimized == ["spotify window"] and len(looks) == 3


def test_play_an_artist_by_exact_name(api):
    artist = {"name": "Arijit Singh", "uri": "spotify:artist:5"}
    fake = api(**{"/search": {"tracks": {"items": [TRACK]}, "artists": {"items": [artist]}}})
    assert player.play_search("arijit singh", lambda: None) == "Playing Arijit Singh."
    assert fake.sent("PUT", "/me/player/play")[0][1] == {"context_uri": "spotify:artist:5"}


def test_nothing_found(api):
    api(**{"/search": {"tracks": {"items": []}, "artists": {"items": []}}})
    with pytest.raises(SpotifyError, match="couldn't find \"zzzz\""):
        player.play_search("zzzz", lambda: None)


def test_active_device_wins_then_this_pc(api, monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "MYPC")
    api(devices=[{"id": "tv", "type": "TV"}, {"id": "other", "type": "Computer", "name": "WORK"},
                 {"id": "mine", "type": "Computer", "name": "MYPC"}])
    assert player._pick_device() == "mine"
    api(devices=[{"id": "phone", "type": "Smartphone", "is_active": True}, {"id": "mine", "type": "Computer"}])
    assert player._pick_device() == "phone"
    api(devices=[{"id": "phone", "type": "Smartphone"}])
    assert player._pick_device() is None  # never start music on another device by surprise


def test_opens_spotify_and_starts_when_it_shows_up(api, monkeypatch):
    fake = api(devices=[], **{"/search": {"tracks": {"items": [TRACK]}, "artists": {"items": []}}})
    opened, started = [], []
    monkeypatch.setattr(player.threading, "Thread",
                        lambda target, args=(), **kw: SimpleNamespace(start=lambda: started.append((target, args))))

    reply = player.play_search("believer", lambda: opened.append("spotify"))

    assert reply == "Opening Spotify — Believer by Imagine Dragons will start in a moment."
    assert opened == ["spotify"] and fake.sent("PUT", "/me/player/play") == []

    # The desktop app registers as a device a moment later
    monkeypatch.setattr(player.time, "sleep", lambda s: fake.devices.append({"id": "pc", "type": "Computer"}))
    target, args = started[0]
    target(*args)
    assert fake.sent("PUT", "/me/player/play")[0][0] == {"device_id": "pc"}
    minimize, _ = started[1]  # then Spotify's window is minimized
    minimize()
    assert fake.calls[-1][0] == "MINIMIZE"


def test_play_my_playlist_shuffled(api, monkeypatch):
    mine = {"name": "Gym 💪", "uri": "spotify:playlist:7", "items": {"total": 30}}
    fake = api(**{"/me/playlists": {"items": [{"name": "Chill", "uri": "c"}, mine], "next": None}})
    monkeypatch.setattr(player.random, "randrange", lambda n: 12)

    assert player.play_named("playlist", "gym", lambda: None, shuffle=True) == "Shuffling your Gym 💪 playlist."
    assert fake.sent("PUT", "/me/player/play")[0][1] == {"context_uri": "spotify:playlist:7", "offset": {"position": 12}}
    assert fake.sent("PUT", "/me/player/shuffle") == [({"state": "true", "device_id": "pc"}, None)]


def test_playlist_not_in_library_is_searched(api):
    fake = api(**{"/me/playlists": {"items": [], "next": None},
                  "/search": {"playlists": {"items": [None, {"name": "Lofi Beats", "uri": "spotify:playlist:3"}]}}})
    assert player.play_named("playlist", "lofi", lambda: None) == "Playing the playlist Lofi Beats."
    assert fake.sent("GET", "/search")[0][0]["type"] == "playlist"


def test_play_liked_songs(api):
    fake = api(**{"/me/tracks": {"items": [{"track": {"uri": "spotify:track:1"}}, {"track": {"uri": "spotify:track:2"}}],
                                 "next": None}})
    assert player.play_liked(lambda: None) == "Playing your liked songs."
    assert fake.sent("PUT", "/me/player/play")[0][1] == {"uris": ["spotify:track:1", "spotify:track:2"]}


def test_queue_needs_something_playing(api, monkeypatch):
    fake = api(**{"/search": {"tracks": {"items": [TRACK]}}})
    assert player.add_to_queue("believer") == "Added Believer by Imagine Dragons to the queue."
    assert fake.sent("POST", "/me/player/queue") == [({"uri": "spotify:track:1"}, None)]

    def no_device(method, path, params=None, json=None):
        if path == "/me/player/queue":
            raise player.NoDevice(player.NOTHING_PLAYING)
        return fake(method, path, params, json)
    monkeypatch.setattr(player, "_api", no_device)
    with pytest.raises(SpotifyError, match="Say \"play believer\" instead"):
        player.add_to_queue("believer")


def test_like_and_unlike_the_current_song(api):
    fake = api(**{"/me/player/currently-playing": {"item": TRACK, "currently_playing_type": "track"}})
    assert player.like_current() == "Added Believer by Imagine Dragons to your liked songs."
    assert player.like_current(False) == "Removed Believer by Imagine Dragons from your liked songs."
    assert fake.sent("PUT", "/me/library") == [({"uris": "spotify:track:1"}, None)]
    assert fake.sent("DELETE", "/me/library") == [({"uris": "spotify:track:1"}, None)]


def test_like_with_nothing_playing(api):
    api()
    with pytest.raises(SpotifyError, match="Nothing is playing"):
        player.like_current()


def test_connect_opens_the_browser_and_disconnect_forgets(configured, monkeypatch):
    opened = []
    monkeypatch.setattr(player.webbrowser, "open", opened.append)
    assert player.connect().startswith("Opened the Spotify login")
    assert opened[0].startswith(auth.AUTHORIZE_URL)

    auth._save({"access_token": "a", "refresh_token": "r", "scope": auth.SCOPES})  # Spotify says what was allowed
    assert "already connected" in player.connect()
    assert player.disconnect().startswith("Disconnected Spotify")
    assert not auth.is_connected()


# ── Through intent ────────────────────────────────────────────────────────────

def _run(message):
    return asyncio.run(try_system_action(message, "openrouter"))


def test_spotify_commands_explain_the_setup_first(monkeypatch):
    monkeypatch.setattr(config, "SPOTIFY_CLIENT_ID", "")
    result = _run("shuffle")
    assert not result.success and "SPOTIFY_CLIENT_ID" in result.message


def test_spotify_commands_ask_to_connect(configured):
    assert _run("repeat this song") == ActionResult(False, auth.NOT_CONNECTED)


def test_play_song_uses_spotify_when_connected(connected, monkeypatch):
    played = []
    monkeypatch.setattr(intent.spotify, "play_search", lambda query, open_player: played.append(query) or "Playing it.")
    assert _run("play dilbara by pritam") == ActionResult(True, "Playing it.", repeatable=False)
    assert played == ["dilbara by pritam"]


def test_playlist_without_spotify_login_opens_a_search(configured, monkeypatch):
    opened = []
    monkeypatch.setattr(intent.system, "list_apps", lambda: ["spotify"])
    monkeypatch.setattr(media.os, "startfile", opened.append)
    assert _run("play my gym playlist").success
    assert opened == ["spotify:search:gym"]


def test_ai_tool_call_for_spotify_runs(connected, monkeypatch):
    monkeypatch.setattr(intent.spotify, "set_shuffle", lambda on: f"Shuffle is {'on' if on else 'off'}.")
    assert intent._execute({"type": "system", "action": "set_shuffle", "on": "false"}) == ActionResult(
        True, "Shuffle is off."
    )
