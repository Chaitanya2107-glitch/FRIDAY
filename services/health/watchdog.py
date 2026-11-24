"""Health signals and bounded restart ownership for FRIDAY's local subsystems."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
import threading
import time

from core.errors import ProviderError
from core.logger import logger

RESTART_LIMIT = 3
RESTART_WINDOW = 10 * 60
CHECK_SECONDS = 5
LABELS = {'voice': 'Voice', 'bridge': 'Desktop bridge', 'phone': 'Phone monitor',
          'plugins': 'Plugin host', 'model': 'Model'}


@dataclass
class Health:
    state: str = 'starting'
    heartbeat: float | None = None
    last_failure: float | None = None
    error: str | None = None
    failures: int = 0
    down_since: float | None = None
    restarts: deque = field(default_factory=deque)


class Watchdog:
    def __init__(self, *, clock=time.monotonic, wall_clock=time.time):
        self.clock, self.wall_clock = clock, wall_clock
        self._lock = threading.RLock()
        self._health = {name: Health() for name in LABELS}
        self._pending = {}
        self._serial = 0
        self._running = set()
        self._handset_heartbeat = None

    def _notice(self, name, text):
        self._serial += 1
        self._pending[name] = self._serial, text

    def heartbeat(self, name, at=None):
        with self._lock:
            row = self._health[name]
            row.state = 'ready'
            row.heartbeat = self.wall_clock() if at is None else at
            if row.down_since is not None:
                seconds = max(1, round(self.clock() - row.down_since))
                unit = 'second' if seconds == 1 else 'seconds'
                self._notice(name, f'{LABELS[name]} was down for {seconds} {unit}. Fixed.')
                row.down_since = None

    def set_state(self, name, state):
        with self._lock:
            row = self._health[name]
            row.state = state
            if state in {'idle', 'off'}:
                row.down_since = None
                if state == 'off':
                    self._pending.pop(name, None)

    def handset_contact(self, at):
        with self._lock:
            if self._handset_heartbeat is None or at > self._handset_heartbeat:
                self._handset_heartbeat = at

    def failure(self, name, error, at=None):
        with self._lock:
            row = self._health[name]
            if at is not None and row.last_failure is not None and at <= row.last_failure:
                return
            if row.state == 'ready':
                self._pending.pop(name, None)
            if row.state != 'stopped':
                row.state = 'failed'
            row.error = type(error).__name__
            row.last_failure = self.wall_clock() if at is None else at
            row.failures += 1
            if row.down_since is None:
                row.down_since = self.clock()

    def failure_if_running(self, name, error):
        with self._lock:
            if self._health[name].down_since is None:
                self.failure(name, error)

    def exhausted(self, name):
        with self._lock:
            row = self._health[name]
            if row.state != 'stopped':
                row.state = 'stopped'
                self._notice(name, f'{LABELS[name]} is still down after {RESTART_LIMIT} restarts in 10 minutes. I stopped retrying.')

    def _restart_times(self, row):
        now = self.clock()
        while row.restarts and now - row.restarts[0] >= RESTART_WINDOW:
            row.restarts.popleft()
        return row.restarts

    async def supervise(self, name, worker, *, sleep=asyncio.sleep):
        """Restart a crashed owned worker. A stopped worker needs an owner restart."""
        with self._lock:
            if name in self._running:
                return
            self._running.add(name)
            self.set_state(name, 'starting')
        try:
            while True:
                try:
                    await worker()
                    raise RuntimeError('Worker exited unexpectedly')
                except asyncio.CancelledError:
                    self.set_state(name, 'stopped')
                    raise
                except Exception as error:
                    self.failure(name, error)
                    logger.warning('%s worker failed (%s)', LABELS[name], type(error).__name__)
                with self._lock:
                    restarts = len(self._restart_times(self._health[name]))
                    if restarts >= RESTART_LIMIT:
                        self.exhausted(name)
                        return
                await sleep(2 ** (restarts + 1))
                with self._lock:
                    self._restart_times(self._health[name]).append(self.clock())
                    self._health[name].state = 'recovering'
        finally:
            with self._lock:
                self._running.discard(name)

    def snapshot(self):
        with self._lock:
            return {
                name: {'state': row.state, 'last_heartbeat': row.heartbeat,
                       'last_failure': row.last_failure, 'last_error': row.error,
                       'failures': row.failures, 'restarts': len(self._restart_times(row)),
                       **({'handset_heartbeat': self._handset_heartbeat} if name == 'phone' else {})}
                for name, row in self._health.items()
            }

    def pending(self):
        with self._lock:
            item = min(self._pending.items(), key=lambda pair: pair[1][0], default=None)
            return (item[0], *item[1]) if item else None

    def delivered(self, name, serial):
        with self._lock:
            if self._pending.get(name, (None,))[0] == serial:
                del self._pending[name]


watchdog = Watchdog()


async def watch_model(*, sleep=asyncio.sleep):
    """Observe the gateway and recover only a server known to belong to FRIDAY."""
    from providers.failover import model_state, recover_local_model

    owned_crash = False
    while True:
        model = model_state()
        state = model['status']
        needs_restart = model['enabled'] and model.get('needs_restart', False)
        if not model['enabled']:
            watchdog.set_state('model', 'off')
        else:
            if model.get('last_failure') is not None:
                watchdog.failure('model', ProviderError('Local model unavailable'), at=model['last_failure'])
            if needs_restart and not owned_crash:
                watchdog.failure_if_running('model', OSError('Owned model exited'))
            if needs_restart and model.get('restart_limit'):
                watchdog.exhausted('model')
            elif needs_restart:
                try:
                    await recover_local_model()
                except (ProviderError, OSError, TimeoutError):
                    pass  # Gateway owns backoff and the retry limit.
            elif state == 'ready':
                watchdog.heartbeat('model', model.get('last_success'))
            else:
                watchdog.set_state('model', state)
        owned_crash = needs_restart
        await sleep(CHECK_SECONDS)
