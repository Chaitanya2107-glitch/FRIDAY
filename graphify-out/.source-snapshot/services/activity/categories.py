"""
services/activity/categories.py

Sorts every activity row into a category (coding, study, ai, communication, …)
so habits can be read as "you study around 10" instead of a pile of app names.

This file is the single list to edit. Old rows are re-sorted each time FRIDAY
starts, so a word added here also relabels everything already recorded.
Anything that matches nothing is "other".
"""

import os
import re
from functools import lru_cache
from pathlib import Path, PurePath

# Program names as the log stores them (lower case, no .exe)
APPS = {
    "coding": {"code", "cursor", "windsurf", "windowsterminal", "cmd", "powershell", "pwsh", "openconsole",
               "bash", "git", "curl", "esbuild", "node", "npm", "grep", "head", "tail",
               "pycharm64", "idea64", "devenv", "sublime_text", "notepad++", "postman", "docker desktop"},
    "ai": {"claude", "chatgpt", "ollama app", "ollama", "freellmapi", "lm studio"},
    "communication": {"whatsapp", "whatsapp.root", "zoom", "ms-teams", "teams", "discord", "telegram", "slack",
                      "outlook", "olk", "thunderbird"},
    "documents": {"winword", "excel", "powerpnt", "onenote", "acrobat", "acrord32", "notepad", "obsidian", "notion"},
    "music": {"spotify"},
    "entertainment": {"vlc", "netflix", "primevideo", "mpc-hc64", "potplayermini64"},
    "gaming": {"steam", "steamwebhelper", "epicgameslauncher", "xboxpcapp", "xboxpcappft", "gamingservices",
               "riotclientservices", "riotclientux", "leagueclient", "valorant", "battle.net", "eadesktop",
               "ubisoftconnect", "upc", "galaxyclient", "robloxplayerbeta", "minecraft", "minecraftlauncher",
               "javaw", "gamebar"},
    "media": {"photos", "photoshop", "lightroom", "gimp", "blender", "obs64", "clipchamp"},
    "files": {"explorer"},
    "system": {"taskmgr", "shellhost", "systemsettings", "snippingtool", "openwith", "credentialuibroker",
               "control", "regedit", "mmc", "mpcmdrun", "storedesktopextension",
               "idlescheduleeventaction", "opushutil", "officec2rclient"},
}
# Games found by where they're installed (any drive), so a new game needs no entry above
GAME_FOLDERS = ["Games", "XboxGames", "Riot Games", "SteamLibrary/steamapps/common",
                "Program Files (x86)/Steam/steamapps/common", "Program Files/Epic Games",
                "Program Files (x86)/Epic Games", "Program Files/EA Games", "Program Files (x86)/Ubisoft",
                "Program Files (x86)/GOG Galaxy/Games"]
STEAM_LIBRARIES = "Program Files (x86)/Steam/steamapps/libraryfolders.vdf"
GAME_PROGRAM = re.compile(r"-win64-shipping$|-shipping$")  # Unreal Engine games ("b1-win64-shipping")

# Background helpers that show up as launches (updaters, services, vendor add-ins)
SYSTEM_PROCESS = re.compile(r"update|helper|service|plugin|addin|host|install|setup|agent|broker|server|"
                            r"telemetry|lenovo|onedrive|powertoys|nahimic|rzchroma|provision|\.task$|_x64_")

