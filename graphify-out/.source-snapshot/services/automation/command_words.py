"""
services/automation/command_words.py

Every word and phrase FRIDAY recognises as a command, in one place. The local
matchers (device_commands.py, app_commands.py) read these lists, so a command
worded with any of them runs straight away, without asking the AI.

TO TEACH FRIDAY A NEW WAY TO SAY SOMETHING: add it to the right list below.
Keep everything lowercase. Multi-word phrases are fine.

Anything these lists don't cover still reaches the AI (with native tool calling),
as long as it starts with a word in AI_COMMAND_STARTERS or asks for several
things at once.
"""

import re

COLLEGE_SCHEDULE_OPEN = {'open college schedules', 'open college schedule', 'show college schedules',
                         'college schedules', 'open my college schedules'}
COLLEGE_NEXT_FACULTY = {'who takes my next class', 'who teaches my next class',
                        'who is taking my next class', 'who is my next class faculty'}
COLLEGE_EVENTS_QUERY = {'show college events', 'list college events', 'upcoming college events',
                        'what are my upcoming college events', 'what are my upcoming events'}

from services.automation.command_phrases import PHRASE_ALIASES
from services.automation.spoken_numbers import normalize_command_numbers
from services.automation.task_phrases import rephrase_task_command

# ── Filler stripped before matching ───────────────────────────────────────────
# "hey friday, can you please open chrome for me?" → "open chrome"
LEADING_FILLER = (
    r"(?:hey|hi|hello|ok|okay|yo)\s+friday",
    r"friday",
    r"please", r"pls", r"plz", r"kindly", r"just", r"quickly", r"now",
    r"(?:can|could|would|will)\s+(?:you|u)",
    r"(?:can|could|would|will)\s+(?:you|u)\s+be\s+able\s+to",
    r"is\s+it\s+possible\s+for\s+you\s+to",
    r"i\s+was\s+wondering\s+if\s+you\s+(?:can|could|would)",
    r"(?:i\s+)?(?:want|need|wanna)\s+(?:you\s+)?to",
    r"i'?d\s+like\s+(?:you\s+)?to",
    r"go\s+ahead\s+and",
    r"let'?s",
)
TRAILING_FILLER = (
    r"please", r"pls", r"plz", r"for\s+me", r"right\s+now", r"now", r"asap",
    r"thanks", r"thank\s+you", r"real\s+quick", r"quickly",
    # her name, but not the day: "classes on friday", "due friday", "add class DBMS on friday …"
    "".join(rf"(?<!\b{w} )" for w in ("on", "by", "this", "next", "last", "every", "until", "till", "for",
                                      "from", "to", "due", "before", "after", "project", "resume", "continue")) + "friday",
)

# Dropped around a target: "open the chrome app" → "chrome"
TARGET_PREFIXES = ("the", "my", "a", "an", "this", "that", "up")
TARGET_SUFFIXES = (
    "app", "application", "program", "game", "browser", "window",
    "folder", "directory", "website", "site", "web site", "page", "homepage",
)

# ── Apps ──────────────────────────────────────────────────────────────────────
OPEN_VERBS = (
    "open", "open up", "launch", "start", "start up", "run", "execute", "load",
    "fire up", "boot up", "bring up", "pull up", "switch to",
    "pop open", "access",
    "show", "show me", "go to", "take me to", "head to", "get me",
)
CLOSE_VERBS = (
    "close", "quit", "exit", "kill", "terminate", "stop", "shut", "shut down",
    "end task", "force close", "force quit",
)
# Other names for apps in system_control.APP_REGISTRY (ignored if the app isn't registered)
APP_ALIASES = {
    "browser": "chrome", "web browser": "chrome", "google chrome browser": "chrome",
    "microsoft edge": "edge", "ms edge": "edge",
    "whats app": "whatsapp", "whatsapp desktop": "whatsapp",
    "calc": "calculator",
    "file explorer": "explorer", "windows explorer": "explorer", "files": "explorer",
    "notes": "notepad", "note pad": "notepad",
    "taskmanager": "task manager", "task mgr": "task manager",
    "system settings": "settings", "windows settings": "settings", "pc settings": "settings",
    "vbox": "virtualbox", "oracle virtualbox": "virtualbox",
    "expedition33": "expedition 33", "clair obscur": "expedition 33",
    "spotify music": "spotify",
}
# ── Music ─────────────────────────────────────────────────────────────────────
# Controls whatever player is open (services/automation/media_control.py).
# Matched as whole messages, after filler and a trailing "on spotify" are dropped.
MEDIA_PHRASES = {
    "media_play": (
        "play", "resume", "unpause", "play it", "resume it", "resume playing", "resume playback",
        "resume the music", "resume music", "resume the song", "continue playing",
        "continue the music", "keep playing", "start playing", "hit play", "press play",
        "carry on playing", "carry on with the music", "get the music going again",
    ),
    "media_pause": (
        "pause", "pause it", "pause music", "pause the music", "pause the song", "pause song",
        "pause playback", "stop the music", "stop music", "stop playing", "stop the song",
        "hit pause", "press pause", "hold the music",
        "put the music on hold", "put playback on hold", "pause the audio",
    ),
    "media_next": (
        "next", "next song", "next track", "next one", "play next", "play the next song",
        "skip", "skip it", "skip this", "skip song", "skip this song", "skip the song",
        "skip track", "skip this track", "skip to the next song", "change the song",
        "change song", "another song", "different song",
        "move to the next track", "move to the next song", "skip ahead a song",
    ),
    "media_previous": (
        "previous", "previous song", "previous track", "last song", "last track",
        "play previous", "play the previous song", "play the last song", "go back",
        "back", "go back a song", "go back a track", "replay", "replay the song",
        "restart the song", "restart song", "play that again", "play it again",
        "go back to the previous track", "go back to the previous song",
    ),
    "now_playing": (
        "what's playing", "whats playing", "what is playing", "now playing",
        "what song is this", "what's this song", "whats this song", "what is this song",
        "which song is this", "what song is playing", "what am i listening to",
        "who sings this", "who is singing", "what's the song", "song name",
    ),
}
# Short words that only mean music when a player is open ("next" could be chat)
MEDIA_NEEDS_PLAYER = {
    "next", "next one", "skip", "skip it", "skip this", "previous", "go back", "back",
    "replay", "play it again", "play that again",
}
MEDIA_SUFFIX = re.compile(r"\s+(?:(?:on|in)\s+(?:spotify|youtube|chrome|the player)|spotify)$")
# "play music" → resume the player, or open Spotify and start it
PLAY_MUSIC = re.compile(
    r"^(?:play|put on|start|turn on|listen to)\s+(?:some\s+|my\s+|the\s+)?(?:music|songs|tunes|spotify)$"
)
# "play dilbara by pritam" → plays it once Spotify is connected, otherwise opens a Spotify search
PLAY_SONG = re.compile(r"^(?:play|listen to)\s+(?:the\s+song\s+|song\s+|some\s+)?(?P<query>.+?)(?:\s+(?:on|in)\s+spotify)?$")
NOT_A_SONG = re.compile(
    r"^(?:a\s+game|games?\b|video\s+games?|chess|cards|with\b|along\b|around\b|a\s+joke|dead\b"
    r"|it\s+(?:cool|safe)|pretend|some\s+games?|a\s+trick|tricks)"
)

