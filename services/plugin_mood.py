"""Phase 0 compatibility adapter. The mood plugin owns arbitration at runtime."""
import logging
from pathlib import Path
import threading
from types import SimpleNamespace

from plugins.mood.engine import MoodEngine


class MoodController:
    def __init__(self, bus):
        self.bus = bus
        api = SimpleNamespace(settings={}, log=logging.getLogger(__name__), publish=bus.publish)
        self.engine = MoodEngine(api, Path(__file__).resolve().parents[1] / 'plugins/mood/mood_rules.json')
        self.subscription = bus.subscribe('mood.set', self.engine.receive, plugin_id='friday-mood')
        self.stop_event = threading.Event()
        def run():
            while not self.stop_event.wait(.05):
                self.engine.tick()
        self.thread = threading.Thread(target=run, name='mood-compat', daemon=True)
        self.thread.start()

    @property
    def current(self):
        value = self.engine.snapshot()
        return dict(value, expires_at=value['until'] or 0)

    def close(self):
        self.stop_event.set()
        self.bus.unsubscribe(self.subscription)
        self.thread.join(.5)
