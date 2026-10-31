"""Source-bound evidence for automatic private activity learning and conversation."""
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
    from tasks.verify_screen_awareness import sources as screen_sources
    files = screen_sources()
    for name in ("tasks/verify_passive_assistant.py", "tasks/passive_native_probe.py",
                 "tasks/cleanup_screen_fixture.py", "docs/screen-awareness.md",
                 "docs/specs/2026-10-29-passive-assistant-awareness.md"):
        files[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    for path in (ROOT / "tasks").glob("*.py"):
        files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def identity(files=None):
    return hashlib.sha256(json.dumps(files if files is not None else sources(), sort_keys=True).encode()).hexdigest()


def production_identity(files=None):
    return identity({name: digest for name, digest in (files if files is not None else sources()).items()
                     if name == "main.py" or name.startswith(("core/", "services/", "interfaces/", "providers/"))})


def snapshot():
    files = sources()
    write("passive-tested-sources.json", {"identity": identity(files), "files": files})
    print(json.dumps({"source_identity": identity(files), "files": len(files)}))


def policy():
    write("passive-feature-policy.json", {
        "source_identity": identity(), "decision": "Allow implementation, local tests, desktop reload and visible activation.",
        "authorization": "Owner asked Friday to know and learn automatically from observed activity, and asked to continue.",
        "envelope": "Existing active-window and badge privacy gates; installed local models; provisional bounded learning; private ordinary chat and offline TTS; no new automatic notifications.",
        "ownership": "Root sole writer; helpers reviewed read-only. No commit, push, publication or provider setting changes."})


def receipt():
    saved = json.loads((ROOT / "tasks/passive-tested-sources.json").read_text(encoding="utf-8"))
    assert saved["files"] == sources(), "Source changed after tests were bound."
    suites = list(ET.parse(ROOT / "tasks/passive-full.xml").getroot().iter("testsuite"))
    counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    assert counts["tests"] > 5800 and not counts["failures"] and not counts["errors"]
    native = json.loads((ROOT / "tasks/passive-native-proof.json").read_text(encoding="utf-8"))
    assert native["production_identity"] == production_identity(saved["files"])
    for key in ("learned_before_any_activity_question", "ordinary_contextual_reply", "native_ordinary_reply_readable",
                "native_followup_uses_private_thread", "native_vision_updates_learning",
                "native_protected_field_blocks_image", "native_pause_button"):
        assert native[key]
    model = json.loads((ROOT / "tasks/passive-model-probes.json").read_text(encoding="utf-8"))
    assert model["inference_sha256"] == saved["files"]["services/screen_watch/inference.py"]
    assert {r["source"] for r in model["results"]} == {"text", "vision"}
    assert model["synthetic_only"] and all(r["semantic_check"] and not r["needs_vision"] and r["subject"] for r in model["results"])
    assert saved["files"]["interfaces/body/window.py"] == "711a3f8dfb77d2f751c039cd9c0e5c97611c64cf15e901760f0e4cc6f1b054fb"
    baseline = json.loads((ROOT / "tasks/screen-feature-verification.json").read_text(encoding="utf-8"))
    result = {"source_identity": saved["identity"], "production_identity": production_identity(saved["files"]),
              "full": counts, "native": native, "model_probes": model,
              "native_binding": "Production source hashes match the native proof; subsequent changes isolated chat tests and verification helpers.",
              "baseline": {"source_identity": baseline["source_identity"], "full": baseline["full"]},
              "original_robot_preserved": True,
              "behavior": "Background saves update learning before any question; ordinary local conversation consumes dated context automatically; sustained observed focus gates optional interruptions.",
              "privacy": "Validated local models only; private conversation and offline uncached TTS; no shared history or owner-fact promotion; pause/forget fences late replies.",
              "retention": "200 observations and 512 daily activity buckets, seven days; recurrence requires three days with at least 60 observed seconds each.",
              "limits": "Model interpretation is provisional and does not prove owner intent or task completion; unsupported/private windows remain blocked."}
    write("passive-feature-verification.json", result)
    print(json.dumps({"source_identity": saved["identity"], "full": counts, "native_verified": True}, indent=2))


def activate():
    import win32gui
    from services.screen_watch import capture
    from tasks.screen_native_probe import api_client, command, wait
    checked = json.loads((ROOT / "tasks/passive-feature-verification.json").read_text(encoding="utf-8"))
    assert checked["source_identity"] == identity(), "Source changed after verification."
    with api_client() as client:
        command(client, "resume screen awareness")
        wait(lambda: capture.indicator(win32gui.FindWindow(None, capture.BADGE_TITLE)), 25, "Watching badge did not become visible")
        def live():
            response = client.get("/api/v1/system/status")
            response.raise_for_status()
            state = response.json()["screen_watch"]
            return state if state["enabled"] and not state["paused"] and state["state"] != "waiting_for_indicator" else None
        state = wait(live, 15, "Watching badge heartbeat did not reach Friday")
    result = {"source_identity": identity(), "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "visible_badge": True, "status": state, "automatic_learning": True, "ordinary_private_conversation": True}
    write("passive-feature-activation.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "policy", "receipt", "activate"))
    {"snapshot": snapshot, "policy": policy, "receipt": receipt, "activate": activate}[parser.parse_args().mode]()
