"""Copy the validated assistant source into an isolated test checkout."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tasks/passive-validation/source"
OWN_UPDATES = {"tests/conftest.py", "tests/test_chat_test_isolation.py",
               "tasks/passive_native_probe.py", "tasks/verify_passive_assistant.py"}


def main():
    saved = json.loads((ROOT / "tasks/passive-tested-sources.json").read_text(encoding="utf-8"))
    assert TARGET.resolve().is_relative_to(ROOT / "tasks") and not TARGET.exists()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    names = set(tracked) | set(saved["files"]) | OWN_UPDATES
    TARGET.mkdir(parents=True)
    copied = {}
    for name in sorted(names):
        if not name or name.startswith(("memory/", "logs/", "venv/", ".git/", "services/college/")):
            continue
        if name.startswith("tasks/git-publication/"):
            continue
        if name.startswith("docs/specs/2026-10-29-college") or Path(name).name == ".env":
            continue
        source = ROOT / name
        if not source.is_file():
            continue
        assert source.resolve().is_relative_to(ROOT)
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if name in saved["files"] and name not in OWN_UPDATES:
            assert digest == saved["files"][name], "Concurrent edit: " + name
        destination = TARGET / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        copied[name] = digest
    # Native helpers and the ordinary model probe are in this exact source copy.
    manifest = {"origin_identity": saved["identity"], "copied_files": copied,
                "scope": "Assistant source only; concurrent college feature excluded; no owner databases, credentials or logs copied."}
    (ROOT / "tasks/passive-validation-snapshot.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"validation_source": str(TARGET), "files": len(copied)}))


if __name__ == "__main__":
    main()
