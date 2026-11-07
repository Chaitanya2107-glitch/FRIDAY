"""Clock-injected mood arbitration; one ordered subscriber owns all contexts."""
from datetime import datetime
import threading
import time

from .rules import MOODS, Rules, message, number


class MoodEngine:
    def __init__(self, api, rules_path, *, clock=time.time, localtime=datetime.fromtimestamp,
                 active=lambda: False, quiet=lambda: False, idle_seconds=lambda: None):
        self.api, self.clock, self.localtime, self.active = api, clock, localtime, active
        self.quiet = quiet
        self.idle_seconds = idle_seconds
        self.lock = threading.RLock()
        self.rules = Rules(rules_path, api.log)
        self.stickies, self.scenes, self.cooldowns = {}, {}, {}
        self.temporary = self.idle_event = None
        self.sequence = 0
        self.current = self._idle()
        self.last_night = float('-inf')
        self.preview, self.preview_at = [], 0

    @staticmethod
    def _idle():
        return dict(mood='idle', message='', until=None, sticky=False, priority=0, plugin_id='mood')

    def calm(self):
        return (self.api.settings.get('mood.calm_mode', False) is True or any(self.scenes.values())
                or bool(self.scenes) and self.quiet())

    @staticmethod
    def owner(topic, payload, plugin_id):
        if topic.startswith('scene.'):
            return 'scene:' + str(payload.get('scene_id', payload.get('name', plugin_id)))
        if topic.startswith('focus.'):
            return 'focus:' + str(payload.get('session_id', plugin_id))
        if topic.startswith('activity.idle_'):
            return 'activity:idle'
        return 'raw:' + plugin_id

    def _select(self):
        now, calm = self.clock(), self.calm()
        if self.temporary and (self.temporary['until'] <= now or (calm and self.temporary['priority'] < 4)):
            self.temporary = None
        candidates = [row for row in self.stickies.values() if not calm or row['priority'] >= 4]
        if self.temporary:
            candidates.append(self.temporary)
        return max(candidates, key=lambda r: (r['priority'], r['order'])) if candidates else None

    def _refresh(self):
        selected = self._select()
        current = {k: selected[k] for k in self._idle()} if selected else self._idle()
        if current != self.current:
            previous = self.current['mood']
            self.current = current
            # Old fields are retained for Phase 0 clients.
            self.api.publish('mood.changed', dict(current, previous=previous,
                                                 expires_at=current['until'] or 0))
            self.api.log.debug('Mochi: %s -> %s (priority %s)', previous, current['mood'], current['priority'])

    def request(self, data, *, owner='raw:mood', plugin_id='mood', rule_key=None, until=()):
        if not isinstance(data, dict):
            return False
        mood, duration = data.get('mood'), data.get('duration_s', 5)
        priority, sticky = data.get('priority', 0), data.get('sticky', False)
        text = data.get('message', '')
        if (mood not in MOODS or type(priority) is not int or type(sticky) is not bool
                or not number(duration) or duration == 0 or not isinstance(text, str) or len(text) > 4000):
            self.api.log.debug('Ignored invalid mood request')
            return False
        with self.lock:
            selected = self._select()
            if not sticky and (self.calm() and priority < 4 or selected and priority < selected['priority']):
                self._refresh()
                return False
            self.sequence += 1
            row = dict(mood=mood, message=text[:60], until=None if sticky else self.clock() + duration,
                       sticky=sticky, priority=priority, plugin_id=plugin_id, order=self.sequence,
                       release=tuple(until), rule_key=rule_key)
            if sticky:
                self.stickies[owner] = row
                if self.temporary and priority >= self.temporary['priority']:
                    self.temporary = None
            else:
                self.temporary = row
            self._refresh()
            return True

    def _rule(self, index, row, payload, owner):
        now = self.clock()
        key = (index, owner) if row.get('sticky') else index
        if now - self.cooldowns.get(key, float('-inf')) < row.get('cooldown_s', 60):
            return
        data = dict(row, message=message(row.get('message', ''), payload))
        if self.request(data, owner=owner, rule_key=key, until=row.get('until', ())):
            self.cooldowns[key] = now

    def receive(self, event):
        topic, payload = event.get('topic', ''), event.get('payload', {})
        plugin_id = str(event.get('plugin_id', 'friday'))
        if not isinstance(payload, dict) or topic in {'mood.changed', 'mood.preview'}:
            return
        with self.lock:
            owner = self.owner(topic, payload, plugin_id)
            if topic == 'mood.set':
                self.request(payload, owner=owner, plugin_id=plugin_id)
                return
            if topic == 'scene.started':
                self.scenes[owner] = payload.get('quiet_mode') is True
            elif topic == 'scene.ended':
                self.scenes.pop(owner, None)
            for key, row in list(self.stickies.items()):
                if key == owner and topic in row['release']:
                    del self.stickies[key]
                    self.cooldowns.pop(row['rule_key'], None)
            if topic == 'activity.idle_started':
                since = payload.get('since', event.get('at', self.clock()))
                if number(since, 0, self.clock()):
                    self.idle_event = dict(payload, since=since)
            elif topic == 'activity.idle_ended':
                self.idle_event = None
            for index, row in enumerate(self.rules.rows):
                if row['event'] != topic or any(payload.get(k) not in values for k, values in row.get('match', {}).items()):
                    continue
                if row.get('min_idle_s', 0):
                    continue  # tick waits until actual last input + threshold.
                self._rule(index, row, payload, owner)
            self._refresh()

    def tick(self):
        with self.lock:
            self.rules.reload()
            now = self.clock()
            if self.idle_event is None:
                idle = self.idle_seconds()
                if number(idle, 600, 864000):
                    self.idle_event = {'since': now - idle}
            if self.preview and now >= self.preview_at:
                value = self.preview.pop(0)
                self.request(dict(mood=value, duration_s=3, priority=100), owner='preview')
                self.preview_at = now + 3
            if self.idle_event:
                for index, row in enumerate(self.rules.rows):
                    if row['event'] == 'activity.idle_started' and now - self.idle_event['since'] >= row.get('min_idle_s', 600):
                        if 'activity:idle' not in self.stickies:
                            self._rule(index, row, self.idle_event, 'activity:idle')
            row = self.rules.late_night
            if (row and not self.idle_event and row.get('start_hour', 1) <= self.localtime(now).hour < row.get('end_hour', 6)
                    and now - self.last_night >= row.get('cooldown_s', 1800) and self.active()):
                if self.request(row):
                    self.last_night = now
            self._refresh()

    def next_delay(self):
        with self.lock:
            deadlines = [self.clock() + .4]
            if self.temporary:
                deadlines.append(self.temporary['until'])
            if self.preview:
                deadlines.append(self.preview_at)
            return max(.01, min(deadlines) - self.clock())

    def test(self, value):
        with self.lock:
            if value not in (*MOODS, 'all'):
                return dict(ok=False, text='Moods: ' + ', '.join(MOODS), error='invalid_mood')
            self.preview = list(MOODS) if value == 'all' else [value]
            self.preview_at = self.clock()
            self.tick()
            return dict(ok=True, text='Mochi is trying ' + value + '.', error=None)

    def snapshot(self):
        with self.lock:
            self._refresh()
            return dict(self.current)
