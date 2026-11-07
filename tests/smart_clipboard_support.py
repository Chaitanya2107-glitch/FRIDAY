"""In-memory adapters: tests never touch the desktop clipboard or register keys."""
import logging
import threading
from types import SimpleNamespace

from plugins.smart_clipboard.main import SmartClipboard


class FakeClipboard:
    def __init__(self):
        self.sequence = 0
        self.text = None
        self.flags = {}
        self.app = 'notepad'
        self.own = False
        self.reads = self.text_reads = 0
        self.writes = []

    def sequence_number(self):
        return self.sequence

    def copy(self, text, *, flags=None, app='notepad', own=False):
        self.sequence += 1
        self.text, self.flags, self.app, self.own = text, flags or {}, app, own

    def read(self, blocklist):
        self.reads += 1
        private = ('ExcludeClipboardContentFromMonitorProcessing' in self.flags
                   or any(self.flags.get(name, 1) != 1 for name in
                          ('CanIncludeInClipboardHistory', 'CanUploadToCloudClipboard'))
                   or self.app.lower().removesuffix('.exe') in {v.lower().removesuffix('.exe') for v in blocklist})
        text = None
        if not private and not self.own:
            text = self.text
            self.text_reads += 1
        return SimpleNamespace(sequence=self.sequence, text=text, sensitive=private, own=self.own)

    def write(self, text, *, expected_sequence=None):
        if expected_sequence is not None and expected_sequence != self.sequence:
            raise ValueError('Clipboard changed before copy.')
        self.writes.append(text)
        self.copy(text, own=True)
        return self.sequence


class FakeSettings(dict):
    def set(self, key, value):
        self[key] = value


class FakeAPI:
    def __init__(self):
        self.settings = FakeSettings()
        self.stop_event = threading.Event()
        self.log = logging.getLogger('friday.plugins.smart_clipboard')
        self.services, self.actions, self.commands = {}, {}, []
        self.cards, self.events, self.timers, self.jobs, self.subscribers = [], [], [], [], {}

    def get_service(self, name):
        return self.services.get(name)

    def provide(self, name, obj):
        self.services[name] = obj

    def show_card(self, title, body, actions=(), ttl_s=30):
        card = dict(title=title, body=body, actions=list(actions), ttl_s=ttl_s)
        self.cards.append(card)
        self.events.append(dict(topic='ui.card', payload=card))

    def set_mood(self, mood, duration_s=5, priority=0):
        self.events.append(dict(topic='mood.set', payload=dict(mood=mood, duration_s=duration_s, priority=priority)))

    def publish(self, topic, payload):
        self.events.append(dict(topic=topic, payload=payload))

    def on_action(self, name, handler):
        self.actions[name] = handler

    def on_command(self, patterns, handler, **kwargs):
        self.commands.append((patterns, handler))

    def subscribe(self, pattern, handler):
        self.subscribers[pattern] = handler

    def every(self, seconds, fn):
        self.timers.append((seconds, fn))

    def run_background(self, fn):
        self.jobs.append(fn)


class FakeActivity:
    def __init__(self):
        self.is_idle, self.is_fullscreen, self.current_scene = False, False, ''

    def idle(self):
        return self.is_idle

    def fullscreen(self):
        return self.is_fullscreen

    def scene(self):
        return self.current_scene


def setup_clipboard():
    api, provider, activity = FakeAPI(), FakeClipboard(), FakeActivity()
    now = [100.0]
    controller = SmartClipboard(api, provider, activity, clock=lambda: now[0])
    return controller, api, provider, activity, now
