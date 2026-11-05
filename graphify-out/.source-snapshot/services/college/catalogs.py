"""Subject metadata and dated events; weekly templates never carry faculty."""
import uuid

from services.college import models, store
from services.proactive import timetable


def subject_key(subject):
    return timetable.subject_named(subject).casefold()


def _subject_rows():
    rows = store.read(store.path('subjects.json'), {})
    try:
        for key, value in rows.items():
            if not isinstance(key, str):
                raise ValueError('Invalid subject key')
            models.Subject.model_validate(value)
    except (ValueError, TypeError) as error:
        raise store.Unavailable('Saved subject details are unreadable; repair them before editing.') from error
    return rows


def subject_for(subject, rows=None):
    rows = _subject_rows() if rows is None else rows
    key = subject_key(subject)
    if key in rows:
        return dict(rows[key])
    matches = [r for r in rows.values() if subject_key(r['subject']) == key
               or timetable.abbreviates(subject, r['subject']) or timetable.abbreviates(r['subject'], subject)]
    return dict(matches[0]) if len(matches) == 1 else {'subject': subject, 'faculty': '', 'room': '', 'email': '', 'notes': ''}


def subjects():
    rows = _subject_rows()
    names = list(dict.fromkeys([*timetable.subjects(), *(r['subject'] for r in rows.values())]))
    items = {}
    for name in names:
        value = subject_for(name, rows)
        items.setdefault(subject_key(value['subject']), {'id': subject_key(value['subject']), **value})
    return {'revision': store.revision(rows), 'items': list(items.values())}


def change_subject(identifier, value, revision):
    validated = models.Subject.model_validate(value).model_dump() if value is not None else None
    with store.edit(store.path('subjects.json')):
        rows = _subject_rows()
        store.require(rows, revision)
        if identifier is not None:
            # Known timetable subjects may not have stored metadata yet.
            if identifier not in {r['id'] for r in subjects()['items']}:
                raise store.Conflict('Subject changed. Reload before editing.')
            for key, row in list(rows.items()):
                if key == identifier or subject_key(row['subject']) == identifier:
                    del rows[key]
        if validated is not None:
            key = subject_key(validated['subject'])
            if key in rows:
                raise ValueError('Subject details already exist. Edit the saved entry.')
            rows[key] = validated
        store.save(store.path('subjects.json'), rows)
        return subjects()


def _events():
    rows = store.read(store.path('events.json'), [])
    try:
        ids = set()
        for row in rows:
            identifier = row['id']
            if not isinstance(identifier, str) or identifier in ids:
                raise ValueError('Invalid event identity')
            ids.add(identifier)
            models.Event.model_validate({k: v for k, v in row.items() if k != 'id'})
    except (ValueError, KeyError, TypeError) as error:
        raise store.Unavailable('Saved college events are unreadable; repair them before editing.') from error
    return rows


def events():
    rows = _events()
    return {'revision': store.revision(rows), 'items': sorted(rows, key=lambda r: (r['date'], r['start'], r['title']))}


def change_event(identifier, value, revision):
    validated = models.Event.model_validate(value).model_dump() if value is not None else None
    with store.edit(store.path('events.json')):
        rows = _events()
        store.require(rows, revision)
        if identifier is not None:
            rows.remove(store.find(rows, identifier))
        if validated is not None:
            rows.append({'id': identifier or uuid.uuid4().hex, **validated})
        store.save(store.path('events.json'), rows)
        return events()
