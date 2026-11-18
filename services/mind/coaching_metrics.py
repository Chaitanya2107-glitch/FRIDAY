"""Read-only local measurements. Missing observations are never invented as zero."""
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from statistics import median


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def seconds(intervals):
    return sum(b - a for a, b in union(intervals))


def intersect(left, right):
    return union((max(a, c), min(b, d)) for a, b in union(left) for c, d in union(right) if max(a, c) < min(b, d))


def focus_rows(start, end):
    from services.plugin_runtime import current_manager
    manager = current_manager()
    timer = manager.get_service('focus') if manager else None
    if not timer:
        return []
    def read():
        with timer.lock:
            rows = list(timer.data['history'])
            active = timer.data['active']
            if active and active['phase'] == 'focus':
                rows += [dict(session_id=active['session_id'], label=active['label'], segments=timer._segments(active, end.timestamp()))]
            return [dict(id=row['session_id'], label=row['label'], start=max(a, start.timestamp()), end=min(b, end.timestamp()))
                    for row in rows for a, b in row['segments'] if max(a, start.timestamp()) < min(b, end.timestamp())]
    return manager.invoke(timer.api, read)


def snapshot(start, end):
    from services.activity import timeline
    rows = timeline.segments(start, end)
    events = timeline.phone_events((start - timedelta(days=30)).timestamp(), end.timestamp())
    contexts = []
    path = Path(timeline.DEFAULT_PATH).with_name('triage.db')
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                contexts = [dict(situation=s, start=max(a, start.timestamp()), end=min(b or end.timestamp(), end.timestamp()))
                            for s, a, b in db.execute('SELECT situation,start,end FROM triage_context WHERE start<? AND (end IS NULL OR end>?)',
                                                     (end.timestamp(), start.timestamp()))]
        except sqlite3.Error:
            pass
    return dict(segments=rows, focus=focus_rows(start, end), events=events, contexts=contexts)


def measure(source, start, end, snapshot=None):
    data = snapshot if snapshot is not None else globals()['snapshot'](start, end)
    kind = source.get('kind')
    if kind == 'focus':
        rows = data['focus']
        if source.get('label'):
            rows = [r for r in rows if r['label'].casefold() == source['label'].casefold()]
        intervals = [(r['start'], r['end']) for r in rows]
        if source.get('category'):
            intervals = intersect(intervals, [(r['start'], r['end']) for r in data['segments'] if r['category'] == source['category']])
        return seconds(intervals) / 60 if data['focus'] else None
    events = [e for e in data['events'] if not source.get('device') or e['device'] == source['device']]
    if kind == 'steps':
        latest = {}
        for row in events:
            if row['type'] == 'steps' and start.date().isoformat() <= row['payload']['date'] <= (end - timedelta(microseconds=1)).date().isoformat():
                latest[row['device'], row['payload']['date']] = row
        # One highest daily aggregate, never a sum of repeated snapshots/handsets.
        days = {}
        for row in latest.values():
            day, count = row['payload']['date'], row['payload']['count']
            days[day] = max(days.get(day, 0), count)
        return float(sum(days.values())) if days else None
    if kind == 'visits':
        selected = [e for e in events if e['type'] == 'places' and e['payload']['place'].casefold() == source.get('place', '').casefold()]
        inside, count = {}, 0
        for row in sorted(selected, key=lambda r: (r['timestamp'], r['id'])):
            entered = row['payload']['transition'] == 'entered'
            if entered and not inside.get(row['device'], False) and start.timestamp() <= row['timestamp'] < end.timestamp():
                count += 1
            inside[row['device']] = entered
        return float(count) if selected else None
    return None


def sleep_days(data, start, end):
    """Keep Health aggregates distinct from screen/charging estimates."""
    from services.mind.phone_patterns import findings
    result = []
    day = start.date()
    while day < end.date() or day == end.date() and end.time() != datetime.min.time():
        latest = {}
        for row in sorted(data['events'], key=lambda e: (e['timestamp'], e['id'])):
            if row['type'] == 'sleep' and row['payload']['date'] == day.isoformat():
                latest[row['device']] = row
        if latest:
            chosen = max(latest.values(), key=lambda e: e['timestamp'])
            result.append(dict(day=day.isoformat(), minutes=chosen['payload']['minutes'], source='Health Connect', device=chosen['device']))
        else:
            when = datetime.combine(day, datetime.max.time())
            found = [r for r in findings([], data['events'], when) if r[1] == 'sleep']
            if found:
                device, _, values, _ = found[-1]
                result.append(dict(day=day.isoformat(), minutes=values['seconds'] / 60, source='screen/charging estimate',
                                   device=device, bedtime=values['last_screen_off'], first_unlock=values['first_unlock']))
        day += timedelta(days=1)
    return result


def baseline(kind, now=None, data=None):
    now = now or datetime.now()
    start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    data = data if data is not None else snapshot(start, now)
    screen = union((r['start'], r['end']) for r in data['segments'])
    active_days = sorted({datetime.fromtimestamp(a).date().isoformat() for a, _ in screen})
    result = dict(days=len(active_days), source='your recorded screen intervals', suggested=None)
    if screen:
        minutes = [min(180, (b - a) / 60) for a, b in screen if b - a >= 300]
        if minutes:
            result['suggested'] = max(5, min(180, round(median(minutes) / 5) * 5))
            result['median_minutes'] = round(median(minutes), 1)
        hours = [datetime.fromtimestamp(a).hour for a, _ in screen]
        ends = [datetime.fromtimestamp(b).hour + 1 for _, b in screen]
        result['window'] = [f'{min(hours):02}:00', f'{min(23, max(ends)):02}:59']
    if kind in {'sleep', 'wind_down'}:
        nights = sleep_days(data, start, now)
        bedtimes = [r['bedtime'] for r in nights if 'bedtime' in r]
        if bedtimes:
            # Times after midnight belong to the preceding evening for the median.
            clocks = [datetime.fromtimestamp(t).hour * 60 + datetime.fromtimestamp(t).minute for t in bedtimes]
            minute = int(median([m + 1440 if m < 720 else m for m in clocks])) % 1440
            result = dict(days=len(bedtimes), source='your uncertain screen-off/charging sleep estimate',
                          suggested=f'{minute // 60:02}:{minute % 60:02}', window=[f'{(minute - 60) % 1440 // 60:02}:{(minute - 60) % 60:02}',
                          f'{(minute + 30) % 1440 // 60:02}:{(minute + 30) % 60:02}'])
            wake_minutes = [datetime.fromtimestamp(r['first_unlock']).hour * 60 + datetime.fromtimestamp(r['first_unlock']).minute for r in nights if 'first_unlock' in r]
            wake = int(median(wake_minutes))
            result['wake'] = f'{wake // 60:02}:{wake % 60:02}'
        else:
            result = dict(days=0, source='no observed bedtime baseline', suggested=None)
    return result
