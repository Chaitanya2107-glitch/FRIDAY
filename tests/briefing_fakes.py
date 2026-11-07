"""Explicit clocks/services; no desktop probes, speech or network in feature tests."""
from datetime import datetime, timedelta
import logging
import threading

from plugins.briefings.content import Builder
from plugins.briefings.delivery import Briefings


class Clock:
    def __init__(self, value=None):
        self.value = value or datetime(2030, 1, 7, 6)

    def now(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


class API:
    def __init__(self, path):
        self.data_dir = path
        path.mkdir(parents=True, exist_ok=True)
        self.settings, self.services = {}, {}
        self.events, self.cards, self.moods, self.spoken, self.jobs = [], [], [], [], []
        self.commands, self.actions, self.timers, self.subscriptions = [], {}, [], []
        self.log = logging.getLogger('briefings-test')
        self.stop_event = threading.Event()

    def _active(self):
        if self.stop_event.is_set():
            raise RuntimeError('Plugin unloaded')

    def get_service(self, name):
        return self.services.get(name)

    def provide(self, name, value):
        self.services[name] = value

    def publish(self, topic, payload):
        self._active()
        self.events.append((topic, payload))

    def show_card(self, *args, **kwargs):
        self.cards.append((args, kwargs))

    def set_mood(self, *args, **kwargs):
        self.moods.append((args, kwargs))

    def speak(self, text):
        self.spoken.append(text)

    def run_background(self, fn):
        self.jobs.append(fn)

    def on_command(self, *args, **kwargs):
        self.commands.append(args)

    def on_action(self, name, callback):
        self.actions[name] = callback

    def subscribe(self, *args):
        self.subscriptions.append(args)

    def every(self, *args):
        self.timers.append(args)

    def payloads(self, topic):
        return [value for name, value in self.events if name == topic]


def make_brief(tmp_path, *, clock=None, services=None, battery=None, desktop=None, quiet=None):
    clock = clock or Clock()
    api = API(tmp_path / 'briefings')
    api.services.update(services or {})
    builder = Builder(api, now=clock.now, battery=lambda: battery, choose=lambda rows: rows[0])
    value = Briefings(api, builder, now=clock.now,
        desktop=desktop or (lambda: dict(active=False, fullscreen=False)), quiet=quiet or (lambda: False))
    return value, clock, api
