"""Conservative, per-handset attention estimates with a debounced coarse bus event."""
from datetime import datetime
import threading
from services.activity.timeline import phone_events

_lock = threading.RLock()
_stable, _candidate, _since = 'away', None, 0.
DEBOUNCE_SECONDS = 30
FRESH_SECONDS = 180


def resolve(events, now, laptop_idle, idle_minutes=3):
    stamp = now.timestamp(); active = []; sleeping = False
    for device in {r['device'] for r in events}:
        rows = sorted((r for r in events if r['device'] == device and r['timestamp'] <= stamp), key=lambda r: r['timestamp'])
        latest = {kind: next((r for r in reversed(rows) if r['type'] == kind), None) for kind in ('screen', 'motion', 'battery')}
        screen, motion, battery = (latest[k] for k in ('screen', 'motion', 'battery'))
        if not screen:
            continue
        state = screen['payload']['state']
        fresh = stamp - screen['timestamp'] <= FRESH_SECONDS
        unlocked = state == 'unlocked' or (state == 'on' and any(r['type'] == 'screen' and r['payload']['state'] == 'unlocked' and r['timestamp'] >= screen['timestamp'] for r in rows))
        if fresh and state != 'off':
            active.append((unlocked, bool(motion and stamp-motion['timestamp'] <= FRESH_SECONDS)))
        if state == 'off' and battery and stamp-battery['timestamp'] <= 8*3600 and battery['payload']['charging'] and (now.hour < 7 or now.hour >= 22):
            sleeping = True
    if active:
        confidence = .9 if any(a and b for a, b in active) else .65
        return dict(attention='phone' if laptop_idle >= idle_minutes*60 else 'both', confidence=confidence,
                    reason='Recent phone screen activity while laptop input is idle.' if laptop_idle >= idle_minutes*60 else 'Recent input on the laptop and a phone screen observation.',
                    sleep_estimate=False, data_available=True)
    return dict(attention='away' if laptop_idle >= idle_minutes*60 else 'laptop', confidence=.65 if sleeping else .4,
                reason='Night charging with screen off suggests sleep, not proof.' if sleeping else 'No fresh phone-use evidence; using laptop input idle time.',
                sleep_estimate=sleeping, data_available=bool(events))


def where_is_attention(now=None, *, events=None, laptop_idle=None, publish=True):
    global _stable, _candidate, _since
    now = now or datetime.now()
    if events is None:
        events = phone_events(now.timestamp()-8*3600, now.timestamp())
    if laptop_idle is None:
        from services.activity.log import idle_seconds
        laptop_idle = idle_seconds()
    result = resolve(events, now, laptop_idle)
    if publish and result['data_available']:
        with _lock:
            if _candidate != result['attention']:
                _candidate, _since = result['attention'], now.timestamp()
            if _stable != _candidate and now.timestamp()-_since >= DEBOUNCE_SECONDS:
                _stable = _candidate
                from services.event_bus import event_bus
                from services.remote.context import origin_scope
                with origin_scope(True):
                    event_bus.publish('attention.changed', {'attention': _stable, 'confidence': result['confidence']})
            result['attention'] = _stable
            if _stable != _candidate:
                result['confidence'] = min(result['confidence'], .4)
                result['reason'] = 'Waiting for a stable attention change; recent input is ambiguous.'
    return result
