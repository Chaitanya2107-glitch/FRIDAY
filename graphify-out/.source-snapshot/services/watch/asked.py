"""
services/watch/asked.py

Watches the user asks for (typed, spoken or from Telegram):
  "tell me when blender closes"            → when every blender process has exited
  "tell me when it's done"                 → the app in front closing (an installer, a render…)
  "tell me when it's charged" / "…to 80"   → the battery reaching that %
  "tell me when example.com/results changes" → the page's visible text changing (checked every
                                               WEB_WATCH_MINUTES, one alert, then the watch ends)
  "tell me when catjang logs an error"     → new lines in the project's newest .log (or a named
  "tell me when server.log says listening"   log/text file) matching; one alert, then it ends
  "what are you watching", "stop watching blender" / "stop watching everything"
Web watches are kept in memory/watches.json; program and battery ones end with FRIDAY.
The always-on ones (Claude Code, terminal, downloads, heavy work) are in done.py and auto.py.
"""

import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psutil

from core.config import config
from core.logger import logger
from services.automation.system_control import AutomationError
from services.watch.done import TERMINAL_APPS, duration

WATCH_ACTIONS = {"watch_program", "watch_foreground", "watch_auto", "watch_battery", "watch_web", "watch_log",
                 "list_watches", "stop_watching"}
path = config.MEMORY_DIR / "watches.json"  # tests point this elsewhere
FETCH_TIMEOUT_SECONDS = 15
# The app in front when "tell me when it's done" is said, which isn't a task that ends by closing
NOT_A_TASK = TERMINAL_APPS | {"chrome", "msedge", "firefox", "brave", "opera", "explorer", "python", "pythonw"}
ALWAYS_ON = ("I always tell you when a Claude Code reply or a terminal command that took "
             f"{config.DONE_MIN_MINUTES}+ min finishes, when a download finishes and when heavy CPU/GPU work ends.")

_ASK = re.compile(r"^(?:tell me|let me know|notify me|ping me|message me|text me|alert me)\s+"
                  r"(?:when|once|as soon as|if)\s+(?P<what>.+)$", re.I)
_BATTERY = re.compile(r"\b(?:battery|charged|charging|charges)\b", re.I)
_PERCENT = re.compile(r"\b(\d{1,3})\s*(?:%|percent)?")
_URL = re.compile(r"(?P<url>(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:/\S*)?)", re.I)
_CHANGES = re.compile(r"\b(?:changes|changed|updates|updated|is updated|gets updated)$", re.I)
_IT_DONE = re.compile(r"^(?:it|that|this)(?:'s|s| is)? (?:done|finished|over|complete)$|^(?:it|that|this) finishes$", re.I)
_AUTO = re.compile(r"\b(?:downloads?|claude|claude code|builds?|commands?|compiles?|render(?:ing|s)?)\b", re.I)
_LOG = re.compile(r"^(?:the |my )?(?P<target>.+?) (?:logs|shows|prints|has|throws|hits|gets) (?:an? |any )?"
                  r"(?P<kind>error|exception|crash|warning|traceback)s?$|^(?:the |my )?(?P<t2>.+?) says (?P<text>.+)$", re.I)
LOG_PATTERNS = {"error": r"error|exception|traceback|\bfailed\b|\bfatal\b", "exception": r"exception|traceback",  # TypeError too
                "crash": r"crash|fatal|segmentation fault|unhandled", "warning": r"\bwarn(?:ing)?\b",
                "traceback": r"traceback"}
LOG_SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "dist", "build"}
_PROGRAM = re.compile(r"^(?:the |my )?(?P<app>.+?) (?:closes|exits|quits|finishes|ends|stops|is done|is finished|is closed)$", re.I)
_LIST = re.compile(r"^(?:what are you watching(?: for)?|what(?:'s| is) being watched|(?:list|show)(?: me)? (?:my |the |all )?watch(?:es)?)$", re.I)
_STOP = re.compile(r"^(?:stop|cancel) watching(?: (?:the |my )?(?P<what>.+))?$|^cancel (?:all )?(?:the |my )?watch(?:es)?$", re.I)

_programs: dict[str, dict] = {}  # label → {"procs": {(pid, create_time)}, "since": time}
_logs: dict[str, dict] = {}      # log file → {"pattern", "offset", "since"}
_battery: int | None = None      # the % to tell the user about
_next_web_check = 0.0


# ── Commands ──────────────────────────────────────────────────────────────────

