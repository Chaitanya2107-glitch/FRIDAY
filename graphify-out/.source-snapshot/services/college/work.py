"""Window edits act on the same deadlines, correction history and reminder proposals."""
from datetime import datetime
import uuid

from services.college import models, store
from services.proactive import college, deadline_changes, deadlines


def is_exam(row):
    return row.get('kind') == 'exam' or bool(college.EXAM_WORDS.search(row['what']))


def project(row):
    due = datetime.fromisoformat(row['due'])
    result = {**row, 'id': store.item_id(row), 'done': row.get('done', False),
              'kind': row.get('kind', 'exam' if is_exam(row) else 'other'),
              'subject': row.get('subject', ''), 'notes': row.get('notes', ''), 'venue': row.get('venue', ''),
              'date': due.date().isoformat(), 'time': due.strftime('%H:%M')}
    if not result['subject']:
        from services.proactive import timetable
        result['subject'] = next((s for s in timetable.subjects() if timetable.mentions_subject(row['what'], timetable.aliases(s))), '')
    result['pending_updates'] = sum(len(p['items']) for p in row.get('reminder_updates', []) if p['status'] == 'pending')
    return result


def snapshot(section='deadlines'):
    rows = deadlines.load(include_done=True)
    return {'revision': store.revision(rows), 'items': [project(r) for r in rows if section != 'exams' or is_exam(r)]}


def _validated(value, section):
    if section == 'exams':
        exam = models.Exam.model_validate(value)
        return models.Deadline(what=exam.subject + ' exam', due=exam.date + 'T' + exam.time,
                               kind='exam', subject=exam.subject, done=exam.done, notes=exam.notes, venue=exam.venue)
    result = models.Deadline.model_validate(value)
    # Preserve existing briefing's word-based exam recognition.
    if result.kind == 'exam' and not college.EXAM_WORDS.search(result.what):
        result.what += ' exam'
    return result


def change(identifier, value, revision, section='deadlines', now=None):
    now = now or datetime.now()
    validated = _validated(value, section) if value is not None else None
    message = 'Changes saved.'
    with deadlines.edit():
        rows = deadlines.load(include_done=True)
        store.require(rows, revision)
        row = store.find(rows, identifier) if identifier is not None else None
        if row is not None and section == 'exams' and not is_exam(row):
            raise ValueError('That record is not an exam.')
        if value is None:
            if row is None:
                raise ValueError('Choose a saved deadline first.')
            rows.remove(row)
        else:
            due = datetime.fromisoformat(validated.due)
            if row is None:
                if due <= now:
                    raise ValueError('Give a future deadline date and time.')
                row = {'id': uuid.uuid4().hex, 'revision': uuid.uuid4().hex,
                       'what': validated.what, 'due': validated.due,
                       'alerted': [stage for stage, before in deadlines.STAGES if due - before <= now]}
                rows.append(row)
            elif row.get('done') and not validated.done and due <= now:
                raise ValueError('Give a future date before reopening completed work.')
            elif datetime.fromisoformat(row['due']) != due:
                message = deadline_changes.move(row, {'when': validated.due[:10] + ' at ' + due.strftime('%I:%M %p'),
                    'quote': f'College Schedules: {row["what"]} due {validated.due}'}, now, 'local')
                if row.get('history'):
                    row['history'][-1]['origin'] = 'college_ui'
            was_done = row.get('done', False)
            row.update(validated.model_dump())
            # The row revision belongs to deadline/reminder correction snapshots.
            # move() has already bound its proposal to this revision. Metadata is
            # protected by the complete catalog hash, including metadata itself.
            row['origin'] = 'college_ui'
            if validated.done and not was_done:
                deadline_changes.complete(row)
        deadlines._save(rows, include_done=True)
        result = snapshot(section)
        if row is not None and value is not None:
            current = project(row)
            if current['pending_updates']:
                message = (f'{current["pending_updates"]} reminder updates pending — '
                           f'tell FRIDAY "review reminder updates for {row["what"]}".')
        return {**result, 'message': message}
