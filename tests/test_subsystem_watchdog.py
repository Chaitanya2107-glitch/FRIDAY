import asyncio
from datetime import datetime
import os

from core.errors import ProviderError
from providers import failover
from services.health import report
from services.health import watchdog as monitor
from services.health.watchdog import Watchdog


def test_watchdog_attempts_three_restarts_then_stops():
    now, delays, starts = [100.0], [], []
    service = Watchdog(clock=lambda: now[0], wall_clock=lambda: 1_800_000_000 + now[0])

    async def closed():
        starts.append(now[0])
        raise OSError('injected crash')

    async def sleep(seconds):
        delays.append(seconds)
        now[0] += seconds

    asyncio.run(service.supervise('bridge', closed, sleep=sleep))
    assert starts == [100, 102, 106, 114] and delays == [2, 4, 8]
    assert service.snapshot()['bridge']['restarts'] == 3
    assert service.snapshot()['bridge']['failures'] == 4
    assert service.snapshot()['bridge']['state'] == 'stopped'
    name, serial, text = service.pending()
    assert name == 'bridge' and '3 restarts in 10 minutes' in text
    service.delivered(name, serial)
    now[0] += 600
    assert service.snapshot()['bridge']['restarts'] == 0
    assert service.snapshot()['bridge']['state'] == 'stopped'
    assert service.pending() is None


def test_recovery_notice_follows_an_observed_heartbeat():
    now = [100.0]
    service = Watchdog(clock=lambda: now[0], wall_clock=lambda: now[0])
    service.heartbeat('voice')
    service.failure('voice', OSError())
    assert service.pending() is None
    now[0] += 40
    service.heartbeat('voice')
    assert service.pending()[2] == 'Voice was down for 40 seconds. Fixed.'
    assert service.snapshot()['voice']['last_heartbeat'] == 140
    service.failure('voice', OSError())
    assert service.pending() is None


def test_model_watchdog_leaves_off_and_idle_alone(monkeypatch):
    service = Watchdog()
    monkeypatch.setattr(monitor, 'watchdog', service)
    states = iter([
        dict(enabled=False, status='off'),
        dict(enabled=True, status='idle'),
        dict(enabled=True, status='unavailable', needs_restart=True),
        dict(enabled=True, status='unavailable', needs_restart=True),
        dict(enabled=True, status='ready', last_success=60),
    ])
    calls = []
    monkeypatch.setattr(failover, 'model_state', lambda: next(states), raising=False)

    async def recover():
        calls.append(service.snapshot()['model']['state'])
        if len(calls) == 1:
            raise ProviderError('backoff')

    async def wait(_):
        if service.snapshot()['model']['last_heartbeat'] == 60:
            raise asyncio.CancelledError()

    monkeypatch.setattr(failover, 'recover_local_model', recover, raising=False)

    async def test():
        try:
            await monitor.watch_model(sleep=wait)
        except asyncio.CancelledError:
            pass

    asyncio.run(test())
    assert calls == ['failed', 'failed']
    assert service.snapshot()['model']['failures'] == 1
    assert service.pending()[0] == 'model'


def test_daily_report_saves_owner_time_and_delivers_once(monkeypatch):
    from core.config import config

    monkeypatch.setattr(report, 'watchdog', Watchdog())
    monkeypatch.setattr(failover, 'model_state', lambda: {'enabled': False, 'status': 'off'}, raising=False)
    memory = config.MEMORY_DIR
    (memory / 'backups').mkdir(parents=True)
    backup = memory / 'backups' / 'snapshot.zip'
    backup.write_bytes(b'a' * 1024 * 1024)
    stamp = datetime(2026, 11, 18, 8, 0).timestamp()
    os.utime(backup, (stamp, stamp))
    notices = []

    def send(text, now):
        notices.append((text, now))
        return len(notices) > 1  # first attempt is held by the interruption budget

    monkeypatch.setattr(report, '_send', send)
    set_time = asyncio.run(report.handle('daily status report at 19:30'))
    assert set_time.success and report.report_time() == '19:30'
    assert not asyncio.run(report.handle('daily status report at 24:00')).success
    assert not asyncio.run(report.handle('status report', remote=True)).success
    before = datetime(2026, 11, 18, 19, 29)
    due = before.replace(minute=30)
    asyncio.run(report.tick(before))
    assert not notices
    asyncio.run(report.tick(due))
    asyncio.run(report.tick(due))
    asyncio.run(report.tick(due))
    assert len(notices) == 2
    text = asyncio.run(report.handle('status report')).message
    assert 'Model: off.' in text and 'Memory folder: 1.0 MiB.' in text
    assert 'Last backup: 2026-11-18 08:00.' in text
    assert asyncio.run(report.handle('turn off daily status report')).success
    assert report.report_time() == ''