def match_watch_command(text: str) -> dict | None:
    """`text` has already been through normalize_command()."""
    text = text.strip()
    if _LIST.match(text):
        return {"type": "system", "action": "list_watches"}
    if m := _STOP.match(text):
        return {"type": "system", "action": "stop_watching", "what": (m["what"] or "").strip()}
    m = _ASK.match(text)
    if not m:
        return None
    what = m["what"].strip()
    if _BATTERY.search(what):
        pct = _PERCENT.search(what)
        return {"type": "system", "action": "watch_battery", "percent": min(int(pct[1]), 100) if pct else 100}
    if _CHANGES.search(what) and (url := _URL.search(what)):
        return {"type": "system", "action": "watch_web", "url": url["url"].rstrip(".,)")}
    if _IT_DONE.match(what):
        return {"type": "system", "action": "watch_foreground"}
    if m := _LOG.match(what):  # "catjang logs an error", "server.log says listening"
        return {"type": "system", "action": "watch_log", "target": (m["target"] or m["t2"]).strip(),
                "pattern": LOG_PATTERNS[m["kind"].lower()] if m["kind"] else re.escape(m["text"].strip())}
    if _AUTO.search(what):  # "…when the download finishes": watched anyway
        return {"type": "system", "action": "watch_auto"}
    if m := _PROGRAM.match(what):
        return {"type": "system", "action": "watch_program", "app": m["app"].strip()}
    return None


def run(parsed: dict) -> str:
    """Blocking: a web watch loads the page once."""
    action = parsed["action"]
    if action == "watch_program":
        return watch_program(parsed["app"])
    if action == "watch_foreground":
        return watch_foreground()
    if action == "watch_battery":
        return watch_battery(int(parsed["percent"]))
    if action == "watch_web":
        return watch_web(parsed["url"])
    if action == "watch_log":
        return watch_log(parsed["target"], parsed["pattern"])
    if action == "watch_auto":
        return ALWAYS_ON
    if action == "list_watches":
        return list_message()
    return stop(parsed.get("what", ""))


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().removesuffix(".exe"))


def _find_processes(target: str) -> set[tuple[int, float]]:
    key = _key(target)
    found = set()
    for p in psutil.process_iter(["name", "create_time"]):
        name = _key(p.info["name"] or "")
        if key and name and (name == key or name.startswith(key)):
            found.add((p.pid, p.info["create_time"]))
    return found


def watch_program(app: str, procs: set[tuple[int, float]] | None = None) -> str:
    procs = procs if procs is not None else _find_processes(app)
    if not procs:
        raise AutomationError(f"I don't see {app} running.")
    _programs[app] = {"procs": procs, "since": time.time()}
    return f"Okay, I'll tell you when {app} closes."


def watch_foreground() -> str:
    from services.activity.log import foreground_ids, foreground_window

    app, _ = foreground_window()
    _, pid = foreground_ids()
    if not app or app in NOT_A_TASK or not pid:
        return ALWAYS_ON + ' For anything else, say "tell me when <app> closes".'
    try:
        procs = {(pid, psutil.Process(pid).create_time())}
    except psutil.Error:
        raise AutomationError(f"I couldn't watch {app}.") from None
    return watch_program(app, procs)


def watch_battery(percent: int) -> str:
    global _battery
    battery = psutil.sensors_battery()
    if battery is None:
        raise AutomationError("This PC has no battery.")
    if battery.percent >= percent:
        return f"The battery is already at {battery.percent:.0f}%."
    _battery = percent
    return f"Okay, I'll tell you when the battery reaches {percent}%" + ("." if battery.power_plugged else " — it isn't charging right now.")


def find_log(target: str) -> Path:
    """A saved project's newest log file, a path, or a log/text file found by name (Everything)."""
    from services.activity import projects
    from services.automation import app_finder

    saved = projects.load().get(target.lower())
    if saved:
        logs = [p for p in Path(saved["path"]).rglob("*.log") if not LOG_SKIP_DIRS & set(p.parts)]
        if not logs:
            raise AutomationError(f"{target} has no .log file. Tell me the file: \"tell me when <file> says …\".")
        return max(logs, key=lambda p: p.stat().st_mtime)
    if (candidate := Path(target.strip("\"'"))).is_file():
        return candidate
    hits = [Path(p) for p in app_finder._everything(["-path", str(Path.home()), "ext:log;txt;out", *target.split(),
                                                     r"!\AppData" + "\\"])]
    hits = [p for p in hits if p.is_file()]
    if not hits:
        raise AutomationError(f"I couldn't find a log called {target}.")
    return max(hits, key=lambda p: p.stat().st_mtime)


def watch_log(target: str, pattern: str) -> str:
    log_file = find_log(target)
    _logs[str(log_file)] = {"pattern": pattern, "offset": log_file.stat().st_size, "since": time.time()}
    return f"Okay, I'll tell you when {log_file.name} shows that."


