"""Run the opt-in widget check through the normal Windows GUI interpreter."""

import ctypes
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout = sys.stderr = (ROOT / "tasks/widget-left-desktop.log").open("w", encoding="utf-8", buffering=1)

if "--probe" in sys.argv:
    import win32api
    import win32con as C
    import win32gui as W
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    bar = W.FindWindow("Shell_TrayWnd", None)
    user.SetThreadDpiAwarenessContext(user.GetWindowDpiAwarenessContext(bar))
    instance = win32api.GetModuleHandle(None)
    wc = W.WNDCLASS()
    wc.hInstance, wc.lpszClassName, wc.lpfnWndProc = instance, "FridayLeftNativeEnvironmentProbe", W.DefWindowProc
    W.RegisterClass(wc)
    report = {"pid": os.getpid(), "parent_pid": os.getppid(), "created": False}
    try:
        hwnd = W.CreateWindowEx(C.WS_EX_LAYERED, wc.lpszClassName, "", C.WS_CHILD,
                                0, 0, 1, 1, bar, 0, instance, None)
        report["created"] = True
        W.DestroyWindow(hwnd)
    except W.error as error:
        report["error"] = str(error)
    finally:
        W.UnregisterClass(wc.lpszClassName, instance)
    (ROOT / "tasks/widget-native-environment.json").write_text(json.dumps(report), encoding="utf-8")
else:
    os.environ["FRIDAY_PANEL_UI_TEST"] = "1"
    import pytest
    result = pytest.main(["tests/test_taskbar_widget.py", "tests/test_taskbar_panel.py", "-q", "-s",
                          "-p", "no:cacheprovider", "--basetemp=tasks/widget-left-desktop-temp",
                          "--junitxml=tasks/widget-left-desktop.xml"])
    (ROOT / "tasks/widget-left-desktop-result.json").write_text(json.dumps({"exit_code": result}), encoding="utf-8")
    sys.exit(result)
