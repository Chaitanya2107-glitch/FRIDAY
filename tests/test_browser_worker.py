from multiprocessing import spawn
from types import SimpleNamespace

import pytest

from services.browser import worker


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("previous_launcher", [None, "existing-launcher"])
def test_windows_owned_worker_uses_direct_gui_python_and_restores_settings(tmp_path, monkeypatch, fail, previous_launcher):
    executable = tmp_path / "pythonw.exe"
    executable.touch()
    base = tmp_path / "base/pythonw.exe"
    base.parent.mkdir()
    base.touch()
    environment = {} if previous_launcher is None else {"__PYVENV_LAUNCHER__": previous_launcher}
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt", environ=environment))
    monkeypatch.setattr(worker.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(worker.sys, "_base_executable", str(base.with_name("python.exe")))
    selected, calls = [b"original-python"], []
    monkeypatch.setattr(spawn, "get_executable", lambda: selected[0])
    def set_executable(path):
        calls.append(path)
        selected[0] = path
    monkeypatch.setattr(worker.multiprocessing, "set_executable", set_executable)
    def start():
        assert selected[0] == str(base)
        assert environment["__PYVENV_LAUNCHER__"] == str(executable)
        if fail:
            raise OSError("Synthetic start failure")
    if fail:
        with pytest.raises(OSError):
            worker._start_process(SimpleNamespace(start=start))
    else:
        worker._start_process(SimpleNamespace(start=start))
    assert calls == [str(base), b"original-python"]
    assert environment == ({} if previous_launcher is None else {"__PYVENV_LAUNCHER__": previous_launcher})


def test_missing_gui_python_never_launches_a_console(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(worker.sys, "executable", str(tmp_path / "python.exe"))
    with pytest.raises(RuntimeError, match="console-free"):
        worker._start_process(SimpleNamespace(start=lambda: pytest.fail("Console worker launched")))


def test_non_windows_start_does_not_change_interpreter(monkeypatch):
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(worker.multiprocessing, "set_executable", lambda path: pytest.fail("Global interpreter changed"))
    called = []
    worker._start_process(SimpleNamespace(start=lambda: called.append(True)))
    assert called == [True]


def test_owned_windows_worker_selects_mta_before_importing_adapter(monkeypatch):
    import threading
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(worker.sys, "coinit_flags", 2, raising=False)
    stopped, replies = threading.Event(), []
    def factory(event):
        assert worker.sys.coinit_flags == 0
        def ping():
            event.set()
            return "ready"
        return SimpleNamespace(ping=ping, close=lambda: None)
    requests = SimpleNamespace(get=lambda timeout: (1, "ping", ()))
    worker._run_worker(factory, (), requests, SimpleNamespace(put=replies.append), stopped)
    assert replies == [(1, True, "ready")]
