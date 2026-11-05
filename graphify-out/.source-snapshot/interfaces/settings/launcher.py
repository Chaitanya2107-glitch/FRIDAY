"""Start the editor independently of the command bar and body Tk threads."""
import os
from pathlib import Path
import subprocess
import sys

TITLE = 'FRIDAY · Customize'


def launch():
    subprocess.Popen([sys.executable, '-m', 'interfaces.settings'],
                     cwd=Path(__file__).resolve().parents[2],
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def instance():
    """Keep one native editor; a second tray click brings its window forward."""
    if os.name != 'nt':
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, 'FridayCustomizationWindow')
    if ctypes.get_last_error() == 183:
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user.FindWindowW.restype = wintypes.HWND
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        window = user.FindWindowW(None, TITLE)
        if window:
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)
        return False
    return handle
