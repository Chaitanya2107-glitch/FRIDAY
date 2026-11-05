"""Shared spoken schedule details; display metadata never changes templates."""
from datetime import datetime, timedelta

def room_for(row):
    from services.college import catalogs, store
    from services.automation.intent import remote_request
    if remote_request.get():
        return row.get('room')
    try:
        return catalogs.subject_for(row['subject'])['room'] or row.get('room')
    except (store.Unavailable, OSError):
        # Optional metadata cannot turn a successful class write into an error.
        return row.get('room')


def warning_room(row):
    """Existing warnings can be mirrored; omit superseded rooms without private metadata."""
    return row.get('room') if room_for(row) == row.get('room') else None


def upcoming_events(now=None, *, days=None):
    from services.college import catalogs
    now = now or datetime.now()
    rows = catalogs.events()['items']
    return [row for row in rows if datetime.fromisoformat(row['date'] + 'T' + (row['end'] or row['start'])) >= now
            and (days is None or datetime.fromisoformat(row['date'] + 'T' + row['start']) <= now + timedelta(days=days))][:20]


def events_message(now=None, *, briefing=False):
    from services.proactive import deadlines
    now = now or datetime.now()
    rows = upcoming_events(now, days=7 if briefing else None)
    if not rows:
        return ''
    if briefing:
        rows = rows[:3]
    return 'College events: ' + '; '.join(row['title'] + ' ' +
        deadlines.when(datetime.fromisoformat(row['date'] + 'T' + row['start']), now) +
        (' at ' + row['location'] if row['location'] else '') for row in rows) + '.'
