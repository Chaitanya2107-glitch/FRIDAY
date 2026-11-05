"""One-time local installation. Default only inspects; --apply switches the legacy session."""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from interfaces.taskbar.windows import LAUNCH_PATH, WINDOW_TITLE, create_shortcut, pythonw

user = ctypes.WinDLL("user32", use_last_error=True)
user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user.FindWindowW.restype = wintypes.HWND
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def exact_script(process, script):
    try:
        return any(Path(arg).is_absolute() and Path(arg).resolve() == script for arg in process.cmdline()[1:])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def inspect_legacy():
    if user.FindWindowW(None, WINDOW_TITLE):
        return None
    hwnd = user.FindWindowW("FridayQuickBarWindow", None)
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    tray = psutil.Process(pid.value)
    if "interfaces.tray.app" not in tray.cmdline() or Path(tray.cwd()).resolve() != ROOT:
        raise RuntimeError("The existing desktop is not the legacy session for this checkout.")
    owners = [p for p in tray.parents() if p.name().lower() in {"wscript.exe", "cscript.exe"}
              and exact_script(p, ROOT / "launch_friday.vbs")]
    if len(owners) != 1:
        raise RuntimeError("Cannot identify the old launcher's owner. Quit the old tray once before setup.")
    owner = owners[0]
    backends = []
    for process in psutil.process_iter(["name"]):
        try:
            if process.info["name"].lower() == "python.exe" and exact_script(process, ROOT / "main.py"):
                if "--no-reload" in process.cmdline() and abs(process.create_time() - owner.create_time()) < 15:
                    backends.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    ids = {p.pid for p in backends}
    groups = [p for p in backends if p.ppid() not in ids]
    if len(groups) != 1:
        raise RuntimeError("Old backend ownership is ambiguous; no processes have been changed.")
    return hwnd, tray, owner, backends


CONSOLE_STOP = r'''
import ctypes, json, os, sys
from ctypes import wintypes
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.AttachConsole.argtypes = [wintypes.DWORD]
k.GetConsoleProcessList.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
k.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
k.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
allowed = set(map(int, sys.argv[1:])) | {os.getpid(), os.getppid()}
k.FreeConsole()
sent = False
if k.AttachConsole(int(sys.argv[1])):
    k.SetConsoleCtrlHandler(None, True)
    clients = (wintypes.DWORD * 1024)()
    count = k.GetConsoleProcessList(clients, 1024)
    if 0 < count <= 1024 and set(clients[:count]) <= allowed:
        sent = bool(k.GenerateConsoleCtrlEvent(0, 0))
    k.FreeConsole()
print(json.dumps({'console_signal_sent': sent}))
'''


