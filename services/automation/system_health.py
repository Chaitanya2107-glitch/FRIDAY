"""
services/automation/system_health.py

Longer-term health questions, answered locally:
  "how's my battery health"       — full charge vs design capacity, and charge cycles (powercfg's
                                    battery report: WMI's design capacity needs admin rights)
  "how long has the laptop been on" — since the last restart (shutting down with Fast Startup doesn't
                                    reset it), and whether a restart is waiting
  "do I need to restart"          — Windows Update / servicing asked for one (registry)
  "what's taking up space"        — the biggest files on C (Everything), added up per folder
Boot duration isn't here: its event log (Diagnostics-Performance) needs admin rights.
"""

import os
import re
import subprocess
import tempfile
import time
import winreg
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import psutil

from services.automation import app_finder
from services.automation.system_control import AutomationError

HEALTH_ACTIONS = {"battery_health", "uptime", "pending_restart", "disk_hogs"}
HOG_FILES = 300  # the largest files looked at
HOGS_SHOWN = 6
SYSTEM_FILES = re.compile(r"^[a-z]:\\(?:windows\\|pagefile\.sys|hiberfil\.sys|swapfile\.sys|system volume information\\)", re.I)
RESTART_KEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
)

_PATTERNS = {
    "battery_health": re.compile(r"^(?:(?:how(?:'s| is)|check|what(?:'s| is)) (?:my |the )?battery(?:'s)? (?:health|wear|capacity|condition)"
                                 r"|battery (?:health|wear)|how (?:healthy|worn(?: out)?|good) is (?:my |the )?battery)$", re.I),
    "uptime": re.compile(r"^(?:uptime|how long (?:has|have) (?:the |my )?(?:laptop|pc|computer|windows|it|you) been (?:on|running|up)"
                         r"|when did i (?:last )?(?:turn on|start|boot|restart) (?:the |my )?(?:laptop|pc|computer))$", re.I),
    "pending_restart": re.compile(r"^(?:do i (?:need|have) to restart(?: (?:the |my )?(?:laptop|pc|computer))?"
                                  r"|does (?:the |my )?(?:laptop|pc|computer|windows) need (?:a |to )?restart(?:ing)?"
                                  r"|is (?:a )?restart (?:pending|needed|required)|pending restart)$", re.I),
    "disk_hogs": re.compile(r"^(?:what(?:'s| is) (?:taking|using|eating|filling) (?:up )?(?:all )?(?:my |the )?(?:disk |drive |storage )?(?:space|disk|drive|storage)"
                            r"|disk hogs|(?:show |find )?(?:me )?(?:my |the )?(?:biggest|largest) (?:files|folders))$", re.I),
}


def match_health_command(text: str) -> dict | None:
    text = text.strip().rstrip("?.!")
    for action, pattern in _PATTERNS.items():
        if pattern.match(text):
            return {"type": "system", "action": action}
    return None


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n < 1e11 else f"{n / 1e9:.0f} GB"


# ── Battery ───────────────────────────────────────────────────────────────────

def _battery_report() -> tuple[int, int, int | None]:
    """(design mWh, full charge mWh, cycles) from powercfg's XML battery report (~1 s)."""
    out = Path(tempfile.gettempdir()) / f"friday_battery_{os.getpid()}.xml"
    try:
        subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", str(out)], capture_output=True,
                       timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        root = ET.parse(out).getroot()
    except (OSError, subprocess.TimeoutExpired, ET.ParseError) as e:
        raise AutomationError(f"Windows didn't give me a battery report ({e}).")
    finally:
        out.unlink(missing_ok=True)
    battery = next((el for el in root.iter() if el.tag.endswith("}Battery") or el.tag == "Battery"), None)
    if battery is None:
        raise AutomationError("This PC doesn't seem to have a battery.")
    values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in battery}
    cycles = values.get("CycleCount", "")
    return int(values["DesignCapacity"]), int(values["FullChargeCapacity"]), int(cycles) if cycles.isdigit() else None


def battery_health(report=_battery_report) -> str:
    design, full, cycles = report()
    if design <= 0:
        raise AutomationError("Windows doesn't know your battery's design capacity.")
    percent = round(100 * full / design)
    verdict = "healthy" if percent >= 80 else "worn — expect shorter battery life" if percent >= 60 else "badly worn"
    return (f"Your battery holds {percent}% of its original charge ({full / 1000:.1f} of {design / 1000:.1f} Wh) — {verdict}."
            + (f" {cycles} charge cycles so far." if cycles else ""))


# ── Uptime and restarts ───────────────────────────────────────────────────────

def restart_pending() -> bool:
    for key in RESTART_KEYS:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key))
            return True
        except OSError:
            continue
    return False


def _span(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return f"{days}d {hours}h" if days else f"{hours}h {minutes}m" if hours else f"{minutes}m"


def pending_restart_message() -> str:
    return ("Yes — Windows is waiting for a restart to finish installing updates." if restart_pending()
            else "No restart is waiting.")


def uptime(now: float | None = None, pending: bool | None = None) -> str:
    now = now or time.time()
    booted = psutil.boot_time()
    when = datetime.fromtimestamp(booted)
    day = "today" if when.date() == datetime.fromtimestamp(now).date() else when.strftime("%a %d %b")
    clock = f"{when:%I:%M %p}".lstrip("0")
    text = f"Windows has been running since {day} at {clock} ({_span(now - booted)} — since the last restart)."
    if restart_pending() if pending is None else pending:
        text += " A restart is waiting for updates."
    return text


# ── Disk hogs ─────────────────────────────────────────────────────────────────

def _group(path: str) -> str:
    """The folder a big file counts towards: C:\\games\\Black Myth Wukong, C:\\Users\\me\\Downloads\\kali…"""
    parts = Path(path).parts
    depth = 3
    if len(parts) > 2 and parts[1].lower() == "users":
        depth = 6 if len(parts) > 3 and parts[3].lower() == "appdata" else 5
    return str(Path(*parts[:min(depth, len(parts) - 1)]))


def disk_hogs(search=None) -> str:
    """The biggest space users, from the HOG_FILES largest files (Everything)."""
    lines = (search or app_finder._everything)(["-n", str(HOG_FILES), "-sort", "size-descending", "-size", "file:"])
    if not lines:
        raise AutomationError("I need Everything running to look for big files.")
    folders: dict[str, int] = {}
    for line in lines:
        m = re.match(r"^\s*([\d,]+)\s+(.+)$", line)
        if not m or SYSTEM_FILES.match(m[2]):
            continue
        size = int(m[1].replace(",", ""))
        folders[_group(m[2])] = folders.get(_group(m[2]), 0) + size
    top = sorted(folders.items(), key=lambda item: -item[1])[:HOGS_SHOWN]
    usage = psutil.disk_usage("C:\\")
    return ("Biggest space users (the largest files, added up per folder): "
            + "; ".join(f"{folder} {_gb(size)}" for folder, size in top)
            + f". Drive C: {_gb(usage.free)} free of {_gb(usage.total)}.")


def run(parsed: dict) -> str:
    """Blocking (powercfg, Everything) — run it in a thread."""
    return {"battery_health": battery_health, "uptime": uptime,
            "pending_restart": pending_restart_message, "disk_hogs": disk_hogs}[parsed["action"]]()
