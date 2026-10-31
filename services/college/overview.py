"""Projection of existing effective classes and commitments for native clients."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from services.college import catalogs, reading, work
from services.memory import schedule
from services.proactive import college, timetable


def safe_link(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        return url if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def enrich(row, day, subjects):
    if row is None:
        return None
    subject = catalogs.subject_for(row['subject'], subjects)
    return {**row, 'date': day, 'faculty': subject['faculty'], 'room': subject['room'] or row.get('room'),
            'join_link': safe_link(college.link_for(row['subject']))}


def overview(now=None):
    now = now or datetime.now()
    subjects = catalogs._subject_rows()
    today = timetable.classes_for_date(now.date())
    current = next((r for r in today if r['start'] <= now.strftime('%H:%M') < r['end']), None)
    following = timetable.next_class_occurrence(now) if timetable.load() else None
    rows = work.snapshot()['items']
    active = [r for r in rows if not r['done']]
    return {'now': now.isoformat(timespec='seconds'),
            'current_class': enrich(current, now.date().isoformat(), subjects),
            'next_class': enrich(following, following['date'], subjects) if following else None,
            'today': [enrich(r, now.date().isoformat(), subjects) for r in today],
            'cancellations': [f.context() for f in schedule.facts() if not f.available],
            'due_soon': [r for r in active if datetime.fromisoformat(r['due']) <= now + timedelta(days=7)],
            'exams': [r for r in active if work.is_exam(r) and datetime.fromisoformat(r['due']) >= now][:20],
            'events': reading.upcoming_events(now)}