# ── Spotify ───────────────────────────────────────────────────────────────────
# Need a connected Spotify account (services/spotify/). Phrases are matched as
# whole messages, like MEDIA_PHRASES; the patterns run after them.
SPOTIFY_PHRASES = {
    ("set_shuffle", True): (
        "shuffle", "shuffle on", "turn on shuffle", "turn shuffle on", "enable shuffle",
        "shuffle it", "shuffle the music", "shuffle my music", "shuffle the songs",
        "shuffle songs", "start shuffling", "put it on shuffle", "put on shuffle",
    ),
    ("set_shuffle", False): (
        "shuffle off", "turn off shuffle", "turn shuffle off", "disable shuffle",
        "stop shuffling", "no shuffle", "unshuffle", "don't shuffle", "dont shuffle",
    ),
    ("set_repeat", "track"): (
        "repeat this song", "repeat the song", "repeat song", "repeat this track", "repeat one",
        "loop this song", "loop the song", "loop song", "put this on repeat",
        "put this song on repeat", "put the song on repeat", "on repeat",
    ),
    ("set_repeat", "context"): (
        "repeat", "repeat on", "turn on repeat", "turn repeat on", "repeat all",
        "repeat the playlist", "repeat this playlist", "repeat the album", "repeat this album",
        "loop the playlist", "loop this playlist", "loop the album", "loop this album",
    ),
    ("set_repeat", "off"): (
        "repeat off", "turn off repeat", "turn repeat off", "stop repeating", "no repeat",
        "disable repeat", "stop looping", "loop off", "don't repeat", "dont repeat",
    ),
    ("like_song", True): (
        "like this song", "like the song", "like this", "like this track", "like it",
        "save this song", "save the song", "save this track", "heart this song",
        "favorite this song", "favourite this song", "add this to my liked songs",
        "add this song to my liked songs", "add this song to liked songs",
        "add this to liked songs", "add the song to my liked songs",
    ),
    ("like_song", False): (
        "unlike this song", "unlike this", "unlike the song", "unsave this song",
        "remove this from my liked songs", "remove this song from my liked songs",
        "remove this from liked songs", "remove this song from liked songs",
    ),
}
# Matched on the whole message (before " spotify" is dropped from the end)
SPOTIFY_CONNECT = re.compile(
    r"^(?:connect|link|log\s*in|login|sign\s+in|set\s*up)\s+(?:(?:to|into|in\s+to)\s+)?(?:my\s+)?spotify"
    r"(?:\s+account)?$"
)
SPOTIFY_DISCONNECT = re.compile(
    r"^(?:disconnect|unlink|log\s*out|logout|sign\s+out)\s+(?:(?:of|from)\s+)?(?:my\s+)?spotify(?:\s+account)?$"
)
_PLAY_OR_SHUFFLE = r"(?P<verb>play|shuffle|put on|start|listen to)\s+"
# "play my liked songs", "shuffle my favourites"
PLAY_LIKED = re.compile(
    rf"^{_PLAY_OR_SHUFFLE}(?:my\s+|the\s+)?(?:liked|saved|favou?rite)(?:\s+(?:songs|tracks|music))?$"
    r"|^(?P<verb2>play|shuffle)\s+(?:my\s+)?likes$"
)
# "play my gym playlist", "shuffle the playlist chill vibes"
PLAY_PLAYLIST = re.compile(
    rf"^{_PLAY_OR_SHUFFLE}(?:my\s+|the\s+)?(?:playlist\s+(?P<name>.+)|(?P<name2>.+?)\s+playlist)$"
)
# "play the album divide", "play divide album"
PLAY_ALBUM = re.compile(
    rf"^{_PLAY_OR_SHUFFLE}(?:the\s+)?(?:album\s+(?P<name>.+)|(?P<name2>.+?)\s+album)$"
)
# "play songs by arijit singh", "play the artist pritam"
PLAY_ARTIST = re.compile(
    rf"^{_PLAY_OR_SHUFFLE}(?:(?:some\s+)?(?:songs|music|tracks)\s+(?:by|from|of)\s+|(?:the\s+)?artist\s+)(?P<name>.+)$"
)
# "add believer to the queue", "queue up believer", "play believer next"
QUEUE_SONG = re.compile(
    r"^(?:add|put)\s+(?P<query>.+?)\s+(?:to|in|on)\s+(?:the\s+|my\s+)?queue$"
    r"|^queue(?:\s+up)?\s+(?P<query2>.+)$"
    r"|^play\s+(?P<query3>.+?)\s+(?:next|after\s+this(?:\s+song)?)$"
)

