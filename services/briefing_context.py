"""Read-only input/fullscreen/battery metadata; never window text or screenshots."""
import ctypes
from ctypes import wintypes as W
import os


class LastInput(ctypes.Structure):
    _fields_ = [('cbSize', W.UINT), ('dwTime', W.DWORD)]


class Monitor(ctypes.Structure):
    _fields_ = [('cbSize', W.DWORD), ('screen', W.RECT), ('work', W.RECT), ('flags', W.DWORD)]


def desktop():
    unknown = dict(active=False, fullscreen=None)
    if os.name != 'nt':
        return unknown
    try:
        user, kernel = ctypes.WinDLL('user32'), ctypes.WinDLL('kernel32')
        signatures = {
            'GetForegroundWindow': ([], W.HWND), 'GetShellWindow': ([], W.HWND), 'GetDesktopWindow': ([], W.HWND),
            'IsIconic': ([W.HWND], W.BOOL), 'GetWindowRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'MonitorFromWindow': ([W.HWND, W.DWORD], W.HANDLE),
            'GetMonitorInfoW': ([W.HANDLE, ctypes.POINTER(Monitor)], W.BOOL),
            'GetClassNameW': ([W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetLastInputInfo': ([ctypes.POINTER(LastInput)], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(user, name)
            fn.argtypes, fn.restype = args, result
        info = LastInput(ctypes.sizeof(LastInput), 0)
        active = bool(user.GetLastInputInfo(ctypes.byref(info)) and
                      ((kernel.GetTickCount() - info.dwTime) & 0xffffffff) / 1000 <= 30)
        hwnd = user.GetForegroundWindow()
        if not hwnd:
            return dict(active=active, fullscreen=None)
        name = ctypes.create_unicode_buffer(128)
        user.GetClassNameW(hwnd, name, 128)
        if hwnd in {user.GetShellWindow(), user.GetDesktopWindow()} or name.value in {
                'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'} or user.IsIconic(hwnd):
            return dict(active=active, fullscreen=False)
        user.SetThreadDpiAwarenessContext.argtypes, user.SetThreadDpiAwarenessContext.restype = [W.HANDLE], W.HANDLE
        previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            rect, monitor = W.RECT(), Monitor()
            monitor.cbSize = ctypes.sizeof(Monitor)
            if not user.GetWindowRect(hwnd, ctypes.byref(rect)) or not user.GetMonitorInfoW(
                    user.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor)):
                return dict(active=active, fullscreen=None)
            screen = monitor.screen
            fullscreen = rect.left <= screen.left and rect.top <= screen.top and rect.right >= screen.right and rect.bottom >= screen.bottom
            return dict(active=active, fullscreen=fullscreen)
        finally:
            if previous:
                user.SetThreadDpiAwarenessContext(previous)
    except (OSError, AttributeError):
        return unknown


def battery():
    try:
        import psutil
        value = psutil.sensors_battery()
        return dict(percent=value.percent, plugged=value.power_plugged, charging=value.power_plugged) if value else None
    except (OSError, RuntimeError, ImportError):
        return None
