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
def save(path: Path, value: dict) -> None:
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
