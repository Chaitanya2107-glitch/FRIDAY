"""
services/activity/projects.py

Projects the user names ("this is a project", "save catjang as a project"),
so activity time is counted per project and "resume catjang" / "pick up where
I left off" reopens it: a terminal in the folder, the folder in File Explorer,
and its websites (the GitHub repo page, its deployed site, any saved sites).

Kept in memory/projects.json, editable by hand:
    {"catjang": {"path": "C:\\Users\\me\\Documents\\catjang", "repo": "me/catjang", "sites": [],
                 "resume": ["open the terminal", "run npm run dev", "open vs code", "play lofi"]}}
Only folders the user names count — nothing is added on its own.

What "resume" does is a list of plain steps per project, set by voice ("when I
resume catjang, run npm run dev, open vs code and play lofi") or in the file;
without one it's DEFAULT_RESUME. "open the terminal" / "run <command>" open one
Windows Terminal window in the folder (a tab per command), "open the folder" and
"open the sites" are the project's own; anything else is a normal FRIDAY command
(apps, URLs, music, routines…). "what does resume catjang do", "reset resume for catjang".

Which project an activity row belongs to (its category is then "project"):
  - an app whose program or child processes run inside the folder
    (a terminal or Claude Code session in it, the app being built) — checked
    while recording, since it can't be worked out later
  - a window title with the project's name ("IDEA-LAB-WEB - File Explorer")
  - a GitHub page of its repo ("me/IDEA-LAB-WEB"), a site named after it
    (idealab.vercel.app), a site saved for it
  - a localhost page served from its folder (its dev server, checked while
    recording) or titled with its name
"""

import json
import copy
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import comtypes
import comtypes.client
import psutil

from core.logger import logger
from services import settings_store
from services.activity.categories import BROWSERS, LOCAL_SITE
from services.automation import app_finder
from services.automation.command_words import split_steps
from services.automation.routines import _base_verb
from services.automation.system_control import AutomationError, system

path = Path("memory/projects.json")  # tests point this elsewhere

HOME = Path.home()
# Folders that are never a project, and cwd noise (tools, caches, hidden folders)
SKIP_FOLDER = re.compile(r"\\(?:appdata|node_modules|\.[^\\]+|\$recycle\.bin|site-packages|venv|windows|program files[^\\]*)(?:\\|$)", re.I)
RESUME_DAYS = 14        # sites used with the project this recently are reopened
PROJECT_ACTIONS = {"save_project", "list_projects", "remove_project", "project_time",
                   "set_resume", "show_resume", "reset_resume"}  # resume_project itself runs in intent.py
DEFAULT_RESUME = ["open the terminal", "open the folder", "open the sites"]

# Resume steps about the project itself; any other step is a normal FRIDAY command
_BUILTIN = re.compile(
    r"^(?:open\s+)?(?:the\s+|a\s+|my\s+)?(?:project(?:'s)?\s+)?"
    r"(?P<what>terminal|folder|project folder|sites?|websites?|github(?: page)?|repo(?: page)?)$", re.I,
)
_RUN_STEP = re.compile(r"^run\s+(?P<cmd>.+)$", re.I)  # "run npm run dev" → in the project's terminal
_SET_RESUME = re.compile(
    r"^(?:(?:when(?:ever)?|each time|every time) i (?:say )?(?:resume|continue|pick up|open project)"
    r"|(?:set|change) (?:the )?resume(?: steps)? (?:for|of))\s+(?P<rest>.+)$", re.I,
)
_SHOW_RESUME = re.compile(r"^what (?:does|will) (?:resume|resuming|resume project) (?P<name>.+?) (?:do|open)$", re.I)
_RESET_RESUME = re.compile(r"^reset (?:the )?resume(?: steps)? (?:for|of) (?P<name>.+)$", re.I)
_STEP_LEAD = re.compile(r"^[\s,:;-]*(?:(?:you should|please|then|to|just|i want you to|i want to)\s+)*", re.I)

