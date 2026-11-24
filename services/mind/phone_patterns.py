"""Local hypotheses only. Owner answers live in the existing thoughts/reasons store."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
import threading

from services.activity import timeline
from services.mind import knowledge, thoughts

lock = threading.RLock()


def commute_estimate(events, now, *, device=None):
    """The existing P3 home-to-college table, extended with a decayed duration estimate."""
    candidates = []
    for handset in ({device} if device else {e['device'] for e in events}):
        places = sorted((e for e in events if e['device'] == handset and e['type'] == 'places'), key=lambda e: e['timestamp'])
        trips = []
        for start, end in zip(places, places[1:]):
            duration = end['timestamp'] - start['timestamp']
            if (start['payload'] == dict(place='home', transition='left')
                    and end['payload'] == dict(place='college', transition='entered') and 120 <= duration <= 4 * 3600):
                trips.append((duration, .5 ** ((now.timestamp() - end['timestamp']) / (14 * 86400)),
                              datetime.fromtimestamp(end['timestamp']).date()))
        if len({r[2] for r in trips}) < 3:
            continue
        weighted, total = sorted(trips), sum(r[1] for r in trips)
        accumulated = 0
        for duration, weight, _ in weighted:
            accumulated += weight
            if accumulated >= total / 2:
                with knowledge.db() as db:
                    row = db.execute('SELECT reason FROM reasons WHERE pattern=?', (f'phone:{handset}:place_routine',)).fetchone()
                answer = str(row[0]).strip().lower() if row else ''
                confirmed = answer.startswith(('yes', 'correct', "that's right", 'that is right', 'true'))
                candidates.append(dict(seconds=duration, samples=len(trips), device=handset, confirmed=confirmed,
                                       uncertainty='Geofence timing is an estimate, not a verified route.'))
                break
    return max(candidates, key=lambda r: r['samples']) if candidates else None


def private_thought(thought):
    return bool(thought and (thought.kind == 'phone_pattern' or thought.subject.startswith('app:phone:')))


def observe_android(package, label, category, seconds, now, device):
    name = f'phone:{device}:{package}'
    with knowledge.db() as db:
        knowledge.see(db, 'app', name, category, now)
        knowledge.spend(db, 'app', name, seconds)
    if category == 'other':
        thoughts.add('unknown', knowledge.key_for('app', name), dict(name=package, phone_private=True, device=device), .6, now)


def sleep_estimate(events, now):
    """P3's completed overnight estimate for a single phone."""
    unlocks = [e['timestamp'] for e in events if e['type'] == 'screen' and e['payload']['state'] == 'unlocked'
               and datetime.fromtimestamp(e['timestamp'], now.tzinfo).date() == now.date()]
    if not unlocks:
        return None
    wake = min(unlocks)
    offs = [e['timestamp'] for e in events if e['type'] == 'screen' and e['payload']['state'] == 'off'
            and datetime.fromtimestamp(e['timestamp'], now.tzinfo).hour >= 20 and e['timestamp'] < wake]
    if not offs:
        return None
    off = max(offs)
    if not 2*3600 <= wake-off <= 14*3600 or not any(
            e['type'] == 'battery' and e['payload']['charging'] and off-300 <= e['timestamp'] <= wake for e in events):
        return None
    health = [e['payload']['minutes'] for e in events if e['type'] == 'sleep' and e['payload']['date'] == now.date().isoformat()]
    estimate = wake-off
    surprise = min(1., abs(estimate/60-health[-1])/240) if health else 0.
    return dict(seconds=estimate, first_unlock=wake, last_screen_off=off, health_minutes=health[-1] if health else None,
                surprise=surprise, uncertainty='Charging while the screen is off gives an approximate sleep window.')


def findings(rows, events, now, context=None):
    result = []
    for device in {r['device'] for r in events}:
        phone = [r for r in rows if r['device'] == 'phone' and r.get('device_id') == device]
        from services.automation import personality
        def in_window(row):
            if context is not None:
                return context in {'study', 'deadline'}
            when = datetime.fromtimestamp((row['start']+row['end'])/2)
            return bool(personality._class_now(when) or personality._deadline_soon(when) or
                        (personality._study_mode() and row['end'] >= now.timestamp()-300))
        distraction = sum(r['end']-r['start'] for r in phone if r['category'] in {'gaming', 'social', 'entertainment'} and datetime.fromtimestamp(r['end']).date() == now.date() and in_window(r))
        if distraction >= 600:
            result.append((device, 'distraction', dict(category='leisure', seconds=distraction, context=context, uncertainty='May be a break or relevant work, not distraction.'), min(.95, .4+distraction/7200)))
        subset = [e for e in events if e['device'] == device]
        if estimate := sleep_estimate(subset, now):
            result.append((device, 'sleep', estimate, .3+.6*estimate['surprise']))
        places = [e for e in subset if e['type'] == 'places']
        counts = defaultdict(float)
        for a, b in zip(places, places[1:]):
            if a['payload']['place'] == 'home' and a['payload']['transition'] == 'left' and b['payload']['place'] == 'college' and b['payload']['transition'] == 'entered' and 0 < b['timestamp']-a['timestamp'] < 4*3600:
                hour = datetime.fromtimestamp(a['timestamp']).hour
                counts[hour] += .5**((now.timestamp()-b['timestamp'])/(14*86400))
        if counts and sum(counts.values()) >= 2:
            hour = max(counts, key=counts.get)
            surprise = 1-counts[hour]/sum(counts.values())
            result.append((device, 'place_routine', dict(hour=hour, decayed_count=round(counts[hour], 2), half_life_days=14, surprise=surprise, uncertainty='Geofences can be delayed; a route does not establish purpose.'), .3+.6*surprise))
    return result


