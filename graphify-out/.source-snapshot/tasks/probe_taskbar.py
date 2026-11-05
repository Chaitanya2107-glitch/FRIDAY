"""Inspect taskbar geometry; --button briefly tests a taskbar-owned child window."""

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from interfaces.popup.win32 import user32, kernel32, WNDCLASSW, WNDPROC, MSG


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--button", action="store_true")
    args = parser.parse_args()
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
    user32.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    bar = user32.FindWindowW("Shell_TrayWnd", None)
    if not bar:
        raise RuntimeError("Interactive Windows taskbar is not accessible in this environment")
    user32.SetThreadDpiAwarenessContext(user32.GetWindowDpiAwarenessContext(bar))
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    # Reveal an auto-hidden taskbar through its normal mouse gesture, without
    # changing the user's taskbar settings.
    user32.SetCursorPos(user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) - 1)
    time.sleep(1.5)
    bounds = wintypes.RECT()
    user32.GetWindowRect(bar, ctypes.byref(bounds))
    print(json.dumps({"build": sys.getwindowsversion().build, "taskbar": bar,
                      "rect": [bounds.left, bounds.top, bounds.right, bounds.bottom]}), flush=True)
    from pywinauto import Desktop
    desktop = Desktop(backend="uia")
    taskbar = desktop.window(handle=bar).wrapper_object()
    protected = []
    descendants = taskbar.descendants()
    print(json.dumps({"uia_nodes": len(descendants)}), flush=True)
    for child in descendants:
        info, rect = child.element_info, child.rectangle()
        if info.control_type in {"Button", "List", "ListItem", "ToolBar", "CheckBox"}:
            if rect.width() > 0 and rect.height() > 0:
                item = {"type": info.control_type, "class": info.class_name, "id": info.automation_id,
                        "rect": [rect.left, rect.top, rect.right, rect.bottom]}
                protected.append((rect.left, rect.right))
                print(json.dumps(item), flush=True)
        elif len(descendants) < 15:
            print(json.dumps({"type": info.control_type, "class": info.class_name,
                              "id": info.automation_id, "rect": [rect.left, rect.top, rect.right, rect.bottom]}), flush=True)
    import win32gui
    win32gui.EnumChildWindows(bar, lambda hwnd, unused: print(json.dumps(
        {"native_class": win32gui.GetClassName(hwnd), "rect": win32gui.GetWindowRect(hwnd)}), flush=True), None)
    user32.SetCursorPos(original_cursor.x, original_cursor.y)
    if not args.button:
        return
    if not protected:
        print("No safe layout evidence; native button probe skipped", flush=True)
        return
    # The actual widget will use a fully measured free gap. This probe uses
    # the first small fitting gap and immediately removes its own test child.
    intervals = sorted(protected)
    start, slot = bounds.left + 12, None
    for left, right in intervals + [(bounds.right - 12, bounds.right)]:
        if left - start >= 150:
            slot = start
            break
        start = max(start, right + 12)
    if slot is None:
        raise RuntimeError("No safe gap for a temporary compatibility button")
    callback = WNDPROC(lambda hwnd, msg, wp, lp: user32.DefWindowProcW(hwnd, msg, wp, lp))
    wc = WNDCLASSW()
    wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = callback, kernel32.GetModuleHandleW(None), "FridayTaskbarProbe"
    wc.hbrBackground = ctypes.cast(ctypes.c_void_p(6), wintypes.HBRUSH)
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0x08000004, wc.lpszClassName, "FRIDAY probe", 0x50000000,
                                slot - bounds.left, 4, 138, bounds.bottom - bounds.top - 8,
                                bar, None, wc.hInstance, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        assert user32.GetParent(hwnd) == bar
        print(json.dumps({"native_child": hwnd, "parent_is_taskbar": True, "slot": slot}), flush=True)
        msg = MSG()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(.01)
    finally:
        user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(wc.lpszClassName, wc.hInstance)


if __name__ == "__main__":
    main()
