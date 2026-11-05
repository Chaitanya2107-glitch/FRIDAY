"""Conversational mood mixes and artist-based queue building using supported APIs."""

import json
import re

from core.config import config
from services import settings_store
from services.spotify import auth, player
from services.spotify.auth import SpotifyError

MOODS = {"chill": "chill relaxing", "focus": "instrumental focus", "energetic": "energetic upbeat",
         "happy": "happy feel good", "sleep": "peaceful sleep"}
ALIASES = {"relaxed": "chill", "relaxing": "chill", "calm": "chill", "mellow": "chill",
           "study": "focus", "work": "focus", "hype": "energetic", "workout": "energetic",
           "upbeat": "energetic", "sleepy": "sleep"}
MOOD_WORDS = "|".join((*MOODS, *ALIASES))
ACTIONS = {"dj_mood", "dj_more", "dj_save", "dj_preferences", "dj_forget"}


def _mood(word):
    return ALIASES.get(word.lower(), word.lower())


def match_command(message):
    text = " ".join(message.replace("’", "'").split()).strip(" .!?")
    text = re.sub(r"^(?:hey )?friday[, ]+", "", text, flags=re.I)
    text = re.sub(r"\s+please$", "", text, flags=re.I)
    if re.fullmatch(r"(?:show|list)(?: my)? (?:dj|music mood) preferences", text, re.I):
        return {"type": "system", "action": "dj_preferences"}
    if found := re.fullmatch(rf"for ({MOOD_WORDS}) music use (?:my )?(.+?) playlist", text, re.I):
        return {"type": "system", "action": "dj_save", "mood": _mood(found[1]), "kind": "playlist", "value": found[2]}
    if found := re.fullmatch(rf"for ({MOOD_WORDS}) music (?:search for|use songs matching) (.+)", text, re.I):
        return {"type": "system", "action": "dj_save", "mood": _mood(found[1]), "kind": "query", "value": found[2]}
    if found := re.fullmatch(rf"forget (?:my )?({MOOD_WORDS}) (?:music |dj )?preference", text, re.I):
        return {"type": "system", "action": "dj_forget", "mood": _mood(found[1])}
    if re.fullmatch(r"(?:(?:play|queue|add) (?:some )?more (?:songs |music |tracks )?like (?:this|that)(?: song)?"
                    r"|more (?:songs|music|tracks) like (?:this|that)(?: song)?)", text, re.I):
        return {"type": "system", "action": "dj_more"}
    if re.fullmatch(r"(?:switch|change) (?:the |my )?(?:music )?mood", text, re.I):
        return {"type": "system", "action": "dj_mood", "mood": "next"}
    patterns = (
        rf"(?:play|put on|give me|start) (?:some|something) ({MOOD_WORDS})(?: music| songs| tracks| mix| mood)?",
        rf"(?:play|put on|give me|start) (?:a )?({MOOD_WORDS})(?: music| songs| tracks| mix| mood)",
        rf"(?:switch|change)(?: the mood)? to (?:a )?({MOOD_WORDS})(?: music| songs| tracks| mix| mood)?",
    )
    for pattern in patterns:
        if found := re.fullmatch(pattern + r"(?: on spotify)?", text, re.I):
            return {"type": "system", "action": "dj_mood", "mood": _mood(found[1])}
    return None