_THIS = r"(?:this|this folder|this one|it|the current folder)"
_SAVE_THIS = re.compile(
    rf"^(?:{_THIS} is (?:a|my) project|(?:save|mark|add) {_THIS} as (?:a |my )?project|save this project)"
    r"(?:\s+(?:called|named)\s+(?P<name>.+))?$", re.I,
)
_SAVE_NAMED = re.compile(
    r"^(?:(?:save|mark|add)\s+(?P<a>.+?)\s+as\s+(?:a\s+|my\s+)?project|(?P<b>.+?)\s+is\s+(?:a|my)\s+project"
    r"|(?:add|new|create)\s+(?:a\s+)?project\s+(?:called\s+|named\s+)?(?P<c>.+))$", re.I,
)
_LIST = re.compile(r"^(?:(?:list|show)(?: me)?(?: all)?(?: my| the)? projects|what projects do i have|my projects)$", re.I)
_REMOVE = re.compile(
    r"^(?:(?:remove|delete|forget)\s+(?:the\s+)?project\s+(?P<a>.+)|(?:remove|delete|forget)\s+(?P<b>.+?)\s+project"
    r"|(?P<c>.+?)\s+is(?: not|n't) a project)$", re.I,
)
_RESUME_LAST = re.compile(
    r"^(?:pick up|continue|carry on|resume)(?: from)? where i left off|resume(?: my)?(?: last)? project"
    r"|continue(?: my)?(?: last)? project$", re.I,
)
_RESUME = re.compile(
    r"^(?:resume|continue(?: working on| with)?|pick up|back to|get back to|open (?:the )?project)\s+"
    r"(?:the\s+|my\s+)?(?:project\s+)?(?P<name>.+?)(?:\s+project)?$", re.I,
)
_WORK_ON = re.compile(
    r"^(?:(?:(?:i\s+)?(?:want|need)\s+to|(?:i\s+)?wanna|i'?d like to"
    r"|i(?:'m| am) (?:going to|gonna|ready to)|i feel like|time to|start)\s+)?"
    r"(?:work|working)\s+on\s+(?:the\s+|my\s+)?(?:project\s+)?"
    r"(?P<name>.+?)(?:\s+project)?$", re.I,
)
_TIME = re.compile(
    r"^how (?:long|much time) (?:did|have) i (?:work(?:ed)?|spen[dt](?: time)?) on (?:the\s+|my\s+)?(?:project\s+)?"
    r"(?P<name>.+?)(?:\s+project)?(?P<when>\s+today|\s+this week|\s+yesterday)?$", re.I,
)


# ── The file ──────────────────────────────────────────────────────────────────

_cache: tuple[float, dict] | None = None


