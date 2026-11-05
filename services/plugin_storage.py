"""Plugin state lives in the user's profile, using FRIDAY's atomic JSON writer."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Callable

from services import settings_store


def user_data_dir() -> Path:
    path = Path(os.environ.get('FRIDAY_USER_DATA',
                str(Path(os.environ.get('APPDATA', Path.home() / '.config')) / 'FRIDAY')))
    if not path.is_absolute():
        raise ValueError('FRIDAY_USER_DATA must be absolute.')
    path = path.resolve()
    if path.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Plugin user data must be outside the FRIDAY repository.')
    return path


class Settings:
    def __init__(self, path: Path, active: Callable[[], None] = lambda: None):
        self.path, self._active = path, active

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError(f'Expected a JSON object in {self.path.name}')
        return value

    def get(self, key: str, default=None):
        with settings_store.lock:
            return deepcopy(self._read().get(key, default))

    def set(self, key: str, value):
        if not isinstance(key, str) or not key:
            raise ValueError('Setting keys must be nonempty strings.')
        json.dumps(value, allow_nan=False)
        with settings_store.lock:
            self._active()
            settings_store.save(self.path, self._read() | {key: value})
