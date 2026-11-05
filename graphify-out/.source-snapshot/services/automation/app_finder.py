"""
services/automation/app_finder.py

Finds an app to open by name with Everything (voidtools), so apps don't have
to be listed in APP_REGISTRY with their paths.

  find_app("arduino")    → ...\\Start Menu\\Programs\\Arduino IDE.lnk
  find_app("black myth") → C:\\games\\Black Myth Wukong\\b1.exe  (no file name matched, so by folder)

Asks Everything through its command-line tool es.exe (voidtools.Everything.Cli)
for shortcuts and programs whose file name has all the words; if none do, for
programs whose folder path has them (games have names like b1.exe). The best
one wins: a Start Menu shortcut, then a Desktop one, then a program, an exact
name before a partial one, the least-nested before a deep one. Installers,
uninstallers, updaters and anything under Windows or temp folders are skipped;
Downloads (where games get unpacked) is used only when nothing else matches. Everything must be running (it sits in the tray); if it isn't
(es exit 8 — only its service is up after a restart), it's started quietly and
the search is tried again.

Closing: app_windows() + close_windows() send an app's visible windows the
same close message Alt+F4 sends (WM_SYSCOMMAND SC_CLOSE), so unsaved work
still gets its "save?" prompt. The key press itself isn't used: FRIDAY runs in
the background and Windows often won't bring another window to the front, so
Alt+F4 would close whatever window happens to be there instead.
"""

import ctypes
import os
import re
import shutil
import subprocess
import time
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path
from typing import Callable

import comtypes
import comtypes.client
import psutil

from core.logger import logger

MAX_RESULTS = 100
# Programs and shortcuts that are never what "open X" means
SKIP_NAME = re.compile(
    r"unins|setup|install|update|crash|report|helper|redist|dxsetup|elevat|bootstrap|"
    r"readme|help|manual|documentation|license|website|uninstall|repair|debug|squirrel|notification",
    re.I,
)
SKIP_PATH = re.compile(
    r"^[a-z]:\\windows\\|\\\$recycle\.bin\\|\\windowsapps\\|\\temp\\|\\cache\\|"
    r"\\node_modules\\|\\site-packages\\|\\venv\\|\\\.git\\|\\prefetch\\|\\recent\\|\\winget\\packages\\",
    re.I,
)
EVERYTHING_EXE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Everything" / "Everything.exe"
NOT_RUNNING = 8  # es.exe: "Everything IPC not found"
START_WAIT_SECONDS = 20  # the first load after a restart took ~10 s
DOWNLOADS = re.compile(r"\\downloads\\", re.I)  # games get unpacked there: allowed, but only when nothing else matches
START_MENU = re.compile(r"\\start menu\\", re.I)
DESKTOP = re.compile(r"\\desktop\\", re.I)


@lru_cache(maxsize=1)
def es_path() -> str | None:
    """es.exe: on PATH, or where winget put it (the backend may predate the PATH change)."""
    found = shutil.which("es")
    if found:
        return found
    packages = Path(os.environ.get("LOCALAPPDATA", ""), "Microsoft/WinGet/Packages")
    return next((str(p) for p in packages.glob("voidtools.Everything.Cli*/es.exe")), None)


