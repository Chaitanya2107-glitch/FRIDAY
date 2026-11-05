"""Launch one independent Tk process, focusing its existing window on Windows."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time

TITLE = 'FRIDAY - Habits & To-do'
ROOT = Path(__file__).resolve().parents[2]


def launch(view='today'):
    executable = Path(sys.executable)
    if os.name == 'nt' and executable.with_name('pythonw.exe').is_file():
        executable = executable.with_name('pythonw.exe')
    subprocess.Popen([str(executable), '-B', '-m', 'interfaces.productivity', '--view', view], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def instance():
    if os.name != 'nt':
        return True
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, 'Local\\FRIDAY.Productivity')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() != 183:
        return handle
    kernel.CloseHandle(handle)
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        window = user.FindWindowW(None, TITLE)
        if window:
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)
            break
        time.sleep(.05)
    return None


def main(view='today'):
    handle = instance()
    if handle is None:
        return
    try:
        if os.name == 'nt':
            try:
                ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            except (AttributeError, OSError):
                ctypes.windll.user32.SetProcessDPIAware()
        import tkinter as tk
        from interfaces.productivity.app import ProductivityWindow
        root = tk.Tk()
        ProductivityWindow(root, view=view)
        root.mainloop()
    finally:
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
