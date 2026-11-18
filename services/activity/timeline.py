"""Read-only cross-device projections. Never copy phone observations to laptop sessions."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
DEFAULT_PATH = config.MEMORY_DIR / 'phone' / 'phone_events.db'


def phone_events(start, end, device=None, path=None):
    path = Path(path or DEFAULT_PATH).absolute()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        # App intervals can begin before the query window. The retained store is bounded by P2.
        rows = db.execute('SELECT device,id,timestamp,type,payload FROM phone_events WHERE timestamp<=? '
                          + ('AND device=? ' if device else '') + 'ORDER BY timestamp,id',
                          (end, device) if device else (end,)).fetchall()
    return [dict(device=d, id=i, timestamp=t, type=k, payload=json.loads(p)) for d, i, t, k, p in rows
            if t >= start or (k == 'app_usage' and json.loads(p)['end'] >= start)]


def normalize(rows):
    """Latest-starting observation wins overlaps within a physical device; overlaps across devices remain."""
    groups = {}
    for row in rows:
        if row['end'] > row['start']:
            groups.setdefault((row['device'], row.get('device_id', '')), []).append(dict(row))
    result = []
    for group in groups.values():
        clean = []
        for row in sorted(group, key=lambda r: (r['start'], r['end'])):
            while clean and clean[-1]['end'] > row['start']:
                clean[-1]['end'] = row['start']
                if clean[-1]['end'] <= clean[-1]['start']:
                    clean.pop()
                else:
                    break
            if clean and all(clean[-1].get(k) == row.get(k) for k in ('app', 'category')) and clean[-1]['end'] == row['start']:
                clean[-1]['end'] = row['end']
            else:
                clean.append(row)
        result.extend(clean)
    return sorted(result, key=lambda r: (r['start'], r['device'], r.get('device_id', '')))


def segments(start, end, *, device=None, log=None, path=None):
    from services import activity_plugin
    from services.activity.categories import android_category
    low, high = start.timestamp(), end.timestamp()
    rows = []
    if log is not None or not activity_plugin.privacy_active():
        if log is None:
            from services.activity.log import activity_log
            log = activity_log
        for at, app, _title, seconds, category, _project in log.moves(start - timedelta(days=1), end):
            when = datetime.fromisoformat(at).timestamp()
            rows.append(dict(device='laptop', app=app, category=category or 'other', start=max(low, when), end=min(high, when + seconds)))
    else:
        activity = activity_plugin.current()
        if activity:
            from services.plugin_runtime import current_manager
            records = current_manager().invoke(activity.api, lambda: activity.store.rows(low, high))
            for r in records:
                if r['category'] != 'private' and (r.get('app_name') or r.get('process')):
                    rows.append(dict(device='laptop', app=r.get('app_name') or r['process'], category='gaming' if r['category'] == 'games' else r['category'], start=r['start'], end=r['end']))
    for r in phone_events(low, high, device, path):
        if r['type'] == 'app_usage':
            p = r['payload']
            rows.append(dict(device='phone', device_id=r['device'], app=p['package'], label=p['label'],
                             category=android_category(p['package'], p['category'], r['device']),
                             start=max(low, p['start']), end=min(high, p['end'])))
    return normalize(rows)


def totals(rows):
    result = {'laptop': 0., 'phone': 0.}
    # Union phone intervals across multiple handsets for a fair device-lane comparison.
    for device in result:
        intervals = sorted((r['start'], r['end']) for r in rows if r['device'] == device)
        end = float('-inf')
        for a, b in intervals:
            result[device] += max(0, b - max(a, end)); end = max(end, b)
    return result


def phone_line(now, day=None):
    day = day or now.date()
    start = datetime.combine(day, datetime.min.time()); end = min(now, start + timedelta(days=1))
    events = phone_events(start.timestamp(), end.timestamp())
    if not events:
        return None
    rows = [r for r in segments(start, end) if r['device'] == 'phone']
    categories = {}
    for r in rows:
        categories[r['category']] = categories.get(r['category'], 0) + r['end'] - r['start']
    unlocks = [r['timestamp'] for r in events if r['type'] == 'screen' and r['payload']['state'] == 'unlocked']
    top = max(categories, key=categories.get) if categories else 'unavailable'
    return (f"Phone recorded app time: {round(totals(rows)['phone']/60)} min; top category: {top}; "
            f"first recorded unlock: {datetime.fromtimestamp(min(unlocks)):%H:%M}." if unlocks else
            f"Phone recorded app time: {round(totals(rows)['phone']/60)} min; top category: {top}; first unlock unavailable.")