@settings_store.synchronized
def _load():
    try:
        data = json.loads((config.MEMORY_DIR / "spotify_dj.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"preferences": {}}
    except (ValueError, OSError) as error:
        raise SpotifyError("Couldn't read your DJ preferences.") from error
    if not isinstance(data, dict) or not isinstance(data.get("preferences", {}), dict):
        raise SpotifyError("Your DJ preferences file is invalid.")
    for mood, value in data.get("preferences", {}).items():
        if (mood not in MOODS or not isinstance(value, dict) or value.get("kind") not in ("playlist", "query")
                or not isinstance(value.get("value"), str) or not 1 <= len(value["value"].strip()) <= 160
                or "\x00" in value["value"]):
            raise SpotifyError("A saved DJ preference is invalid. Check spotify_dj.json.")
    return data


@settings_store.synchronized
def _update(mood, preference=None, *, forget=False, last=False):
    data = _load()
    if last:
        data["last_requested_mood"] = mood
    elif forget:
        data.setdefault("preferences", {}).pop(mood, None)
    else:
        data.setdefault("preferences", {})[mood] = preference
    settings_store.save(config.MEMORY_DIR / "spotify_dj.json", data)


def _tracks(items, excluded=()):
    seen, found = set(excluded), []
    for item in items:
        if not isinstance(item, dict) or item.get("is_local") or item.get("is_playable") is False:
            continue
        uri = item.get("uri", "")
        if isinstance(uri, str) and re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", uri) and uri not in seen:
            seen.add(uri)
            found.append(item)
    return found


def _play(mood, open_player):
    data = _load()
    if mood == "next":
        order = list(MOODS)
        previous = data.get("last_requested_mood")
        mood = order[(order.index(previous) + 1) % len(order)] if previous in order else "chill"
    if mood not in MOODS:
        raise SpotifyError("Choose chill, focus, energetic, happy or sleep music.")
    preference = data.get("preferences", {}).get(mood)
    if preference and (not isinstance(preference, dict) or preference.get("kind") not in ("playlist", "query")
                       or not isinstance(preference.get("value"), str) or not preference["value"].strip()):
        raise SpotifyError("That saved DJ preference is invalid. Save it again or forget it.")
    playlist = None
    if not preference or preference["kind"] == "playlist":
        playlist = player._find_my_playlist(preference["value"] if preference else mood)
        if preference and not playlist:
            raise SpotifyError("I couldn't find your saved mood playlist. Update the preference or choose another mood.")
    if playlist and not re.fullmatch(r"spotify:playlist:[A-Za-z0-9]{22}", playlist.get("uri", "")):
        raise SpotifyError("Spotify returned an invalid playlist. No music was started.")
    if playlist:
        message = player._start({"context_uri": playlist["uri"]}, f"your {mood} playlist", open_player)
    else:
        query = preference["value"] if preference else MOODS[mood]
        tracks = _tracks(player._search(query, "track", limit=10).get("track", []))[:8]
        if not tracks:
            raise SpotifyError("No playable tracks found for that mood. Try saving a playlist preference.")
        message = player._start({"uris": [track["uri"] for track in tracks]}, f"a {mood} mix", open_player)
    try:
        _update(mood, last=True)
    except OSError:
        return True, message + " I couldn't save the last mood; your music request was already submitted."
    return True, message


def _more():
    playing = player._api("GET", "/me/player/currently-playing")
    current = playing.get("item") or {}
    artists = current.get("artists") or []
    if playing.get("currently_playing_type", "track") != "track" or not artists or not artists[0].get("name"):
        raise SpotifyError("Play a Spotify track first, then ask for more songs like this.")
    artist = artists[0]
    name = artist["name"]
    candidates = player._search('artist:"' + name.replace('"', ' ') + '"', "track", limit=10).get("track", [])
    candidates = [track for track in _tracks(candidates, [current.get("uri")]) if any(
        (other.get("id") == artist["id"] if artist.get("id") else other.get("name", "").casefold() == name.casefold())
        for other in track.get("artists", []) if isinstance(other, dict))][:5]
    if not candidates:
        raise SpotifyError(f"No additional playable tracks found from {name}.")
    added = 0
    for track in candidates:
        try:
            player._api("POST", "/me/player/queue", params={"uri": track["uri"]})
        except SpotifyError as error:
            return False, f"Queued {added} confirmed tracks from {name}, then stopped; the last addition wasn't confirmed: {error}"
        added += 1
    return True, f"Queued {added} more tracks from {name}."


def run(parsed, open_player):
    try:
        action, mood = parsed["action"], parsed.get("mood")
        if action not in ACTIONS:
            return False, "Unknown DJ command. No music was changed."
        if action == "dj_preferences":
            preferences = _load().get("preferences", {})
            return True, "DJ preferences:\n" + ("\n".join(
                f"{key}: {value['kind']} — {value['value']}" for key, value in preferences.items()) or "None saved yet.")
        if action in ("dj_save", "dj_forget"):
            if mood not in MOODS:
                raise SpotifyError("Choose a supported music mood.")
            if action == "dj_forget":
                _update(mood, forget=True)
                return True, f"Forgot your {mood} music preference."
            kind, value = parsed.get("kind"), parsed.get("value", "").strip()
            if kind not in ("playlist", "query") or not 1 <= len(value) <= 160 or "\x00" in value:
                raise SpotifyError("Give me a playlist name or search phrase up to 160 characters.")
            _update(mood, {"kind": kind, "value": value})
            return True, f"Saved your {mood} music preference: {kind} {value}."
        if not auth.is_connected():
            raise SpotifyError("Connect Spotify first. DJ playback needs your connected Spotify account and Premium playback.")
        return _more() if action == "dj_more" else _play(mood, open_player)
    except SpotifyError as error:
        return False, str(error)
    except OSError:
        return False, "Couldn't save your DJ preference. The update wasn't confirmed."
