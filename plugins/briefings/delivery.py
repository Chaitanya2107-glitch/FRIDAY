"""Persisted local delivery, with scene/fullscreen deferral and scoped actions."""
from datetime import datetime, time, timedelta
import json
import re
import threading
import uuid

from services import quiet_mode, settings_store
from services.briefing_runtime import ALIASES



def result(text, ok=True):
    return dict(ok=ok, text=text, error=None if ok else 'briefing', speech='')


class Briefings:
    def __init__(self, api, builder, *, now=datetime.now, desktop=lambda: {}, quiet=quiet_mode.enabled):
        self.api, self.builder, self.now, self.desktop, self.quiet = api, builder, now, desktop, quiet
        self.lock = threading.RLock()
        self.answer_command = None
        self.path = api.data_dir / 'state.json'
        self.scenes = {}
        self.state = self._load()

    def _load(self):
        if not self.path.exists():
            return dict(version=1, delivered={}, openers={}, pending={}, offer=None)
        row = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(row, dict) or row.get('version') != 1
                or any(not isinstance(row.get(k), dict) for k in ('delivered', 'openers', 'pending'))):
            raise ValueError('Invalid briefing state; restore state.json before resuming')
        for kind, at in row['delivered'].items():
            if kind not in {'morning', 'night'}:
                raise ValueError('Invalid briefing kind')
            datetime.strptime(at, '%Y-%m-%d')
        for kind, pending in row['pending'].items():
            if kind not in {'morning', 'night'} or not isinstance(pending, dict):
                raise ValueError('Invalid pending briefing')
            datetime.fromisoformat(pending['at'])
            if pending.get('reason') not in {'manual', 'snooze', 'sleep', 'activity', 'fallback', 'clock'}:
                raise ValueError('Invalid briefing trigger')
        if any(kind not in {'morning', 'night'} or not isinstance(value, str) or len(value) > 500
               for kind, value in row['openers'].items()):
            raise ValueError('Invalid saved briefing opener')
        offer = row.get('offer')
        if offer is not None:
            if (not isinstance(offer, dict) or offer.get('kind') not in {'morning', 'night'}
                    or not isinstance(offer.get('id'), str) or not re.fullmatch(r'[a-f0-9]{32}', offer['id'])):
                raise ValueError('Invalid saved briefing offer')
            datetime.fromisoformat(offer['at'])
        row['offer'] = offer
        return row

    def _save(self):
        self.api._active()
        settings_store.save(self.path, self.state)

    def service(self, name):
        return self.api.get_service(name)

    def build(self, kind):
        # No delivery lock: scenes may call this while holding their own lock.
        return self.builder.render(kind, self.state['openers'].get(kind))[0]

    def tomorrow_summary(self):
        return self.builder.tomorrow_summary()

    def _time(self, key, default):
        value = self.api.settings.get('briefings.' + key, default)
        try:
            return datetime.strptime(value, '%H:%M').time()
        except (ValueError, TypeError):
            return time.fromisoformat(default)

    def in_window(self):
        start, end = self._time('morning_start', '05:00'), self._time('morning_end', '11:00')
        at = self.now().time()
        return start <= at < end if start < end else at >= start or at < end

    def _scene_names(self):
        scenes = self.service('scenes')
        names, transitioning = set(self.scenes.values()), False
        if scenes and callable(getattr(scenes, 'status', None)):
            state = scenes.status()
            active = state.get('active')
            names = {name for (owner, _), name in self.scenes.items() if owner != 'scenes'}
            names.add(str(active.get('name', '') if isinstance(active, dict) else active or '').casefold())
            transitioning = bool(state.get('recovery') or state.get('phase', 'idle') not in {'idle', 'active'})
        from services.automation import modes
        legacy = modes.active(strict=True)
        if legacy:
            names.add(legacy['name'].casefold())
        return names, transitioning

    def _blocked(self, reason):
        names, transitioning = self._scene_names()
        if transitioning:
            return True
        if names & {'game', 'class'}:
            return True
        # Unknown foreground state defers rather than interrupting a possible fullscreen app.
        if self.desktop().get('fullscreen') is not False:
            return True
        return bool(self.quiet() and reason not in {'manual', 'sleep', 'snooze'})

    def _queue(self, kind, reason, minutes, day=None):
        self.state['pending'][kind] = dict(at=(self.now()+timedelta(minutes=minutes)).isoformat(), reason=reason,
                                          day=day or self.now().date().isoformat())
        if reason == 'sleep' and self._scene_names()[1]:
            self.state['pending'][kind]['waiting_for_scene'] = True
        self._save()

    def _speaks(self, kind):
        setting = self.api.settings.get('briefings.speak', {'morning': True, 'night': False})
        return setting if type(setting) is bool else bool(setting.get(kind, kind == 'morning')) if isinstance(setting, dict) else kind == 'morning'

    def request(self, kind, *, reason='manual', day=None):
        if kind not in {'morning', 'night'}:
            raise ValueError('Use morning or night')
        with self.lock:
            today = day or self.now().date().isoformat()
            explicit = reason in {'manual', 'snooze'}
            if not explicit and self.state['delivered'].get(kind) == today:
                return result('This brief was already delivered today.')
            if not explicit and not self.api.settings.get('briefings.enabled', True):
                return result('Automatic briefings are off.')
            if kind == 'morning' and not explicit and not self.in_window():
                self.state['pending'].pop(kind, None)
                self._save()
                return result('The morning window has ended.')
            if self._blocked(reason):
                self._queue(kind, reason, 10, today)
                return result('Brief deferred for 10 minutes.')
            text, opener = self.builder.render(kind, self.state['openers'].get(kind))
            if self._blocked(reason):
                self._queue(kind, reason, 10, today)
                return result('Brief deferred for 10 minutes.')
            sleep_offer = kind == 'night' and self.service('scenes') is not None and 'sleep' not in self._scene_names()[0]
            if sleep_offer:
                lines = text.splitlines()
                lines[-1] += ' Start sleep mode?'
                text = '\n'.join(lines)
            offer = dict(id=uuid.uuid4().hex, kind=kind, at=self.now().isoformat())
            self.state['delivered'][kind] = today
            self.state['openers'][kind] = opener
            self.state['offer'] = offer
            self.state['pending'].pop(kind, None)
            self._save()  # Claim first, including across restarts.
            self.sync_commands()
            def action(ident, label):
                return dict(id=ident, label=label, payload=dict(card_id=offer['id']))
            actions = [action('skip', 'Skip'), action('snooze', 'Snooze 30 min')]
            if sleep_offer:
                actions += [action('sleep', 'Yes'), action('skip', 'Not now')]
            self.api.publish('ui.card', dict(title='Morning brief' if kind == 'morning' else 'Night brief',
                body=text, actions=actions, ttl_s=600, card_id=offer['id'],
                urgency='critical' if reason in {'manual', 'sleep', 'snooze'} else 'normal'))
            self.api.publish('briefing.ready', dict(kind=kind, text=text))
            self.api.set_mood('waving' if kind == 'morning' else 'sleepy', duration_s=3 if kind == 'morning' else 5, priority=2)
            if self._speaks(kind):
                def speak(stop):
                    if not stop.is_set() and self.has_offer(offer['id']) and not self._blocked(reason):
                        self.api.speak(text)
                self.api.run_background(speak)
            if kind == 'morning':
                def smile(stop):
                    if not stop.wait(3) and self.has_offer(offer['id']):
                        self.api.set_mood('happy', duration_s=4, priority=2)
                self.api.run_background(smile)
            return result(text)

    def has_offer(self, card_id=None):
        with self.lock:
            offer = self.state['offer']
            return bool(offer and (card_id is None or offer['id'] == card_id)
                        and 0 <= (self.now()-datetime.fromisoformat(offer['at'])).total_seconds() <= 600)

    def sync_commands(self):
        if self.answer_command is not None:
            self.answer_command.patterns = [re.compile(r'skip|snooze 30' if self.has_offer() else r'(?!)', re.I)]

    def respond(self, action, payload=None):
        with self.lock:
            card_id = payload.get('card_id') if isinstance(payload, dict) else None
            if payload is not None and (not isinstance(card_id, str) or not card_id):
                return result('This briefing action needs its current card ID.', False)
            if not self.has_offer(card_id):
                return result('That brief is no longer awaiting a reply.', False)
            offer = self.state['offer']
            if action == 'sleep' and offer['kind'] != 'night':
                return result('Sleep mode belongs to the night brief.', False)
            scenes = self.service('scenes') if action == 'sleep' else None
            self.state['offer'] = None
            self.state['pending'].pop(offer['kind'], None)
            if action == 'snooze':
                self._queue(offer['kind'], 'snooze', 30)
            else:
                self._save()
            self.sync_commands()
            self.api.publish('briefing.dismissed', dict(kind=offer['kind'], card_id=offer['id']))
        # Scene actions may call tomorrow_summary(). Never acquire the scene lock under ours.
        if action == 'sleep':
            return scenes.request('sleep') if scenes and callable(getattr(scenes, 'request', None)) else result('Scenes are unavailable.', False)
        return result('Brief snoozed for 30 minutes.' if action == 'snooze' else 'Brief skipped.')

    def matches(self, text):
        self.sync_commands()
        return bool(re.fullmatch(ALIASES, text, re.I) or self.has_offer() and re.fullmatch(r'skip|snooze 30', text, re.I))

    def handle_command(self, text):
        text = text.casefold().strip()
        if text in {'skip', 'snooze 30'}:
            return self.respond('skip' if text == 'skip' else 'snooze')
        if not re.fullmatch(ALIASES, text, re.I):
            return result('Unknown briefing command.', False)
        return self.request('night' if text == 'night brief' else 'morning')

    def event(self, event):
        topic, payload = event['topic'], event.get('payload', {})
        if topic in {'scene.started', 'scene.ended', 'scene.state'}:
            name = str(payload.get('name') or '').casefold()
            owner = event.get('plugin_id', 'events')
            key = (owner, str(payload.get('scene_id', name)))
            with self.lock:
                if topic == 'scene.state':
                    self.scenes = {k: v for k, v in self.scenes.items() if k[0] != owner}
                if topic != 'scene.ended' and name:
                    self.scenes[key] = name
                else:
                    self.scenes.pop(key, None)
                release_sleep = (topic == 'scene.state' and payload.get('phase') == 'active'
                                 and self.state['pending'].get('night', {}).get('waiting_for_scene') is True)
            if name == 'sleep' and (topic == 'scene.started' or release_sleep):
                self.request('night', reason='sleep')
        elif topic == 'activity.idle_ended' and self.in_window():
            with self.lock:
                if 'morning' not in self.state['pending']:
                    self.request('morning', reason='activity')

    def tick(self):
        with self.lock:
            self.sync_commands()
            now = self.now()
            for kind, pending in list(self.state['pending'].items()):
                if datetime.fromisoformat(pending['at']) <= now:
                    self.request(kind, reason=pending['reason'], day=pending.get('day'))
            today = now.date().isoformat()
            if 'morning' not in self.state['pending'] and self.state['delivered'].get('morning') != today and self.in_window():
                if now.time() >= self._time('morning_fallback', '07:30'):
                    self.request('morning', reason='fallback')
                elif self.service('activity') is None and self.desktop().get('active') is True:
                    self.request('morning', reason='activity')
            if ('night' not in self.state['pending'] and self.state['delivered'].get('night') != today
                    and now.time() >= self._time('night_time', '22:30')):
                self.request('night', reason='clock')
