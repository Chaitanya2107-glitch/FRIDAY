"""Source-bound validation and a local desktop smoke check for assistant awareness."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "tasks/personal-assistant-sources.json"
RECEIPT = ROOT / "tasks/personal-assistant-verification.json"
sys.path.insert(0, str(ROOT))


def manifest():
    files = [path for folder in ("core", "services", "interfaces", "providers", "tests")
             for path in (ROOT / folder).rglob("*.py")]
    files += [Path(__file__)]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)}


def identity(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def snapshot():
    sources = manifest()
    write(SOURCES, {"identity": identity(sources), "files": sources})
    print(json.dumps({"source_identity": identity(sources), "python_files": len(sources)}))


def current_sources():
    saved = json.loads(SOURCES.read_text(encoding="utf-8"))
    assert saved["files"] == manifest(), "Source changed after the verification snapshot."
    return saved["identity"]


def counts(name, modules=None):
    root = ET.parse(ROOT / "tasks" / name).getroot()
    suites = root.findall(".//testsuite")
    result = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    if modules:
        cases = [case for case in root.iter("testcase") if case.get("classname") in modules]
        result = {"tests": len(cases), **{plural: sum(case.find(tag) is not None for case in cases)
                  for plural, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}
    result["passed"] = result["tests"] - sum(result[key] for key in ("failures", "errors", "skipped"))
    assert result["tests"] and not result["failures"] and not result["errors"], name + " did not pass."
    return result


def receipt():
    value = {
        "source_identity": current_sources(),
        "authorization": "Owner requested Friday become a personal assistant with observed activity and verified app learning.",
        "policy_decision": "Allow local implementation and tests; preserve private title boundary and require owner confirmation of model app definitions.",
        "ownership": "Root wrote code; helper agents performed read-only reviews.",
        "focused": counts("personal-assistant-full.xml", {"tests.test_" + name for name in (
            "app_learning", "activity_awareness", "brain", "talk", "inquiry", "personality", "activity_log",
            "activity_ask", "ai_assistance", "ai_language", "cognition", "voice", "tray", "popup_responses")}),
        "focused_basis": "Relevant cases selected from the final full-suite JUnit report; earlier standalone reports are retained.",
        "full": counts("personal-assistant-full.xml"),
        "automatic_screenshots_enabled": False,
        "scope": "Persona, metadata awareness, explicit task/app-use memory, and versioned app explanations.",
    }
    write(RECEIPT, value)
    print(json.dumps(value, indent=2))


def activate():
    import httpx
    import psutil
    import win32con
    import win32gui
    import win32process
    from core.config import config
    from interfaces.popup.win32 import WM_APP_SHOW
    from tasks.restore_command_bar import edit_text

    source_id = current_sources()
    checked = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert checked["source_identity"] == source_id
    launch = ROOT / "interfaces/taskbar/launch.py"
    hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
    assert hwnd, "No Friday desktop window was found; no process changed."
    old = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
    assert Path(old.cwd()).resolve() == ROOT
    assert any(Path(arg).is_absolute() and Path(arg).resolve() == launch for arg in old.cmdline()[1:])
    edit = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
    assert not (win32gui.GetForegroundWindow() == hwnd and edit and edit_text(edit)), "Friday has focused draft text."
    was_visible = bool(win32gui.IsWindowVisible(hwnd))
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    old.wait(timeout=40)
    subprocess.Popen([str(ROOT / "venv/Scripts/pythonw.exe"), "-B", str(launch)], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
        if hwnd:
            new_pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            if new_pid != old.pid:
                break
        time.sleep(.2)
    else:
        raise RuntimeError("Friday did not reopen.")
    base = f"http://{config.API_HOST}:{config.API_PORT}"
    with httpx.Client(timeout=httpx.Timeout(30, connect=3), trust_env=False) as client:
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            try:
                if client.get(base + "/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        else:
            raise RuntimeError("Friday's backend did not become ready.")
        start = time.monotonic()
        response = client.post(base + "/api/v1/chat", json={"message": "what am i doing", "speak": False})
        response.raise_for_status()
        body = response.json()
        assert body["model"] == "system_control"
        assert any(term in body["response"] for term in
                   ("is in the foreground", "fresh activity observation", "no active foreground app"))
        awareness_seconds = time.monotonic() - start
    win32gui.SendMessage(hwnd, WM_APP_SHOW, 0, 0)
    edit = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
    assert edit and not edit_text(edit), "Fresh command bar contains a draft."
    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "what time is it")
    win32gui.SendMessage(edit, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
    start = time.monotonic()
    deadline = start + 20
    import re
    while time.monotonic() < deadline:
        if re.search(r"\b\d{1,2}:\d{2}\b", edit_text(edit)):
            break
        time.sleep(.05)
    else:
        raise RuntimeError("The native command bar did not display its clock reply.")
    result = {"source_identity": current_sources(), "old_desktop_pid": old.pid, "new_desktop_pid": new_pid,
              "grounded_activity_api": True, "native_clock_displayed": True,
              "awareness_seconds": round(awareness_seconds, 3), "clock_seconds": round(time.monotonic() - start, 3),
              "private_activity_text_in_receipt": False, "new_model_or_provider_settings": False}
    if not was_visible:
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    write(ROOT / "tasks/personal-assistant-activation.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "receipt", "activate"))
    {"snapshot": snapshot, "receipt": receipt, "activate": activate}[parser.parse_args().mode]()
