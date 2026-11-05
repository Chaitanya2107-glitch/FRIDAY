"""Weekly CRUD and dated corrections using the existing schedule authorities."""
from datetime import date, datetime

from services.college import models, store
from services.memory import schedule
from services.proactive import attendance, class_changes, class_sessions, timetable


def _state():
    raw = store.read(timetable.path, [])
    try:
        for row in raw:
            if not isinstance(row, dict):
                raise ValueError('Invalid weekly row')
            _template(row)
        weekly = timetable.load()
    except (ValueError, TypeError, KeyError) as error:
        raise store.Unavailable('Saved weekly timetable is unreadable. Repair it before editing.') from error
    return {'weekly': weekly, 'sessions': class_sessions.load(),
            'facts': [f.context() for f in schedule.facts()], 'holidays': attendance.load()['holidays']}


def _template(row):
    # Legacy optional/extra fields survive verbatim; validate the known fields only.
    return models.Slot.model_validate({key: value for key, value in row.items() if key in models.Slot.model_fields})


def snapshot(day=None):
    state = _state()
    target = date.fromisoformat(day) if day else datetime.now().date()
    rows = [{'id': f'slot-{i}', **row} for i, row in enumerate(state['weekly'])]
    return {'revision': store.revision(state), 'items': rows, 'date': target.isoformat(),
            'effective': timetable.classes_for_date(target), 'cancellations': state['facts'],
            'holidays': state['holidays']}


def selected(rows, identifier):
    found = next((i for i in range(len(rows)) if f'slot-{i}' == identifier), None)
    if found is None:
        raise store.Conflict('The weekly slot changed. Reload before editing it.')
    return found


def validate_rows(rows):
    """Validate candidate copies without normalizing any saved template."""
    checked = [_template(row) for row in rows]
    for i, row in enumerate(checked):
        if any(row.day == other.day and row.start < other.end and other.start < row.end for other in checked[:i]):
            raise ValueError(f'Overlapping classes on {row.day.title()} at {row.start}. Fix the preview first.')


def change(identifier, value, revision):
    new = models.Slot.model_validate(value).model_dump() if value is not None else None
    with timetable.edit(), class_sessions.edit():
        state = _state()
        store.require(state, revision)
        rows = state['weekly']
        original = rows.pop(selected(rows, identifier)) if identifier is not None else None
        if new is not None:
            if original is not None:
                new = {**original, **{key: new[key] for key in value}}
            rows.append(new)
            validate_rows(rows)
        timetable._save(rows)
        return snapshot()


def move_date(body, now=None):
    now = now or datetime.now()
    target = date.fromisoformat(body.date)
    with timetable.edit(), class_sessions.edit():
        state = _state()
        store.require(state, body.revision)
        template = state['weekly'][selected(state['weekly'], body.id)]
        if template['day'] != timetable.DAYS[target.weekday()]:
            raise ValueError('Choose a date on the selected weekly slot\'s weekday.')
        row = class_sessions.row_for(state['sessions'], target, template)
        if row is None:
            row = class_sessions.create(target, template)
            state['sessions'].append(row)
        # Speech parsing treats early bare hours as afternoon: supply explicit AM/PM.
        start = datetime.strptime(body.start, '%H:%M').strftime('%I:%M %p')
        message = class_changes.move(row, {'start': start, 'quote': 'College Schedules: ' + body.date + ' ' + body.start}, now, 'local')
        row['origin'] = 'college_ui'
        if row['history']:
            row['history'][-1]['origin'] = 'college_ui'
        class_sessions.save(state['sessions'])
        return {**snapshot(body.date), 'message': message}


def import_candidate(existing, rows, mode):
    checked = [models.Slot.model_validate(row).model_dump() for row in rows]
    # Merge by the displayed weekday/start identity; every other template survives.
    keys = [(r['day'], r['start']) for r in checked]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate weekday/start rows. Keep one row per slot.')
    candidate = list(existing) if mode == 'merge' else []
    for new in checked:
        new = next((original for original in existing if _template(original).model_dump() == new), new)
        index = next((i for i, row in enumerate(candidate) if (row['day'], row['start']) == (new['day'], new['start'])), None)
        if index is None:
            candidate.append(new)
        elif _template(candidate[index]).model_dump() != _template(new).model_dump():
            candidate[index] = new
        # Equal normalized values keep the original dictionary and full equality.
    validate_rows(candidate)
    return candidate


def diff(existing, candidate):
    kept = [r for r in existing if r in candidate]
    return {'added': [r for r in candidate if r not in existing],
            'removed': [r for r in existing if r not in candidate], 'unchanged': len(kept)}
