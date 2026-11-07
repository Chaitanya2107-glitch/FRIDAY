"""Win32 behavior is simulated with Python functions; no desktop APIs run."""
import ctypes
from ctypes import wintypes as W
from types import SimpleNamespace

from plugins.activity.provider import LastInput, MonitorInfo, WindowsForegroundProvider
from activity_support import make_activity


def test_uwp_child_process_resolver_prefers_corewindow(tmp_path):
    activity = make_activity(tmp_path)
    provider = WindowsForegroundProvider(activity.policy)
    provider.child_callback = lambda fn: fn
    provider.user = SimpleNamespace(IsWindowVisible=lambda hwnd: True,
        EnumChildWindows=lambda frame, callback, data: [callback(window, data) for window in [1, 2, 3]])
    provider._process = lambda hwnd: {1: (100, 'applicationframehost.exe'), 2: (200, 'helper.exe'), 3: (300, 'calculator.exe')}[hwnd]
    provider._class = lambda hwnd: 'Windows.UI.Core.CoreWindow' if hwnd == 3 else 'Other'
    try:
        assert provider._uwp_process(99, 100) == 'calculator.exe'
    finally:
        activity.api.stop(); activity.tracker.close(); activity.manager.bus.close()


def test_fullscreen_uses_the_window_monitor_and_excludes_shell(tmp_path):
    activity = make_activity(tmp_path)
    provider = WindowsForegroundProvider(activity.policy)
    area = [1920, 0, 3840, 1080]
    def rect(hwnd, pointer):
        value = ctypes.cast(pointer, ctypes.POINTER(W.RECT)).contents
        value.left, value.top, value.right, value.bottom = area
        return True
    def monitor(handle, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(MonitorInfo)).contents
        info.rcMonitor = W.RECT(1920, 0, 3840, 1080)
        return True
    provider.user = SimpleNamespace(GetDesktopWindow=lambda: 1, GetShellWindow=lambda: 2,
        IsIconic=lambda hwnd: False, MonitorFromWindow=lambda hwnd, flags: 10,
        GetWindowRect=rect, GetMonitorInfoW=monitor)
    provider._class = lambda hwnd: 'MainWindow'
    try:
        assert provider._fullscreen(3)
        area[3] = 1040  # Maximized above a taskbar is not monitor-covering fullscreen.
        assert not provider._fullscreen(3)
        area[3] = 1080
        provider._class = lambda hwnd: 'Shell_TrayWnd'
        assert not provider._fullscreen(3)
        assert not provider._fullscreen(1)
    finally:
        activity.api.stop(); activity.tracker.close(); activity.manager.bus.close()


def test_last_input_wrap_and_missing_window_fail_closed(tmp_path):
    activity = make_activity(tmp_path)
    provider = WindowsForegroundProvider(activity.policy)
    provider._bind = lambda: True
    def last_input(pointer):
        ctypes.cast(pointer, ctypes.POINTER(LastInput)).contents.dwTime = 0xffffff00
        return True
    provider.user = SimpleNamespace(GetLastInputInfo=last_input, GetForegroundWindow=lambda: 0)
    provider.kernel = SimpleNamespace(GetTickCount=lambda: 100)
    try:
        sample = provider.sample()
        assert sample.idle_seconds == .356 and sample.process is None
        provider.user.GetLastInputInfo = lambda pointer: False
        assert provider.sample().process is None
    finally:
        activity.api.stop(); activity.tracker.close(); activity.manager.bus.close()
