"""Activity tests use only fake metadata, a fake clock and temporary storage."""
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

from services.event_bus import EventBus
from services.plugin_api import PluginAPI
from plugins.activity.commands import Commands
from plugins.activity.policy import Policy, Sample
from plugins.activity.tracker import Activity


class FakeClock:
    def __init__(self, now=None):
        self.value = now or datetime(2026, 11, 6, 10, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        self.ticks = 1000.

    def now(self):
        return self.value

    def monotonic(self):
        return self.ticks

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)
        self.ticks += seconds


class FakeProvider:
    def __init__(self, policy):
        self.policy = policy
        self.value = Sample()
        self.reads = 0

    def choose(self, process='code.exe', title='', idle=0, fullscreen=False):
        self.value = self.policy.sanitize(process, title, idle, fullscreen) if process else Sample(idle_seconds=idle)

    def sample(self):
        self.reads += 1
        return self.value


class FakeManager:
    def __init__(self):
        self.bus = EventBus()
        self.services = {}
        self.notifications = []
        self.failures = []

    def provide(self, plugin_id, name, obj, owner=None):
        self.services[name] = obj

    def get_service(self, name):
        return self.services.get(name)

    def failed(self, plugin_id):
        self.failures.append(plugin_id)

    def notify(self, *args):
        self.notifications.append(args)

    def invoke(self, api, handler, *args, **kwargs):
        return api._call(handler, *args)


def make_activity(tmp_path, now=None):
    folder = tmp_path / 'maps'
    folder.mkdir()
    source = Path(__file__).resolve().parents[1] / 'plugins/activity'
    for name in ['categories.json', 'sites.json']:
        shutil.copyfile(source / name, folder / name)
    manager = FakeManager()
    api = PluginAPI(manager, 'activity', tmp_path / 'data')
    policy = Policy(api, folder)
    clock = FakeClock(now)
    provider = FakeProvider(policy)
    tracker = Activity(api, policy, provider, clock)
    tracker.commands = Commands(tracker)
    manager.services['activity'] = tracker
    return SimpleNamespace(tracker=tracker, manager=manager, api=api, policy=policy, clock=clock, provider=provider)


def advance(activity, seconds, *, step=2):
    while seconds > 0:
        duration = min(seconds, step)
        activity.clock.advance(duration)
        activity.tracker.poll()
        seconds -= duration
