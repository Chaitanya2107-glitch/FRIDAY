"""The managed, cooperative lifecycle offered to trusted in-process plugins."""
from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
import logging
from pathlib import Path
import re
import threading
import time
from typing import Callable

from services.plugin_storage import Settings


@dataclass
class Command:
    patterns: list[re.Pattern]
    handler: Callable
    help: str
    examples: list[str]


class PluginAPI:
    def __init__(self, manager, plugin_id: str, data_dir: Path):
        self.manager, self.plugin_id, self.data_dir = manager, plugin_id, data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(f'friday.plugins.{plugin_id}')
        self.stop_event = threading.Event()
        self._resources = threading.RLock()
        self.settings = Settings(data_dir / 'settings.json', self._active)
        self.commands: list[Command] = []
        self.actions: dict[str, Callable] = {}
        self.routes: dict[str, Callable] = {}
        self.subscriptions = []
        self.threads: list[threading.Thread] = []

    def _active(self):
        if self.stop_event.is_set():
            raise RuntimeError(f'Plugin {self.plugin_id} has been unloaded.')

    def on_command(self, patterns, handler: Callable, help: str = '', examples=()):
        self._active()
        if isinstance(patterns, str):
            patterns = [patterns]
        if not patterns or not callable(handler):
            raise ValueError('Provide command patterns and a callable handler.')
        self.commands.append(Command([re.compile(p, re.I) for p in patterns], handler, help, list(examples)))

    def _call(self, callback, *args):
        self._active()
        try:
            return callback(*args)
        except Exception:
            self.log.exception('Plugin callback failed [plugin=%s]', self.plugin_id)
            if not self.stop_event.is_set():
                self.manager.failed(self.plugin_id)
            raise

    def subscribe(self, pattern: str, callback: Callable):
        def deliver(event):
            if not self.stop_event.is_set():
                try:
                    self._call(callback, event)
                except Exception:
                    pass  # _call logged the plugin ID and counted this failure.
        with self._resources:
            self._active()
            subscription = self.manager.bus.subscribe(pattern, deliver, plugin_id=self.plugin_id)
            self.subscriptions.append(subscription)
            return subscription

    def publish(self, topic: str, payload: dict):
        self._active()
        json.dumps(payload, allow_nan=False)
        return self.manager.bus.publish(topic, payload, plugin_id=self.plugin_id)

    def every(self, seconds: float, fn: Callable):
        if not isinstance(seconds, (float, int)) or not 0 < seconds < float('inf'):
            raise ValueError('Timer interval must be finite and positive.')
        def repeat():
            while not self.stop_event.wait(seconds):
                try:
                    self._call(fn)
                except Exception:
                    pass
        return self._thread(repeat)

    def run_background(self, fn: Callable):
        # Long-running jobs accept this Event and must stop when it is set.
        args = (self.stop_event,) if inspect.signature(fn).parameters else ()
        def run():
            if not self.stop_event.is_set():
                try:
                    self._call(fn, *args)
                except Exception:
                    pass
        return self._thread(run)

    def _thread(self, fn):
        with self._resources:
            self._active()
            thread = threading.Thread(target=fn, name=f'plugin:{self.plugin_id}', daemon=True)
            self.threads.append(thread)
            thread.start()
            return thread

    def notify(self, title: str, body: str, urgency: str = 'normal'):
        self._active()
        self.manager.notify(str(title), str(body), urgency)

    def speak(self, text: str):
        self._active()
        self.manager.speak(str(text))

    def set_mood(self, mood: str, duration_s: float = 5, priority: int = 0, message: str = '', *, sticky: bool = False):
        return self.publish('mood.set', dict(mood=mood, duration_s=duration_s, priority=priority, message=message, sticky=sticky))

    def show_card(self, title: str, body: str, actions=(), ttl_s: float = 30):
        return self.publish('ui.card', dict(title=title, body=body, actions=list(actions), ttl_s=ttl_s))

    def on_action(self, action_id: str, handler: Callable):
        self._active()
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', action_id) or not callable(handler):
            raise ValueError('Invalid action ID or handler.')
        self.actions[action_id] = handler

    def provide(self, name: str, obj):
        self._active()
        self.manager.provide(self.plugin_id, name, obj, owner=self)

    def get_service(self, name: str):
        self._active()
        return self.manager.get_service(name)

    def add_route(self, method: str, path: str, handler: Callable):
        self._active()
        path = path.strip('/')
        if method.upper() != 'GET' or not re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*', path) or not callable(handler):
            raise ValueError('v1 supports static GET paths containing letters, numbers, - and _.')
        self.routes[path] = handler

    def stop(self):
        with self._resources:
            self.stop_event.set()  # Fence late managed callbacks before removing registrations.
            subscriptions, threads = list(self.subscriptions), list(self.threads)
        for subscription in subscriptions:
            self.manager.bus.unsubscribe(subscription)
        deadline = time.monotonic() + .5
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(max(0, deadline - time.monotonic()))
        if any(t.is_alive() and t is not threading.current_thread() for t in self.threads):
            self.log.warning('Background job ignored cancellation [plugin=%s]; API is fenced', self.plugin_id)
