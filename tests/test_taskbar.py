"""Lifecycle checks use disposable processes and never touch the owner's backend."""

from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil
import pytest

from interfaces.taskbar import runtime as runtime_module, windows
from interfaces.taskbar.runtime import BackendRuntime

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop")

STOP_WAIT = (
    "import ctypes\n"
    "k=ctypes.WinDLL('kernel32')\n"
    "k.OpenEventW.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_wchar_p]\n"
    "k.OpenEventW.restype=ctypes.c_void_p\n"
    "k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]\n"
    "name=next(a.split('=',1)[1] for a in sys.argv if a.startswith('--desktop-stop-event='))\n"
    "event=k.OpenEventW(0x100000,False,name)\n"
    "k.WaitForSingleObject(event,0xffffffff)\n"
)


def wait_for(check, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.05)
    pytest.fail("Disposable process did not reach the expected state")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "FRIDAY with spaces"
    root.mkdir()
    (root / "main.py").write_text(
        "import os, sys\nfrom pathlib import Path\n"
        "Path('backend.pid').write_text(str(os.getpid()))\n"
        + STOP_WAIT +
        "Path('graceful.txt').write_text('closed')\n", encoding="utf-8")
    instance = BackendRuntime(root)

    def online():
        marker = root / "backend.pid"
        if not instance.owned or not marker.exists():
            return False
        try:
            return psutil.pid_exists(int(marker.read_text()))
        except ValueError:
            return False

    monkeypatch.setattr(runtime_module.backend, "is_online", online)
    yield instance
    instance.close()


def test_start_is_idempotent_and_restart_replaces_only_owned_backend(runtime):
    manual = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"],
                              creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        runtime.operate("start")
        first = runtime.process
        assert runtime.owned and not runtime.busy
        runtime.operate("start")
        assert runtime.process is first
        runtime.operate("restart")
        assert first.poll() is not None
        assert runtime.owned and runtime.process.pid != first.pid
        replacement = runtime.process
        runtime.operate("stop")
        assert replacement.poll() is not None and not runtime.owned
        assert (runtime.root / "graceful.txt").read_text() == "closed"
        assert manual.poll() is None
    finally:
        manual.terminate()
        manual.wait(timeout=5)


def test_attached_backend_is_never_stopped_or_restarted(runtime, monkeypatch):
    monkeypatch.setattr(runtime_module.backend, "is_online", lambda: True)
    runtime.operate("start")
    assert runtime.process is None and "existing" in runtime.message
    for action in ("stop", "restart"):
        runtime.operate(action)
        assert runtime.process is None and "elsewhere" in runtime.message


def test_startup_failure_is_visible_and_retry_works(runtime):
    (runtime.root / "main.py").write_text("raise RuntimeError('disposable startup error')", encoding="utf-8")
    runtime.operate("start")
    assert not runtime.owned and "could not start" in runtime.message
    assert "disposable startup error" in (runtime.root / "logs/backend-desktop.log").read_text()


def test_timeout_cleans_up_and_quit_interrupts_pending_start(runtime, monkeypatch):
    monkeypatch.setattr(runtime_module.backend, "is_online", lambda: False)
    monkeypatch.setattr(runtime_module, "START_TIMEOUT", .1)
    runtime.operate("start")
    assert not runtime.owned and "timed out" in runtime.message
    monkeypatch.setattr(runtime_module, "START_TIMEOUT", 90)
    worker = threading.Thread(target=runtime.operate, args=("start",))
    worker.start()
    wait_for(lambda: runtime.owned)
    owned = runtime.process
    runtime.close()
    worker.join(timeout=5)
    assert not worker.is_alive() and owned.poll() is not None


def test_stop_preserves_apps_started_by_friday(runtime):
    (runtime.root / "main.py").write_text(
        "import subprocess, sys, os, time\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "Path('child.pid').write_text(str(child.pid))\n"
        "Path('backend.pid').write_text(str(os.getpid()))\n"
        + STOP_WAIT, encoding="utf-8")
    runtime.operate("start")
    child = psutil.Process(int((runtime.root / "child.pid").read_text()))
    try:
        runtime.operate("stop")
        assert child.is_running()
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_force_fallback_stops_the_managed_interpreter(runtime, monkeypatch):
    monkeypatch.setattr(runtime_module, "STOP_TIMEOUT", .1)
    (runtime.root / "main.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        "Path('backend.pid').write_text(str(os.getpid()))\n"
        "while True: time.sleep(.05)\n", encoding="utf-8")
    runtime.operate("start")
    actual = psutil.Process(int((runtime.root / "backend.pid").read_text()))
    runtime.operate("stop")
    actual.wait(timeout=5)
    assert not actual.is_running() and not runtime.owned


def test_single_instance_focuses_without_starting_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(windows, "MUTEX_NAME", "FridayTaskbarTest" + tmp_path.name)
    focused = []
    monkeypatch.setattr(windows, "focus_existing", lambda: focused.append(True))
    handle = windows.acquire_instance()
    try:
        assert handle
        assert windows.acquire_instance() is None
        assert focused == [True]
    finally:
        windows.release_instance(handle)
    handle = windows.acquire_instance()
    assert handle
    windows.release_instance(handle)


def test_second_main_exits_before_backend_creation(monkeypatch):
    from interfaces.tray import app
    monkeypatch.setattr(app, "prepare_process", lambda: None)
    monkeypatch.setattr(app, "acquire_instance", lambda: None)
    monkeypatch.setattr(app, "BackendRuntime", lambda: pytest.fail("duplicate launch started a backend"))
    app.main()


def test_shortcut_has_matching_identity_icon_and_relaunch(tmp_path):
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell
    destination = windows.create_shortcut(tmp_path / "FRIDAY shortcut.lnk")
    pythoncom.CoInitialize()
    try:
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                         pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(destination))
        assert Path(link.GetPath(0)[0]).resolve() == windows.pythonw()
        assert link.GetArguments() == subprocess.list2cmdline(["-B", str(windows.LAUNCH_PATH)])
        assert Path(link.GetWorkingDirectory()) == windows.ROOT
        assert Path(link.GetIconLocation()[0]) == windows.ICON_PATH
        store = link.QueryInterface(propsys.IID_IPropertyStore)
        assert store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue() == windows.APP_ID
        assert store.GetValue(pscon.PKEY_AppUserModel_RelaunchCommand).GetValue() == windows.relaunch_command()
    finally:
        pythoncom.CoUninitialize()
