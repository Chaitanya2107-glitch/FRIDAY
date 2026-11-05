"""Apply the owner's requested orb rollback to this checkout's desktop only."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil
import win32con
import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "interfaces" / "taskbar" / "launch.py"
STATE = ROOT / "memory" / "body" / "state.json"


def owner(hwnd):
    process = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
    if Path(process.cwd()).resolve() != ROOT or not any(
        Path(arg).is_absolute() and Path(arg).resolve() == LAUNCH for arg in process.cmdline()[1:]
    ):
        raise RuntimeError("Desktop window does not belong to this checkout; leaving it untouched.")
    return process


def main():
    source = ROOT / "interfaces" / "body" / "window.py"
    text = source.read_text(encoding="utf-8")
    assert "sprite.render(frame.pose)" in text and "presence" not in text
    receipt = {"authorization": "Owner requested undo and restoration of the old desktop robot",
               "policy_decision": "Restore original local desktop through its normal close/launch path",
               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "tests": "88 passed: tasks/restore-robot-tests.xml", "restarted": False}
    hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
    if hwnd:
        old = owner(hwnd)
        receipt["old_pid"] = old.pid
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        old.wait(timeout=30)
    if STATE.is_file():
        state = json.loads(STATE.read_text(encoding="utf-8"))
        state.pop("appearance", None)
        state.pop("reduced_motion", None)
        STATE.write_text(json.dumps(state), encoding="utf-8")
    if hwnd:
        subprocess.Popen([str(ROOT / "venv" / "Scripts" / "pythonw.exe"), "-B", str(LAUNCH)],
                         cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            new_window = win32gui.FindWindow("FridayQuickBarWindow", None)
            if new_window:
                current = owner(new_window)
                if current.pid != receipt["old_pid"]:
                    receipt.update(restarted=True, new_pid=current.pid)
                    break
            time.sleep(.2)
        if not receipt["restarted"]:
            raise RuntimeError("Old desktop closed; relaunch did not expose its window within 40 seconds.")
    receipt["settings_restored"] = True
    (ROOT / "tasks" / "restore-robot-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
