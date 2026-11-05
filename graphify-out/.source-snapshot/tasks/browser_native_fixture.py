"""Disposable native Save As-shaped window for UIA checks; never writes a file."""

import json

import win32con
import win32gui

status = None


def procedure(hwnd, message, wparam, lparam):
    if message == win32con.WM_COMMAND and (wparam & 0xFFFF) == 1:
        win32gui.SetWindowText(status, "Fixture button invoked")
        return 0
    if message == win32con.WM_CLOSE:
        win32gui.DestroyWindow(hwnd)
        return 0
    if message == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


if __name__ == "__main__":
    window = win32gui.CreateWindowEx(0, "#32770", "Save As", win32con.WS_OVERLAPPEDWINDOW,
                                     150, 150, 520, 220, 0, 0, 0, None)
    win32gui.SetWindowLong(window, win32con.GWL_WNDPROC, procedure)
    base = win32con.WS_CHILD | win32con.WS_VISIBLE
    win32gui.CreateWindowEx(0, "Static", "File name:", base, 20, 25, 100, 24, window, 100, 0, None)
    win32gui.CreateWindowEx(0, "Edit", "original.txt", base | win32con.WS_BORDER | win32con.WS_TABSTOP,
                           130, 25, 240, 28, window, 1148, 0, None)
    win32gui.CreateWindowEx(0, "Button", "Save", base | win32con.WS_TABSTOP,
                           380, 25, 80, 28, window, 1, 0, None)
    status = win32gui.CreateWindowEx(0, "Edit", "Waiting for fixture test", base | win32con.ES_READONLY,
                                    20, 90, 440, 28, window, 1149, 0, None)
    win32gui.ShowWindow(window, win32con.SW_SHOW)
    try:
        win32gui.SetForegroundWindow(window)
    except Exception:
        # This developer fixture is launched by a hidden shell. Attach input
        # queues only long enough to activate its own window, without sending keys.
        import ctypes
        import win32api
        import win32process
        foreground = win32gui.GetForegroundWindow()
        foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground)
        current = win32api.GetCurrentThreadId()
        ctypes.windll.user32.AttachThreadInput(current, foreground_thread, True)
        try:
            win32gui.BringWindowToTop(window)
            win32gui.SetForegroundWindow(window)
        finally:
            ctypes.windll.user32.AttachThreadInput(current, foreground_thread, False)
    print(json.dumps({"hwnd": window}), flush=True)
    win32gui.PumpMessages()
