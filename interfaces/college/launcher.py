"""Separate native window, named mutex and existing managed backend bootstrap."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

TITLE = 'FRIDAY - College Schedules'
MUTEX = 'Local\\FRIDAY.CollegeSchedules'
ROOT = Path(__file__).resolve().parents[2]


def launch():
    executable = Path(sys.executable)
    if os.name == 'nt' and executable.with_name('pythonw.exe').is_file():
        executable = executable.with_name('pythonw.exe')
    subprocess.Popen([str(executable), '-B', '-m', 'interfaces.college'], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def focus_existing(timeout=5):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    deadline = time.monotonic() + timeout
    while True:
        window = user.FindWindowW(None, TITLE)
        if window:
            user.ShowWindow(window, 9)
            return bool(user.SetForegroundWindow(window))
        if time.monotonic() >= deadline:
            return False
        time.sleep(.05)


def acquire_instance():
    if os.name != 'nt':
        return True
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        focus_existing()
        return None
    return handle


def release_instance(handle):
    if os.name == 'nt' and handle:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)


def dpi_awareness():
    if os.name == 'nt':
        try:
            ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def ensure_backend():
    """Run in a worker. Taskbar runtime remains the backend's lifecycle owner."""
    import json
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:8000/health', timeout=2) as response:
            data = json.loads(response.read())
            if isinstance(data, dict) and data.get('service') == 'F.R.I.D.A.Y':
                return
    except (OSError, ValueError):
        pass
    executable = ROOT / 'venv' / 'Scripts' / 'pythonw.exe'
    if not executable.is_file():
        raise FileNotFoundError('Project venv pythonw.exe was not found. Start FRIDAY manually, then Retry.')
    subprocess.Popen([str(executable), '-B', str(ROOT / 'interfaces' / 'taskbar' / 'launch.py')], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
