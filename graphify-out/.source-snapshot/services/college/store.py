"""Small catalog snapshots using FRIDAY's existing atomic writer and OS guard."""
import hashlib
import json

from core.config import config
from services import settings_store
from services.proactive import deadline_store


class Conflict(ValueError):
    pass


class Unavailable(ValueError):
    pass


def path(name):
    return config.MEMORY_DIR / 'college' / name


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def require(value, expected):
    if revision(value) != expected:
        raise Conflict('Changed elsewhere. Your draft is kept; reload and review the current version before saving.')


def read(file, default):
    try:
        value = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(value, type(default)):
            raise ValueError('Invalid catalog')
        return value
    except FileNotFoundError:
        return default.copy()
    except (OSError, ValueError, TypeError) as error:
        raise Unavailable('Saved college data is unreadable. Repair the file before editing it.') from error


def edit(file):
    return deadline_store.edit(file)


def save(file, value):
    settings_store.save(file, value)


def item_id(row):
    return row.get('id') or 'legacy-' + revision(row)


def find(rows, identifier):
    found = [row for row in rows if item_id(row) == identifier]
    if len(found) != 1:
        raise Conflict('That entry changed or is ambiguous. Reload before editing it.')
    return found[0]