def _start_everything() -> bool:
    """Start Everything in the tray (no window) so es.exe can ask it. True if it's there to ask."""
    if not EVERYTHING_EXE.exists():
        return False
    logger.info("Everything isn't running — starting it in the tray")
    try:
        subprocess.Popen([str(EVERYTHING_EXE), "-startup"], creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as e:
        logger.warning(f"Couldn't start Everything: {e}")
        return False
    return True


def _everything(args: list[str], retry: bool = True) -> list[str]:
    """Paths Everything returns for a search; [] if es.exe is missing or Everything can't be reached."""
    es = es_path()
    if not es:
        logger.warning("Everything's es.exe isn't installed — can't look up apps")
        return []
    try:
        result = subprocess.run(
            [es, "-cp", "65001", "-n", str(MAX_RESULTS), *args],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Everything search failed: {e}")
        return []
    if result.returncode == NOT_RUNNING and retry and _start_everything():
        deadline = time.monotonic() + START_WAIT_SECONDS
        while time.monotonic() < deadline:  # its window (the IPC es.exe talks to) takes a moment to appear
            time.sleep(0.5)
            if (found := _everything(args, retry=False)) or not _ipc_missing():
                return found
        return []
    if result.returncode != 0:  # e.g. 8: Everything isn't running
        logger.warning(f"Everything search failed (es exit {result.returncode}): {result.stderr.strip()}")
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def wake_everything() -> None:
    """At FRIDAY's start: make sure Everything is up (and has loaded) before the first "open X"."""
    _everything(["-get-result-count", "*.lnk"])


def _ipc_missing() -> bool:
    """True while Everything's window isn't up yet (es.exe can't reach it)."""
    return not ctypes.windll.user32.FindWindowW("EVERYTHING_TASKBAR_NOTIFICATION", None)


def _usable(path: str) -> bool:
    return not SKIP_PATH.search(path) and not SKIP_NAME.search(Path(path).stem)


def _rank(path: str, name: str, words: list[str]) -> tuple:
    """Lower is better: exact name, then whole words ("code" isn't "Unicode"), then where it lives, then shortest."""
    p = Path(path)
    stem = p.stem.lower()
    exact = 0 if re.sub(r"[\s_.-]", "", stem) == re.sub(r"\s", "", name) else 1
    whole = 0 if all(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", stem) for w in words) else 1
    is_link = p.suffix.lower() == ".lnk"
    place = 0 if is_link and START_MENU.search(path) else 1 if is_link and DESKTOP.search(path) else 2 if not is_link else 3
    return bool(DOWNLOADS.search(path)), exact, whole, place, len(p.parts), len(stem)


def find_app(name: str) -> str | None:
    """The shortcut or program to open for `name`, or None."""
    name = name.lower().strip()
    words = re.findall(r"[\w+#]+", name)
    if not words:
        return None
    # ponytail: file-name words, then folder words; an app known by a nickname ("vs code") needs an APP_SEARCH_NAMES entry
    hits = [p for p in _everything(["ext:exe;lnk", *words]) if _usable(p)]
    if not hits:  # games: "black myth" is the folder, the program is b1.exe
        hits = [p for p in _everything(["-p", "ext:exe", *words]) if _usable(p)]
    if not hits:
        return None
    best = min(hits, key=lambda p: _rank(p, name, words))
    logger.info(f"Everything found '{name}' → {best}")
    return best


# ── Closing ───────────────────────────────────────────────────────────────────

WM_SYSCOMMAND, SC_CLOSE, GW_OWNER, SW_MINIMIZE, SW_RESTORE = 0x0112, 0xF060, 4, 6, 9
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def shortcut_target(path: str) -> str:
    """The program a .lnk shortcut starts ("" if it has none, like Store-app shortcuts)."""
    comtypes.CoInitialize()  # this runs on worker threads
    try:
        return comtypes.client.CreateObject("WScript.Shell", dynamic=True).CreateShortcut(path).TargetPath or ""
    finally:
        comtypes.CoUninitialize()


def app_windows(is_app: Callable[[psutil.Process], bool]) -> list[int]:
    """Visible, titled top-level windows (what Alt+F4 would close) whose process `is_app` accepts."""
    user32 = ctypes.windll.user32
    found = []

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) and not user32.GetWindow(hwnd, GW_OWNER):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                if pid.value != os.getpid() and is_app(psutil.Process(pid.value)):
                    found.append(hwnd)
            except psutil.Error:
                pass  # gone, or an admin process we can't look at
        return True

    user32.EnumWindows(_WNDENUMPROC(visit), 0)
    return found


def bring_to_front(hwnd: int) -> bool:
    """
    Show a window on top. Windows only lets the program that has the foreground move it elsewhere, and
    FRIDAY runs in the background, so it briefly joins the foreground window's input to be allowed to.
    """
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    front = user32.GetForegroundWindow()
    front_thread = user32.GetWindowThreadProcessId(front, None) if front else 0
    ours = kernel32.GetCurrentThreadId()
    attached = bool(front_thread) and front_thread != ours and user32.AttachThreadInput(ours, front_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(ours, front_thread, False)


def minimize_windows(hwnds: list[int]) -> None:
    for hwnd in hwnds:
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)


def close_windows(hwnds: list[int]) -> int:
    """Send each window Alt+F4's close message; returns how many accepted it (admin apps refuse)."""
    post = ctypes.windll.user32.PostMessageW
    return sum(1 for hwnd in hwnds if post(hwnd, WM_SYSCOMMAND, SC_CLOSE, 0))
