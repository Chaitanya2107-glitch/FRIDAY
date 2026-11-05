"""Independent native window; one control center per Windows desktop."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TITLE = 'FRIDAY · Control Center'


def launch():
    executable = Path(sys.executable)
    if os.name == 'nt' and executable.with_name('pythonw.exe').is_file():
        executable = executable.with_name('pythonw.exe')
    subprocess.Popen([str(executable), '-B', '-m', 'interfaces.control_center'], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def start_desktop():
    executable = ROOT / 'venv' / 'Scripts' / ('pythonw.exe' if os.name == 'nt' else 'python')
    if not executable.is_file():
        raise FileNotFoundError('Project Python was not found. Start FRIDAY with launch_friday.vbs, then Refresh.')
    subprocess.Popen([str(executable), '-B', str(ROOT / 'interfaces/taskbar/launch.py')], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return 'FRIDAY desktop requested. Cold startup can take a few minutes; Refresh checks readiness.'


def open_editor(name):
    if name == 'customization':
        from interfaces.settings.launcher import launch as open_window
    elif name == 'college':
        from interfaces.college.launcher import launch as open_window
    elif name == 'productivity':
        from interfaces.productivity.launcher import launch as open_window
    else:
        raise ValueError('Unknown native editor.')
    open_window()
    return 'Opened the native editor.'


def main():
    import ctypes
    from ctypes import wintypes
    handle = None
    if os.name == 'nt':
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        ctypes.set_last_error(0)
        handle = kernel.CreateMutexW(None, False, 'Local\\FRIDAY.ControlCenter')
        if not handle:
            raise OSError('Could not acquire the control center window lock.')
        if ctypes.get_last_error() == 183:
            user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user.FindWindowW.restype = wintypes.HWND
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.SetForegroundWindow.argtypes = [wintypes.HWND]
            window = user.FindWindowW(None, TITLE)
            if window:
                user.ShowWindow(window, 9)
                user.SetForegroundWindow(window)
            kernel.CloseHandle(handle)
            return
        try:
            user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            user.SetProcessDPIAware()
    try:
        import tkinter as tk
        from interfaces.control_center.app import ControlCenter
        root = tk.Tk()
        ControlCenter(root)
        root.mainloop()
    finally:
        if handle:
            kernel.CloseHandle(handle)