# Website domains; a domain also covers its subdomains ("reva.edu.in" covers "rulms.reva.edu.in")
SITES = {
    "coding": {"github.com", "gitlab.com", "stackoverflow.com", "vercel.app", "supabase.co", "npmjs.com",
               "pypi.org", "developer.mozilla.org", "render.com", "netlify.app", "aws.amazon.com"},
    "study": {"reva.edu.in", "coursera.org", "udemy.com", "geeksforgeeks.org", "w3schools.com", "leetcode.com",
              "khanacademy.org", "nptel.ac.in", "swayam.gov.in"},
    "ai": {"claude.ai", "chatgpt.com", "openai.com", "openrouter.ai", "ollama.com", "kimi.com",
           "gemini.google.com", "perplexity.ai", "huggingface.co", "anthropic.com"},
    "communication": {"mail.google.com", "meet.google.com", "web.whatsapp.com", "outlook.live.com",
                      "outlook.office.com", "teams.microsoft.com", "zoom.us", "discord.com"},
    "documents": {"docs.google.com", "drive.google.com", "forms.google.com", "forms.cloud.microsoft",
                  "office.com", "notion.so", "canva.com"},
    "music": {"open.spotify.com", "music.youtube.com", "gaana.com", "jiosaavn.com"},
    "entertainment": {"youtube.com", "netflix.com", "primevideo.com", "hotstar.com", "jiocinema.com", "twitch.tv"},
    "gaming": {"slither.io", "slither.com", "poki.com", "chess.com", "crazygames.com", "store.steampowered.com",
               "steamcommunity.com", "epicgames.com", "itch.io", "roblox.com", "miniclip.com", "krunker.io",
               "lichess.org", "ign.com"},
    "social": {"x.com", "twitter.com", "reddit.com", "instagram.com", "facebook.com", "linkedin.com"},
    "shopping": {"amazon.in", "amazon.com", "flipkart.com", "myntra.com"},
    "search": {"google.com", "bing.com", "duckduckgo.com"},
    "system": {"msftconnecttest.com"},
}
LOCAL_SITE = re.compile(r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)")  # your own dev servers
CAPTIVE_PORTAL = re.compile(r"captiveportal|hotspot|wifi")

# Browser tab titles. The first match wins, so more specific words come first.
# ponytail: keyword match on the tab title; a title naming two sites ("GitHub App - Claude") goes to the earlier rule
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi"}
TITLE_RULES = [
    ("search", r"(^| - )(google search|bing|duckduckgo)$"),  # a results page, whatever the query was about
    ("ai", r"\bclaude\b|chatgpt|openrouter|gemini|perplexity|ollama"),
    ("study", r"\| reva\b|\breva university\b|rulms|coursera|udemy|geeksforgeeks|w3schools|leetcode|nptel"),
    ("communication", r"\bgmail\b|google meet|\bmeet -|whatsapp|outlook|\bteams\b|zoom|discord"),
    ("music", r"spotify|youtube music"),
    ("entertainment", r"youtube|netflix|prime video|hotstar|twitch"),
    ("gaming", r"slither|poki|chess\.com|steam|epic games|crazygames|itch\.io|roblox|miniclip"),
    ("social", r"reddit|instagram|facebook|linkedin|/ x\b|twitter"),
    ("coding", r"^[\w.-]+/[\w.-]+$|your repositories|github|gitlab|stack overflow|vercel|supabase|localhost|npm\b|pypi"),
    ("documents", r"google docs|google sheets|google slides|google drive|google forms|notion|canva"),
]
_TITLE_RULES = [(category, re.compile(pattern, re.I)) for category, pattern in TITLE_RULES]

# Opened files, by extension; no extension means a folder
FILES = {
    "coding": {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".java", ".c", ".cpp", ".h",
               ".ipynb", ".sql", ".sh", ".bat", ".vbs", ".ps1", ".yml", ".yaml", ".toml", ".env", ".pid", ".log"},
    "documents": {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".txt", ".md", ".odt", ".rtf"},
    "media": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".arw", ".raw", ".psd"},
    "entertainment": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "music": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"},
}

# FRIDAY commands, by action (open_app instead takes the category of the app it opened)
MUSIC_ACTIONS = re.compile(r"^(play_|media_|spotify_)")
FILE_ACTIONS = {"find_files", "answer_files", "organise_folder", "open_folder", "open_file"}

# What FRIDAY worked out or was told herself (services/mind/knowledge.py fills this): program name → category,
# and cleaned window title (lower case) → category. The lists above win; these fill in what they don't cover.
LEARNED: dict[str, dict[str, str]] = {"app": {}, "title": {}}
_TITLE_MARKS = re.compile(r"^[^\w(\[]+")  # "✳ Build next", "◐ Build next" (Claude Code's status marks)
_BROWSER_SUFFIX = re.compile(r" - (google chrome|microsoft​? edge|mozilla firefox|brave|opera)$", re.I)
_UNREAD_COUNT = re.compile(r"^\(\d+\)\s*")  # "(436) YouTube"

