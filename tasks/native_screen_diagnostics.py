"""Owned-window diagnostics: process/focus metadata only, never desktop pixels/text."""
import asyncio
import ctypes
from pathlib import Path
import json
import os
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


class WorkerStatus:
    def __init__(self, stopped):
        from services.screen_watch import create_reader
        self.reader = create_reader(stopped)
        (ROOT / "tasks/screen-native-worker-started.json").write_text(json.dumps({
            "interpreter": sys.executable, "prefix": sys.prefix}), encoding="utf-8")

    def state(self):
        try:
            apartment, qualifier = ctypes.c_int(), ctypes.c_int()
            ctypes.OleDLL("ole32").CoGetApartmentType(ctypes.byref(apartment), ctypes.byref(qualifier))
            return {"pid": os.getpid(), "interpreter": Path(sys.executable).name,
                    "has_console": bool(ctypes.windll.kernel32.GetConsoleWindow()),
                    "venv": Path(sys.prefix).resolve() == ROOT / "venv", "apartment": apartment.value}
        except Exception:
            import traceback
            (ROOT / "tasks/screen-native-worker-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            raise

    def close(self):
        self.reader.close()


async def worker_state():
    from services.browser.worker import ProcessRuntime
    stopped = threading.Event()
    worker = ProcessRuntime(WorkerStatus, (), stopped, timeout=8)
    try:
        state = await worker.call("state")
        assert state["pid"] == worker.process.pid and state["venv"] and not state["has_console"] and state["apartment"] == 1
        import hashlib
        state["worker_sha256"] = hashlib.sha256((ROOT / "services/browser/worker.py").read_bytes()).hexdigest()
        state["reader_factory_sha256"] = hashlib.sha256((ROOT / "services/screen_watch/__init__.py").read_bytes()).hexdigest()
        (ROOT / "tasks/screen-native-worker-proof.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state
    finally:
        stopped.set()
        await worker.aclose()


def diagnose():
    import psutil
    import win32con
    import win32gui
    import win32process
    from services.browser.worker import ProcessRuntime
    from services.screen_watch import capture
    from services.screen_watch.store import ScreenStore
    from tasks.screen_native_probe import api_client, build_fixture, command, focus_fixture, wait
    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    fixture = build_fixture()
    hwnd = None
    try:
        hwnd = wait(lambda: win32gui.FindWindow(None, "Graph lecture fixture - Friday screen test"))
        assert win32process.GetWindowThreadProcessId(hwnd)[1] == fixture.pid
        focus_fixture(hwnd)
        with api_client() as client:
            command(client, "start screen awareness")
            last = None
            for i in range(60):
                foreground = capture.foreground()
                state = (foreground["app"], foreground["scope"]["pid"]) if foreground else (None, None)
                if state != last:
                    print(json.dumps({"after_seconds": round(i * .2, 1), "foreground": state,
                                      "fixture": fixture.pid}), flush=True)
                    last = state
                time.sleep(.2)
            async def hidden():
                stopped = threading.Event()
                worker = ProcessRuntime(WorkerStatus, (), stopped, timeout=30)
                try:
                    job = asyncio.create_task(worker.call("state"))
                    await asyncio.sleep(2)
                    print(json.dumps({"parent_interpreter": sys.executable,
                                      "worker_pid": worker.process.pid}), flush=True)
                    for process in [psutil.Process(worker.process.pid), *psutil.Process(worker.process.pid).children(recursive=True)]:
                        print(json.dumps({"child_metadata": {"pid": process.pid, "name": process.name(),
                              "executable": process.exe(), "command": process.cmdline()}}), flush=True)
                    return await job
                finally:
                    stopped.set()
                    await worker.aclose()
            print(json.dumps({"owned_worker": asyncio.run(hidden())}), flush=True)
            for process in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
                try:
                    args = process.info["cmdline"] or []
                    entry = next((Path(arg).name for arg in args if str(ROOT).lower() in arg.lower()
                                  and Path(arg).suffix == ".py"), None)
                    if entry or process.info["name"].lower() == "fridayscreenfixture.exe":
                        print(json.dumps({"owned_process": {key: process.info[key] for key in ("pid", "ppid", "name")},
                                          "entry": entry}), flush=True)
                except (psutil.Error, OSError):
                    pass
    finally:
        ScreenStore().control("pause")
        ScreenStore().forget("fridayscreenfixture")
        if hwnd and win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        fixture.wait(timeout=10)
