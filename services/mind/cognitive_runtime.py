"""Meaningful events wake local executive attention; idle timers reconcile missed work."""
import asyncio
from datetime import datetime

from core.config import config
from core.logger import logger

_loop = None
_wake = None
MEANINGFUL = {'request', 'feature_request', 'action', 'action_outcome', 'owner_episode', 'reaction', 'notification', 'observation'}


def running():
    return _loop is not None and not _loop.is_closed()


def signal(kind, status='completed'):
    if kind not in MEANINGFUL or status == 'started' or _loop is None or _wake is None:
        return
    try:
        _loop.call_soon_threadsafe(_wake.set)
    except RuntimeError:
        pass  # process/event loop is stopping; durable sources remain available on restart


def available():
    from services.activity.log import idle_seconds
    from services.mind.cognition import cognition
    from services.mind.cognition_context import live_state
    from services.proactive.watcher import is_busy
    if not (config.COGNITION_ENABLED and config.REASONING_ENABLED and config.COGNITIVE_REVIEW_ENABLED):
        return False
    if is_busy() or idle_seconds() < 5:
        return False
    if any(row['kind'] in {'request', 'feature_request'} for row in cognition.active()):
        return False
    live = live_state()
    from services.mind.life_state import current
    return (live.get('state') != 'partly unavailable' and not any(live.get(k) for k in
                ('speaking', 'listening', 'waiting_for_answer')) and current(live=live).get('can_review', False))


async def run():
    global _loop, _wake
    from services.mind.executive import executive
    from services.mind import evening
    _loop, _wake = asyncio.get_running_loop(), asyncio.Event()
    evening.stop()  # retire pre-upgrade interview queues without delivering them
    _wake.set()
    try:
        while True:
            try:
                await asyncio.wait_for(_wake.wait(), timeout=60)
            except TimeoutError:
                pass
            _wake.clear()
            try:
                if available():
                    await executive.review(datetime.now(), busy=False)
            except Exception as error:
                logger.debug('Event-driven attention deferred (%s)', type(error).__name__)
    finally:
        _loop, _wake = None, None