def _check_log(file: str, watch: dict) -> str | None:
    """New lines since the last look; the first one matching, as an alert."""
    try:
        size = Path(file).stat().st_size
        with open(file, "rb") as f:
            f.seek(watch["offset"] if size >= watch["offset"] else 0)  # a smaller file was rotated / rewritten
            new = f.read(1_000_000).decode("utf-8", "replace")
        watch["offset"] = size
    except OSError:
        return None
    line = next((ln.strip() for ln in new.splitlines() if re.search(watch["pattern"], ln, re.I)), None)
    return f"{Path(file).name}: {line[:200]}" if line else None


def _load() -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(watches: list[dict]) -> None:
    path.write_text(json.dumps(watches, indent=2), encoding="utf-8")


def page_text(page: str) -> str:
    """The page's visible text, roughly."""
    page = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1\s*>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->|<[^>]+>", " ", page)
    return " ".join(html.unescape(page).split())


def fingerprint(url: str) -> str:
    """Blocking. Raises httpx.HTTPError when the page can't be loaded."""
    response = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FRIDAY"})
    response.raise_for_status()
    # ponytail: any change in visible text counts — a page with a live clock or rotating ads always "changes";
    # add "tell me when <url> says <text>" if that bites
    return hashlib.sha1(page_text(response.text).encode("utf-8")).hexdigest()


def _site(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.") or url


def watch_web(url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    watches = _load()
    if any(w["url"] == url for w in watches):
        return f"I'm already watching {_site(url)}."
    try:
        seen = fingerprint(url)
    except httpx.HTTPError as e:
        raise AutomationError(f"I couldn't load {url}: {type(e).__name__}.") from None
    _save(watches + [{"url": url, "seen": seen, "since": time.time()}])
    return f"Okay, I'll tell you when {_site(url)} changes. I'll check it every {config.WEB_WATCH_MINUTES} min."


def list_message() -> str:
    lines = [f"{app} closing" for app in _programs] + [f"{Path(f).name} for a match" for f in _logs]
    if _battery is not None:
        lines.append(f"the battery reaching {_battery}%")
    lines += [f"{_site(w['url'])} changing" for w in _load()]
    asked = ("I'm watching for " + ", ".join(lines) + ".") if lines else "You haven't asked me to watch anything."
    return f"{asked} {ALWAYS_ON}"


def stop(what: str) -> str:
    global _battery
    what = what.lower().strip()
    if what in ("", "everything", "all", "anything", "it", "them"):
        count = len(_programs) + len(_logs) + (_battery is not None) + len(_load())
        _programs.clear()
        _logs.clear()
        _battery = None
        _save([])
        return "Stopped all watches." if count else "I wasn't watching anything."
    if _BATTERY.search(what) and _battery is not None:
        _battery = None
        return "Okay, I won't tell you about the battery."
    for app in list(_programs):
        if _key(app) == _key(what) or _key(what) in _key(app):
            del _programs[app]
            return f"Stopped watching {app}."
    for file in list(_logs):
        if _key(what) in _key(Path(file).name) or _key(what) in _key(str(Path(file).parent)):
            del _logs[file]
            return f"Stopped watching {Path(file).name}."
    watches = _load()
    kept = [w for w in watches if what not in w["url"].lower()]
    if len(kept) != len(watches):
        _save(kept)
        return f"Stopped watching {what}."
    return f"I'm not watching {what}."


# ── Checks (from auto.run_watches) ────────────────────────────────────────────

def _alive(pid: int, created: float) -> bool:
    try:
        return psutil.Process(pid).create_time() == created
    except psutil.Error:
        return False


def check(now: float | None = None, online: bool = True) -> list[str]:
    """Blocking. The alerts due now; each watch fires once and ends."""
    global _battery, _next_web_check
    now = time.time() if now is None else now
    alerts = []
    for app, watch in list(_programs.items()):
        if not any(_alive(pid, created) for pid, created in watch["procs"]):
            del _programs[app]
            alerts.append(f"{app[:1].upper() + app[1:]} closed after {duration(now - watch['since'])}.")
    for file, watch in list(_logs.items()):
        if alert := _check_log(file, watch):
            del _logs[file]
            alerts.append(alert)
    if _battery is not None:
        battery = psutil.sensors_battery()
        if battery and battery.percent >= _battery:
            alerts.append(f"The battery is at {battery.percent:.0f}%." + (" Fully charged." if _battery >= 100 else ""))
            _battery = None
    if online and now >= _next_web_check and (watches := _load()):
        _next_web_check = now + config.WEB_WATCH_MINUTES * 60
        changed = set()
        for w in watches:
            try:
                if fingerprint(w["url"]) != w["seen"]:
                    changed.add(w["url"])
                    alerts.append(f"{_site(w['url'])} changed: {w['url']}")
            except httpx.HTTPError as e:
                logger.info(f"Web watch: couldn't load {w['url']}: {type(e).__name__}")  # tried again next time
        if changed:  # re-read: a watch may have been added while the pages loaded
            _save([w for w in _load() if w["url"] not in changed])
    return alerts
