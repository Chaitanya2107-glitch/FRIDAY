"""One leased desktop controller; commands are claimed once and never replayed."""
from collections import deque
import secrets
import threading
import time

ACTIONS = frozenset({'listen', 'wake', 'conversation', 'speech', 'speak_typed',
                     'body', 'controls', 'customization', 'college', 'productivity',
                     'start', 'stop', 'restart', 'quit', 'typed', 'typed_done', 'provider'})


class DesktopLink:
    def __init__(self):
        self.lock = threading.Lock()
        self.owner = ''
        self.seen = 0.0
        self.state = {}
        self.pending = deque(maxlen=24)
        self.claimed = {}
        self.completed = deque(maxlen=64)

    def snapshot(self):
        with self.lock:
            online = time.monotonic() - self.seen < 5
            return {**self.state, 'connected': online}

    def enqueue(self, action, value=''):
        if action not in ACTIONS:
            raise ValueError('Unknown desktop action')
        with self.lock:
            if time.monotonic() - self.seen >= 5:
                raise ValueError('FRIDAY desktop controls are unavailable. Launch FRIDAY again.')
            if len(self.pending) >= self.pending.maxlen:
                raise ValueError('Desktop controls are busy. Try again shortly.')
            command = {'id': secrets.token_hex(12), 'action': action,
                       'value': str(value)[:4000], 'at': time.monotonic(),
                       'expires': time.monotonic() + (2 if action == 'typed' else 5)}
            self.pending.append(command)
            return command['id']

    def acknowledged(self, command_id):
        with self.lock:
            return command_id in self.completed

    def cancel_pending(self, command_id):
        with self.lock:
            self.pending = deque((row for row in self.pending if row['id'] != command_id), maxlen=24)

    def exchange(self, owner, state, completed=()):
        with self.lock:
            now = time.monotonic()
            if self.owner and owner != self.owner and now - self.seen < 5:
                raise ValueError('Another desktop controller owns this session')
            if owner != self.owner:
                self.pending.clear()
                self.claimed.clear()
                self.completed.clear()
            self.claimed = {key: at for key, at in self.claimed.items() if now - at < 10}
            for command_id in completed:
                if command_id in self.claimed:
                    self.claimed.pop(command_id)
                    self.completed.append(command_id)
            self.owner, self.seen, self.state = owner, now, dict(state)
            commands = [row for row in self.pending if now < row['expires']]
            self.claimed.update({row['id']: now for row in commands})
            self.pending.clear()  # Lost HTTP replies must never replay microphone/OS actions.
            return commands


desktop = DesktopLink()
