"""Shared backend lock and atomic writes for editable JSON configuration."""
import functools
import json
import os
from pathlib import Path
import tempfile
import threading

lock = threading.RLock()


def synchronized(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with lock:
            return function(*args, **kwargs)
    return wrapped


@synchronized
def publish(path: Path, content: bytes) -> None:
    """Publish bytes atomically; callers hold the relevant catalog writer guard."""
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@synchronized
def save(path: Path, value: dict | list) -> None:
    publish(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))
