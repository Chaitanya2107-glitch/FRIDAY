"""Rule-based presence estimates with hysteresis; estimates never grant action authority."""
from datetime import datetime
import threading

STATES = {'at_desk', 'on_phone', 'in_class', 'commuting', 'at_college_free', 'at_home',
          'away', 'winding_down', 'asleep'}


def infer(observed, now):
    fresh = observed.get('fresh', False)
    idle = observed.get('laptop_idle', 999999)
    place = observed.get('place') if fresh else None
    screen = observed.get('screen') if fresh else None
    motion = observed.get('motion') if fresh else None
    night = now.hour >= 22 or now.hour < 7
    if fresh and night and observed.get('charging') and screen == 'off' and idle >= 300:
        return 'asleep', .7, 'Night charging, phone screen off and no recent laptop input suggest sleep.'
    if fresh and motion == 'in_vehicle':
        return 'commuting', .85, 'The phone reports in-vehicle motion.'
    if fresh and motion == 'walking' and not place:
        return 'commuting', .65, 'Walking after leaving a named place suggests travel.'
    if place == 'college' and observed.get('class_window'):
        return 'in_class', .75, 'The phone is at college during a scheduled class window; attendance is not verified.'
    if night and (place == 'home' and idle >= 180 or observed.get('scene') == 'sleep') and screen != 'unlocked':
        return 'winding_down', .65, 'It is late at home or sleep mode is active; sleep is not verified.'
    if idle < 180:
        return 'at_desk', .95, 'Recent laptop input indicates attention at the desk.'
    if fresh and screen == 'unlocked' and motion in {'still', 'walking'}:
        return 'on_phone', .85, 'The phone is unlocked with a current motion state while the laptop is idle.'
    if place == 'college':
        return 'at_college_free', .8, 'The phone is at college and no class is scheduled now.'
    if place == 'home':
        return 'at_home', .8, 'The phone reports home, with no stronger activity signal.'
    return 'away', .6 if fresh and observed.get('transition') else .3, 'No recent desk input or reliable current place is available.'


class PresenceEngine:
    def __init__(self, *, hysteresis=45, minimum_dwell=60, publish=None):
        self.hysteresis, self.minimum_dwell, self.publish = hysteresis, minimum_dwell, publish
        self.lock = threading.RLock()
        self.value = None
        self.candidate, self.candidate_since = None, 0
        self.place_ready, self.place, self.place_candidate, self.place_since = False, None, None, 0
        self.place_edge, self.source_device = None, None

    def reset(self, device=None):
        with self.lock:
            if device is None or self.value and self.value.get('device') == device or self.source_device == device:
                self.value, self.candidate = None, None
                self.place_ready, self.place, self.place_edge = False, None, None
                self.place_candidate, self.source_device = None, None

    def _place(self, observed, stamp):
        device = observed.get('device')
        if not observed.get('fresh'):
            self.place_ready, self.place, self.place_edge = False, None, None
            return
        place = observed.get('place')
        if not self.place_ready or device != self.source_device:
            self.place_ready, self.place, self.place_candidate = True, place, place
            self.place_since, self.source_device, self.place_edge = stamp, device, None
            return  # Initial observations/reconnections are not new arrivals.
        if place != self.place_candidate:
            self.place_candidate, self.place_since = place, stamp
        if place != self.place and stamp - self.place_since >= self.hysteresis:
            previous, self.place = self.place, place
            edge = observed.get('transition') or {}
            self.place_edge = edge if (edge.get('event') == 'arrive' and edge.get('place') == place
                or edge.get('event') == 'leave' and place is None and edge.get('place') == previous) else None
        if self.place_edge and stamp - self.place_edge.get('at', stamp) > 900:
            self.place_edge = None

    def observe(self, observed, now=None):
        now = now or datetime.now()
        stamp = now.timestamp()
        state, confidence, reason = infer(observed, now)
        with self.lock:
            previous = self.value['state'] if self.value else None
            if self.value and stamp < self.value['sampled_at']:
                return dict(self.value)  # An old batch cannot rewind presence.
            self._place(observed, stamp)
            if state != self.candidate:
                self.candidate, self.candidate_since = state, stamp
            changed = False
            if self.value is None:
                initial = 'winding_down' if state == 'asleep' else state
                self.value = dict(state=initial, since=stamp, reason=reason, confidence=confidence)
                changed = True
            elif state != self.value['state']:
                wait = 300 if state == 'asleep' else 60 if state == 'commuting' else self.hysteresis
                if stamp - self.candidate_since >= wait and stamp - self.value['since'] >= self.minimum_dwell:
                    self.value.update(state=state, since=stamp, reason=reason, confidence=confidence)
                    changed = True
            else:
                self.value.update(reason=reason, confidence=confidence)
            # Raw notification/app content is deliberately absent from every snapshot.
            self.value.update(sampled_at=stamp, place=self.place,
                              device=observed.get('device') if observed.get('fresh') else None,
                              data_available=bool(observed.get('fresh') or observed.get('laptop_idle', 999999) < 180),
                              in_class=bool(observed.get('class_window')),
                              transition=self.place_edge)
            if not observed.get('fresh') and self.value['state'] != 'at_desk':
                self.value.update(confidence=min(self.value['confidence'], .3), reason='Phone observations are stale or sharing is off; retaining the prior estimate during hysteresis.')
            result = dict(self.value)
            if changed and self.publish:
                self.publish(dict(result, previous=previous))
            return result


def _publish(snapshot):
    from services.event_bus import event_bus
    from services.remote.context import origin_scope
    with origin_scope(True):
        event_bus.publish('presence.changed', {key: snapshot[key] for key in
            ('state', 'reason', 'confidence', 'since', 'previous')}, plugin_id='presence')


engine = PresenceEngine(publish=_publish)


def current(now=None):
    import sqlite3
    from .inputs import observation
    now = now or datetime.now()
    try:
        return engine.observe(observation(now), now)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
        return engine.observe(dict(fresh=False, laptop_idle=999999), now)