def switch_legacy(plan):
    hwnd, tray, owner, backends = plan
    # Prevent the old VBS's unconditional taskkill /T before closing its tray.
    # Terminate only this verified script process, never its children.
    if not exact_script(owner, ROOT / "launch_friday.vbs") or not all(
        exact_script(p, ROOT / "main.py") for p in backends
    ):
        raise RuntimeError("Legacy process identity changed; installation stopped.")
    owner.terminate()
    owner.wait(timeout=5)
    user.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE, exactly like request_quit()
    tray.wait(timeout=10)
    result = subprocess.run([sys.executable, "-B", "-c", CONSOLE_STOP, *[str(p.pid) for p in backends]],
                            capture_output=True, text=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    signaled = result.returncode == 0 and json.loads(result.stdout).get("console_signal_sent")
    _, remaining = psutil.wait_procs(backends, timeout=20 if signaled else 1)
    for process in remaining:
        if exact_script(process, ROOT / "main.py"):
            process.terminate()  # Scoped fallback; applications it opened are preserved.
    _, remaining = psutil.wait_procs(backends, timeout=5)
    if remaining:
        raise RuntimeError("The old backend has not exited; no replacement was launched.")
    return "console signal" if signaled else "scoped interpreter termination"


def verify_current(expected=None):
    """Check the native child, hidden host, flyout styles and backend health."""
    import httpx
    import win32con as C
    import win32gui as W
    from core.config import config
    from interfaces.taskbar.host import HOST_CLASS, BUTTON_CLASS, user as host_user
    host = W.FindWindow(HOST_CLASS, None)
    taskbar = W.FindWindow("Shell_TrayWnd", None)
    button = W.FindWindowEx(taskbar, 0, BUTTON_CLASS, None)
    hwnd = user.FindWindowW(None, WINDOW_TITLE)
    if not all((host, taskbar, button, hwnd)):
        raise RuntimeError("FRIDAY's taskbar widget or flyout was not found.")
    host_user.SetThreadDpiAwarenessContext(host_user.GetWindowDpiAwarenessContext(taskbar))
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    current = psutil.Process(pid.value)
    if not exact_script(current, LAUNCH_PATH) or Path(current.cwd()).resolve() != ROOT:
        raise RuntimeError("The taskbar window is not running this checkout's bootstrap.")
    for owned in (host, button):
        owner_pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(owned, ctypes.byref(owner_pid))
        if owner_pid.value != current.pid:
            raise RuntimeError("The widget and flyout belong to different processes.")
    try:
        response = httpx.get(f"http://{config.API_HOST}:{config.API_PORT}/health", timeout=3)
        ready = response.status_code == 200 and response.json().get("service") == "F.R.I.D.A.Y"
    except httpx.RequestError:
        ready = False
    style = W.GetWindowLong(hwnd, C.GWL_EXSTYLE)
    managed = [p.pid for p in current.children(recursive=True)
               if exact_script(p, ROOT / "main.py") and "--desktop-managed" in p.cmdline()]
    report = {"window_pid": current.pid, "taskbar_parent": W.GetParent(button) == taskbar,
              "native_child": bool(W.GetWindowLong(button, C.GWL_STYLE) & C.WS_CHILD),
              "host_hidden": not W.IsWindowVisible(host), "flyout_toolwindow": bool(style & C.WS_EX_TOOLWINDOW),
              "separate_app_button": bool(style & C.WS_EX_APPWINDOW), "flyout_visible": bool(W.IsWindowVisible(hwnd)),
              "widget_rect": W.GetWindowRect(button), "widget_status": W.GetWindowText(button),
              "verified_online": ready, "managed_backend_pids": managed}
    correct = report["taskbar_parent"] and report["native_child"] and report["host_hidden"]
    correct = correct and report["flyout_toolwindow"] and not report["separate_app_button"]
    correct = correct and (expected != "online" or ready) and (expected != "offline" or (not ready and not managed))
    if not correct:
        raise RuntimeError(f"Live verification failed: {report}")
    path = ROOT / "tasks/taskbar-installation.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["live_verification"] = report
    receipt.setdefault("widget_checks", []).append(report)
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restart-current", action="store_true", help="Refresh an already installed desktop after code changes")
    parser.add_argument("--verify", action="store_true", help="Verify the live window and backend without restarting")
    parser.add_argument("--expect", choices=("online", "offline"), help="Require this backend state during verification")
    parser.add_argument("--startup", action="store_true", help="Show the widget when signing into Windows")
    parser.add_argument("--activate", action="store_true", help="Click the installed widget and wait for FRIDAY before verifying")
    args = parser.parse_args()
    if args.verify:
        if args.activate:
            import win32con as C
            import win32gui as W
            from interfaces.taskbar.host import BUTTON_CLASS
            from interfaces.tray import backend
            button = W.FindWindowEx(W.FindWindow("Shell_TrayWnd", None), 0, BUTTON_CLASS, None)
            if not button:
                raise RuntimeError("The installed FRIDAY button was not found.")
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(button, ctypes.byref(pid))
            if not exact_script(psutil.Process(pid.value), LAUNCH_PATH):
                raise RuntimeError("The button does not belong to this checkout.")
            W.PostMessage(button, C.WM_LBUTTONUP, 0, 0)
            print("Clicked FRIDAY's taskbar button; waiting for backend readiness.", flush=True)
            deadline = time.monotonic() + 300
            while not backend.is_online():
                if time.monotonic() >= deadline:
                    raise RuntimeError("FRIDAY did not become ready after the taskbar click.")
                time.sleep(.5)
        verify_current(args.expect)
        return
    plan = inspect_legacy()
    summary = {"legacy": bool(plan), "tray_pid": plan[1].pid if plan else None,
               "script_pid": plan[2].pid if plan else None,
               "backend_pids": [p.pid for p in plan[3]] if plan else []}
    print(json.dumps(summary), flush=True)
    if not args.apply:
        return
    method = switch_legacy(plan) if plan else "already current or stopped"
    if args.restart_current:
        hwnd = user.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            current = psutil.Process(pid.value)
            if not exact_script(current, LAUNCH_PATH) or Path(current.cwd()).resolve() != ROOT:
                raise RuntimeError("The taskbar window's process identity does not match this checkout.")
            bar = user.FindWindowW("FridayQuickBarWindow", None)
            bar_pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(bar, ctypes.byref(bar_pid))
            if bar_pid.value != current.pid:
                raise RuntimeError("The command bar belongs to another desktop; refresh stopped.")
            user.PostMessageW(bar, 0x10, 0, 0)
            current.wait(timeout=40)
    shortcut = create_shortcut(Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/FRIDAY.lnk")
    startup = None
    if args.startup:
        startup = create_shortcut(Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/FRIDAY Widget.lnk")
    process = subprocess.Popen([str(pythonw()), "-B", str(LAUNCH_PATH)], cwd=ROOT)
    receipt = {"time": datetime.now(timezone.utc).isoformat(), "plan": summary,
               "legacy_shutdown": method, "shortcut": str(shortcut), "desktop_pid": process.pid,
               "startup_shortcut": str(startup) if startup else None}
    receipt_path = ROOT / "tasks/taskbar-installation.json"
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["previous_sessions"] = [*previous.get("previous_sessions", []),
                                        {k: v for k, v in previous.items() if k != "previous_sessions"}]
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
