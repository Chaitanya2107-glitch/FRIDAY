"""Pure care candidates. The dispatcher rechecks consent, windows, caps and quiet."""
from datetime import datetime, timedelta

from . import coaching_metrics as metrics
from .care import in_window


def candidates(settings, now, data, *, classes=(), context='free', followups=(), entries=()):
    result = []
    screen = metrics.union((r['start'], r['end']) for r in data['segments'])
    # Device changes do not reset exposure; a genuine five-minute gap does.
    continuous = []
    for a, b in screen:
        if continuous and a - continuous[-1][1] < 300:
            continuous[-1][1] = max(b, continuous[-1][1])
        else:
            continuous.append([a, b])
    for row in settings:
        d, kind = row['definition'], row['definition']['type']
        if not in_window(d, now):
            continue
        day = now.date().isoformat()
        key, text = None, None
        if kind in {'breaks', 'eye_rest'} and continuous and now.timestamp() - continuous[-1][1] <= 120:
            a, b = continuous[-1]
            logged = [e['at'] for e in entries if e['kind'] == kind and a <= e['at'] <= b]
            a = max([a] + logged)
            elapsed = metrics.seconds(metrics.intersect(screen, [(a, b)])) / 60
            if elapsed >= d['limit']:
                key = f'{kind}:{day}:{int(a)}'
                text = (f'About {elapsed:.0f} recorded screen minutes across laptop and phone since your last gap/logged rest; your chosen limit is {d["limit"]}. '
                        + ('Want to use your chosen eye-rest routine: look about 20 feet away for 20 seconds?' if kind == 'eye_rest' else 'Want a break?')
                        + ' Reason: overlapping device intervals are counted once; this measures screen records, not attention or health.')
        elif kind in {'water', 'stretch'}:
            logged = [e['at'] for e in entries if e['kind'] == kind]
            since = max([row['enabled_at']] + logged)
            periods = int((now.timestamp() - since) / (d['limit'] * 60))
            if periods >= 1:
                key = f'{kind}:{day}:{int(since)}:{periods}'
                text = f'Your chosen {kind.replace("_", " ")} interval of {d["limit"]} minutes has passed. Want a reminder now? Reason: your own interval and last manual log; no intake or health need is inferred.'
        elif kind in {'sleep', 'wind_down'}:
            bedtime = int(d['limit'][:2]) * 60 + int(d['limit'][3:])
            current = now.hour * 60 + now.minute
            late = (current - bedtime) % 1440 < 180
            if late:
                first = min(classes, key=lambda c: c.start) if classes else None
                next_class = f"Tomorrow's first class is {first.subject} at {first.start:%H:%M}." if first else 'No first class is recorded for tomorrow.'
                if kind == 'wind_down' or first is not None:
                    key = f'{kind}:{day}'
                    text = (f'It is past your chosen {d["limit"]} bedtime. {next_class} '
                            + ('Want to review a dim wind-down scene and an optional phone DND offer?' if kind == 'wind_down' else 'Want to wind down?')
                            + ' Reason: your confirmed bedtime and timetable; sleep estimates are uncertain.')
        elif kind == 'phone_use':
            intervals = [(r['start'], r['end']) for r in data['segments'] if r['device'] == 'phone' and (r['category'] in d['categories'] or r['app'] in d['apps'])]
            window_start = datetime.combine(now.date(), datetime.min.time()).replace(hour=int(d['window'][0][:2]), minute=int(d['window'][0][3:]))
            if window_start > now:
                window_start -= timedelta(days=1)
            intervals = metrics.intersect(intervals, [(window_start.timestamp(), now.timestamp())])
            if d['context'] != 'any':
                scope = [(r['start'], r['end']) for r in data.get('contexts', []) if r['situation'] == d['context']]
                if d['context'] == 'study':
                    scope += [(r['start'], r['end']) for r in data['focus']]
                intervals = metrics.intersect(intervals, scope)
            elapsed = metrics.seconds(intervals) / 60
            if elapsed >= d['limit'] and (d['context'] == 'any' or context == d['context']):
                names = ', '.join(d['categories'] + d['apps'])
                key = f'phone_use:{day}:{window_start.isoformat()}'
                text = f'About {elapsed:.0f} recorded minutes on your selected {names} in your {d["context"]} window; your own limit is {d["limit"]}. Want a 15-minute reminder, or leave it? Reason: opted-in app/category intervals inside your chosen window. App records do not identify particular video content.'
        elif kind == 'weekly_review' and now.weekday() == 6:
            key = f'weekly_review:{now.date().isocalendar()[:2]}'
            text = 'Your private weekly care review is ready. Want to see your own numbers and optionally choose one small experiment?'
        elif kind == 'wellbeing':
            if not any(e['kind'] == 'wellbeing' and datetime.fromtimestamp(e['at']).date() == now.date() for e in entries):
                key, text = f'wellbeing:{day}', 'Optional private check-in: choose 1 to 5 in the PWA, or tell me your number. You can leave it unanswered.'
        if key and text:
            result.append(dict(type=kind, key=key, text=text, voice=d['voice'], revision=row['revision']))
    for followup in followups:
        row = next((r for r in settings if r['definition']['type'] == followup['kind']), None)
        if (row and followup['due'] <= now.timestamp() < followup['expires'] and in_window(row['definition'], now)
                and (row['definition']['context'] == 'any' or context == row['definition']['context'])):
            result.append(dict(type=followup['kind'], key='followup:' + followup['id'], voice=False, revision=row['revision'],
                               text='The 15-minute follow-up you chose is here. Leave it, or decide what you want to do next. Reason: your explicit earlier choice.'))
    return result
