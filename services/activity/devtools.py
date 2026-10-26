"""
services/activity/devtools.py

Coding helpers for saved projects and this PC's dev servers:
  - "what's running on port 3000", "what dev servers are running" (listening ports of dev
    programs — node, python, java … — with the saved project they run in)
  - "stop the dev server on port 3000", "stop catjang's dev server", "kill port 3000"
    (asks first; stops the program and its children)
  - "did CI pass on catjang", "CI status" (GitHub Actions' latest run, through the gh CLI)
  - "check outdated packages", "…in catjang" (npm outdated / the project venv's pip)
The weekly summary lists each project's commits as a "Shipped" draft (weekly.py); a failed
terminal command's alert has an [Explain] button (screen question, buttons.py).
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil

from core.config import config
from core.logger import logger
from services.activity import projects
from services.automation.system_control import AutomationError

DEV_PROGRAMS = {"node", "python", "pythonw", "java", "deno", "bun", "go", "dotnet", "ruby", "php", "uvicorn",
                "gunicorn", "flask", "cargo", "air", "hugo", "caddy", "nginx", "httpd", "docker", "com.docker.backend",
                "wslrelay", "postgres", "mysqld", "redis-server", "mongod", "ollama"}
COMMAND_TIMEOUT = 60
DEV_ACTIONS = {"port_info", "list_servers", "stop_server", "ci_status", "outdated"}

_PORT_INFO = re.compile(r"^what(?:'s| is) (?:running|listening) on (?:port )?(?P<port>\d{2,5})$|^who(?:'s| is) using port (?P<p2>\d{2,5})$", re.I)
_LIST = re.compile(r"^(?:what|which) (?:dev )?servers are running|^(?:list|show)(?: me)? (?:my |the )?(?:dev )?servers$"
                   r"|^what(?:'s| is) (?:running )?on my ports$", re.I)
_STOP = re.compile(r"^(?:stop|kill|end|free|shut down) (?:the )?(?:dev server |server )?(?:on |at )?port (?P<port>\d{2,5})$"
                   r"|^(?:stop|kill|shut down) (?P<name>.+?)(?:'s)? (?:dev )?server$", re.I)
_CI = re.compile(r"^(?:did (?:the )?ci pass|ci status|check (?:the )?ci|is (?:the )?ci (?:green|passing)|did (?:the )?build pass)"
                 r"(?: (?:on|for|in) (?P<name>.+))?$", re.I)
_OUTDATED = re.compile(r"^(?:check|any|list|show)(?: me)? (?:for )?outdated (?:packages|dependencies|deps)(?: (?:in|for|on) (?P<name>.+))?$", re.I)


def match_dev_command(text: str) -> dict | None:
    """`text` has been through normalize_command()."""
    text = text.strip().rstrip("?.!")
    if m := _PORT_INFO.match(text):
        return {"type": "system", "action": "port_info", "port": int(m["port"] or m["p2"])}
    if _LIST.match(text):
        return {"type": "system", "action": "list_servers"}
    if m := _STOP.match(text):
        if m["port"]:
            return {"type": "system", "action": "stop_server", "port": int(m["port"])}
        return {"type": "system", "action": "stop_server", "project": m["name"].strip()} \
            if m["name"].strip().lower() in projects.load() else None
    if m := _CI.match(text):
        return {"type": "system", "action": "ci_status", "name": (m["name"] or "").strip()}
    if m := _OUTDATED.match(text):
        return {"type": "system", "action": "outdated", "name": (m["name"] or "").strip()}
    return None


# ── Dev servers ───────────────────────────────────────────────────────────────

def servers() -> list[dict]:
    """Listening TCP ports of dev programs (not Windows' own, not FRIDAY): port, pid, program, project/folder."""
    saved = projects.load()
    found, seen = [], {config.API_PORT}  # FRIDAY itself (its reloader may own the socket, not this process)
    try:
        listening = [c for c in psutil.net_connections(kind="tcp") if c.status == psutil.CONN_LISTEN and c.pid]
    except (psutil.Error, OSError) as e:
        raise AutomationError(f"I couldn't list the ports: {e}") from None
    for conn in sorted(listening, key=lambda c: c.laddr.port):
        if conn.pid == os.getpid() or conn.laddr.port in seen:
            continue
        try:
            proc = psutil.Process(conn.pid)
            name = proc.name().lower().removesuffix(".exe")
            exe = (proc.exe() or "").lower()
        except (psutil.Error, OSError):
            continue
        if name not in DEV_PROGRAMS or exe.startswith("c:\\windows"):
            continue
        try:
            folder = Path(proc.cwd())
            where = projects.project_of_folder(projects.git_root(folder), saved) or folder.name
        except (psutil.Error, OSError, ValueError):
            where = ""
        seen.add(conn.laddr.port)
        found.append({"port": conn.laddr.port, "pid": conn.pid, "program": name, "where": where})
    return found


def _describe(s: dict) -> str:
    return f"port {s['port']}: {s['program']}" + (f" in {s['where']}" if s["where"] else "")


def port_info(port: int) -> str:
    for s in servers():
        if s["port"] == port:
            return _describe(s)[0].upper() + _describe(s)[1:] + "."
    return f"Nothing from a dev program is listening on port {port}."


def list_servers() -> str:
    found = servers()
    return ("Running: " + "; ".join(_describe(s) for s in found) + ".") if found else "No dev servers are running."


def server_for(parsed: dict) -> dict:
    """The server a stop command means (raises AutomationError if there isn't one)."""
    found = servers()
    if "port" in parsed:
        match = next((s for s in found if s["port"] == parsed["port"]), None)
        if not match:
            raise AutomationError(f"Nothing from a dev program is listening on port {parsed['port']}.")
        return match
    name = parsed["project"].lower()
    match = next((s for s in found if s["where"].lower() == name), None)
    if not match:
        raise AutomationError(f"{parsed['project']} doesn't have a dev server running.")
    return match


def stop_server(server: dict) -> str:
    """Stop the program serving the port, and the programs it started."""
    try:
        proc = psutil.Process(server["pid"])
        family = proc.children(recursive=True) + [proc]
    except psutil.Error:
        return f"Port {server['port']} is already free."
    for p in family:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(family, timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    logger.info(f"Stopped the dev server on port {server['port']} ({server['program']})")
    return f"Stopped {server['program']} on port {server['port']}" + (f" ({server['where']})." if server["where"] else ".")


# ── CI and packages ───────────────────────────────────────────────────────────

def _run(args: list[str], folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
                          creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8", errors="replace")


def _folders(name: str) -> dict[str, Path]:
    saved = projects.load()
    if not saved:
        raise AutomationError('You haven\'t saved any projects. Open one and say "this is a project".')
    if name:
        if name.lower() not in saved:
            raise AutomationError(f"You don't have a project called {name}.")
        saved = {name.lower(): saved[name.lower()]}
    return {n: Path(info["path"]) for n, info in saved.items()}


def _ago(stamp: str, now: datetime) -> str:
    minutes = int((now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() // 60)
    return f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h ago" if minutes < 48 * 60 else f"{minutes // 1440} days ago"


def ci_status(name: str = "", now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = []
    for project, folder in _folders(name).items():
        try:
            done = _run(["gh", "run", "list", "-L", "1", "--json", "status,conclusion,workflowName,headBranch,createdAt"], folder)
        except (OSError, subprocess.TimeoutExpired):
            raise AutomationError("I couldn't run gh (the GitHub CLI) — is it installed?") from None
        if done.returncode:
            reason = "not signed in to gh (run: gh auth login)" if "auth" in done.stderr.lower() else "no GitHub repo or Actions"
            lines.append(f"{project}: {reason}")
            continue
        runs = json.loads(done.stdout or "[]")
        if not runs:
            lines.append(f"{project}: no CI runs")
            continue
        r = runs[0]
        state = r["conclusion"] or r["status"].replace("_", " ")
        word = {"success": "passed", "failure": "failed", "cancelled": "was cancelled"}.get(state, state)
        lines.append(f"{project}: {r['workflowName']} {word} on {r['headBranch']} {_ago(r['createdAt'], now)}")
    return "; ".join(lines) + "."


def outdated(name: str = "") -> str:
    lines = []
    for project, folder in _folders(name).items():
        found: list[str] = []
        if (folder / "package.json").exists():
            done = _run(["npm.cmd", "outdated", "--json"], folder)  # exit code 1 = something is outdated
            found += list(json.loads(done.stdout or "{}"))
        venv = next((folder / v / "Scripts" / "python.exe" for v in ("venv", ".venv") if (folder / v).is_dir()), None)
        if venv and venv.exists():
            done = _run([str(venv), "-m", "pip", "list", "--outdated", "--format", "json"], folder)
            found += [p["name"] for p in json.loads(done.stdout or "[]")]
        if found:
            lines.append(f"{project}: {len(found)} outdated ({', '.join(found[:5])}{'…' if len(found) > 5 else ''})")
    return ("Outdated packages — " + "; ".join(lines) + ".") if lines else "Everything's up to date (npm and venv packages)."
