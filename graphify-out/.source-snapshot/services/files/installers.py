"""
services/files/installers.py

Old installers left in Downloads: "what installers are in my downloads", "delete my installers".
Only files directly in Downloads (not subfolders), older than MIN_AGE_HOURS so one you're
about to run is never touched. Deleting asks first and moves them to the Recycle Bin.
"""

import re
import time
from pathlib import Path

from services.automation.system_control import AutomationError

INSTALLER_ACTIONS = {"list_installers", "delete_installers"}
EXTENSIONS = {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"}
DOWNLOADS = Path.home() / "Downloads"  # tests point this elsewhere
MIN_AGE_HOURS = 24
SHOWN = 5

_DELETE = re.compile(r"^(?:delete|remove|clean up|clear(?: out)?|get rid of|trash|bin)(?: all)?(?: of)?"
                     r" (?:my |the |old |all )*installers?(?: files)?(?: (?:in|from) (?:my |the )?downloads)?$", re.I)
_LIST = re.compile(r"^(?:(?:list|show|find)(?: me)? (?:my |the |old )*installers?(?: files)?(?: in (?:my |the )?downloads)?"
                   r"|what installers (?:are|do i have)(?: in (?:my |the )?downloads)?)$", re.I)


def match_installer_command(text: str) -> dict | None:
    text = text.strip().rstrip(".!?")
    if _DELETE.match(text):
        return {"type": "system", "action": "delete_installers"}
    if _LIST.match(text):
        return {"type": "system", "action": "list_installers"}
    return None


def find(now: float | None = None) -> list[Path]:
    cutoff = (now or time.time()) - MIN_AGE_HOURS * 3600
    try:
        files = [f for f in DOWNLOADS.iterdir() if f.suffix.lower() in EXTENSIONS and f.is_file()]
    except FileNotFoundError:
        return []
    except OSError as e:
        raise AutomationError(f"I couldn't look in Downloads: {e}")
    return sorted((f for f in files if f.stat().st_mtime < cutoff), key=lambda f: -f.stat().st_size)


def _size(files: list[Path]) -> str:
    total = sum(f.stat().st_size for f in files)
    return f"{total / 1e9:.1f} GB" if total >= 1e9 else f"{max(1, round(total / 1e6))} MB"


def describe(files: list[Path]) -> str:
    names = ", ".join(f.name for f in files[:SHOWN]) + (f" and {len(files) - SHOWN} more" if len(files) > SHOWN else "")
    return f"{len(files)} installer{'s' if len(files) != 1 else ''} ({_size(files)}): {names}"


def question() -> str | None:
    """The yes/no question before deleting, or None if there's nothing to delete."""
    files = find()
    return f"Move {describe(files)} to the Recycle Bin? Say yes or no." if files else None


def list_message() -> str:
    files = find()
    return f"In Downloads: {describe(files)}. Say \"delete my installers\" to bin them." if files \
        else "No old installers in Downloads."


def _recycle(files: list[Path]) -> None:
    from win32com.shell import shell, shellcon

    flags = shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI
    result, aborted = shell.SHFileOperation((0, shellcon.FO_DELETE, "\0".join(map(str, files)), None, flags, None, None))
    if result or aborted:
        raise AutomationError(f"Windows couldn't move them to the Recycle Bin (error {result}).")


def delete() -> str:
    files = find()  # looked up again: the list may have changed since the question
    if not files:
        return "No old installers in Downloads."
    size = _size(files)
    _recycle(files)
    return f"Moved {len(files)} installer{'s' if len(files) != 1 else ''} ({size}) to the Recycle Bin."
