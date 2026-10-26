"""Windows identity, single-instance activation and widget shortcuts."""

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "FRIDAY.Desktop.Controls"
MUTEX_NAME = "FridayTrayMutex"
WINDOW_TITLE = "FRIDAY - Control panel"
ICON_PATH = ROOT / "assets" / "friday.ico"
LAUNCH_PATH = ROOT / "interfaces" / "taskbar" / "launch.py"


def prepare_process() -> None:
    """Resolve relative settings and give pythonw useful, UTF-8 diagnostics."""
    os.chdir(ROOT)
    if sys.stdout is None or sys.stderr is None:
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        stream = (logs / "desktop.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def pythonw() -> Path:
    executable = Path(sys.executable).with_name("pythonw.exe").resolve()
    if not executable.is_file():
        raise FileNotFoundError("FRIDAY needs the project's Windows Python environment.")
    return executable


def relaunch_command() -> str:
    return subprocess.list2cmdline([str(pythonw()), "-B", str(LAUNCH_PATH)])


def focus_existing(timeout: float = 5) -> bool:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    deadline = time.monotonic() + timeout
    while True:
        host = user.FindWindowW("FridayTaskbarHost", None)
        if host:
            return bool(user.PostMessageW(host, 0x8000 + 41, 1, 0))
        hwnd = user.FindWindowW(None, WINDOW_TITLE)
        if hwnd and user.IsWindowVisible(hwnd) and not user.GetWindowLongW(hwnd, -20) & 0x80:
            user.ShowWindow(hwnd, 9)  # SW_RESTORE, including a minimized panel
            return bool(user.SetForegroundWindow(hwnd))
        if time.monotonic() >= deadline:
            return False
        time.sleep(.1)


def acquire_instance() -> int | None:
    """Acquire the desktop lock before starting any backend or registering hotkeys."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        focus_existing()
        return None
    return handle


def release_instance(handle: int) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle(handle)


def create_backend_stop() -> tuple[str, int]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    name = "Local\\FRIDAY.BackendStop." + uuid.uuid4().hex
    handle = kernel.CreateEventW(None, True, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return name, handle


def signal_backend_stop(handle: int) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    if not kernel.SetEvent(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def wait_for_backend_stop(name: str, owner_pid: int) -> None:
    """Wait on a private event or the desktop owner's exit, without touching stdin."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
    kernel.WaitForMultipleObjects.restype = wintypes.DWORD
    event = kernel.OpenEventW(0x100000, False, name)  # SYNCHRONIZE
    owner = kernel.OpenProcess(0x100000, False, owner_pid)
    try:
        if not event or not owner:
            return  # The owner may already have exited during startup.
        handles = (wintypes.HANDLE * 2)(event, owner)
        if kernel.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        for handle in (event, owner):
            if handle:
                release_instance(handle)


def _properties(store) -> None:
    from win32com.propsys import propsys, pscon
    for key, value in (
        (pscon.PKEY_AppUserModel_ID, APP_ID),
        (pscon.PKEY_AppUserModel_RelaunchCommand, relaunch_command()),
        (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "FRIDAY"),
        (pscon.PKEY_AppUserModel_RelaunchIconResource, str(ICON_PATH)),
    ):
        store.SetValue(key, propsys.PROPVARIANTType(value))
    store.Commit()


def configure_window(hwnd: int) -> None:
    """The running button and the pinned shortcut must have the same identity."""
    import pythoncom
    from win32com.propsys import propsys
    pythoncom.CoInitialize()
    try:
        _properties(propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore))
    finally:
        pythoncom.CoUninitialize()


def create_shortcut(destination: Path) -> Path:
    import pythoncom
    from win32com.propsys import propsys
    from win32com.shell import shell
    destination = destination.resolve()
    if destination.suffix.lower() != ".lnk":
        raise ValueError("A Windows shortcut must use the .lnk extension.")
    pythoncom.CoInitialize()
    try:
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                         pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        link.SetPath(str(pythonw()))
        link.SetArguments(subprocess.list2cmdline(["-B", str(LAUNCH_PATH)]))
        link.SetWorkingDirectory(str(ROOT))
        link.SetDescription("Show the FRIDAY taskbar button and controls")
        link.SetIconLocation(str(ICON_PATH), 0)
        _properties(link.QueryInterface(propsys.IID_IPropertyStore))
        destination.parent.mkdir(parents=True, exist_ok=True)
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(destination), 0)
    finally:
        pythoncom.CoUninitialize()
    return destination
