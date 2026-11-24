"""Capacity and failure limits shared by all model transports."""
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout
from contextvars import copy_context
from dataclasses import dataclass
import threading
import time

from core.config import config
from core.errors import ModelUnavailable

FAILURES_BEFORE_OPEN = 3
RECOVERY_SECONDS = 120
_io_slots = threading.BoundedSemaphore(4)
_embedding_slots = threading.BoundedSemaphore(2)
_embedding_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="friday-embeddings")
_lock = threading.RLock()
_tasks: set[asyncio.Task] = set()
_epoch = 0


@dataclass
class Circuit:
    failures: int = 0
    generation: int = 0
    open_until: float = 0.
    probing: bool = False
    last_failure: float | None = None
    last_success: float | None = None


_circuits: dict[str, Circuit] = {}


def require_enabled():
    if config.FRIDAY_LLM != "on":
        raise ModelUnavailable("The model is off.")


def status(name):
    with _lock:
        state = _circuits.get(name, Circuit())
        enabled = config.FRIDAY_LLM == "on"
        opened = time.monotonic() < state.open_until
        label = ("off" if not enabled else "circuit open" if opened else "probing" if state.probing else
                 "unavailable" if (state.last_failure or 0) > (state.last_success or 0) else
                 "ready" if state.last_success else "idle")
        return {"enabled": enabled, "status": label, "last_success": state.last_success,
                "last_failure": state.last_failure,
                "open_until": time.time() + max(0, state.open_until - time.monotonic()) if opened else None}


def reset():
    global _epoch
    with _lock:
        _epoch += 1
        _circuits.clear()


def cancel_pending():
    with _lock:
        for task in tuple(_tasks):
            try:
                task.get_loop().call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # That loop has already shut down.


def _admit(name, slots):
    require_enabled()
    with _lock:
        state = _circuits.setdefault(name, Circuit())
        if time.monotonic() < state.open_until or state.probing:
            raise ModelUnavailable("The model is recovering. I can use local rules.")
        if not slots.acquire(blocking=False):
            raise ModelUnavailable("The model is busy. I can use local rules.")
        state.probing = bool(state.open_until)
        return state, state.generation, _epoch


def _require_current(ticket):
    require_enabled()
    with _lock:
        if ticket[2] != _epoch:
            raise ModelUnavailable("Model settings changed during the request.")


def _finish(ticket, success):
    state, generation, epoch = ticket
    with _lock:
        if state.generation != generation or epoch != _epoch:
            return
        state.probing = False
        if success is None or config.FRIDAY_LLM != "on":
            return
        if success:
            state.failures = 0
            state.open_until = 0.
            state.last_success = time.time()
        else:
            state.last_failure = time.time()
            state.failures += 1
            if state.failures >= FAILURES_BEFORE_OPEN:
                state.open_until = time.monotonic() + RECOVERY_SECONDS
                state.generation += 1


async def _invoke(operation):
    require_enabled()
    return await operation()


async def run_async(name, operation, *, timeout):
    """Bound I/O tasks without queueing or tying up a thread per HTTP request."""
    ticket = _admit(name, _io_slots)
    task = asyncio.create_task(_invoke(operation))
    with _lock:
        _tasks.add(task)

    def done(future):
        if not future.cancelled():
            future.exception()  # Consume failures even if the caller already fell back.
        with _lock:
            _tasks.discard(future)
        _io_slots.release()

    task.add_done_callback(done)
    try:
        completed, _ = await asyncio.wait({task}, timeout=timeout)
        if not completed:
            task.cancel()
            raise ModelUnavailable("The model timed out.")
        if task.cancelled() and config.FRIDAY_LLM != "on":
            raise ModelUnavailable("The model is off.")
        result = task.result()
        _require_current(ticket)
    except (asyncio.CancelledError, InterruptedError):
        task.cancel()
        _finish(ticket, None)
        raise
    except Exception:
        _finish(ticket, False)
        raise
    _finish(ticket, True)
    return result


def _invoke_embedding(operation):
    require_enabled()
    return operation()


def run_embedding(name, operation, *, timeout):
    """Keep native inference bounded even if a model loader cannot be interrupted."""
    ticket = _admit(name, _embedding_slots)
    try:
        future = _embedding_workers.submit(copy_context().run, _invoke_embedding, operation)
    except BaseException:
        _embedding_slots.release()
        _finish(ticket, None)
        raise
    future.add_done_callback(lambda _: _embedding_slots.release())
    try:
        result = future.result(timeout=timeout)
        _require_current(ticket)
    except WorkerTimeout as error:
        future.cancel()
        _finish(ticket, False)
        raise ModelUnavailable("The embedding model timed out.") from error
    except Exception:
        _finish(ticket, False)
        raise
    _finish(ticket, True)
    return result
