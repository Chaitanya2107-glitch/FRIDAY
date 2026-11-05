"""Plain formatting/filtering functions: testable without Tcl or a backend."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit
import textwrap

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
KINDS = ('assignment', 'homework', 'exam', 'project', 'other')
FIELDS = {
    'timetable': [('day', 'Day', DAYS), ('start', 'Start (24h HH:MM)', None),
                  ('end', 'End (24h HH:MM)', None), ('subject', 'Subject', None)],
    'subjects': [('subject', 'Subject', None), ('faculty', 'Faculty name', None), ('room', 'Room', None),
                 ('email', 'Faculty email (optional)', None), ('notes', 'Notes', 'text')],
    'deadlines': [('what', 'Assignment / homework title', None), ('subject', 'Subject (optional)', None),
                  ('kind', 'Kind', KINDS), ('date', 'Due date (YYYY-MM-DD)', None), ('time', 'Due time (24h HH:MM)', None),
                  ('done', 'Completed', 'bool'), ('notes', 'Notes', 'text')],
    'exams': [('subject', 'Subject', None), ('date', 'Exam date (YYYY-MM-DD)', None),
              ('time', 'Start (24h HH:MM)', None), ('venue', 'Venue', None), ('done', 'Completed', 'bool'), ('notes', 'Notes', 'text')],
    'events': [('title', 'Event title', None), ('date', 'Date (YYYY-MM-DD)', None), ('start', 'Start (24h HH:MM)', None),
               ('end', 'End (optional, HH:MM)', None), ('location', 'Location', None), ('notes', 'Notes', 'text')],
}


def countdown(due, now=None, done=False):
    if done:
        return 'Done'
    now = now or datetime.now()
    try:
        target = datetime.fromisoformat(due)
        seconds = (target - now).total_seconds()
    except (ValueError, TypeError):
        return 'Date unavailable'
    if seconds < 0:
        return 'Overdue'
    if seconds < 60:
        return 'Now'
    if seconds < 3600:
        return f'In {max(1, int(seconds / 60))} min'
    if seconds < 86400:
        return f'In {int(seconds / 3600)}h {int(seconds % 3600 / 60)}m'
    days = int(seconds / 86400)
    return f'In {days} day' + ('s' if days != 1 else '')


def short(value, width=28):
    return textwrap.shorten(value, width=width, placeholder='…')


def date_time(value):
    try:
        return datetime.fromisoformat(value).strftime('%a %d %b · %H:%M')
    except (TypeError, ValueError):
        return str(value or '')


def filtered(rows, subject='', status='All', kind='All', now=None):
    def matches(row):
        return (not subject or subject.casefold() in (row.get('subject', '') + ' ' + row.get('what', '')).casefold()) and \
            (status == 'All' or bool(row.get('done')) == (status == 'Done')) and (kind == 'All' or row.get('kind') == kind)
    return sorted((row for row in rows if matches(row)), key=lambda r: (bool(r.get('done')), r.get('due', r.get('date', ''))))


def defaults(section, row=None, now=None):
    now = now or datetime.now()
    result = {'day': DAYS[now.weekday()], 'start': '09:00', 'end': '10:00', 'time': '23:59',
              'date': (now + timedelta(days=1)).date().isoformat(), 'kind': 'assignment', 'done': False}
    if section == 'events':
        result['end'] = ''
    if section == 'exams':
        result['time'] = '09:00'
    result.update(row or {})
    if row and row.get('due'):
        result['date'], _, result['time'] = row['due'].partition('T')
        result['time'] = result['time'][:5]
    return {key: result.get(key, '') for key, _, _ in FIELDS[section]}


def payload(section, values, row=None):
    result = dict(values)
    if section == 'deadlines':
        result['due'] = result.pop('date') + 'T' + result.pop('time')
        result['venue'] = (row or {}).get('venue', '')
    if section == 'timetable' and row and 'room' in row:
        result['room'] = row['room']
    return result


def safe_join(url):
    try:
        parsed = urlsplit(url or '')
        return bool(parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password)
    except ValueError:
        return False


def class_card(data):
    row = data.get('current_class') or data.get('next_class')
    if not row:
        return {'title': 'Your next class will appear here', 'details': 'Add your weekly timetable to get started.', 'link': None}
    label = 'NOW' if data.get('current_class') else 'UP NEXT'
    details = (f'{row.get("date", "")} · {row["start"]}–{row["end"]}\n'
               f'Faculty: {row.get("faculty") or "Not saved"}    Room: {row.get("room") or "Not saved"}')
    return {'title': label + '  /  ' + row['subject'], 'details': details, 'link': row.get('join_link')}


def grid_rows(items):
    times = sorted({(r['start'], r['end']) for r in items})
    result, cells = [], {}
    for i, (start, end) in enumerate(times):
        values = [start + '–' + end]
        for day in DAYS:
            rows = [r for r in items if r['day'] == day and (r['start'], r['end']) == (start, end)]
            values.append(short(' / '.join(r['subject'] for r in rows), 16))
            if rows:
                cells[(str(i), day)] = rows[0]['id']
        result.append((str(i), values))
    return result, cells


def review_text(diff):
    lines = [f'{len(diff.get("added", []))} added / changed, {len(diff.get("removed", []))} removed, '
             f'{diff.get("unchanged", 0)} unchanged']
    for label, key in (('+', 'added'), ('−', 'removed')):
        lines.extend(f'{label} {r["day"].title()} {r["start"]}–{r["end"]} {r["subject"]}' for r in diff.get(key, []))
    return '\n'.join(lines)
