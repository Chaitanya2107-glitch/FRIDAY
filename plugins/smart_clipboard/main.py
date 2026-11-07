"""Windows smart clipboard: one item in RAM, bounded UI previews, no telemetry."""
import math
import os
import re
import threading
import time
from uuid import uuid4

from .detectors import populate
from .registry import Registry
from .windows import Activity, DEFAULT_BLOCKLIST, Hotkey, WindowsClipboard

_controller = None


def preview(value) -> str:
    line = ' '.join(str(value).split())
    # Remove control characters before exposing a literal-text preview.
    line = ''.join(c for c in line if c.isprintable())
    return line if len(line) <= 80 else line[:79] + '…'


def reply(text, ok=True, error=None):
    return {'ok': ok, 'text': text, 'error': error}


class SmartClipboard:
    def __init__(self, api, clipboard=None, activity=None, clock=time.monotonic, hotkey_factory=Hotkey):
        self.api, self.clock = api, clock
        self.clipboard = clipboard if clipboard is not None else WindowsClipboard() if os.name == 'nt' else None
        self.activity = activity or Activity()
        self.hotkey_factory = hotkey_factory
        self.registry = Registry()
        populate(self.registry, api)
        self.lock = threading.RLock()
        self.latest = self.result = None
        self.token = None
        self.expires = 0.0
        self.sequence = None
        self.last_card = -math.inf
        self.card_token = None
        self.idle = False
        self.scenes = {}

    def setting(self, key, default):
        return self.api.settings.get('smart_clipboard.' + key, default)

    def number(self, key, default, minimum, maximum):
        value = self.setting(key, default)
        if type(value) not in (int, float) or not math.isfinite(value):
            return default
        return min(maximum, max(minimum, value))

    def enabled(self):
        return self.setting('enabled', True) is True

    def clear(self):
        self.latest = self.result = self.token = None
        self.expires = 0.0

    def _refresh(self):
        if self.api.stop_event.is_set() or self.clipboard is None or not self.enabled():
            self.clear()
            self.sequence = None
            return False
        sequence = self.clipboard.sequence_number()
        if sequence == self.sequence:
            return False
        blocklist = self.setting('blocklist', DEFAULT_BLOCKLIST)
        if not isinstance(blocklist, list) or not all(isinstance(v, str) for v in blocklist):
            blocklist = DEFAULT_BLOCKLIST
        try:
            item = self.clipboard.read(blocklist)
        except Exception:
            self.clear()  # Busy/failed reads cannot leave old actions usable; retry next tick.
            raise
        self.sequence = item.sequence
        if self.api.stop_event.is_set():
            self.clear()
            return False
        if item.own:
            self.clear()  # An unrelated FRIDAY write invalidates old chips.
            return False
        self.clear()
        if item.sensitive or not isinstance(item.text, str) or not item.text.strip() or len(item.text) > 65536:
            return False
        self.latest = item.text
        self.token = uuid4().hex
        return True

    def allowed(self):
        if self.idle or any(name in {'game', 'sleep'} for name in self.scenes.values()):
            return False
        service = self.api.get_service('activity')
        if self.activity.idle() or self.activity.scene() in {'game', 'sleep'}:
            return False
        if service is not None and callable(getattr(service, 'is_fullscreen', None)):
            return not service.is_fullscreen()
        return not self.activity.fullscreen()

    def ttl(self):
        return self.number('card_ttl_seconds', 6, 1, 3600)

    def _show(self, title, body, actions=(), *, automatic=False):
        if self.api.stop_event.is_set() or not self.enabled() or not self.allowed():
            return False
        if self.api.stop_event.is_set():
            return False  # A service lookup may have waited behind host unload.
        new_card = self.card_token != self.token
        if new_card and self.clock() - self.last_card < 3:
            return False
        ttl = self.ttl()
        self.expires = self.clock() + ttl
        self.api.show_card(title, preview(body), list(actions)[:3], ttl_s=ttl)
        if new_card:
            self.api.publish('clipboard.action_available', {'action_id': 'run', 'label': title})
        if new_card:
            self.last_card = self.clock()
            self.card_token = self.token
        return True

    def _actions(self, detector):
        actions = detector.actions
        if detector.name == 'math':
            wanted = 'solve' if '=' in self.latest else 'evaluate'
            actions = tuple(a for a in actions if a.name == wanted)
        return [{'id': 'run', 'label': action.label,
                 'payload': {'token': self.token, 'detector': detector.name, 'action': action.name}}
                for action in actions[:3]]

    def show(self, *, automatic=False, forced_detector=None):
        if not self.latest:
            return reply('No readable clipboard item. Private and blocked copies are skipped.')
        detector, confidence = self.registry.classify(self.latest)
        if forced_detector and (detector is None or detector.name != forced_detector):
            return reply('The current clipboard does not match that action.', False, 'no_match')
        if automatic and confidence < self.number('confidence_threshold', .8, 0, 1):
            return reply('No confident clipboard action.')
        if detector is None:
            title, body, actions = 'Clipboard', 'No matching offline actions.', []
        else:
            title = 'Clipboard · ' + detector.name.replace('_', ' ').title()
            try:
                body = detector.preview(self.latest)
            except Exception:
                body = 'Clipboard actions available.'
            actions = self._actions(detector)
        shown = self._show(title, body, actions, automatic=automatic)
        # Commands/chat/bridge get a description, never the clipboard or result.
        labels = ', '.join(action['label'] for action in actions)
        return reply(f"{detector.name.replace('_', ' ').title() if detector else 'Clipboard'}"
                     f"{': ' + labels if labels else ': no actions'}."
                     + ('' if shown else ' Card held by clipboard display limits.'))

    def poll(self):
        try:
            with self.lock:
                if self.api.stop_event.is_set():
                    self.clear()
                    return
                if self._refresh():
                    self.show(automatic=True)
        except Exception:
            # The host logs callback tracebacks; none may contain clipboard data.
            with self.lock:
                self.clear()
            self.api.log.debug('Clipboard check unavailable; retrying.')
        finally:
            if self.api.stop_event.is_set():
                self.clear()

    def activity_event(self, event):
        with self.lock:
            if event['topic'] == 'activity.idle_started':
                self.idle = True
            elif event['topic'] == 'activity.idle_ended':
                self.idle = False

    def scene_event(self, event):
        payload = event.get('payload', {})
        name = str(payload.get('name', '')).lower()
        scene_id = str(payload.get('scene_id') or name)
        with self.lock:
            if event['topic'] == 'scene.started':
                self.scenes[scene_id] = name
            else:
                self.scenes.pop(scene_id, None)

    def command(self, match):
        try:
            with self.lock:
                text = match.group(0).lower().replace('’', "'")
                if text in {'clipboard on', 'clipboard off'}:
                    on = text.endswith(' on')
                    self.api.settings.set('smart_clipboard.enabled', on)
                    self.clear()
                    self.sequence = None
                    return reply('Smart clipboard ' + ('on.' if on else 'off.'))
                if not self.enabled():
                    self.clear()
                    return reply('Smart clipboard is off. Say clipboard on to enable it.')
                self._refresh()
                kind = {'solve clipboard': 'math', 'convert clipboard': 'units', 'clean clipboard link': 'url'}.get(text)
                if kind:
                    detector, _ = self.registry.classify(self.latest or '')
                    if not detector or detector.name != kind:
                        return reply('The current clipboard does not match that action.', False, 'no_match')
                    self.expires = self.clock() + self.ttl()
                    action = 'solve' if kind == 'math' and '=' in self.latest else 'evaluate' if kind == 'math' else 'convert' if kind == 'units' else 'clean'
                    return self.perform({'token': self.token, 'detector': kind, 'action': action})
                return self.show()
        except Exception:
            return reply('Clipboard action unavailable. Try again.', False, 'clipboard_unavailable')
        finally:
            if self.api.stop_event.is_set():
                self.clear()

    def perform(self, payload):
        try:
            with self.lock:
                if self._refresh():
                    self.show(automatic=True)
                if (self.api.stop_event.is_set() or not self.enabled() or not self.latest or not self.token or payload.get('token') != self.token
                        or self.clock() >= self.expires):
                    return reply('Clipboard action expired. Show clipboard actions again.', False, 'expired')
                if payload.get('copy') is True:
                    if self.result is None:
                        return reply('No result to copy.', False, 'no_result')
                    self.sequence = self.clipboard.write(self.result, expected_sequence=self.sequence)
                    return reply('Result copied.')
                detector, _ = self.registry.classify(self.latest)
                if detector is None or detector.name != payload.get('detector'):
                    return reply('Clipboard action unavailable.', False, 'no_match')
                action = next((a for a in detector.actions if a.name == payload.get('action')), None)
                if not action:
                    return reply('Clipboard action unavailable.', False, 'no_match')
                if self.api.stop_event.is_set():
                    self.clear()
                    return reply('Clipboard action expired.', False, 'expired')
                source_sequence = self.sequence
                value = action.run(self.latest)
                if self.api.stop_event.is_set():
                    self.clear()
                    return reply('Clipboard action expired.', False, 'expired')
                if self.clipboard.sequence_number() != source_sequence:
                    if self._refresh():
                        self.show(automatic=True)
                    return reply('Clipboard changed; show its actions again.', False, 'expired')
                if value is not None:
                    if not isinstance(value, str) or len(value) > 131072:
                        raise ValueError('Unsupported result.')
                    self.result = value
                    if action.name in {'format', 'clean'}:
                        self.sequence = self.clipboard.write(value, expected_sequence=source_sequence)
                    self._show('Clipboard · ' + detector.name.replace('_', ' ').title(), value,
                               [{'id': 'run', 'label': 'Copy result', 'payload': {'token': self.token, 'copy': True}}])
                return reply('Clipboard action completed.' if value is not None else 'Opened on this PC.')
        except Exception:
            return reply('Clipboard action unavailable. Check the input or local helper.', False, 'action_unavailable')
        finally:
            if self.api.stop_event.is_set():
                self.clear()

    def hotkeys(self, stop):
        hotkey, previous = None, object()
        try:
            hotkey = self.hotkey_factory()
            while not stop.is_set():
                spec = self.setting('hotkey', 'Ctrl+Shift+Alt+V') if self.enabled() else None
                if spec != previous:
                    hotkey.close()
                    if spec and not hotkey.register(spec):
                        self.api.log.warning('Smart clipboard hotkey unavailable; choose another shortcut in plugin settings.')
                        if self.allowed():
                            self.api.show_card('Clipboard hotkey unavailable',
                                               'Choose another smart_clipboard.hotkey; use clipboard commands meanwhile.', ttl_s=6)
                    previous = spec
                if spec and hotkey.pressed():
                    self.command(re.fullmatch(r'.+', "what's on my clipboard"))
                stop.wait(.05)
        except Exception:
            if not stop.is_set():
                self.api.log.warning('Smart clipboard hotkey unavailable; use clipboard commands.')
                try:
                    if self.allowed():
                        self.api.show_card('Clipboard hotkey unavailable',
                                           'Use clipboard commands or change smart_clipboard.hotkey in settings.', ttl_s=6)
                except Exception:
                    pass
        finally:
            if hotkey:
                hotkey.close()
            if stop.is_set():
                self.clear()

    def start(self):
        self.api.provide('clipboard_actions', self.registry)
        self.api.provide('smart_clipboard', self)
        self.api.on_action('run', self.perform)
        self.api.on_command([r'clipboard (?:on|off)', r"what(?:'|’)?s on my clipboard",
                             r'(?:solve|convert) clipboard', r'clean clipboard link'], self.command,
                            help='Offline clipboard actions; clipboard on/off controls monitoring.',
                            examples=['clipboard on', 'clipboard off', "what's on my clipboard",
                                      'solve clipboard', 'convert clipboard', 'clean clipboard link'])
        self.api.subscribe('activity.*', self.activity_event)
        self.api.subscribe('scene.*', self.scene_event)
        if self.clipboard is not None:
            self.api.every(.4, self.poll)
            self.api.run_background(self.hotkeys)


def register(api):
    global _controller
    _controller = SmartClipboard(api)
    _controller.start()


def unload():
    if _controller:
        # The host holds its manager lock and has already fenced this API. A
        # worker may hold our lock while awaiting that manager; never join it here.
        _controller.clear()