# ── Your files (services/files/) ──────────────────────────────────────────────
# Finding files: FRIDAY lists them, no AI involved. "my" is what makes "find my
# resume" a file search; "find a good laptop" stays a Chrome search.
_FILE_PLACES = r"(?:files|documents|docs|computer|pc|laptop|drive|downloads|desktop|folders)"
FILE_FIND = (
    re.compile(r"^\\f\s+(?P<query>.+)$"),
    re.compile(
        r"^(?:find|locate|search\s+for|look\s+for|where(?:'s|s|\s+is|\s+are)|where\s+did\s+i\s+(?:save|put|keep))"
        r"\s+(?:all\s+)?my\s+(?P<query>.+)$"
    ),
    re.compile(
        rf"^(?:find|search|search\s+for|look\s+for|locate)\s+(?P<query>.+?)\s+(?:in|on|across|from)\s+"
        rf"(?:my\s+|the\s+)?{_FILE_PLACES}$"
    ),
    re.compile(rf"^(?:search|look\s+through|go\s+through|check)\s+my\s+{_FILE_PLACES}\s+(?:for|about)\s+(?P<query>.+)$"),
    re.compile(
        r"^(?:find|locate|search\s+for|look\s+for|get)\s+(?:me\s+)?(?:the\s+|a\s+|any\s+)?"
        r"(?:files?|documents?|docs?|pdfs?)\s+(?:about|called|named|on|with|containing|mentioning"
        r"|that\s+(?:mentions?|says?|has|talks\s+about))\s+(?P<query>.+)$"
    ),
    re.compile(
        r"^which\s+(?:of\s+my\s+)?(?:files?|documents?|docs?|pdfs?)\s+(?:has|have|mentions?|contains?"
        r"|talks?\s+about|is\s+about|are\s+about|says?)\s+(?P<query>.+)$"
    ),
)
# After a search: "open 2", "open the first one", "open it", "show 2 in folder"
_RESULT = (
    r"(?:file\s+|result\s+|number\s+|no\.?\s*)?(?P<n>\d+|it|that(?:\s+one)?|this(?:\s+one)?"
    r"|(?:the\s+)?(?:first|second|third|fourth|fifth|last|top)(?:\s+(?:one|file|result))?"
    r"|one|two|three|four|five)"
)
FILE_OPEN = re.compile(rf"^open\s+{_RESULT}$")
FILE_REVEAL = re.compile(
    rf"^(?:show|reveal|open)\s+(?:me\s+)?(?:where\s+)?{_RESULT}\s+(?:is\s+)?in\s+(?:the\s+)?(?:folder|explorer|file\s+explorer)$"
    rf"|^open\s+(?:the\s+)?folder\s+(?:of|for)\s+{_RESULT.replace('(?P<n>', '(?P<n2>')}$"
)
RESULT_NUMBERS = {
    "one": 1, "first": 1, "top": 1, "it": 1, "that": 1, "that one": 1, "this": 1, "this one": 1,
    "two": 2, "second": 2, "three": 3, "third": 3, "four": 4, "fourth": 4, "five": 5, "fifth": 5,
}
FILE_RESCAN = re.compile(
    r"^(?:re-?scan|re-?index|update|refresh)\s+(?:my\s+|the\s+)?(?:files|file\s+index|file\s+search|documents)$"
    r"|^(?:scan|index)\s+my\s+files(?:\s+again)?$"
)
# Answering from files: these go to the chat AI with excerpts from the files
FILE_QUESTION_PREFIX = (
    re.compile(r"^\\d\s+(?P<question>.+)$"),
    re.compile(r"^(?:ask|check)\s+my\s+(?:files|documents|docs|notes)\s*(?:[,:]|about|whether|if)?\s+(?P<question>.+)$"),
)
FILE_QUESTION_MENTION = re.compile(
    r"\b(?:in|from|according\s+to|based\s+on|using|inside|within|per)\s+(?:my|the)\s+"
    r"(?:own\s+)?(?:files|documents|docs|notes|pdfs|papers)\b"
    r"|\bmy\s+(?:files|documents|docs|notes|pdfs)\s+(?:say|said|mention|have|contain|talk)"
    r"|^what\s+do(?:es)?\s+my\s+[\w'-]+(?:\s+[\w'-]+)?\s+says?\b"  # "what does my lease say about pets"
)

