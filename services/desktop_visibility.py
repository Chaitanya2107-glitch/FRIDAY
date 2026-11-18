"""One foreground visibility rule for FRIDAY's desktop surfaces."""
import ctypes
import os

QUNS_FULLSCREEN_GAME, QUNS_PRESENTATION_MODE = 3, 4


def suppressed():
    if os.name != 'nt':
        return False
    import win32api
    import win32con
    import win32gui
    import win32process
    import psutil
    from services.activity.categories import app_category
    try:
        notification = ctypes.c_int()
        if (ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(notification)) == 0
                and notification.value in (QUNS_FULLSCREEN_GAME, QUNS_PRESENTATION_MODE)):
            return True
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or win32gui.IsIconic(hwnd):
            return False
        if win32gui.GetClassName(hwnd) in {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}:
            return False
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if pid == os.getpid():
            return False
        name = psutil.Process(pid).name().removesuffix('.exe').lower()
        if app_category(name, win32gui.GetWindowText(hwnd)) == 'gaming':
            return True
        if win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_MAXIMIZE:
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        ml, mt, mr, mb = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))['Monitor']
        return left <= ml and top <= mt and right >= mr and bottom >= mb
    except (psutil.Error, OSError, win32gui.error):
        return False
