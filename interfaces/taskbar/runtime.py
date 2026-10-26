"""Own only the backend this desktop session started; never kill manual servers."""

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil

from core.logger import logger
from interfaces.taskbar.windows import ROOT, create_backend_stop, release_instance, signal_backend_stop
from interfaces.tray import backend

START_TIMEOUT = 300  # Cold speech/ML imports can exceed a minute on Windows.
STOP_TIMEOUT = 20


class BackendRuntime:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()
        self.process: subprocess.Popen | None = None
        self.busy = False
        self.message = "Click the taskbar button to start FRIDAY."
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._stop_event = None

    @property
    def owned(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def operate(self, action: str) -> None:
        """Serialize lifecycle changes; call on a worker, never Tk's event thread."""
        if action not in {"start", "stop", "restart"}:
            raise ValueError("Unknown FRIDAY lifecycle action")
        if not self._lock.acquire(blocking=False):
            return
        self.busy = True
        try:
            if self._closing.is_set():
                return
            self.message = {"start": "Starting FRIDAY...", "stop": "Stopping FRIDAY...",
                            "restart": "Restarting FRIDAY..."}[action]
            if action in {"stop", "restart"}:
                if not self.owned and backend.is_online():
                    raise RuntimeError("This backend was started elsewhere. Stop it in its own window.")
                self._stop()
            if action in {"start", "restart"}:
                self._start()
                self.message = "Ready" if self.owned else "Connected to an existing backend"
            else:
                self.message = "Stopped. Start FRIDAY whenever you're ready."
        except Exception as error:
            self.message = str(error)
            logger.exception("FRIDAY desktop %s failed", action)
        finally:
            self.busy = False
            self._lock.release()

    def _start(self) -> None:
        if self.owned or backend.is_online() or self._closing.is_set():
            return
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        executable = Path(sys.executable).with_name("python.exe")
        if self._stop_event:
            release_instance(self._stop_event)
        event_name, self._stop_event = create_backend_stop()
        env = {**os.environ, "API_RELOAD": "false", "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
        with (logs / "backend-desktop.log").open("ab") as output:
            self.process = subprocess.Popen(
                [str(executable), "-B", str(self.root / "main.py"), "--no-reload", "--desktop-managed",
                 f"--desktop-stop-event={event_name}", f"--desktop-owner={os.getpid()}"],
                cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        logger.info("Desktop started FRIDAY backend PID %s", self.process.pid)
        deadline = time.monotonic() + START_TIMEOUT
        while not self._closing.is_set():
            if self.process.poll() is not None:
                raise RuntimeError("FRIDAY could not start. See logs/backend-desktop.log.")
            if backend.is_online():
                return
            if time.monotonic() >= deadline:
                self._stop()
                raise RuntimeError("Startup timed out. See logs/backend-desktop.log, then try Start again.")
            self._closing.wait(.25)

    def _stop(self) -> None:
        if not self.owned:
            self.process = None
            if self._stop_event:
                release_instance(self._stop_event)
                self._stop_event = None
            return
        try:
            if self._stop_event:
                signal_backend_stop(self._stop_event)
            self.process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Windows' venv executable is a redirector with a child interpreter.
            # Match this exact managed script; other descendants can be user apps.
            logger.warning("Backend did not shut down in time; terminating its interpreter")
            try:
                parent = psutil.Process(self.process.pid)
                for process in parent.children(recursive=True):
                    try:
                        args = process.cmdline()
                        if "--desktop-managed" in args and any(
                            Path(arg).is_absolute() and Path(arg).resolve() == self.root / "main.py"
                            for arg in args[1:]
                        ):
                            process.terminate()
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=5)
        self.process = None
        if self._stop_event:
            release_instance(self._stop_event)
            self._stop_event = None

    def close(self) -> None:
        self._closing.set()
        with self._lock:
            self._stop()
