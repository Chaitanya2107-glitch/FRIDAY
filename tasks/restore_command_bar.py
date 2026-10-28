"""Activate the tested command-bar fix and verify a real clock-command round trip."""

import hashlib
import ctypes
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import psutil
import win32con
import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from interfaces.popup.win32 import WM_APP_SHOW, user32


def edit_text(hwnd):
    # Cross-process GetWindowText only reads captions, not another process's
    # edit buffer. WM_GETTEXT retrieves the actual command/response text.
    buffer = ctypes.create_unicode_buffer(512)
    user32.SendMessageW(hwnd, win32con.WM_GETTEXT, len(buffer), ctypes.addressof(buffer))
    return buffer.value


def inspect():
    hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
    assert hwnd
    process = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
    assert Path(process.cwd()).resolve() == ROOT
    edit = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
    text = edit_text(edit)
    result = {"pid": process.pid, "visible": bool(win32gui.IsWindowVisible(hwnd)),
              "still_sending": text == "Sending...", "text_length": len(text),
              "clock_text": text if re.search(r"\b\d{1,2}:\d{2}\b", text) and len(text) < 200 else None}
    print(json.dumps(result, indent=2))


def main(reload=True):
    launch = ROOT / "interfaces/taskbar/launch.py"
    source = ROOT / "interfaces/popup/app.py"
    suite = ET.parse(ROOT / "tasks/command-bar-fixed.xml").getroot().find("testsuite")
    assert suite.get("failures") == "0" and suite.get("errors") == "0"
    def owner(hwnd):
        process = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
        assert Path(process.cwd()).resolve() == ROOT, "Desktop belongs to a different checkout."
        assert any(Path(arg).is_absolute() and Path(arg).resolve() == launch for arg in process.cmdline()[1:])
        return process
    current = win32gui.FindWindow("FridayQuickBarWindow", None)
    if not current:
        raise RuntimeError("FRIDAY's desktop window is missing; no process was changed.")
    old = owner(current)
    process = old
    if reload:
        win32gui.PostMessage(current, win32con.WM_CLOSE, 0, 0)
        old.wait(timeout=40)
        subprocess.Popen([str(ROOT / "venv/Scripts/pythonw.exe"), "-B", str(launch)], cwd=ROOT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            current = win32gui.FindWindow("FridayQuickBarWindow", None)
            if current and (process := owner(current)).pid != old.pid:
                break
            time.sleep(.2)
        else:
            raise RuntimeError("FRIDAY did not reopen its desktop window.")

    import httpx
    from core.config import config
    base = f"http://{config.API_HOST}:{config.API_PORT}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if httpx.get(base + "/health", timeout=2, trust_env=False).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.25)
    else:
        raise RuntimeError("The desktop reopened, but its backend did not become ready.")

    win32gui.SendMessage(current, WM_APP_SHOW, 0, 0)
    deadline = time.monotonic() + 5
    while not win32gui.IsWindowVisible(current) and time.monotonic() < deadline:
        time.sleep(.05)
    edit = win32gui.FindWindowEx(current, 0, "Edit", None)
    assert edit, "Command-bar edit control is missing."
    if edit_text(edit):
        raise RuntimeError("The reopened bar already contains a draft; leaving it untouched.")
    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "what time is it")
    win32gui.SendMessage(edit, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
    start = time.monotonic()
    deadline = start + 20
    while time.monotonic() < deadline:
        reply = edit_text(edit)
        if re.search(r"\b\d{1,2}:\d{2}\b", reply) and reply != "what time is it":
            break
        time.sleep(.05)
    else:
        raise RuntimeError(f"The native command bar did not display its clock reply (last length={len(reply)}, sending={reply == 'Sending...'}).")
    receipt = {"authorization": "Owner requested repair of FRIDAY's command bar stuck on Sending",
               "policy_decision": "Apply the tested timer fix and reload this checkout's desktop through its normal lifecycle",
               "cause": "First 100 ms poll stopped the timer before an in-flight response was ready",
               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "focused_passed": int(suite.get("tests")) - int(suite.get("skipped")),
               "focused_skipped": int(suite.get("skipped")), "old_pid": old.pid, "new_pid": process.pid,
               "reloaded_in_this_probe": reload,
               "native_clock_reply_displayed": True, "round_trip_seconds": round(time.monotonic() - start, 3),
               "probe": "Real command-bar Enter, backend request and displayed response; clock only, no external actions"}
    (ROOT / "tasks/command-bar-fix-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    inspect() if "--inspect" in sys.argv else main(reload="--probe" not in sys.argv)