def predictions(rows, events, now):
    """Extend the existing count predictor/features, keeping laptop-only artifacts untouched."""
    from services.activity.predict import Predictor
    from services.mind.learner import features
    predictor = Predictor(); contexts = defaultdict(Counter)
    sequence = sorted(rows, key=lambda r: r['start'])
    def key(r):
        return r['device'] + ':' + r['app']
    previous = None
    for a, b in zip(sequence, sequence[1:]):
        when = datetime.fromtimestamp(b['start'])
        if b['start']-a['end'] > 4*3600 or key(a) == key(b):
            previous = key(a); continue
        place = next((e['payload']['place'] for e in reversed(events) if e['type'] == 'places' and e['timestamp'] <= a['start'] and e['payload']['transition'] == 'entered'), '-')
        base = features(key(a), previous, when)
        context = (when.hour, when.weekday(), place, base[f'from={key(a)}'], key(a), previous, a['device'])
        contexts[context][key(b)] += 1
        predictor.learn(key(a), key(b), when, previous)
        previous = key(a)
    if not sequence:
        return []
    last = sequence[-1]; place = next((e['payload']['place'] for e in reversed(events) if e['type'] == 'places' and e['payload']['transition'] == 'entered'), '-')
    candidates = Counter()
    for context, counts in contexts.items():
        if context[4] == key(last) and context[6] == last['device']:
            weight = 1 + (context[0] == now.hour) + (context[1] == now.weekday()) + (context[2] == place) + (context[5] == previous)
            candidates.update({k: v*weight for k, v in counts.items()})
    return [dict(app=k, count=v, confirmed=False) for k, v in candidates.most_common(3)] or [dict(app=k, count=0, confirmed=False) for k in predictor.top(key(last), now, previous)]


def analyze(now=None, *, path=None, device=None):
    now = now or datetime.now()
    with lock:
        start = now-timedelta(days=30)
        events = timeline.phone_events(start.timestamp(), now.timestamp(), device, path)
        if not events:
            return []
        rows = timeline.segments(start, now, device=device, path=path)
        from services.mind import humour
        context = humour.situation(now)
        observed = findings(rows, events, now)
        predicted = predictions(rows, events, now)
        if predicted and len(events) >= 3:
            total = sum(p['count'] for p in predicted)
            surprise = 1-predicted[0]['count']/total if total else 0.
            observed.append((events[-1]['device'], 'next_app', dict(candidates=predicted, surprise=surprise, uncertainty='Counting prediction only; not an owner-confirmed habit.'), .3+.6*surprise))
        # Source-id ledger makes replays idempotent, without a second knowledge system.
        with knowledge.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS phone_observed (device TEXT,id TEXT,subject TEXT,PRIMARY KEY(device,id))')
        for event in events:
            if event['type'] != 'app_usage':
                continue
            p = event['payload']; name = f"app:phone:{event['device']}:{p['package']}"
            with knowledge.db() as db:
                seen = db.execute('SELECT 1 FROM phone_observed WHERE device=? AND id=?', (event['device'], event['id'])).fetchone()
            if not seen:
                from services.activity.categories import android_category
                observe_android(p['package'], p['label'], android_category(p['package'], p['category'], event['device']), p['end']-p['start'], datetime.fromtimestamp(p['end']), event['device'])
                with knowledge.db() as db:
                    db.execute('INSERT OR IGNORE INTO phone_observed VALUES(?,?,?)', (event['device'], event['id'], name))
        for handset, kind, data, strength in observed:
            pattern = f'phone:{handset}:{kind}'
            thoughts.add('phone_pattern', pattern, dict(data, pattern=pattern, finding=kind, device=handset, confirmed=False), strength, now)
        return observed


def forget(device, *, path=None):
    with lock, knowledge.db() as db:
        prefix = f'phone:{device}:'
        for table, column in (('thoughts', 'subject'), ('reasons', 'pattern'), ('things', 'key'), ('thing_revisions', 'key'), ('app_explanations', 'key')):
            db.execute(f'DELETE FROM {table} WHERE substr({column},1,?)=? OR substr({column},1,?)=?', (len(prefix), prefix, len('app:'+prefix), 'app:'+prefix))
        db.execute('CREATE TABLE IF NOT EXISTS phone_observed (device TEXT,id TEXT,subject TEXT,PRIMARY KEY(device,id))')
        db.execute('DELETE FROM phone_observed WHERE device=?', (device,))
    from services.mind import talk
    knowledge.refresh_learned()
    state = talk.load(); pending = state.get('pending') or {}
    if pending.get('phone_device') == device:
        state.pop('pending', None); talk._save(state)
    # Predictions are rebuilt on demand from the remaining source intervals; no stale model exists.
