"""HUD settings/control and deliberately slow, privacy-filtered service state."""
from copy import deepcopy
from datetime import datetime
import math
import threading
import time

from .gpu import GPU
from .stats import Stats

WIDGETS = ('system', 'network', 'clock', 'class', 'focus', 'scene', 'activity')
DEFAULTS = dict(enabled=True, editing=False, layer='desktop', monitor='primary', x=64, y=120,
                width=480, height=720, opacity=0.82, hide_fullscreen=True, hide_game=True,
                saver=False, auto_saver=True, battery_threshold=30, widgets=dict.fromkeys(WIDGETS, True))
_gpu = None


def validate(changes):
    if not isinstance(changes, dict) or changes.keys() - DEFAULTS.keys():
        raise ValueError('Unknown HUD setting.')
    for key, value in changes.items():
        default = DEFAULTS[key]
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif key == 'widgets':
            valid = isinstance(value, dict) and not value.keys() - set(WIDGETS) and all(isinstance(v, bool) for v in value.values())
        elif key == 'layer':
            valid = value in ('desktop', 'top')
        elif key == 'monitor':
            valid = isinstance(value, str) and 0 < len(value) <= 128 and not any(ord(c) < 32 for c in value)
        else:
            bounds = {'x': (0, 16000), 'y': (0, 16000), 'width': (300, 16000), 'height': (360, 16000),
                      'opacity': (.2, 1), 'battery_threshold': (1, 100)}
            low, high = bounds[key]
            valid = type(value) in (int, float) and math.isfinite(value) and low <= value <= high
        if not valid:
            raise ValueError(f'Invalid HUD setting: {key}.')
    return changes


class HUD:
    def __init__(self, api):
        self.api, self.lock = api, threading.RLock()
        self.scenes, self.focus, self.editing = {}, None, False
        self.activity_at, self.activity = 0, None
        self.settings()  # Fail visibly for malformed persisted settings; never overwrite them.

    def settings(self):
        saved = self.api.settings.get('hud', {})
        validate(saved)
        # Edit mode is session-only; a crash must never leave a clickable HUD on restart.
        result = deepcopy(DEFAULTS) | saved | {'editing': self.editing}
        result['widgets'] = DEFAULTS['widgets'] | saved.get('widgets', {})
        return result

    def change(self, payload, action='settings'):
        try:
            validate(payload)
            with self.lock:
                settings = self.settings()
                if 'widgets' in payload:
                    payload = payload | {'widgets': settings['widgets'] | payload['widgets']}
                settings.update(payload)
                self.editing = settings['editing']
                self.api.settings.set('hud', settings | {'editing': False})
                self.api.publish('hud.changed', {'settings': settings, 'action': action})
            return {'ok': True, 'text': 'HUD layout saved.' if action == 'done' else 'HUD settings saved.', 'data': settings}
        except ValueError as error:
            return {'ok': False, 'text': str(error), 'error': 'invalid_settings'}

    def command(self, match):
        command = match.group(1).lower()
        changes = {'on': {'enabled': True}, 'off': {'enabled': False, 'editing': False},
                   'edit': {'enabled': True, 'editing': True}, 'done': {'editing': False},
                   'layer desktop': {'layer': 'desktop'}, 'layer top': {'layer': 'top'},
                   'saver on': {'saver': True}, 'saver off': {'saver': False}}
        result = self.change(changes[command], command)
        if result['ok']:
            result['text'] = {'on': 'HUD on. Clicks pass through.', 'off': 'HUD off.',
                              'edit': 'HUD edit mode. Drag the header or resize a corner; say hud done to save.',
                              'done': 'HUD click-through restored; connected Island saves its position.',
                              'layer desktop': 'HUD behind normal windows.', 'layer top': 'HUD on top at reduced opacity.',
                              'saver on': 'HUD saver on: five-second readings, animations off.',
                              'saver off': 'Manual HUD saver off. Low-battery saver still follows settings.'}[command]
        return result

    def event(self, event):
        payload, topic = event['payload'], event['topic']
        with self.lock:
            if topic == 'scene.started':
                self.scenes[str(payload.get('scene_id', 'scene'))] = str(payload.get('name', ''))[:80]
            elif topic == 'scene.ended':
                self.scenes.pop(str(payload.get('scene_id', 'scene')), None)
            elif topic == 'focus.started':
                duration = payload.get('duration_s')
                if type(duration) in (int, float) and math.isfinite(duration) and 0 < duration <= 604800:
                    self.focus = dict(session_id=str(payload.get('session_id', '')), duration_s=duration,
                                      ends_at=event['at'] + duration, remaining_s=None)
            elif self.focus and payload.get('session_id') == self.focus['session_id']:
                if topic == 'focus.paused':
                    remaining = payload.get('remaining_s')
                    if type(remaining) in (int, float) and math.isfinite(remaining):
                        self.focus.update(remaining_s=max(0, remaining), ends_at=None)
                elif topic == 'focus.done':
                    self.focus = None
            self.api.publish('hud.state_changed', {'source': topic})

    def state(self, request=None):
        with self.lock:
            activity = self.api.get_service('activity')
            if activity is None:
                self.activity = None
            elif time.monotonic() - self.activity_at >= 30 or self.activity is None:
                try:
                    raw = activity.summary('today').get('categories', {})
                    self.activity = {str(k)[:32]: max(0, float(v)) for k, v in raw.items()
                                     if type(v) in (int, float) and math.isfinite(v)}
                    self.activity_at = time.monotonic()
                except Exception:
                    self.api.log.debug('HUD activity service unavailable', exc_info=True)
                    self.activity = None
            next_class = None
            schedule = self.api.get_service('schedule')
            if schedule is not None:
                try:
                    candidate = schedule.next_class()
                    if isinstance(candidate, dict) and isinstance(candidate.get('starts_at'), str):
                        datetime.fromisoformat(candidate['starts_at'])
                        next_class = {key: str(candidate.get(key, ''))[:160] for key in ('subject', 'faculty', 'room', 'starts_at')}
                except Exception:
                    self.api.log.debug('HUD schedule service unavailable', exc_info=True)
            try:
                fullscreen = bool(activity and activity.is_fullscreen())
            except Exception:
                fullscreen = False
            return dict(settings=self.settings(), scene=next(reversed(self.scenes.values()), ''),
                        game=any(name.lower() == 'game' for name in self.scenes.values()), focus=deepcopy(self.focus),
                        next_class=next_class, activity=self.activity, fullscreen=fullscreen)


def register(api):
    global _gpu
    _gpu = GPU()
    hud, stats = HUD(api), Stats(gpu=_gpu.read)
    api.provide('hud', hud)
    api.add_route('GET', 'stats', stats.snapshot)
    api.add_route('GET', 'state', hud.state)
    api.on_action('settings', hud.change)
    api.on_command(r'hud (on|off|edit|done|layer desktop|layer top|saver on|saver off)', hud.command,
                   help='Control the desktop HUD.', examples=['hud on', 'hud edit', 'hud done'])
    api.subscribe('scene.*', hud.event)
    api.subscribe('focus.*', hud.event)
    api.publish('hud.available', {})


def unload():
    if _gpu:
        _gpu.close()
