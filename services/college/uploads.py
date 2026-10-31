"""Ephemeral editable imports. Only explicit, reviewed confirmation publishes data."""
import asyncio
from datetime import datetime
import hashlib
import re
import threading
import time
import uuid

from core.config import config
from core.errors import ProviderError
from services import settings_store
from services.college import parsers, schedules, store
from services.proactive import class_sessions, timetable

_pending = {}
_lock = threading.RLock()
TTL = 15 * 60
MAX_PENDING = 4


def vision():
    from providers.failover import OLLAMA_VISION_MODEL, provider_chain
    from providers.policy import check_allowed
    chain = provider_chain(config.VISION_PROVIDER or config.ACTIVE_PROVIDER)
    candidates = []
    for name in chain:
        model = config.vision_model_for(name) or getattr(config, name.upper() + '_MODEL', '')
        if name != 'ollama' or OLLAMA_VISION_MODEL.search(model):
            candidates.append({'provider': name, 'model': model})
    selected = candidates[0] if candidates else None
    reason = ''
    try:
        check_allowed()
    except ProviderError as error:
        reason = str(error)
    if selected is None:
        reason = 'No configured, reachable vision provider is available.'
    state = {'selected': selected, 'available': bool(selected and not reason), 'reason': reason,
             'notice': 'Only the named provider receives this file; uploads do not use automatic provider fallback.'}
    return {**state, 'consent': store.revision(state)}


def _identity(identifier):
    if not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid upload identifier.')


def _prune():
    root = str(config.MEMORY_DIR.resolve())
    for key, entry in list(_pending.items()):
        if entry['expires'] <= time.monotonic() or entry['root'] != root:
            del _pending[key]


def _entry(token):
    _identity(token)
    _prune()
    if token not in _pending:
        raise store.Conflict('The upload preview expired. Choose the file again; nothing was saved.')
    return _pending[token]


def _response(token, entry):
    notice = ('No labeled text table found. Add preview rows manually; this text PDF stays local.'
              if not entry['rows'] and not entry['requires_vision'] else
              'Nothing is saved until Confirm. PDF imports use the first three pages; XLSX uses the active sheet.')
    return {'token': token, 'filename': entry['filename'], 'size': len(entry['bytes']),
            'rows': entry['rows'], 'revision': entry['revision'], 'requires_vision': entry['requires_vision'],
            'warnings': parsers.warnings(entry['rows'], timetable.subjects()),
            'notice': notice}


def stage(name, data):
    extension = parsers.filename(name)
    try:
        parsers.validate(data, extension)
        rows, needs_vision = parsers.parse(data, extension)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('The document could not be parsed. Check its format and table headings.') from error
    with _lock:
        _prune()
        if len(_pending) >= MAX_PENDING:
            raise ValueError('Four previews are already open. Discard an upload preview or wait 15 minutes.')
        token = uuid.uuid4().hex
        entry = {'root': str(config.MEMORY_DIR.resolve()), 'bytes': data, 'extension': extension,
                 'filename': name, 'rows': rows, 'requires_vision': needs_vision,
                 'revision': schedules.snapshot()['revision'], 'expires': time.monotonic() + TTL}
        _pending[token] = entry
        return _response(token, entry)


async def extract(token, consent, section=''):
    with _lock:
        entry = dict(_entry(token))
    approved = vision()
    if consent != approved['consent']:
        raise store.Conflict('Vision settings changed. Review the provider and give consent again.')
    if not approved['available']:
        raise ValueError(approved['reason'])
    if not entry['requires_vision']:
        raise ValueError('This file was parsed locally; no provider is needed.')
    images = await asyncio.to_thread(parsers.images, entry['bytes'], entry['extension'])
    # Frozen provider/model: consent cannot silently authorize a fallback recipient.
    rows = await timetable.extract_classes(images, approved['selected']['provider'], section,
                                            approved_model=approved['selected']['model'])
    if len(rows) > parsers.MAX_ROWS:
        raise ValueError('The extraction exceeds 300 class rows.')
    with _lock:
        current = _entry(token)
        current.update(rows=rows, requires_vision=False)
        current.pop('review', None)
        return _response(token, current)


