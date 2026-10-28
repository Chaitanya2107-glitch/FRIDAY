"""Bind Telegram verification to sources and reload this checkout's desktop."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "tasks/telegram-upgrades-verification.json"
SNAPSHOT = ROOT / "tasks/telegram-upgrades-sources.json"
TESTS = ROOT / "tasks/telegram-upgrades-receipt-tests.xml"


def sources():
    files = [ROOT / "requirements.txt"]
    for directory in ("core", "interfaces", "providers", "services", "tests"):
        files.extend((ROOT / directory).rglob("*.py"))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def snapshot():
    data = sources()
    SNAPSHOT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Recorded {len(data)} source hashes.", flush=True)


def receipt():
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == sources(), "Sources changed during verification"
    suites = list(ET.parse(TESTS).getroot().iter("testsuite"))
    assert suites and all(int(s.get("failures", "0")) == int(s.get("errors", "0")) == 0 for s in suites)
    result = {"recorded_at": datetime.now(timezone.utc).isoformat(), "tests": sum(int(s.get("tests")) for s in suites),
              "failures": 0, "errors": 0, "test_artifact": TESTS.relative_to(ROOT).as_posix(),
              "test_sha256": hashlib.sha256(TESTS.read_bytes()).hexdigest(),
              "source_manifest": SNAPSHOT.relative_to(ROOT).as_posix(),
              "source_sha256": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
              "sources": sources(), "activation": "pending"}
    RECEIPT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Verified {result['tests']} passing tests against the recorded sources.", flush=True)


def activate():
    import ctypes
    from ctypes import wintypes
    import os
    import httpx
    import psutil
    import win32con
    import win32gui
    import win32process
    sys.path.insert(0, str(ROOT))
    from core.config import config

    data = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert data["sources"] == sources(), "Sources changed after tests"
    launch = ROOT / "interfaces/taskbar/launch.py"

    def owner(hwnd):
        process = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
        assert Path(process.cwd()).resolve() == ROOT, "Window belongs to another checkout"
        assert any(Path(arg).is_absolute() and Path(arg).resolve() == launch for arg in process.cmdline()[1:])
        return process

    hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
    if not hwnd:
        data["activation"] = "No desktop running; ready for normal FRIDAY launch"
    else:
        old = owner(hwnd)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = wintypes.LPARAM
        edit = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
        draft, visible = "", win32gui.IsWindowVisible(hwnd)
        if edit and not win32gui.GetWindowLong(edit, win32con.GWL_STYLE) & 0x800:  # ES_READONLY
            length = user32.SendMessageW(edit, win32con.WM_GETTEXTLENGTH, 0, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.SendMessageW(edit, win32con.WM_GETTEXT, len(buffer), ctypes.addressof(buffer))
            draft = buffer.value
        cli = Path(os.environ["LOCALAPPDATA"]) / "npm-cache/_npx/85fb20e3e7e3a233/node_modules/@claude-flow/cli/bin/cli.js"
        decision = subprocess.run(["node", str(cli), "policy", "evaluate", json.dumps({
            "identity": {"id": "codex-telegram-upgrade", "type": "agent"},
            "action": {"type": "desktop.restart", "environment": "development", "resource": str(ROOT)}})],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=30)
        policy = json.loads(decision.stdout)
        assert policy["enforcedOutcome"] == "allowed", policy.get("reason")
        data["activation_policy"] = policy
        data["activation_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        RECEIPT.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # A normal close releases the managed backend and microphone before relaunch.
        print("Reloading this checkout's desktop and managed backend...", flush=True)
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        old.wait(timeout=45)
        subprocess.Popen([str(ROOT / "venv/Scripts/pythonw.exe"), "-B", str(launch)], cwd=ROOT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            current = win32gui.FindWindow("FridayQuickBarWindow", None)
            if current and (new := owner(current)).pid != old.pid:
                try:
                    response = httpx.get(f"http://{config.API_HOST}:{config.API_PORT}/health", timeout=2, trust_env=False)
                    if response.status_code == 200 and response.json().get("service") == "F.R.I.D.A.Y":
                        if draft and (new_edit := win32gui.FindWindowEx(current, 0, "Edit", None)):
                            buffer = ctypes.create_unicode_buffer(draft)
                            user32.SendMessageW(new_edit, win32con.WM_SETTEXT, 0, ctypes.addressof(buffer))
                        if visible:
                            win32gui.ShowWindow(current, win32con.SW_SHOWNOACTIVATE)
                        data["activation"] = {"old_desktop_pid": old.pid, "new_desktop_pid": new.pid,
                                              "backend_health": "ready", "at": datetime.now(timezone.utc).isoformat()}
                        break
                except (httpx.HTTPError, ValueError):
                    pass
            time.sleep(.25)
        else:
            raise RuntimeError("Desktop was relaunched; backend readiness was not confirmed within 55 seconds")
    RECEIPT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data["activation"]), flush=True)


if __name__ == "__main__":
    {"snapshot": snapshot, "receipt": receipt, "activate": activate}[sys.argv[1]]()