# ── Websites ──────────────────────────────────────────────────────────────────
URL_VERBS = ("open", "go to", "visit", "navigate to", "browse to", "take me to", "head to", "load", "pull up")
SITES = {
    "youtube": "youtube.com", "yt": "youtube.com",
    "gmail": "mail.google.com", "google mail": "mail.google.com",
    "google": "google.com",
    "google maps": "maps.google.com", "maps": "maps.google.com",
    "google drive": "drive.google.com", "drive": "drive.google.com",
    "google docs": "docs.google.com",
    "google calendar": "calendar.google.com", "calendar": "calendar.google.com",
    "github": "github.com",
    "netflix": "netflix.com", "prime video": "primevideo.com", "twitch": "twitch.tv",
    "instagram": "instagram.com", "insta": "instagram.com",
    "facebook": "facebook.com", "twitter": "x.com",
    "reddit": "reddit.com", "linkedin": "linkedin.com",
    "whatsapp web": "web.whatsapp.com",
    "chatgpt": "chatgpt.com", "claude": "claude.ai",
    "wikipedia": "wikipedia.org", "stack overflow": "stackoverflow.com", "stackoverflow": "stackoverflow.com",
}

# ── Chrome search ─────────────────────────────────────────────────────────────
SEARCH_VERBS = (
    "search", "search for", "search up", "google", "google for", "google search",
    "look for", "find", "find me", "search google for",
)
NOT_A_SEARCH = ("find out",)  # "find out why the sky is blue" is a question
SEARCH_ENGINE_WORDS = r"(?:google|chrome|the web|the internet|online|the browser)"
# "search lofi beats on youtube", "youtube lofi beats"
YOUTUBE_SEARCH = (
    re.compile(r"^(?:search|find|look for|play)\s+(?:for\s+)?(?P<query>.+?)\s+(?:on|in)\s+youtube$"),
    re.compile(r"^(?:search\s+)?youtube\s+(?:for\s+)?(?P<query>.+)$"),
)

# ── Folders ───────────────────────────────────────────────────────────────────
FOLDER_MAP = {
    "downloads":  r"C:\Users\chait\Downloads",
    "documents":  r"C:\Users\chait\Documents",
    "pictures":   r"C:\Users\chait\Pictures",
    "photos":     r"C:\Users\chait\Pictures",
    "images":     r"C:\Users\chait\Pictures",
    "desktop":    r"C:\Users\chait\Desktop",
    "videos":     r"C:\Users\chait\Videos",
    "music":      r"C:\Users\chait\Music",
}
# Other names for the folders above
FOLDER_ALIASES = {
    "download": "downloads",
    "document": "documents", "docs": "documents", "my docs": "documents",
    "picture": "pictures", "photo": "pictures", "pics": "pictures", "image": "pictures",
    "video": "videos", "movies": "videos", "vids": "videos",
    "songs": "music",
}
ORGANISE_VERBS = (
    "organise", "organize", "sort", "sort out", "clean", "clean up", "tidy", "tidy up",
    "declutter", "arrange",
)

# ── Volume ────────────────────────────────────────────────────────────────────
VOLUME_NOUNS = {"volume", "sound", "audio", "speaker", "speakers"}
# Words that make a sentence a volume command even without a noun: "a bit louder"
VOLUME_ALONE_UP = {"louder"}
VOLUME_ALONE_DOWN = {"quieter", "softer"}
MUTE_WORDS = {"mute", "silence"}
UNMUTE_WORDS = {"unmute"}
# Words allowed after "mute": "mute the laptop sound", but not "mute button is broken"
MUTE_OBJECT_WORDS = {
    "the", "my", "this", "sound", "audio", "volume", "speaker", "speakers",
    "computer", "laptop", "pc", "system", "everything", "all", "it", "sounds",
}

# ── Brightness ────────────────────────────────────────────────────────────────
BRIGHTNESS_NOUNS = {"brightness"}
SCREEN_NOUNS = {"screen", "display", "monitor"}
BRIGHTNESS_UP = {"brighten", "brighter", "lighter"}
BRIGHTNESS_DOWN = {"dim", "dimmer", "darker", "darken"}

# ── Shared level words (volume and brightness) ────────────────────────────────
UP_WORDS = {"up", "increase", "raise", "higher", "boost", "crank", "pump", "more"} | VOLUME_ALONE_UP | BRIGHTNESS_UP
DOWN_WORDS = {"down", "decrease", "lower", "reduce", "drop", "less"} | VOLUME_ALONE_DOWN | BRIGHTNESS_DOWN
MAX_WORDS = {"max", "maximum", "full", "highest", "loudest", "brightest", "100"}
MIN_WORDS = {"min", "minimum", "lowest", "quietest", "darkest", "dimmest", "zero"}
HALF_WORDS = {"half", "halfway"}
BIG_STEP_WORDS = {"lot", "much", "way", "loads"}  # "a lot louder" = 30 instead of 10
DEFAULT_STEP = 10
BIG_STEP = 30
# "a bit louder" — these starters only ever mean a small step up or down
SOFTENERS = {"a", "bit", "little", "slightly"}
# First words that can start a volume/brightness command
LEVEL_STARTERS = {
    "set", "change", "adjust", "put", "make", "turn", "bring", "increase", "decrease",
    "raise", "lower", "reduce", "boost", "crank", "pump", "drop", "max", "full", "half",
} | SOFTENERS

# ── Screenshots ───────────────────────────────────────────────────────────────
SCREENSHOT_WORDS = {"screenshot", "screenshots", "screengrab", "screencap", "printscreen"}
SCREENSHOT_PHRASES = re.compile(
    r"\b(?:screen\s+shot|screen\s+grab|print\s+screen|"
    r"(?:capture|grab|snap|save)\s+(?:the\s+|my\s+|this\s+)?(?:whole\s+|entire\s+)?screen)\b"
)
SCREENSHOT_STARTERS = {"take", "screenshot", "capture", "grab", "snap", "get", "make", "print", "screen", "save"}