def preview(token, body):
    with _lock:
        entry = _entry(token)
        state = schedules._state()
        store.require(state, body.revision)
        review = store.revision(body.model_dump())
        result = {'warnings': parsers.warnings(body.rows, timetable.subjects()), 'valid': False,
                  'revision': body.revision, 'review': review}
        try:
            candidate = schedules.import_candidate(state['weekly'], body.rows, body.mode)
        except ValueError:
            entry.pop('review', None)
            return {**result, 'message': 'Fix missing/invalid fields and overlaps before Confirm.', 'diff': {}}
        entry.update(review=review, revision=body.revision, rows=body.rows)
        return {**result, 'valid': True, 'diff': schedules.diff(state['weekly'], candidate),
                'message': 'Review the added and removed slots, then Confirm.'}


def _root():
    base = config.MEMORY_DIR.resolve()
    folder = config.MEMORY_DIR / 'college' / 'uploads'
    for part in (folder.parent, folder):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise store.Unavailable('The uploads folder must not be a link or junction.')
    if not folder.resolve().is_relative_to(base):
        raise store.Unavailable('Unsafe uploads folder.')
    return folder


def _manifest():
    folder = _root()
    rows = store.read(folder / 'index.json', [])
    try:
        seen = set()
        for row in rows:
            _identity(row['id'])
            if row['id'] in seen or parsers.filename(row['filename']) != row['extension']:
                raise ValueError('Invalid upload manifest')
            seen.add(row['id'])
    except (ValueError, TypeError, KeyError) as error:
        raise store.Unavailable('Saved upload list is unreadable; repair it before editing.') from error
    return rows


def listing():
    rows = _manifest()
    return {'revision': store.revision(rows), 'items': rows}


def confirm(token, body):
    checked = body.model_dump(exclude={'review'})
    with _lock, timetable.edit(), class_sessions.edit(), store.edit(_root() / 'index.json'):
        entry = _entry(token)
        if entry.get('review') != body.review or body.review != store.revision(checked):
            raise store.Conflict('The edited rows or import mode changed. Review the diff again before Confirm.')
        state = schedules._state()
        store.require(state, body.revision)
        candidate = schedules.import_candidate(state['weekly'], body.rows, body.mode)
        rows = _manifest()
        identifier = uuid.uuid4().hex
        folder = _root()
        file = folder / (identifier + entry['extension'])
        record = {'id': identifier, 'filename': entry['filename'], 'extension': entry['extension'],
                  'size': len(entry['bytes']), 'sha256': hashlib.sha256(entry['bytes']).hexdigest(),
                  'confirmed_at': datetime.now().isoformat(timespec='seconds'), 'mode': body.mode}
        try:
            settings_store.publish(file, entry['bytes'])
            store.save(folder / 'index.json', [*rows, record])
            timetable._save(candidate)
        except OSError:
            # Best effort across three independent atomic files, not a crash transaction.
            for cleanup in (lambda: timetable._save(state['weekly']),
                            lambda: store.save(folder / 'index.json', rows),
                            lambda: file.unlink(missing_ok=True)):
                try:
                    cleanup()
                except OSError:
                    pass
            raise
        del _pending[token]
        return {'timetable': schedules.snapshot(), 'uploads': listing(), 'message': 'Upload confirmed and timetable saved.'}


def discard(token):
    with _lock:
        _identity(token)
        _pending.pop(token, None)
    return {'message': 'Preview discarded. Nothing was saved.'}


def delete(identifier, revision):
    _identity(identifier)
    folder = _root()
    with store.edit(folder / 'index.json'):
        rows = _manifest()
        store.require(rows, revision)
        row = store.find(rows, identifier)
        file = folder / (identifier + row['extension'])
        if file.is_symlink() or not file.resolve().is_relative_to(folder.resolve()):
            raise store.Unavailable('Unsafe saved upload path.')
        # Remove bytes first: a failure preserves the manifest so deletion can be retried.
        file.unlink(missing_ok=True)
        rows.remove(row)
        store.save(folder / 'index.json', rows)
        return listing()
