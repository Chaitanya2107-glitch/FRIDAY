"""Killable owned adapters. A stalled page or native provider cannot hang the API."""

import asyncio
import multiprocessing
import os
from pathlib import Path
import queue
import sys
import threading
import time

_spawn_lock = threading.Lock()


def _start_process(process):
    if os.name != "nt":
        process.start()
        return
    from multiprocessing.spawn import get_executable
    executable = Path(sys.executable).with_name("pythonw.exe")
    base = Path(getattr(sys, "_base_executable", sys.executable)).with_name("pythonw.exe")
    if not executable.is_file() or not base.is_file():
        raise RuntimeError("A console-free Python worker is unavailable")
    # Windows spawn otherwise opens a console when the desktop parent has none.
    # Restore the global setting even if starting this owned helper fails.
    with _spawn_lock:
        previous = get_executable()
        launcher = os.environ.get("__PYVENV_LAUNCHER__")
        try:
            # Launch the base interpreter directly: the venv redirector cannot
            # inherit the handles multiprocessing duplicates into its child.
            os.environ["__PYVENV_LAUNCHER__"] = str(executable)
            multiprocessing.set_executable(str(base))
            process.start()
        finally:
            multiprocessing.set_executable(previous)
            if launcher is None:
                os.environ.pop("__PYVENV_LAUNCHER__", None)
            else:
                os.environ["__PYVENV_LAUNCHER__"] = launcher


def _run_worker(factory, arguments, requests, replies, stopped):
    if os.name == "nt":
        sys.coinit_flags = 0  # pythoncom must select MTA on its first import.
    adapter = factory(stopped, *arguments)
    try:
        while not stopped.is_set():
            try:
                number, name, args = requests.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                value = getattr(adapter, name)(*args)
                replies.put((number, True, value))
            except Exception as error:
                # Exception messages can contain URLs, page bodies or private text.
                replies.put((number, False, type(error).__name__))
    finally:
        try:
            adapter.close()
        except Exception:
            pass  # the parent closes the owned job/process and checks its exit


class ProcessRuntime:
    def __init__(self, factory, arguments, stopped, *, browser_tree=False, timeout=20):
        self.stopped, self.browser_tree, self.timeout = stopped, browser_tree, timeout
        context = multiprocessing.get_context("spawn")
        self.requests, self.replies = context.Queue(), context.Queue()
        self.cancelled = context.Event()
        self.process = context.Process(target=_run_worker,
            args=(factory, arguments, self.requests, self.replies, self.cancelled),
            daemon=True, name="friday-browser" if browser_tree else "friday-uia")
        self.started, self.number, self.job = False, 0, None
        self.children = []

    def _start(self):
        _start_process(self.process)
        self.started = True
        if self.browser_tree and os.name == "nt":
            # Establish the job BEFORE sending an operation that can spawn a
            # browser. Closing this handle kills only this helper and its children.
            import win32api
            import win32job
            self.job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
            handle = win32api.OpenProcess(0x0100 | 0x0001, False, self.process.pid)
            try:
                win32job.AssignProcessToJobObject(self.job, handle)
            finally:
                handle.Close()

    def _remember_children(self):
        if self.browser_tree and os.name != "nt":
            import psutil
            try:
                self.children.extend(psutil.Process(self.process.pid).children(recursive=True))
            except psutil.NoSuchProcess:
                pass

    async def call(self, name, *args):
        if self.stopped.is_set() or self.cancelled.is_set():
            raise InterruptedError()
        if not self.started:
            self._start()
        self.number += 1
        number = self.number
        self.requests.put((number, name, args))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.stopped.is_set():
                self.cancelled.set()
                raise InterruptedError()
            try:
                received, success, value = self.replies.get_nowait()
                if received == number:
                    self._remember_children()
                    if not success:
                        raise ValueError("Automation operation unavailable: " + value)
                    return value
            except queue.Empty:
                pass
            if not self.process.is_alive():
                raise ValueError("Automation worker exited")
            await asyncio.sleep(.02)
        self.cancelled.set()
        raise TimeoutError("Automation provider did not respond")

    async def aclose(self):
        self.cancelled.set()
        if self.started:
            self._remember_children()
            await asyncio.to_thread(self.process.join, 2)
            if self.job:
                self.job.Close()
                self.job = None
            elif self.browser_tree and os.name != "nt":
                import psutil
                for child in reversed(self.children):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
            if self.process.is_alive():
                self.process.terminate()
            await asyncio.to_thread(self.process.join, 2)
            if self.process.is_alive():
                raise RuntimeError("Owned automation worker did not exit")
        for channel in (self.requests, self.replies):
            channel.cancel_join_thread()
            channel.close()
