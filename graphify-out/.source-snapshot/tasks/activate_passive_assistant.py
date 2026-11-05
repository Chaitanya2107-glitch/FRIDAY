"""Activate the verified assistant feature while preserving concurrent college work."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VALIDATION = ROOT / "tasks/passive-validation/source/tasks"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    checked = json.loads((VALIDATION / "passive-feature-verification.json").read_text(encoding="utf-8"))
    saved = json.loads((VALIDATION / "passive-tested-sources.json").read_text(encoding="utf-8"))
    assert checked["source_identity"] == saved["identity"]
    assert not checked["full"]["failures"] and not checked["full"]["errors"]
    critical = {name: value for name, value in saved["files"].items() if name.startswith("services/screen_watch/")}
    for name in ("interfaces/api/routes/chat.py", "interfaces/api/routes/voice.py", "interfaces/popup/app.py",
                 "services/mind/cognition.py", "services/mind/executive.py", "services/mind/language.py",
                 "services/proactive/watcher.py", "services/browser/worker.py", "core/config.py", "main.py",
                 "interfaces/body/window.py", "interfaces/taskbar/screen_badge.py"):
        critical[name] = saved["files"][name]
    assert all(digest(ROOT / name) == value for name, value in critical.items()), "Assistant feature source changed after validation."
    # College adds command registrations and menu items; the private command guard is identical.
    name = "services/automation/intent.py"
    def guard(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return ast.dump(next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                             and node.name == "_understand_command"), include_attributes=False)
    assert guard(ROOT / name) == guard(VALIDATION.parent / name)
    return checked, critical


def main():
    import win32gui
    from services.screen_watch import capture
    from tasks.screen_native_probe import api_client, command, wait
    checked, critical = verify()
    policy = {"decision": "Activate the owner-requested, locally validated automatic assistant awareness.",
              "source_identity": checked["source_identity"], "critical_source_files": critical,
              "concurrent_work": "College feature edits are preserved and outside this isolated validation receipt.",
              "envelope": "Existing visible pause badge, local models only, no screenshots saved or publication."}
    (ROOT / "tasks/passive-activation-policy.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    with api_client() as client:
        command(client, "resume screen awareness")
        wait(lambda: capture.indicator(win32gui.FindWindow(None, capture.BADGE_TITLE)), 25,
             "The native watching badge did not become visible")
        def live():
            response = client.get("/api/v1/system/status")
            response.raise_for_status()
            state = response.json()["screen_watch"]
            return state if state["enabled"] and not state["paused"] and state["state"] != "waiting_for_indicator" else None
        state = wait(live, 15, "The native watching badge did not reach Friday")
    result = {"source_identity": checked["source_identity"], "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "visible_badge": True, "status": state, "automatic_learning": True,
              "ordinary_private_conversation": True, "full": checked["full"],
              "critical_source_files": critical, "activation_helper_sha256": digest(Path(__file__))}
    (ROOT / "tasks/passive-feature-activation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("source_identity", "visible_badge", "status", "full")}, indent=2))


if __name__ == "__main__":
    main()
