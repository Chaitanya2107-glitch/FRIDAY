"""
services/automation/app_commands.py

Local matchers for opening things (apps, websites, folders, Chrome and YouTube
searches, organising folders) and for music (play, pause, next, "play <song>",
shuffle, playlists, liked songs, queue). The words it accepts live in
services/automation/command_words.py.

Targets must be named exactly (after dropping "the", "my", "app", "folder"…),
so "open chrome" runs here but "open chrome so I can check mail" goes to the AI.
Apps that aren't listed are looked up with Everything (app_finder.py).
"""

import re
from urllib.parse import quote

from services.automation import app_finder, command_words as words
from services.automation.command_words import FOLDER_MAP, first_word, normalize_command
from services.automation.system_control import system

URL_PATTERN = re.compile(r'\b(?:https?://)?(?:www\.)?[\w.-]+\.\w{2,}(?:/\S*)?\b')
# A bare message is only treated as an address with a common web ending, so "config.py" isn't one
WEB_ENDING = re.compile(r"^(?:https?://)|\.(?:com|org|net|io|dev|ai|in|co|app|gov|edu|me|tv|gg|xyz)(?:/|$)")

# The caller only runs this matcher for messages starting with one of these.
APP_STARTERS = {
    verb.split()[0]
    for verb in words.OPEN_VERBS + words.URL_VERBS + words.SEARCH_VERBS + words.ORGANISE_VERBS
} | {"play", "put", "turn", "youtube"}

_SEARCH_PREFIX = re.compile(rf"^(?:(?:on|in|with|using)\s+{words.SEARCH_ENGINE_WORDS}\s+)?(?:for\s+)?")
_SEARCH_SUFFIX = re.compile(rf"\s+(?:(?:on|in|with|using)\s+{words.SEARCH_ENGINE_WORDS}|online)$")


def _action(action: str, **arguments) -> dict:
    return {"type": "system", "action": action, **arguments}


def _find_folder(msg: str) -> str | None:
    """The first folder named anywhere in the message, e.g. "sort out my downloads"."""
    names = sorted(set(FOLDER_MAP) | set(words.FOLDER_ALIASES), key=len, reverse=True)
    match = re.search(rf"\b(?:{'|'.join(map(re.escape, names))})\b", msg)
    return words.resolve_folder(match.group()) if match else None


def _organise_command(msg: str) -> dict | None:
    verbs = "|".join(map(re.escape, words.ORGANISE_VERBS))
    if not re.search(rf"\b(?:{verbs})\b", msg):
        return None
    folder = _find_folder(msg)
    return _action("organise_folder", path=FOLDER_MAP[folder]) if folder else None


def _open_command(msg: str) -> dict | None:
    rest = words.strip_verb(msg, words.OPEN_VERBS + words.URL_VERBS)
    if not rest:
        return None
    target = words.clean_target(rest)

    app_name = words.resolve_app(target, system.list_apps())
    if app_name:
        return _action("open_app", app_name=app_name)
    folder = words.resolve_folder(target)
    if folder:
        return _action("open_folder", path=FOLDER_MAP[folder])
    site = words.resolve_site(target)
    if site:
        return _action("open_url", url=site)
    if URL_PATTERN.fullmatch(rest):
        return _action("open_url", url=rest)
    if app_finder.find_app(target):  # an installed app that isn't listed ("open arduino")
        return _action("open_app", app_name=target)
    return None


def _search_command(msg: str) -> dict | None:
    if msg.startswith(words.NOT_A_SEARCH):
        return None
    rest = words.strip_verb(msg, words.SEARCH_VERBS)
    if not rest:
        return None
    query = _SEARCH_SUFFIX.sub("", _SEARCH_PREFIX.sub("", rest, count=1)).strip()
    return _action("search_chrome", query=query) if query else None


def _youtube_command(msg: str) -> dict | None:
    for pattern in words.YOUTUBE_SEARCH:
        match = pattern.match(msg)
        if match:
            query = match.group("query").strip()
            return _action("open_url", url=f"https://www.youtube.com/results?search_query={quote(query)}")
    return None


def match_app_command(message: str) -> dict | None:
    msg = normalize_command(message).lower()
    if not msg or first_word(msg) not in APP_STARTERS:
        return None

    return (
        _youtube_command(msg)
        or _organise_command(msg)
        or _open_command(msg)
        or _search_command(msg)
    )