# ── Clipboard ─────────────────────────────────────────────────────────────────
CLIPBOARD_READ_STARTERS = {"read", "show", "check", "display", "print", "get", "paste"}
CLIPBOARD_READ_PHRASES = re.compile(
    r"^(?:what(?:'s|s| is)\s+(?:in|on)\s+(?:my\s+|the\s+)?clipboard"
    r"|what\s+did\s+i\s+(?:just\s+)?copy"
    r"|what(?:'s|s| is)\s+copied)\b"
)
CLIPBOARD_HISTORY_LIST_STARTERS = {"show", "list", "read", "clipboard", "check", "display", "open", "view"}
CLIPBOARD_HISTORY_CLEAR_STARTERS = {"clear", "delete", "wipe", "erase", "empty", "forget", "reset"}
CLIPBOARD_WRITE_STARTERS = {"copy", "put", "add", "save"}
CLIPBOARD_RESTORE_STARTERS = {"copy", "restore", "paste", "use", "get"}

# ── Typing ────────────────────────────────────────────────────────────────────
# Typed into the app the user is using (services/automation/keyboard.py).
# "type see you at 5" types exactly that; "write an email to…" has the AI write it first.
DICTATE = re.compile(r"^(?:type|type out|dictate|write down)\s*[:,]?\s+(?P<text>.+)$", re.IGNORECASE | re.DOTALL)
WRITE = re.compile(r"^(?:write|compose|draft)\s+(?!down\b)(?P<request>.+)$", re.IGNORECASE | re.DOTALL)
# "type hi and send it", "type hello, then press enter"
THEN_KEYS = re.compile(
    r"(?:\s*,)?\s+(?:and\s+then|and|then)\s+"
    r"(?:(?:press|hit)\s+(?P<keys>[\w+ ]+?)|(?P<send>send(?:\s+it)?))\s*[.!]?$",
    re.IGNORECASE,
)
# Spoken line breaks inside dictation
DICTATION_BREAKS = {"new paragraph": "\n\n", "new line": "\n", "next line": "\n"}
PRESS = re.compile(
    r"^(?:press|hit|tap|push)\s+(?:the\s+)?(?P<keys>.+?)(?:\s+(?:key|keys|button))?"
    r"(?:\s+(?P<times>\d+|two|three|four|five|ten)\s+times|\s+(?P<word>once|twice))?$"
)
TIMES_WORDS = {"once": 1, "twice": 2, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
# Whole messages that mean a key press
KEY_PHRASES = {
    "select all": "ctrl+a", "select everything": "ctrl+a",
    "undo": "ctrl+z", "undo that": "ctrl+z", "redo": "ctrl+y", "redo that": "ctrl+y",
    "save": "ctrl+s", "save it": "ctrl+s", "save this": "ctrl+s", "save the file": "ctrl+s",
    "copy that": "ctrl+c", "copy this": "ctrl+c", "copy the selection": "ctrl+c",
    "paste": "ctrl+v", "paste it": "ctrl+v", "paste that": "ctrl+v",
    "cut": "ctrl+x", "cut that": "ctrl+x", "cut this": "ctrl+x",
    "new line": "enter", "enter": "enter", "send it": "enter", "send the message": "enter", "hit send": "enter",
    "backspace": "backspace", "delete that": "ctrl+backspace", "delete the last word": "ctrl+backspace",
    "escape": "esc", "cancel that": "esc",
    "new tab": "ctrl+t", "open a new tab": "ctrl+t", "close tab": "ctrl+w", "close this tab": "ctrl+w",
    "close the tab": "ctrl+w", "reopen tab": "ctrl+shift+t", "reopen closed tab": "ctrl+shift+t",
    "reopen the closed tab": "ctrl+shift+t", "next tab": "ctrl+tab", "previous tab": "ctrl+shift+tab",
    "refresh": "f5", "reload": "f5", "refresh the page": "f5", "reload the page": "f5", "refresh page": "f5",
    "find on page": "ctrl+f", "find on this page": "ctrl+f", "search this page": "ctrl+f",
    "zoom in": "ctrl+plus", "zoom out": "ctrl+minus", "reset zoom": "ctrl+0",
    "scroll down": "page down", "scroll up": "page up", "page down": "page down", "page up": "page up",
    "go to the top": "ctrl+home", "go to the bottom": "ctrl+end",
    "switch window": "alt+tab", "switch windows": "alt+tab", "switch apps": "alt+tab", "alt tab": "alt+tab",
    "minimize this": "win+down", "minimize window": "win+down", "minimize the window": "win+down",
    "maximize this": "win+up", "maximize window": "win+up", "maximize the window": "win+up",
    "show desktop": "win+d", "show the desktop": "win+d",
}

# ── System stats ──────────────────────────────────────────────────────────────
# Matched as whole messages (after filler and "?" are dropped), so questions like
# "how much ram do I need for gaming" or "what is ram" stay chat.
_MACHINE = r"(?:system|pc|computer|laptop|machine)"
STATS_EVERYTHING = re.compile(
    rf"^(?:how(?:'s|s| is)\s+(?:my\s+|the\s+|this\s+)?{_MACHINE}(?:\s+doing)?"
    rf"|(?:(?:show|check|get|give)\s+(?:me\s+)?(?:my\s+|the\s+)?)?{_MACHINE}\s+"
    r"(?:stats|status|health|info|report|performance|check|usage)"
    rf"|(?:check|scan)\s+(?:my\s+|the\s+)?{_MACHINE}"
    r"|stats|resource usage"
    rf"|is\s+(?:my\s+|the\s+)?{_MACHINE}\s+(?:ok|okay|fine|alright|running\s+(?:ok|okay|fine|hot))"
    rf"|why\s+is\s+(?:my\s+|the\s+)?{_MACHINE}\s+(?:so\s+|running\s+)?(?:slow|laggy|lagging|hot))$"
)
# Complaints about slowness also name the apps using the most memory
STATS_SLOW = re.compile(r"\b(?:slow|laggy|lagging)\b")
# part → how it can be named. "memory" is left out of the bare form ("memory" alone is ambiguous).
STATS_PARTS = {
    "cpu": r"(?:cpu|processor)",
    "memory": r"(?:ram|memory)",
    "battery": r"(?:battery|battery life)",
    "gpu": r"(?:gpu|graphics card|graphics|vram|video memory)",
    "disk": r"(?:disk|disk space|storage|storage space|free space|hard drive|ssd|drive space)",
}
STATS_BARE = {"cpu", "processor", "ram", "battery", "gpu", "vram", "disk space", "storage", "free space"}
_STAT = r"(?:usage|use|load|level|stats|status|percentage|percent|temp|temperature|life|left|space|remaining)"


def _stats_patterns(part: str) -> re.Pattern:
    return re.compile(
        rf"^(?:(?:my|the|current)\s+)*{part}\s+{_STAT}"                                  # "cpu usage"
        rf"|^(?:what(?:'s|s| is)|check|show(?:\s+me)?|tell\s+me|get)\s+(?:(?:my|the|current)\s+)+{part}(?:\s+{_STAT})?"
        rf"|^(?:what(?:'s|s| is)|check|show(?:\s+me)?|tell\s+me|get)\s+{part}\s+{_STAT}"  # "check gpu temp"
        rf"|^how\s+(?:much|hot|busy|full)\s+(?:is\s+)?(?:my\s+|the\s+)?{part}"
        r"(?:\s+(?:is\s+)?(?:left|used|free|being used|in use|remaining|running|is|getting))?"
        rf"|^how\s+much\s+{part}\s+(?:is\s+left|do\s+i\s+have(?:\s+left)?|is\s+(?:being\s+)?used"
        r"|am\s+i\s+using|is\s+free|remaining|left)"
        rf"|^what(?:'s|s| is)\s+(?P<top>using|eating|hogging)\s+(?:(?:all|up|my|the)\s+)*{part}"
    )


STATS_PART_PATTERNS = {name: _stats_patterns(words) for name, words in STATS_PARTS.items()}
STATS_CHARGING = re.compile(
    rf"^(?:(?:am\s+i|is\s+(?:my\s+|the\s+|this\s+)?(?:{_MACHINE}|it))\s+)?(?:charging|plugged\s+in)"
)

# ── Reminders ─────────────────────────────────────────────────────────────────
# "set a reminder for 5pm to call mom" is rewritten to "remind me at 5pm to call mom"
SET_REMINDER = re.compile(
    r"^(?:set|create|add|make|schedule)\s+(?:a\s+|an\s+|me\s+a\s+)?(?:new\s+)?(?:reminder|notification|alert)\s+"
    r"(?:for\s+(?=\d|tomorrow))?",
)
REMINDER_LIST_PHRASES = re.compile(
    r"^(?:(?:what(?:'s| are| is)\s+my\s+|(?:list|show|check|view|see|read)\s+(?:all\s+)?(?:my\s+|the\s+)?)reminders\b"
    r"|(?:do\s+i\s+have\s+)?(?:any|my)?\s*(?:upcoming\s+)?reminders$)"
)
REMINDER_CANCEL_STARTERS = {"cancel", "delete", "remove", "clear", "stop", "drop", "forget"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _alternation(options) -> str:
    # Longest first, so "open up" wins over "open"
    return "|".join(sorted(options, key=len, reverse=True))


_LEADING = re.compile(rf"^\s*(?:{_alternation(LEADING_FILLER)})\b[\s,:!.]*", re.IGNORECASE)
_TRAILING = re.compile(rf"[\s,]*\b(?:{'|'.join(TRAILING_FILLER)})\s*[.!?]*\s*$", re.IGNORECASE)
_TARGET_PREFIX = re.compile(rf"^(?:(?:{_alternation(TARGET_PREFIXES)})\s+)+")
_TARGET_SUFFIX = re.compile(rf"(?:\s+(?:{_alternation(TARGET_SUFFIXES)}))+$")


def strip_leading_filler(message: str) -> str:
    """Like normalize_command, but only from the front: dictated text keeps its ending."""
    text = message.strip().replace("’", "'")
    previous = None
    while text != previous:
        previous = text
        text = _LEADING.sub("", text, count=1)
    return text


# Contractions typed without the apostrophe ("hows my battery", "whats my streak"), so every
# matcher only has to know the "how's" spelling. Not "its" / "ill" / "wont": those are words too.
_CONTRACTION_S = re.compile(r"\b(how|what|where|when|who|that)s\b", re.I)
_CONTRACTION_NT = re.compile(r"\b(do|does|did|ca|is|are|was|were|have|has|should|could|would)nt\b", re.I)
_CONTRACTION_I = re.compile(r"\b(i)(m|ve)\b", re.I)


def normalize_command(message: str) -> str:
    """Strip wake words, politeness and end punctuation; keeps the original letter case."""
    text = message.strip().replace("’", "'")
    text = _CONTRACTION_I.sub(r"\1'\2", _CONTRACTION_NT.sub(r"\1n't", _CONTRACTION_S.sub(r"\1's", text)))
    previous = None
    while text != previous:
        previous = text
        text = _LEADING.sub("", text, count=1)
        text = _TRAILING.sub("", text, count=1)
    return text.strip().rstrip(".!?").strip()


# Sentence patterns stay separate from normalization: never replace words inside
# dictation, notes, searches, reminders or clipboard contents.
_NORMALIZED_PHRASE_ALIASES = {
    normalize_command(alias).casefold(): canonical for alias, canonical in PHRASE_ALIASES.items()
}
# These patterns own their payloads, including conjunctions and final punctuation.
# Match the original text with only its leading request filler removed.
_PARAMETER_PARAPHRASES = tuple((re.compile(pattern, re.I | re.S), replacement) for pattern, replacement in (
    (r"replace steps in (?:my |the )?(?:workflow|routine) (?P<name>.+?) with (?P<steps>.+)",
     r"create a routine called \g<name>: \g<steps>"),
    (r"(?:remove|delete) (?:my |the )?workflow (?P<name>.+)", r"delete routine \g<name>"),
    (r"change actions in (?P<name>[a-z][\w -]{0,30}?) mode to (?P<steps>.+)", r"set steps for \g<name> mode: \g<steps>"),
    (r"keep (?P<name>[a-z][\w -]{0,30}?) mode silent[.!?]*", r"make \g<name> mode quiet"),
    (r"allow notifications in (?P<name>[a-z][\w -]{0,30}?) mode[.!?]*", r"make \g<name> mode not quiet"),
    (r"activate saved mode (?P<name>[a-z][\w -]{0,30}?)[.!?]*", r"start \g<name> mode"),
    (r"end saved mode (?P<name>[a-z][\w -]{0,30}?)[.!?]*", r"end \g<name> mode"),
    (r"(?:remove|delete) saved mode (?P<name>[a-z][\w -]{0,30}?)[.!?]*", r"delete \g<name> mode"),
    (r"register project (?P<name>.+)", r"create project \g<name>"),
    (r"unregister project (?P<name>.+)", r"remove project \g<name>"),
    (r"reopen saved project (?P<name>.+)", r"resume \g<name>"),
    (r"change launch steps for project (?P<name>.+?) to (?P<steps>.+)", r"set resume steps for \g<name>: \g<steps>"),
    (r"show startup steps for project (?P<name>.+)", r"what does resume \g<name> do"),
    (r"restore default startup steps for project (?P<name>.+)", r"reset resume steps for \g<name>"),
    (r"open search result (?P<n>\d+)[.!?]*", r"open \g<n>"),
    (r"show search result (?P<n>\d+) in its folder[.!?]*", r"show \g<n> in folder"),
    (r"(?:store|update) contact (?P<name>.+?) with number (?P<number>\+?[\d -]+)",
     r"save contact \g<name> \g<number>"),
    (r"forget whatsapp contact (?P<name>.+)", r"remove contact \g<name>"),
    (r"message saved contact (?P<name>[^:\r\n]+):\s*(?P<body>.+)", r"message \g<name> on whatsapp: \g<body>"),
    (r"save (?P<url>https?://\S+) to read later[.!?]*", r"add \g<url> to my reading list"),
    (r"open saved reading item (?P<n>\d+)[.!?]*", r"open reading list \g<n>"),
    (r"mark reading item (?P<n>\d+) as (?:read|finished)[.!?]*", r"done with reading list \g<n>"),
    (r"research online:\s*(?P<query>.+)", r"look up \g<query>"),
    (r"answer from my (?:files|documents):\s*(?P<question>.+)", r"\\d \g<question>"),
    (r"add (?:a )?diary entry:\s*(?P<body>.+)", r"journal: \g<body>"),
    (r"(?:create|define|set up) (?:a )?(?:workflow|automation) (?:called|named) (?P<rest>.+)",
     r"create a routine called \g<rest>"),
    (r"(?:run|execute|start) (?:the |my )?(?:workflow|automation) (?P<name>.+)", r"run routine \g<name>"),
    (r"whatsapp message to (?P<contact>[^:\r\n]+):\s*(?P<body>.+)", r"message \g<contact> on whatsapp: \g<body>"),
    (r"forward (?P<what>.+?) (?:via|on|through|to) telegram(?: bot)?[.!?]*", r"send \g<what> through telegram"),
    (r"track down my (?P<query>.+)", r"find my \g<query>"),
    (r"set (?:a )?due date for (?P<task>.+?) (?:to|as) (?P<when>.+)", r"add deadline \g<task> due \g<when>"),
    (r"record attendance for (?P<subject>.+?) as present(?P<day> today| yesterday)?", r"attended \g<subject>\g<day>"),
    (r"record attendance for (?P<subject>.+?) as absent(?P<day> today| yesterday)?", r"missed \g<subject>\g<day>"),
    (r"join (?:my )?(?P<subject>.+?) online (?:class|lecture)", r"join \g<subject> class"),
    (r"prepare (?P<subject>.+?) revision notes", r"make a revision pack for \g<subject>"),
    (r"build (?:a )?(?P<subject>.+?) revision pack", r"make a revision pack for \g<subject>"),
    (r"use my saved login for (?P<name>.+)", r"log in to \g<name>"),
    (r"prepare (?:a )?handover for (?P<reference>.+)", r"prepare a handoff for \g<reference>"),
    (r"create (?:a )?task:\s*(?P<title>.+)", r"start task: \g<title>"),
    (r"create (?:a )?goal:\s*(?P<title>.+)", r"add goal: \g<title>"),
))
_SENTENCE_PATTERNS = tuple((re.compile(pattern, re.I), replacement) for pattern, replacement in (
    (r"get\s+(?P<target>.+?)\s+(?:running|started|launched|open)", r"open \g<target>"),
    (r"bring\s+(?P<target>.+?)\s+to\s+(?:the\s+)?(?:front|foreground)", r"open \g<target>"),
    (r"(?:close|shut)\s+(?P<target>.+?)\s+down", r"close \g<target>"),
    (r"(?:take|capture|grab|snap|save)\s+(?:a\s+|an\s+)?(?:picture|image|snapshot|photo)\s+of\s+"
     r"(?:my\s+|the\s+|this\s+)?(?:screen|display|desktop)", "take a screenshot"),
))


def rephrase_command(message: str) -> str:
    """Translate a whole, explicit request to an existing command; keep targets intact."""
    literal = strip_leading_filler(message)
    numbered = normalize_command_numbers(literal)
    if rewritten := rephrase_task_command(numbered):
        return rewritten
    literal = numbered
    for pattern, replacement in _PARAMETER_PARAPHRASES:
        if match := pattern.fullmatch(literal):
            return match.expand(replacement)
    text = normalize_command(literal)
    if canonical := _NORMALIZED_PHRASE_ALIASES.get(text.casefold()):
        return canonical
    if len(split_steps(text)) > 1:
        return literal if literal != strip_leading_filler(message) else message
    for pattern, replacement in _SENTENCE_PATTERNS:
        if match := pattern.fullmatch(text):
            if replacement.startswith("close") and clean_target(match["target"].lower()) in {
                "pc", "computer", "laptop", "system", "machine", "windows", "everything", "all",
            }:
                return message  # leave power commands with their dedicated matcher
            return match.expand(replacement)
    return literal if literal != strip_leading_filler(message) else message


def strip_verb(text: str, verbs) -> str | None:
    """If lowercase `text` starts with one of the verbs, return what follows it."""
    match = re.match(rf"(?:{_alternation(map(re.escape, verbs))})(?:\s+|$)", text)
    return text[match.end():].strip() if match else None


def clean_target(text: str) -> str:
    """ "the chrome app" → "chrome" """
    text = _TARGET_PREFIX.sub("", text.strip())
    return _TARGET_SUFFIX.sub("", text).strip()


def resolve_app(target: str, registered: list[str]) -> str | None:
    """The registered app a cleaned target names exactly, directly or by alias."""
    if target in registered:
        return target
    alias = APP_ALIASES.get(target)
    return alias if alias in registered else None


def resolve_folder(target: str) -> str | None:
    """The FOLDER_MAP key a cleaned target names, directly or by alias."""
    key = FOLDER_ALIASES.get(target, target)
    return key if key in FOLDER_MAP else None


def resolve_site(target: str) -> str | None:
    return SITES.get(target)


# Words that start a command, for spotting "do X and then do Y"
STEP_STARTERS = (
    {w.split()[0] for w in OPEN_VERBS + CLOSE_VERBS + SEARCH_VERBS + URL_VERBS + ORGANISE_VERBS}
    | VOLUME_NOUNS | BRIGHTNESS_NOUNS | MUTE_WORDS | UNMUTE_WORDS | BRIGHTNESS_UP | BRIGHTNESS_DOWN
    | SCREENSHOT_STARTERS | CLIPBOARD_HISTORY_CLEAR_STARTERS | CLIPBOARD_WRITE_STARTERS
    | {"set", "turn", "remind", "copy", "take", "increase", "decrease", "lower", "raise"}
    | {"play", "pause", "resume", "skip", "next", "previous", "unpause"}
    | {"shuffle", "repeat", "queue", "like", "unlike"}
    | {"type", "write", "press", "hit", "select", "undo", "redo", "paste", "scroll", "refresh"}
    | {"what", "tell", "time", "date", "day"}
)
_STEP_SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and\s+then|and\s+also|then|and|also)\b\s*|\s*[;,]\s*|\s+&\s+", re.I)
_QUOTED_STEP_TEXT = re.compile(r'''"(?:\\.|[^"\\])*(?:"|$)|(?<!\w)'(?:\\.|[^'\\])*(?:'|$)''')


def split_steps(text: str) -> list[str]:
    """Split command separators, keeping quoted text and its punctuation intact."""
    quoted = [(m.start(), m.end()) for m in _QUOTED_STEP_TEXT.finditer(text)]
    parts, start = [], 0
    for match in _STEP_SPLIT.finditer(text):
        if any(left <= match.start() < right for left, right in quoted):
            continue
        part = text[start:match.start()].strip()
        if part:
            parts.append(part)
        start = match.end()
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def is_multi_step(text: str) -> bool:
    """ "mute and open chrome": two or more parts that each start with a command word."""
    parts = split_steps(text.lower())
    if len(parts) < 2:
        return False
    return all(first_word(p) in STEP_STARTERS for p in parts)


def first_word(text: str) -> str:
    match = re.match(r"\s*([a-z]+)", text.lower())
    return match.group(1) if match else ""


# Messages starting with these may still be commands the lists missed, so the AI
# gets a look. Everything else is chat — which keeps "set up my project plan" or
# "take me through fastapi" away from the AI.
AI_COMMAND_STARTERS = {
    "open", "launch", "start", "run", "search", "google", "go", "navigate", "visit", "browse",
    "organise", "organize", "sort", "clean", "tidy", "declutter", "show", "find", "look",
    "close", "quit", "exit", "kill", "terminate",
    "volume", "mute", "unmute", "brightness", "brighten", "dim", "louder", "quieter",
    "screenshot", "play", "pause", "resume", "skip", "shuffle", "repeat", "queue",
    "press", "hit", "scroll", "zoom", "switch", "minimize", "maximize",
}
