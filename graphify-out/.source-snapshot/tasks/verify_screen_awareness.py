"""Bind tests, native evidence and activation to the implemented source state."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write(name, value):
    (ROOT / "tasks" / name).write_text(json.dumps(value, indent=2), encoding="utf-8")


def sources():
    files = [path for folder in ("core", "services", "interfaces", "providers", "tests")
             for path in (ROOT / folder).rglob("*.py")]
    files.append(ROOT / "main.py")
    files += [ROOT / "tasks" / name for name in (
        "verify_screen_awareness.py", "screen_native_probe.py", "prepare_screen_vision.py",
        "probe_local_screen_models.py", "native_screen_diagnostics.py", "fixtures/ScreenWatchFixture.cs")]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)}


def identity(files=None):
    return hashlib.sha256(json.dumps(files if files is not None else sources(), sort_keys=True).encode()).hexdigest()


def snapshot():
    files = sources()
    value = {"identity": identity(files), "files": files}
    write("screen-tested-sources.json", value)
    print(json.dumps({"source_identity": value["identity"], "files": len(files)}))


def policy():
    write("screen-feature-policy.json", {
        "source_identity": identity(),
        "authorization": "Owner requested the discussed personal-assistant screen awareness and asked to continue implementation.",
        "decision": "Allow local implementation, model setup, tests, normal desktop reload and visible local activation.",
        "envelope": "Active window only, visible pause badge, local models only, no screenshots saved, protected fields excluded, bounded provisional summaries.",
        "ownership": "Root is the sole writer; helpers performed read-only research and reviews.",
        "release": "No commit, push, publication or shared provider/voice setting change.",
    })


def receipt():
    saved = json.loads((ROOT / "tasks/screen-tested-sources.json").read_text(encoding="utf-8"))
    assert saved["files"] == sources(), "Source changed after the full-suite snapshot."
    report = ET.parse(ROOT / "tasks/screen-full.xml").getroot()
    suites = list(report.iter("testsuite"))
    counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    assert counts["tests"] > 5700 and not counts["failures"] and not counts["errors"]
    native = json.loads((ROOT / "tasks/screen-native-proof.json").read_text(encoding="utf-8"))
    assert native["source_identity"] == saved["identity"]
    model = json.loads((ROOT / "tasks/screen-model-probes.json").read_text(encoding="utf-8"))
    assert model["inference_sha256"] == saved["files"]["services/screen_watch/inference.py"]
    assert {r["source"] for r in model["results"]} == {"text", "vision"}
    assert model["synthetic_only"] and all(r["semantic_check"] and not r["needs_vision"] for r in model["results"])
    worker = json.loads((ROOT / "tasks/screen-native-worker-proof.json").read_text(encoding="utf-8"))
    assert worker["worker_sha256"] == saved["files"]["services/browser/worker.py"]
    assert worker["reader_factory_sha256"] == saved["files"]["services/screen_watch/__init__.py"]
    assert worker["venv"] and not worker["has_console"] and worker["apartment"] == 1
    robot = saved["files"]["interfaces/body/window.py"]
    assert robot == "711a3f8dfb77d2f751c039cd9c0e5c97611c64cf15e901760f0e4cc6f1b054fb"
    value = {"source_identity": saved["identity"], "full": counts, "native": native,
             "model_probes": model, "native_worker": worker, "original_robot_preserved": True,
             "privacy": "No screen content reaches general chat history, owner facts, cloud models, online TTS or disk images.",
             "retention": "At most 200 provisional summaries, pruned after seven days.",
             "limits": "Supported accessible active windows only; unknown/private/complex windows are blocked. Model interpretations do not prove intent or task completion."}
    write("screen-feature-verification.json", value)
    print(json.dumps({"source_identity": saved["identity"], "full": counts,
                      "native_verified": True, "model_verified": True}, indent=2))


def activate():
    import win32gui
    from services.screen_watch import capture
    from tasks.screen_native_probe import api_client, command, wait
    checked = json.loads((ROOT / "tasks/screen-feature-verification.json").read_text(encoding="utf-8"))
    assert checked["source_identity"] == identity(), "Source changed after verification."
    with api_client() as client:
        command(client, "resume screen awareness")
        wait(lambda: capture.indicator(win32gui.FindWindow(None, capture.BADGE_TITLE)), 25,
             "The watching badge did not become visible")
        def live():
            response = client.get("/api/v1/system/status")
            response.raise_for_status()
            state = response.json()["screen_watch"]
            return state if state["enabled"] and not state["paused"] and state["state"] != "waiting_for_indicator" else None
        state = wait(live, 15, "Screen awareness did not receive its native badge heartbeat")
        value = {"source_identity": identity(), "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "visible_badge": True, "status": state, "local_only": True}
    write("screen-feature-activation.json", value)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "policy", "receipt", "activate"))
    {"snapshot": snapshot, "policy": policy, "receipt": receipt, "activate": activate}[parser.parse_args().mode]()