def load() -> dict[str, dict]:
    """Every project by lowercase name. Re-read when the file changes (it's also edited by hand)."""
    global _cache
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _cache and _cache[0] == mtime:
        return _cache[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning(f"Couldn't read {path}: {e}")
        return {}
    projects = {str(name).strip().lower(): info for name, info in data.items() if isinstance(info, dict) and info.get("path")}
    _cache = (mtime, projects)
    return projects


def _save(projects: dict[str, dict]) -> None:
    global _cache
    settings_store.save(path, projects)
    _cache = None


# ── Folders ───────────────────────────────────────────────────────────────────

def _usable_folder(folder: Path) -> bool:
    return folder.is_relative_to(HOME) and folder != HOME and not SKIP_FOLDER.search("\\" + str(folder.relative_to(HOME)))


def git_root(folder: Path) -> Path:
    """The git project a folder is inside ("…\\catjang\\src" → "…\\catjang"), or the folder itself."""
    for candidate in (folder, *folder.parents):
        if candidate == HOME or not candidate.is_relative_to(HOME):
            break
        if (candidate / ".git").exists():
            return candidate
    return folder


def repo_of(folder: Path) -> str | None:
    """'owner/repo' of the folder's GitHub remote, if it has one."""
    try:
        config = (folder / ".git" / "config").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$", config, re.M)
    return match.group(1) if match else None


def find_folder(name: str) -> Path | None:
    """A folder called `name` in the user's files (Everything), a git project first, then the least nested."""
    # Only the user's folders, skipping AppData/node_modules in Everything itself (they'd crowd out real results)
    words = re.findall(r"\S+", name)
    hits = [Path(p) for p in app_finder._everything(
        ["-path", str(HOME), "folder:", *words, r"!\AppData" + "\\", r"!\node_modules" + "\\"])]
    hits = [p for p in hits if p.name.lower() == name.lower() and _usable_folder(p)]
    if not hits:
        return None
    return min(hits, key=lambda p: (not (p / ".git").exists(), len(p.parts)))


def _explorer_folder(hwnd: int) -> Path | None:
    """The folder a File Explorer window shows."""
    comtypes.CoInitialize()
    try:
        for window in comtypes.client.CreateObject("Shell.Application", dynamic=True).Windows():
            try:
                if int(window.HWND) == int(hwnd):
                    return Path(window.Document.Folder.Self.Path)
            except Exception:
                continue  # an Internet Explorer / odd shell window
    finally:
        comtypes.CoUninitialize()
    return None


def process_folders(pid: int) -> set[Path]:
    """The project-like folders a program and its child processes run in (a terminal's shells, Claude Code, node…)."""
    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
    except psutil.Error:
        return set()
    folders = set()
    for proc in processes:
        try:
            folder = Path(proc.cwd())
        except (psutil.Error, OSError, ValueError):
            continue
        if _usable_folder(folder):
            folders.add(git_root(folder))
    return folders


def window_folders(hwnd: int | None, pid: int | None) -> set[Path]:
    if not pid:
        return set()
    try:
        is_explorer = psutil.Process(pid).name().lower() == "explorer.exe"
    except psutil.Error:
        return set()
    if is_explorer:
        folder = _explorer_folder(hwnd) if hwnd else None
        return {git_root(folder)} if folder and _usable_folder(folder) else set()
    return process_folders(pid)


# ── Which project a row belongs to ────────────────────────────────────────────

def project_of_folder(folder: Path, projects: dict[str, dict]) -> str | None:
    for name, info in projects.items():
        if folder.is_relative_to(Path(info["path"])):
            return name
    return None


def project_of_process(pid: int | None, projects: dict[str, dict] | None = None) -> str | None:
    """The one project a program runs in; None if none, or several (a terminal with tabs in two projects)."""
    projects = load() if projects is None else projects
    if not projects or not pid:
        return None
    # ponytail: a terminal with tabs in two projects counts as neither; Windows doesn't say which tab is showing
    found = {project_of_folder(folder, projects) for folder in process_folders(pid)} - {None}
    return found.pop() if len(found) == 1 else None


def _words(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.I)


def site_host(value: str) -> str:
    """Read a legacy domain or an HTTP(S) URL without treating schemes as hosts."""
    try:
        url = urlsplit(value if '://' in value else 'https://' + value)
        return (url.hostname or '').lower().removeprefix('www.') if url.scheme in {'http', 'https'} and not url.username and not url.password else ''
    except ValueError:
        return ''


def project_of_row(kind: str, app: str | None, target: str | None, title: str | None,
                   projects: dict[str, dict]) -> str | None:
    """A project from what the row itself says (titles, sites). Dev servers are matched while recording."""
    for name, info in projects.items():
        folder = Path(info["path"]).name
        repo = info.get("repo") or ""
        repo_title = re.compile(rf"{re.escape(repo)}\b" if repo else rf"\b[\w-]+/{re.escape(folder)}\b", re.I)
        if kind == "app" and title:
            if (app or "").lower() in BROWSERS:
                if repo_title.search(title):  # a GitHub tab of its repo
                    return name
            elif _words(name).search(title) or _words(folder).search(title):
                return name
        elif kind == "web" and target:
            host = site_host(target)
            squashed = re.sub(r"[\W_]", "", folder.lower())
            if (is_local_site(host) and title and (_words(name).search(title) or _words(folder).search(title))) \
                    or (host == "github.com" and title and repo_title.search(title)) \
                    or host and host in {site_host(s) for s in info.get("sites", [])} \
                    or (len(squashed) >= 5 and squashed in re.sub(r"[\W_]", "", host.split(".")[0])):
                return name
    return None


def is_local_site(domain: str | None) -> bool:
    return bool(domain and (domain in {'::1', '[::1]'} or LOCAL_SITE.match(domain.lower())))


def port_of(domain: str | None) -> int | None:
    """The port of a localhost address ("localhost:3000" → 3000); None for other sites."""
    if not is_local_site(domain):
        return None
    _, _, port = domain.partition(":")
    return int(port) if port.isdigit() else 80


def local_servers(saved: dict[str, dict] | None = None) -> dict[int, str]:
    """Ports served on this PC by a program running in a saved project's folder (its dev server)."""
    saved = load() if saved is None else saved
    if not saved:
        return {}
    servers = {}
    try:
        listening = [c for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.pid]
    except (psutil.Error, OSError) as e:
        logger.warning(f"Couldn't list local servers: {e}")
        return {}
    for conn in listening:
        try:
            folder = Path(psutil.Process(conn.pid).cwd())
        except (psutil.Error, OSError, ValueError):
            continue
        if _usable_folder(folder) and (name := project_of_folder(git_root(folder), saved)):
            servers[conn.laddr.port] = name
    return servers


# ── Commands ──────────────────────────────────────────────────────────────────

def match_project_command(text: str) -> dict | None:
    """Project commands. `text` has already been through normalize_command()."""
    text = text.strip()
    if (m := _SET_RESUME.match(text)) and (set_resume := _parse_set_resume(m["rest"])):
        return set_resume
    for pattern, action in ((_SHOW_RESUME, "show_resume"), (_RESET_RESUME, "reset_resume")):
        if (m := pattern.match(text)) and m["name"].lower() in load():
            return {"type": "system", "action": action, "name": m["name"].lower()}
    if m := _SAVE_THIS.match(text):
        return {"type": "system", "action": "save_project", "name": (m["name"] or "").strip(), "this": True}
    if _LIST.match(text):
        return {"type": "system", "action": "list_projects"}
    if m := _REMOVE.match(text):
        return {"type": "system", "action": "remove_project", "name": (m["a"] or m["b"] or m["c"]).strip().lower()}
    if m := _SAVE_NAMED.match(text):
        return {"type": "system", "action": "save_project", "name": (m["a"] or m["b"] or m["c"]).strip(), "this": False}
    if _RESUME_LAST.match(text):
        return {"type": "system", "action": "resume_project", "name": ""}
    if (m := _TIME.match(text)) and m["name"].lower() in load():
        return {"type": "system", "action": "project_time", "name": m["name"].lower(),
                "when": (m["when"] or " today").strip()}
    if (m := _RESUME.match(text)) and m["name"].lower() in load():  # only saved projects: "continue the song" isn't one
        return {"type": "system", "action": "resume_project", "name": m["name"].lower()}
    if m := _WORK_ON.match(text):
        saved = load()
        target = m["name"].strip().lower()
        # Spoken punctuation varies ("F.R.I.D.A.Y.", "idea lab"). Only offer
        # a saved name, and never choose between ambiguous normalized names.
        key = re.sub(r"[\W_]+", "", target)
        matches = [name for name in saved if re.sub(r"[\W_]+", "", name) == key]
        name = target if target in saved else None
        if name is None and len(matches) == 1:
            name = matches[0]
        if name:
            return {"type": "system", "action": "suggest_resume_project", "name": name}
    return None


def _parse_set_resume(rest: str) -> dict | None:
    """ "catjang, run npm run dev and open vs code" → catjang + its steps. The name must be a saved project."""
    lowered = rest.lower()
    name = next((n for n in sorted(load(), key=len, reverse=True)
                 if lowered.startswith(n) and not lowered[len(n):len(n) + 1].isalnum()), None)
    if name is None:
        return None
    # ponytail: steps split on ", and then"; a terminal command that itself says "and" needs editing projects.json
    steps = [_base_verb(_STEP_LEAD.sub("", step).strip(" .")) for step in split_steps(rest[len(name):])]
    return {"type": "system", "action": "set_resume", "name": name, "steps": [s for s in steps if s]}


@settings_store.synchronized
def run(parsed: dict, log) -> str:
    """Run a project command. `log` is the ActivityLog (for "this" window, times and relabelling)."""
    action, projects = parsed["action"], copy.deepcopy(load())
    if action == "list_projects":
        if not projects:
            return 'You haven\'t saved any projects yet. Open its folder or terminal and say "this is a project".'
        return "Your projects: " + ", ".join(projects) + "."
    if action == "remove_project":
        name = parsed["name"]
        if name not in projects:
            raise AutomationError(f'You don\'t have a project called "{name}".')
        del projects[name]
        _save(projects)
        log.resort()
        return f'Removed the "{name}" project. Its time counts as its usual category again.'
    if action == "save_project":
        return _save_project(parsed, projects, log)
    if action == "project_time":
        return log.project_time(parsed["name"], parsed["when"])
    return _set_resume(parsed, projects)  # resuming itself is start_resume, run from intent.py


def _save_project(parsed: dict, projects: dict[str, dict], log) -> str:
    if parsed["this"]:
        folders = window_folders(*log.last_window)
        if not folders:
            raise AutomationError("I can't tell which folder you're in. Say \"save <folder name> as a project\".")
        if len(folders) > 1:
            names = ", ".join(sorted(f.name for f in folders))
            raise AutomationError(f"That window has several folders open ({names}). Say \"save <name> as a project\".")
        folder = folders.pop()
        name = (parsed["name"] or folder.name).lower()
    else:
        name = parsed["name"].lower()
        folder = find_folder(name)
        if folder is None:
            raise AutomationError(f'I couldn\'t find a folder called "{parsed["name"]}". Open it and say "this is a project".')
    if name in projects and Path(projects[name]["path"]) == folder:
        return f'"{name}" is already a project.'
    projects[name] = {"sites": [], **projects.get(name, {}), "path": str(folder), "repo": repo_of(folder)}
    _save(projects)
    log.resort()  # label the time already spent on it
    repo = f" (GitHub: {projects[name]['repo']})" if projects[name]["repo"] else ""
    return f'Saved "{name}" as a project: {folder}{repo}. Say "resume {name}" to pick it up later.'


def start_resume(name: str | None, log, *, expected=...) -> tuple[str, list[str]]:
    """
    Run the project's resume steps that are about the project itself (terminal, `run …`, folder, sites)
    and return (what was opened, the other steps) — those are normal FRIDAY commands, run by intent.py.
    """
    name = name or log.last_project()
    if not name:
        raise AutomationError('I haven\'t seen you work on a saved project yet. Say "this is a project" in its folder first.')
    with settings_store.lock:
        info = copy.deepcopy(load().get(name))
        if expected is not ... and info != expected:
            raise AutomationError('That project changed since the offer. Ask again to review its saved settings.')
    if not info:
        raise AutomationError(f'You don\'t have a project called "{name}".')
    folder = Path(info["path"])
    if not folder.exists():
        raise AutomationError(f"The {name} folder isn't at {folder} any more. Save it again from its new place.")

    tabs, opened, other_steps = [], [], []  # tabs: None = a plain terminal, else a command to run in it
    for step in resume_steps(info):
        if m := _BUILTIN.match(step.strip()):
            what = m["what"].lower()
            if what == "terminal":
                tabs.append(None)
            elif "folder" in what:
                system.open_folder(str(folder))
                opened.append("the folder")
            else:
                sites = resume_sites(name, info, log)
                for url in sites:
                    system.open_url(url)
                if sites:
                    listed = ", ".join(u.split("//", 1)[1] for u in sites)
                    opened.append(f"{len(sites)} site{'s' if len(sites) != 1 else ''} ({listed})")
        elif m := _RUN_STEP.match(step.strip()):
            tabs.append(m["cmd"].strip("`\"' "))
        else:
            other_steps.append(step)
    if tabs:
        opened.insert(0, _open_terminal(folder, tabs))
    said = ", ".join(opened[:-1]) + (" and " if len(opened) > 1 else "") + (opened[-1] if opened else "")
    return (f"Resuming {name}: opened {said}." if opened else f"Resuming {name}."), other_steps


def _open_terminal(folder: Path, tabs: list[str | None]) -> str:
    """One Windows Terminal window in the folder: a tab per `run …` command (and a plain one if asked)."""
    args = ["wt.exe"]
    for i, command in enumerate(tabs):
        args += ([";", "new-tab"] if i else []) + ["-d", str(folder)]
        if command:  # -NoExit keeps the tab open to show the output (or the error)
            args += ["powershell", "-NoExit", "-Command", command.replace(";", "\\;")]  # wt reads a bare ; as "next tab"
    try:
        subprocess.Popen(args)
    except OSError as e:
        logger.warning(f"Couldn't open Windows Terminal in {folder}: {e}")
        return "no terminal (Windows Terminal didn't start)"
    commands = [c for c in tabs if c]
    return "a terminal" + (f" running {' and '.join(commands)}" if commands else "")


def resume_steps(info: dict) -> list[str]:
    return [str(s) for s in info.get("resume") or []] or DEFAULT_RESUME


def _set_resume(parsed: dict, projects: dict[str, dict]) -> str:
    name = parsed["name"]
    if name not in projects:
        raise AutomationError(f'You don\'t have a project called "{name}".')
    if parsed["action"] == "reset_resume":
        projects[name].pop("resume", None)
        _save(projects)
        return f'"resume {name}" is back to the default: {_numbered(DEFAULT_RESUME)}.'
    if parsed["action"] == "show_resume":
        custom = "" if projects[name].get("resume") else " (the default)"
        return f'"resume {name}" will{custom}: {_numbered(resume_steps(projects[name]))}.'
    steps = [s for s in parsed["steps"] if s]
    if not steps:
        raise AutomationError(f'Tell me the steps too, like "when I resume {name}, run npm run dev and open vs code".')
    projects[name]["resume"] = steps
    _save(projects)
    return f'Done. "resume {name}" will now: {_numbered(steps)}.'


def _numbered(steps: list[str]) -> str:
    return ", ".join(f"{i}. {step}" for i, step in enumerate(steps, 1))


def resume_sites(name: str, info: dict, log) -> list[str]:
    """The repo page, saved sites, and sites named after the project used lately — never localhost."""
    sites = [f"https://github.com/{info['repo']}"] if info.get("repo") else []
    domains = list(info.get("sites", [])) + log.project_domains(name, datetime.now() - timedelta(days=RESUME_DAYS))
    for domain in domains:
        host = site_host(domain)
        if host and not is_local_site(host) and host != "github.com":
            url = domain if "//" in domain else f"https://{domain}"
            if url not in sites:
                sites.append(url)
    return sites
