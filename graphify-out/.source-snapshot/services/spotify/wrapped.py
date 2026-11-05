"""
services/spotify/wrapped.py

"My Spotify wrapped" any time, from Spotify's own top lists (they count listening in the
background too, which the activity log can't see):
  "my spotify wrapped" / "…this month"  → last ~4 weeks
  "…this semester" / "…6 months"          → last ~6 months
  "…all time" / "…this year"              → several years (Spotify's longest range)
  "who are my top artists", "what are my top songs"
Needs the user-top-read permission: an older login gets "say connect Spotify" once.
"""

import re

from services.spotify import auth, player
from services.spotify.auth import SpotifyError

WRAPPED_ACTION = "spotify_wrapped"
SHOWN = 5
RANGES = {"short_term": "the last 4 weeks", "medium_term": "the last 6 months", "long_term": "all time"}

_WRAPPED = re.compile(r"^(?:(?:show |give me |what'?s )?(?:my )?spotify wrapped|(?:who are|what are|show)(?: me)? my top "
                      r"(?P<kind>artists|songs|tracks)(?: on spotify)?)(?P<when>.*)$", re.I)


def match_wrapped_command(text: str) -> dict | None:
    m = _WRAPPED.match(text.strip().rstrip("?.!"))
    if not m:
        return None
    when = m["when"].lower()
    span = ("medium_term" if re.search(r"semester|6 months|six months|half", when)
            else "long_term" if re.search(r"all time|ever|year", when) else "short_term")
    kind = {"artists": "artists", "songs": "tracks", "tracks": "tracks"}.get((m["kind"] or "").lower(), "both")
    return {"type": "system", "action": WRAPPED_ACTION, "span": span, "kind": kind}


def _top(kind: str, span: str) -> list[dict]:
    return player._api("GET", f"/me/top/{kind}", params={"time_range": span, "limit": SHOWN}).get("items", [])


def wrapped(span: str = "short_term", kind: str = "both") -> str:
    if not auth.is_connected():
        raise SpotifyError("Spotify isn't connected. Say \"connect Spotify\" first.")
    if "user-top-read" in auth.missing_scopes():
        raise SpotifyError("For your top artists and songs, Spotify needs one more permission — "
                           "say \"connect Spotify\" and press Agree.")
    parts = []
    if kind in ("both", "artists"):
        artists = [a["name"] for a in _top("artists", span)]
        if artists:
            parts.append("Top artists: " + ", ".join(artists))
    if kind in ("both", "tracks"):
        tracks = [f"{t['name']} — {player._artist_names(t)}" for t in _top("tracks", span)]
        if tracks:
            parts.append("Top songs: " + "; ".join(tracks))
    if not parts:
        return f"Spotify doesn't have enough listening from {RANGES[span]} yet."
    return f"Your Spotify, {RANGES[span]}. " + ". ".join(parts) + "."
