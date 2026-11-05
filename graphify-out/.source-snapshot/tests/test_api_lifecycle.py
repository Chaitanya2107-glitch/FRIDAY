"""Shutdown must release the other services even if browser cleanup fails."""
import asyncio

import pytest

from interfaces.api import app as api


@pytest.mark.parametrize('failure', [RuntimeError, asyncio.CancelledError])
def test_failed_browser_cleanup_still_cancels_workers_and_closes_ollama(monkeypatch, failure):
    from services.browser.service import automation
    from providers.ollama.runtime import runtime
    from services.friday_island_server import server
    from services.mind import cognitive_runtime, development
    from services.screen_watch import service as screen_watch
    started, cancelled, closed = set(), set(), []

    async def worker(name):
        started.add(name)
        try:
            await asyncio.Future()
        finally:
            cancelled.add(name)

    async def fail_close():
        raise failure('Synthetic browser shutdown failure')

    async def close_runtime():
        closed.append(True)

    for name in ['run_scheduler', 'watch_clipboard', 'preload_speech_model', 'run_indexer',
                 'watch_activity', 'run_proactive', 'watch_network', 'run_bot', 'run_watches']:
        monkeypatch.setattr(api, name, lambda *args, name=name: worker(name))
    monkeypatch.setattr(api.tts, 'prewarm', lambda: worker('tts'))
    monkeypatch.setattr(api.app_finder, 'wake_everything', lambda: None)
    monkeypatch.setattr(server, 'run_integrated_bridge', lambda: worker('bridge'))
    monkeypatch.setattr(cognitive_runtime, 'run', lambda: worker('cognition'))
    monkeypatch.setattr(screen_watch.watch, 'run', lambda: worker('screen'))
    monkeypatch.setattr(development.development, 'run', lambda: worker('development'))
    monkeypatch.setattr(development.development, 'scan', lambda: None)
    monkeypatch.setattr(automation, 'close', fail_close)
    monkeypatch.setattr(runtime, 'close', close_runtime)

    async def run():
        with pytest.raises(failure, match='Synthetic browser shutdown failure'):
            async with api.lifespan(api.create_app()):
                await asyncio.sleep(.01)
        assert len(started) == 14
        assert cancelled == started
        assert closed == [True]

    asyncio.run(run())
