"""FRIDAY notification suppression shared by backend and desktop processes."""
import json

from services import settings_store
from services import plugin_storage


def path():
    return plugin_storage.user_data_dir() / 'quiet-state.json'


def _read():
    file = path()
    if not file.exists():
        return {'version': 1, 'owners': {}}
    value = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('owners'), dict):
        raise ValueError('Invalid quiet-state.json; restore it before changing quiet mode.')
    if any(not isinstance(k, str) or not 1 <= len(k) <= 128 or type(v) is not bool for k, v in value['owners'].items()):
        raise ValueError('Invalid quiet-mode owner data; original state was preserved.')
    return value


def enabled():
    try:
        return any(_read()['owners'].values())
    except (OSError, ValueError):
        return True  # An unreadable saved quiet state must not leak ordinary interruptions.


def suppresses(urgency='normal'):
    return urgency != 'critical' and enabled()


def owner_enabled(owner):
    with settings_store.lock:
        return bool(_read()['owners'].get(owner))


def set_owner(owner, on):
    if not isinstance(owner, str) or not owner or len(owner) > 128 or type(on) is not bool:
        raise ValueError('Quiet mode needs a bounded owner and a boolean value.')
    with settings_store.lock:
        state = _read()
        if on:
            state['owners'][owner] = True
        else:
            state['owners'].pop(owner, None)
        settings_store.save(path(), state)