def match_media_command(message: str, has_player) -> dict | None:
    """
    Music commands. has_player() is only called for short words like "next" or
    "back", which are only music commands while a player is open.
    """
    from services.spotify.dj import match_command as match_dj
    if dj := match_dj(message):
        return dj
    full = normalize_command(message).lower()
    if words.PLAY_MUSIC.match(full):
        return _action("play_music")
    if words.SPOTIFY_CONNECT.match(full):
        return _action("connect_spotify")
    if words.SPOTIFY_DISCONNECT.match(full):
        return _action("disconnect_spotify")
    if _youtube_command(full):
        return None  # "play despacito on youtube" is a YouTube search

    msg = words.MEDIA_SUFFIX.sub("", full)
    if not msg:
        return None

    for action, phrases in words.MEDIA_PHRASES.items():
        if msg in phrases:
            if msg in words.MEDIA_NEEDS_PLAYER and not has_player():
                return None
            return _action(action)

    # General command cleanup treats "now" and "friday" as filler. In a
    # named music request they may be part of the title, so strip wake words
    # and explicit politeness only before extracting a name.
    named = message.strip().replace("\u2019", "'")
    previous = None
    while named != previous:
        previous = named
        named = words._LEADING.sub("", named, count=1)
        named = re.sub(r"\s+(?:please|pls|plz|for me|thanks|thank you)[.!?]*$", "", named, flags=re.I)
    named = named.lower()
    if named.startswith("put ") and not named.startswith("put on ") and words.MEDIA_SUFFIX.search(named):
        named = "put on " + named[4:]
    spotify_match = _spotify_command(words.MEDIA_SUFFIX.sub("", named)) or _spotify_command(msg)
    if spotify_match:
        return spotify_match

    song = words.PLAY_SONG.match(named)
    if song and not words.NOT_A_SONG.match(song.group("query")):
        if _UNNAMED_MUSIC.fullmatch(song.group("query")) or re.fullmatch(
            r"(?:songs|music|tracks)\s+(?:by|from|of)(?:\s+(?:the\s+)?artist)?", song.group("query")
        ):
            return None
        return _action("play_song", query=song.group("query"))
    return None


_SPOTIFY_ARGUMENT = {"set_shuffle": "on", "set_repeat": "mode", "like_song": "like"}
_COLLECTION_VERB = r"(?P<verb>play|shuffle|put on|start(?: playing)?|listen to)\s+"
_COLLECTION_PATTERNS = (
    ("playlist", re.compile(
        rf"^{_COLLECTION_VERB}(?:my\s+|the\s+)?(?:playlist(?:\s+(?:named|called))?\s+(?P<name>.+)|(?P<name2>.+?)\s+playlist)$")),
    ("album", re.compile(
        rf"^{_COLLECTION_VERB}(?:my\s+|the\s+)?(?:album(?:\s+(?:named|called))?\s+(?P<name>.+)|(?P<name2>.+?)\s+album)$")),
    ("artist", re.compile(
        rf"^{_COLLECTION_VERB}(?:(?:some\s+)?(?:songs|music|tracks)\s+(?:by|from|of)\s+(?:(?:the\s+)?artist\s+)?"
        r"|(?:the\s+)?artist(?:\s+(?:named|called))?\s+)(?P<name>.+)$")),
)
_QUEUE_PATTERNS = (
    re.compile(r"^(?:add|put)\s+(.+?)\s+(?:(?:to|in|on)\s+(?:the\s+|my\s+)?(?:play\s+)?queue|to play next|on next|after the current (?:song|track))$"),
    re.compile(r"^(?:enqueue|queue(?:\s+up)?)\s+(.+)$"),
    re.compile(r"^play\s+(.+?)\s+(?:next|after\s+this(?:\s+(?:song|track))?)$"),
)
_UNNAMED_MUSIC = re.compile(
    r"^(?:(?:the|my|this|that)\s+)?(?:song|track|album|artist|playlist|music|songs|tracks)$"
    r"|^(?:this|that|it|named|called)$"
)


def _spotify_command(msg: str) -> dict | None:
    """Shuffle, repeat, like, queue, and playing liked songs, playlists, albums and artists."""
    for (action, value), phrases in words.SPOTIFY_PHRASES.items():
        if msg in phrases:
            return _action(action, **{_SPOTIFY_ARGUMENT[action]: value})

    # Move only command grammar; names such as "On and On" stay intact.
    if put := re.fullmatch(r"put\s+(?!on\s)(.+)\s+on", msg):
        msg = "put on " + put.group(1)
    msg = re.sub(r"^start playing\s+", "play ", msg)

    for pattern in _QUEUE_PATTERNS:
        if match := pattern.fullmatch(msg):
            query = re.sub(r"^(?:the\s+)?(?:song|track)\s+", "", match.group(1)).strip()
            if not re.fullmatch(r"(?:(?:the|this|that)\s+)?(?:song|track)|this|that|it", query):
                return _action("queue_song", query=query)
            return None

    if match := words.PLAY_LIKED.match(msg):
        return _action("play_liked", shuffle=(match.group("verb") or match.group("verb2")) == "shuffle")
    for kind, pattern in _COLLECTION_PATTERNS:
        if match := pattern.match(msg):
            name = next(g for g in (match.groupdict().get("name"), match.groupdict().get("name2")) if g)
            if name in {"this", "that", "it", "named", "called"} or (kind == "artist" and name in {"artist", "the artist"}):
                return None
            return _action("play_collection", kind=kind, query=name.strip(),
                           shuffle=match.group("verb") == "shuffle")
    return None


def match_bare_url(message: str) -> dict | None:
    """A message that is only a web address: "youtube.com"."""
    msg = normalize_command(message).lower()
    if " " not in msg and URL_PATTERN.fullmatch(msg) and WEB_ENDING.search(msg):
        return _action("open_url", url=msg)
    return None
