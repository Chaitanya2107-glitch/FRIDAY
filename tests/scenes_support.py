"""Scene tests use temporary JSON, fake settings and no real desktop APIs."""
from pathlib import Path
import threading
from types import SimpleNamespace

from services import settings_store
from services.event_bus import EventBus
from services.plugin_api import PluginAPI
from plugins.scenes.actions import install
from plugins.scenes.commands import Commands
from plugins.scenes.engine import Scenes
from plugins.scenes.registry import Registry


class Manager:
    def __init__(self):
        self.bus, self.services = EventBus(), {}
        self.states, self.lock, self.failures = {}, threading.RLock(), []

    def get_service(self, name):
        return self.services.get(name)

    def failed(self, name):
        self.failures.append(name)

    def notify(self, *args):
        pass

    def speak(self, text):
        pass

    def invoke(self, api, fn, *args, **kwargs):
        return api._call(fn, *args)


class Hardware:
    def __init__(self):
        self.audio = dict(device='fake-speakers', scalar=.734, mute=True)
        self.brightness = {'built-in-fake': 67}
        self.plan = '12345678-1234-1234-1234-123456789abc'
        self.calls, self.running = [], set()

    def audio_snapshot(self): return dict(self.audio)
    def set_volume(self, percent): self.calls.append('volume'); self.audio.update(scalar=percent / 100, mute=False if percent else self.audio['mute'])
    def mute(self, on): self.calls.append('mute'); self.audio['mute'] = on
    def restore_audio(self, value): self.calls.append('undo-audio'); self.audio = dict(value)
    def brightness_snapshot(self): return dict(self.brightness)
    def set_brightness(self, percent): self.calls.append('brightness'); self.brightness = {k: percent for k in self.brightness}
    def restore_brightness(self, value): self.calls.append('undo-brightness'); self.brightness = dict(value)
    def power_plan(self): return self.plan
    def set_power_plan(self, plan): self.calls.append('power:' + plan); self.plan = plan
    def processes(self): return set(self.running)
    def open_app(self, name): self.calls.append('open:' + name)
    def close_app(self, name): self.calls.append('close:' + name)
    def open_path(self, path): self.calls.append('path:' + str(path))
    def open_url(self, url): self.calls.append('url:' + url)
    def play_music(self, value): self.calls.append('music:' + value)
    def window_snapshot(self, name): return []
    def minimize(self, name): self.calls.append('minimize:' + name); return []
    def restore_windows(self, previous): self.calls.append('undo-minimize')


def make_scenes(tmp_path, *, hardware=None, now=None, data=None):
    manager = Manager()
    api = PluginAPI(manager, 'scenes', data or tmp_path / 'user/scenes')
    registry = Registry(api)
    desktop = hardware or Hardware()
    install(registry, desktop)
    clock = now or SimpleNamespace(value=1794000000.)
    engine = Scenes(api, registry, desktop, Path(__file__).resolve().parents[1] / 'plugins/scenes/defaults', now=lambda: clock.value)
    engine.commands = Commands(engine)
    manager.services['scenes'] = engine
    return SimpleNamespace(engine=engine, api=api, registry=registry, desktop=desktop, manager=manager, clock=clock)


def put_scene(host, name='test', actions=None, **options):
    value = dict(name=name, aliases=[name + ' mode'], description='Synthetic test scene',
                 confirm_first_run=False, actions=actions or []) | options
    settings_store.save(host.engine.catalog.folder / (name + '.json'), value)
    host.engine.catalog.reload()
    return host.engine.catalog.folder / (name + '.json')
