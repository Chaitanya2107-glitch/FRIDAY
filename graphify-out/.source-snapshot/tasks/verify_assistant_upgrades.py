"""Bind the approved assistant batch to its source, checks and local activation."""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import timeit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TASKS = ROOT / "tasks"
SNAPSHOT = TASKS / "assistant-upgrades-sources.json"
RECEIPT = TASKS / "assistant-upgrades-verification.json"
NEW_FILES = ["services/phone/__init__.py", "services/phone/transport.py", "services/phone/bridge.py",
             "services/phone/commands.py", "services/voice/conversation_input.py", "services/spotify/dj.py",
             "tests/test_phone_bridge.py", "tests/test_phone_transport.py", "tests/test_conversation_input.py",
             "tests/test_spotify_dj.py", "tasks/probe_assistant_upgrades.py", "tasks/verify_assistant_upgrades.py"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [ROOT / "requirements.txt", ROOT / "AGENTS.md"]
    for folder in ("core", "services", "interfaces", "providers", "tests"):
        paths.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts)
    paths.extend(ROOT / name for name in NEW_FILES if name.startswith("tasks/"))
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(set(paths))}


def snapshot():
    for name in NEW_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        ast.parse(text)
        assert len(text.splitlines()) < 500, name
        assert all(line.rstrip() == line for line in text.splitlines()), name
    SNAPSHOT.write_text(json.dumps(sources(), indent=2), encoding="utf-8")
    print(json.dumps({"source_inputs": len(sources()), "snapshot": str(SNAPSHOT)}))


def benchmark():
    from unittest.mock import patch
    from services.automation.app_commands import match_media_command
    from services.spotify import dj
    cases = ("play Happy", "play Work", "play Friday I'm in Love", "pause music")
    def run():
        for case in cases:
            match_media_command(case, lambda: True)
    with patch.object(dj, "match_command", lambda _: None):
        baseline = statistics.median(timeit.repeat(run, number=100, repeat=5)) * 1000 / 400
    candidate = statistics.median(timeit.repeat(run, number=100, repeat=5)) * 1000 / 400
    result = {"baseline_ms_per_command": baseline, "candidate_ms_per_command": candidate,
              "definition": "Same source: existing media matcher with DJ disabled versus enabled; four ordinary commands, 5 x 100 repetitions.",
              "limits": "Local parser only, no API, STT, microphone or playback. No end-to-end latency or speedup claim."}
    (TASKS / "assistant-upgrades-benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


def test_result(name):
    suite = ET.parse(TASKS / name).getroot().find("testsuite")
    assert suite.get("failures") == "0" and suite.get("errors") == "0", name
    return {"passed": int(suite.get("tests")) - int(suite.get("skipped")), "skipped": int(suite.get("skipped")),
            "seconds": float(suite.get("time")), "failures": 0, "errors": 0}


def receipt():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert expected == sources(), "Source changed after the validation snapshot."
    body = digest(ROOT / "interfaces/body/window.py")
    assert body == json.loads((TASKS / "restore-robot-receipt.json").read_text(encoding="utf-8"))["source_sha256"]
    result = {"authorization": "Owner approved all three personal-assistant upgrades; Android confirmed; KDE installation approved; owner completed pairing/notification permissions.",
              "policy_decision": "Proceed with reversible workspace implementation and approved local integration setup; no publish/commit.",
              "writer": "root; all helper agents read-only", "verified_at": datetime.now(timezone.utc).isoformat(),
              "source_inputs": len(expected), "source_manifest_sha256": digest(SNAPSHOT),
              "source_identity": "Content hashes including current tracked/untracked Python and test inputs; no clean-commit or release claim.",
              "focused": test_result("assistant-upgrades-focused.xml"), "full": test_result("assistant-upgrades-full.xml"),
              "native_readiness": json.loads((TASKS / "assistant-upgrades-live.json").read_text(encoding="utf-8")),
              "benchmark": json.loads((TASKS / "assistant-upgrades-benchmark.json").read_text(encoding="utf-8")),
              "desktop_robot_exactly_preserved": True, "new_python_files_under_500_lines": True,
              "independent_reviews": "Phone transport/privacy, voice cancellation and Spotify correctness: no remaining blockers.",
              "limits": ["Live phone read/reply/ring and microphone echo/playback not exercised; readiness was read-only.",
                         "No acoustic echo cancellation; ASR latency/echo quality needs the owner's normal voice trial.",
                         "Spotify connected/catalog search works; no active playback device during the probe.",
                         "KDE replies are submission acknowledgements, not downstream delivery guarantees."]}
    artifacts = ["assistant-upgrades-focused.xml", "assistant-upgrades-full.xml", "assistant-upgrades-live.json",
                 "assistant-upgrades-benchmark.json", "assistant-upgrades-first-full.xml",
                 "assistant-upgrades-first-sources.json"]
    first = ET.parse(TASKS / "assistant-upgrades-first-full.xml").getroot().find("testsuite")
    result["first_full_attempt"] = {key: first.get(key) for key in ("tests", "failures", "errors", "skipped", "time")}
    result["first_full_attempt"]["resolution"] = (
        "Updated two older speech test doubles for generation/logging parameters; reran native GUI checks "
        "outside sandbox after CScript access denied and Tcl initialization access failures. "
        "Final run uses the current source snapshot.")
    result["phone_ui_privacy"] = "Private metadata propagates through desktop responses; no toast mirroring, raw cognition storage or bar-suggestion learning."
    result["artifact_sha256"] = {name: digest(TASKS / name) for name in artifacts}
    RECEIPT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "focused": result["focused"], "full": result["full"]}, indent=2))


def reload_desktop():
    import psutil
    import win32con
    import win32gui
    import win32process
    data = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == sources()
    launch = ROOT / "interfaces/taskbar/launch.py"
    def owner(hwnd):
        process = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])
        assert Path(process.cwd()).resolve() == ROOT
        assert any(Path(arg).is_absolute() and Path(arg).resolve() == launch for arg in process.cmdline()[1:])
        return process
    hwnd = win32gui.FindWindow("FridayQuickBarWindow", None)
    if not hwnd:
        print("No running desktop to reload; code is ready for the usual FRIDAY launch.")
        return
    old = owner(hwnd)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    old.wait(timeout=40)
    subprocess.Popen([str(ROOT / "venv/Scripts/pythonw.exe"), "-B", str(launch)], cwd=ROOT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        current = win32gui.FindWindow("FridayQuickBarWindow", None)
        if current and (new := owner(current)).pid != old.pid:
            data["desktop_activation"] = {"old_pid": old.pid, "new_pid": new.pid,
                                           "at": datetime.now(timezone.utc).isoformat()}
            RECEIPT.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(json.dumps(data["desktop_activation"]))
            return
        time.sleep(.2)
    raise RuntimeError("Desktop relaunch did not expose its window within 45 seconds.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "benchmark", "receipt", "reload"))
    mode = parser.parse_args().mode
    {"snapshot": snapshot, "benchmark": benchmark, "receipt": receipt, "reload": reload_desktop}[mode]()
