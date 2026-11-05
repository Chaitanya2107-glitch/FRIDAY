"""Reload the app allowance change while preserving the owner's watching setting."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from services.screen_watch.store import ScreenStore
    from tasks.screen_native_probe import api_client, command, reload_desktop
    reports = list(ET.parse(ROOT / "tasks/screen-app-access.xml").getroot().iter("testsuite"))
    assert sum(int(row.get("tests", 0)) for row in reports) >= 100
    assert all(not int(row.get(key, 0)) for row in reports for key in ("errors", "failures"))
    files = ("services/screen_watch/capture.py", "tests/test_screen_watch_capture.py", "docs/screen-awareness.md")
    before = ScreenStore().settings()
    receipt = {"decision": "Allow ordinary app and shell reading as requested; retain sensitive-content and own-window gates.",
               "sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
               "previous_settings": before, "preserve_pause": True}
    target = ROOT / "tasks/screen-app-access-activation.json"
    target.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    receipt["desktop"] = reload_desktop()
    with api_client() as client:
        if not before["enabled"]:
            command(client, "stop screen awareness")
        elif not before["paused"]:
            command(client, "resume screen awareness")
        result = client.get("/api/v1/system/status")
        result.raise_for_status()
        receipt["status"] = result.json()["screen_watch"]
    assert bool(receipt["status"]["enabled"]) == bool(before["enabled"])
    assert bool(receipt["status"]["paused"]) == bool(before["paused"]) if before["enabled"] else not receipt["status"]["enabled"]
    receipt["applied"] = True
    target.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"applied": True, "status": receipt["status"], "desktop": receipt["desktop"]}, indent=2))


if __name__ == "__main__":
    main()
