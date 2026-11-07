"""Read-only Win32 metadata sampling; raw titles exist only inside sample()."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import os
from typing import Protocol

import psutil

from .policy import Policy, Sample


class ForegroundProvider(Protocol):
    def sample(self) -> Sample: ...


class LastInput(ctypes.Structure):
    _fields_ = [('cbSize', W.UINT), ('dwTime', W.DWORD)]


class MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT), ('dwFlags', W.DWORD)]


class WindowsForegroundProvider:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.user = self.kernel = None

    def _bind(self):
        if os.name != 'nt':
            return False
        if self.user is not None:
            return True
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.child_callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = {
            'GetForegroundWindow': ([], W.HWND), 'GetDesktopWindow': ([], W.HWND), 'GetShellWindow': ([], W.HWND),
            'GetWindowThreadProcessId': ([W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            'GetWindowTextW': ([W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetClassNameW': ([W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetLastInputInfo': ([ctypes.POINTER(LastInput)], W.BOOL),
            'GetWindowRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'MonitorFromWindow': ([W.HWND, W.DWORD], W.HANDLE),
            'GetMonitorInfoW': ([W.HANDLE, ctypes.POINTER(MonitorInfo)], W.BOOL),
            'EnumChildWindows': ([W.HWND, self.child_callback, W.LPARAM], W.BOOL),
            'IsWindowVisible': ([W.HWND], W.BOOL), 'IsIconic': ([W.HWND], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result
        self.kernel.GetTickCount.argtypes, self.kernel.GetTickCount.restype = [], W.DWORD
        if hasattr(self.user, 'SetThreadDpiAwarenessContext'):
            self.user.SetThreadDpiAwarenessContext.argtypes = [W.HANDLE]
            self.user.SetThreadDpiAwarenessContext.restype = W.HANDLE
        return True

    def _process(self, hwnd):
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return 0, None
        try:
            return pid.value, psutil.Process(pid.value).name().lower()
        except (psutil.Error, OSError, ValueError):
            return pid.value, None

    def _class(self, hwnd):
        buf = ctypes.create_unicode_buffer(256)
        self.user.GetClassNameW(hwnd, buf, len(buf))
        return buf.value

    def _uwp_process(self, hwnd, frame_pid):
        found = []
        def child(window, data):
            if not self.user.IsWindowVisible(window):
                return True
            pid, process = self._process(window)
            if process and pid != frame_pid and process != 'applicationframehost.exe':
                found.append((self._class(window) == 'Windows.UI.Core.CoreWindow', process))
            return True
        callback = self.child_callback(child)
        self.user.EnumChildWindows(hwnd, callback, 0)
        return max(found, key=lambda row: row[0])[1] if found else None

    def _fullscreen(self, hwnd):
        context = getattr(self.user, 'SetThreadDpiAwarenessContext', None)
        previous = context(ctypes.c_void_p(-4)) if context else None
        try:
            return self._fullscreen_rect(hwnd)
        finally:
            if previous:
                context(previous)

    def _fullscreen_rect(self, hwnd):
        if (hwnd in {self.user.GetDesktopWindow(), self.user.GetShellWindow()} or self.user.IsIconic(hwnd)
                or self._class(hwnd) in {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}):
            return False
        rect, info = W.RECT(), MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        monitor = self.user.MonitorFromWindow(hwnd, 2)
        if not monitor or not self.user.GetWindowRect(hwnd, ctypes.byref(rect)) or not self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        screen = info.rcMonitor
        return bool(rect.right > rect.left and rect.bottom > rect.top and rect.left <= screen.left
                    and rect.top <= screen.top and rect.right >= screen.right and rect.bottom >= screen.bottom)

    def sample(self) -> Sample:
        if not self._bind():
            return Sample()
        info = LastInput(ctypes.sizeof(LastInput), 0)
        if not self.user.GetLastInputInfo(ctypes.byref(info)):
            return Sample()  # Fail closed when input-idle state is unavailable.
        idle = ((self.kernel.GetTickCount() - info.dwTime) & 0xffffffff) / 1000
        if idle >= self.policy.number('idle_seconds'):
            return Sample(idle_seconds=idle)
        hwnd = self.user.GetForegroundWindow()
        if not hwnd:
            return Sample(idle_seconds=idle)
        pid, process = self._process(hwnd)
        if process == 'applicationframehost.exe':
            process = self._uwp_process(hwnd, pid)
        if not process:
            return Sample(idle_seconds=idle)
        buf = ctypes.create_unicode_buffer(1024)
        try:
            self.user.GetWindowTextW(hwnd, buf, len(buf))
            return self.policy.sanitize(process, buf.value, idle, self._fullscreen(hwnd))
        finally:
            ctypes.memset(ctypes.addressof(buf), 0, ctypes.sizeof(buf))
