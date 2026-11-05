"""Offline, bounded event delivery with an independent worker per subscriber."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from fnmatch import fnmatchcase
import logging
import json
import queue
import re
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


def validate_topic(topic: str, *, pattern: bool = False) -> None:
    part = r"(?:[a-zA-Z0-9_-]+|\*)" if pattern else r"[a-zA-Z0-9_-]+"
    if not isinstance(topic, str) or len(topic) > 200 or not re.fullmatch(part + r"(?:\." + part + r")*", topic):
        raise ValueError('Use a dotted event topic; wildcard segments may be *.')


class Subscription:
    def __init__(self, pattern: str, callback: Callable[[dict], None], plugin_id: str):
        self.pattern, self.callback, self.plugin_id = pattern, callback, plugin_id
        self.stopped = threading.Event()
        self.dropped = 0
        self.queue: queue.Queue = queue.Queue(maxsize=200)
        self.thread = threading.Thread(target=self._run, name=f'events:{plugin_id}', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                event = self.queue.get(timeout=.1)
            except queue.Empty:
                continue
            if self.stopped.is_set():
                break
            try:
                if self.dropped:
                    logger.warning('Slow event subscriber dropped queued events [plugin=%s]', self.plugin_id)
                    self.dropped = 0
                self.callback(deepcopy(event))
            except Exception:
                logger.exception('Event subscriber failed [plugin=%s]', self.plugin_id)

    def deliver(self, event: dict):
        if self.stopped.is_set():
            return
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(event)
            except queue.Full:
                pass
            self.dropped += 1

    def close(self, timeout: float = .25):
        self.stopped.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout)


class EventBus:
    def __init__(self):
        self._lock = threading.RLock()
        self._events: deque = deque(maxlen=200)
        self._subscriptions: set[Subscription] = set()
        self._sequence = 0

    def publish(self, topic: str, payload: dict, *, plugin_id: str = 'friday') -> dict:
        validate_topic(topic)
        if not isinstance(payload, dict):
            raise ValueError('Event payload must be a dictionary.')
        json.dumps(payload, allow_nan=False)
        with self._lock:
            self._sequence += 1
            event = dict(id=self._sequence, topic=topic, payload=deepcopy(payload),
                         plugin_id=plugin_id, at=time.time())
            self._events.append(event)
            for subscription in self._subscriptions:
                if fnmatchcase(topic, subscription.pattern):
                    subscription.deliver(event)
            return deepcopy(event)

    def subscribe(self, pattern: str, callback: Callable[[dict], None], *, plugin_id: str = 'friday') -> Subscription:
        validate_topic(pattern, pattern=True)
        if not callable(callback):
            raise ValueError('Subscriber must be callable.')
        with self._lock:
            subscription = Subscription(pattern, callback, plugin_id)
            self._subscriptions.add(subscription)
            return subscription

    def unsubscribe(self, subscription: Subscription):
        with self._lock:
            self._subscriptions.discard(subscription)
        subscription.close()

    def recent(self, pattern: str = '*') -> list[dict]:
        validate_topic(pattern, pattern=True)
        with self._lock:
            return deepcopy([event for event in self._events if fnmatchcase(event['topic'], pattern)])

    def close(self):
        with self._lock:
            subscriptions = list(self._subscriptions)
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()


event_bus = EventBus()
publish = event_bus.publish
subscribe = event_bus.subscribe