_APP_INDEX = {app: category for category, apps in APPS.items() for app in apps}
_FILE_INDEX = {ext: category for category, exts in FILES.items() for ext in exts}
# Longest domains first, so "music.youtube.com" wins over "youtube.com"
_SITE_INDEX = sorted(((d, c) for c, domains in SITES.items() for d in domains), key=lambda item: -len(item[0]))


@lru_cache(maxsize=1)
def game_programs() -> frozenset[str]:
    """Program names (lower case, no .exe) of everything installed in a game folder. Scanned once per start."""
    # ponytail: a game installed somewhere else is only caught by name (APPS) or the -Shipping rule
    drives = [f"{letter}:/" for letter in "CDEFGH" if os.path.exists(f"{letter}:/")]
    roots = [Path(drive, folder) for drive in drives for folder in GAME_FOLDERS]
    for drive in drives:  # extra Steam libraries on other drives
        vdf = Path(drive, STEAM_LIBRARIES)
        if vdf.exists():
            for lib in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                roots.append(Path(lib.replace("\\\\", "/"), "steamapps/common"))
    names = set()
    for root in roots:
        try:
            names.update(exe.stem.lower() for exe in root.rglob("*.exe"))
        except OSError:
            continue  # a folder we can't read
    return frozenset(names)


def clean_title(title: str | None) -> str:
    """A window title without the browser's name, status marks and unread counts: what the window is about."""
    title = _BROWSER_SUFFIX.sub("", (title or "").strip())
    return _UNREAD_COUNT.sub("", _TITLE_MARKS.sub("", title)).strip()


def app_category(app: str | None, title: str | None = None) -> str:
    app = (app or "").lower()
    if app in BROWSERS:
        return title_category(title) or LEARNED["title"].get(clean_title(title).lower()) or "browsing"
    if app in _APP_INDEX:
        return _APP_INDEX[app]
    if app in LEARNED["app"]:
        return LEARNED["app"][app]
    if app and (GAME_PROGRAM.search(app) or app in game_programs()):
        return "gaming"
    return "system" if app and SYSTEM_PROCESS.search(app) else "other"


def title_category(title: str | None) -> str | None:
    title = _BROWSER_SUFFIX.sub("", title or "")
    return next((category for category, rule in _TITLE_RULES if rule.search(title)), None)


def site_category(domain: str | None, title: str | None = None) -> str:
    host = (domain or "").lower().split(":")[0].removeprefix("www.")
    if LOCAL_SITE.match(host):
        return "coding"
    if CAPTIVE_PORTAL.search(host):
        return "system"
    for site, category in _SITE_INDEX:
        if host == site or host.endswith("." + site):
            return category
    return title_category(title) or "other"


def file_category(name: str | None) -> str:
    # The log keeps names like "notes.pdf" or "style.css (2)" (Windows adds the counter), and folder names without a dot
    suffix = PurePath(re.sub(r" \(\d+\)$", "", name or "")).suffix.lower()
    return _FILE_INDEX.get(suffix, "other") if suffix else "files"


def command_category(action: str | None, target: str | None) -> str:
    action = action or ""
    if action == "open_app":
        return app_category(target)
    if MUSIC_ACTIONS.match(action):
        return "music"
    if action in FILE_ACTIONS:
        return "files"
    return "friday"  # talking to FRIDAY itself: reminders, screenshots, summaries


def categorize(kind: str, app: str | None = None, target: str | None = None,
               title: str | None = None, action: str | None = None) -> str:
    """The category of one activity row."""
    if kind in ("app", "launch"):
        return app_category(app, title)
    if kind == "web":
        return site_category(target, title)
    if kind == "file":
        return file_category(target)
    if kind == "command":
        return command_category(action, target)
    return "other"
