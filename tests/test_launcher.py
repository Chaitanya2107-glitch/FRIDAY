"""Exercise the VBS bootstrap with a disposable GUI interpreter and desktop."""

import json
import shutil
import subprocess
import sys
import time
import runpy
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.1)
    pytest.fail("Disposable launcher process did not reach the expected state")


@pytest.fixture
def launch(tmp_path):
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    executable = scripts / "pythonw.exe"
    shutil.copyfile(Path(sys.executable).with_name("pythonw.exe"), executable)
    (scripts.parent / "pyvenv.cfg").write_text(f"home = {sys.base_prefix}\n", encoding="utf-8")
    tray = tmp_path / "interfaces" / "taskbar"
    tray.mkdir(parents=True)
    (tray / "launch.py").write_text(
        "import os, sys, json\nfrom pathlib import Path\n"
        "Path('desktop.json').write_text(json.dumps({'cwd':os.getcwd(),'path':sys.argv[0]}))\n",
        encoding="utf-8")
    source = (ROOT / "launch_friday.vbs").read_text(encoding="utf-8")
    launcher = tmp_path / "launch_friday.vbs"
    launcher.write_text(source, encoding="utf-8")
    return tmp_path, launcher


def test_vbs_launches_absolute_taskbar_bootstrap_from_another_folder(launch, tmp_path):
    root, launcher = launch
    outside = tmp_path / "outside"
    outside.mkdir()
    result = subprocess.run(["cscript.exe", "//nologo", str(launcher)], cwd=outside,
                            capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
    wait_for(lambda: (root / "desktop.json").exists())
    data = json.loads((root / "desktop.json").read_text())
    assert Path(data["cwd"]) == root
    assert Path(data["path"]) == root / "interfaces/taskbar/launch.py"


@pytest.mark.parametrize("arguments, reload", [([], True), (["--no-reload"], False)])
def test_launcher_flag_disables_reload_without_changing_manual_start(monkeypatch, arguments, reload):
    import uvicorn
    from core.config import config

    calls = []
    monkeypatch.setattr(config, "API_RELOAD", True)
    monkeypatch.setattr(config, "validate", lambda: [])
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(sys, "argv", [str(ROOT / "main.py"), *arguments])
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
    assert len(calls) == 1 and calls[0]["reload"] is reload


def test_managed_backend_event_requests_shutdown_without_touching_stdin(monkeypatch):
    import os
    import uvicorn
    from core.config import config
    from interfaces.taskbar.windows import create_backend_stop, release_instance, signal_backend_stop
    from types import SimpleNamespace
    states = []
    event_name, stop_event = create_backend_stop()

    class Server:
        should_exit = False

        def __init__(self, configuration):
            assert configuration.reload is False

        def run(self):
            assert sys.stdin.isatty() is False
            signal_backend_stop(stop_event)
            wait_for(lambda: self.should_exit)
            states.append("graceful shutdown requested")

    monkeypatch.setattr(config, "validate", lambda: [])
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(sys, "argv", [str(ROOT / "main.py"), "--desktop-managed",
                                    f"--desktop-stop-event={event_name}", f"--desktop-owner={os.getpid()}"])
    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(
        isatty=lambda: False, fileno=lambda: pytest.fail("Desktop shutdown must not consume stdin")))
    try:
        runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
    finally:
        release_instance(stop_event)
    assert states == ["graceful shutdown requested"]
