"""Resolve plugin mood requests once in the backend; all displays see the same state."""
import logging
import threading
import time

logger = logging.getLogger(__name__)


class MoodController:
    def __init__(self, bus):
        self.bus, self.lock = bus, threading.RLock()
        self.current = {'mood': 'idle', 'priority': 0, 'expires_at': 0, 'message': '', 'plugin_id': 'friday'}
        self.timer = None
        self.closed = False
        self.subscription = bus.subscribe('mood.set', self._receive, plugin_id='friday-mood')

    def _receive(self, event):
        data = event['payload']
        duration, priority, mood = data.get('duration_s', 5), data.get('priority', 0), data.get('mood')
        if (not isinstance(mood, str) or not 1 <= len(mood) <= 32 or type(priority) is not int
                or type(duration) not in {int, float} or not 0 < duration <= 3600):
            logger.warning('Invalid mood request [plugin=%s]', event['plugin_id'])
            return
        with self.lock:
            if self.closed or (self.current['expires_at'] > time.time() and priority < self.current['priority']):
                return
            if self.timer:
                self.timer.cancel()
            previous = self.current['mood']
            self.current = dict(mood=mood, priority=priority, expires_at=time.time() + duration,
                                message=str(data.get('message', ''))[:4000], plugin_id=event['plugin_id'])
            self.bus.publish('mood.changed', dict(self.current, previous=previous))
            self.timer = threading.Timer(duration, self._expire)
            self.timer.daemon = True
            self.timer.start()

    def _expire(self):
        with self.lock:
            if self.closed or self.current['expires_at'] > time.time():
                return
            previous = self.current['mood']
            self.current = dict(mood='idle', priority=0, expires_at=0, message='', plugin_id='friday')
            self.bus.publish('mood.changed', dict(self.current, previous=previous))

    def close(self):
        with self.lock:
            self.closed = True
            if self.timer:
                self.timer.cancel()
        self.bus.unsubscribe(self.subscription)
