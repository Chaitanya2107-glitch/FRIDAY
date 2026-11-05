"""Meaningful events wake local executive attention; idle timers reconcile missed work."""
import asyncio
from datetime import datetime

from core.config import config
from core.logger import logger

_loop = None
_wake = None
_task = None
_last_blocks = ['not_checked']
MEANINGFUL = {'request', 'feature_request', 'action', 'action_outcome', 'owner_episode', 'reaction', 'notification', 'observation'}


def running():
    return _task is not None and not _task.done() and _loop is not None and not _loop.is_closed()


def signal(kind, status='completed'):
    if kind not in MEANINGFUL or status == 'started' or _loop is None or _wake is None:
        return
    try:
        _loop.call_soon_threadsafe(_wake.set)
    except RuntimeError:
        pass  # process/event loop is stopping; durable sources remain available on restart


def available():
    global _last_blocks
    _last_blocks = review_blocks()
    return not _last_blocks


def review_blocks():
    from services.activity.log import idle_seconds
    from services.mind.cognition import cognition
    from services.mind.cognition_context import live_state
    from services.proactive.watcher import is_busy
    blocks = [reason for enabled, reason in (
        (config.COGNITION_ENABLED, 'cognition_disabled'), (config.REASONING_ENABLED, 'reasoning_disabled'),
        (config.COGNITIVE_REVIEW_ENABLED, 'review_disabled')) if not enabled]
    if blocks:
        return blocks
    if is_busy():
        blocks.append('busy')
    if idle_seconds() < 5:
        blocks.append('typing')
    if any(row['kind'] in {'request', 'feature_request'} for row in cognition.active()):
        blocks.append('owner_request_active')
    live = live_state()
    from services.mind.life_state import current
    if live.get('state') == 'partly unavailable':
        return list(dict.fromkeys([*blocks, 'attention_unavailable']))
    for field, reason in (('speaking', 'speaking'), ('listening', 'listening'), ('waiting_for_answer', 'pending_reply')):
        if live.get(field):
            blocks.append(reason)
    behavior = current(live=live)
    blocks.extend(behavior.get('review_blocks', []))
    if not behavior.get('can_review', False) and not blocks:
        blocks.append('state_unavailable')
    if live.get('executive', {}).get('enabled') is False:
        blocks.append('executive_disabled')
    return list(dict.fromkeys(blocks))


def status():
    from services.mind.cognitive_health import health
    snapshot = health.latest('attention')
    disabled = [reason for value, reason in ((config.COGNITION_ENABLED, 'cognition_disabled'),
                (config.REASONING_ENABLED, 'reasoning_disabled'),
                (config.COGNITIVE_REVIEW_ENABLED, 'review_disabled')) if not value]
    return {'running': running(), 'disabled_by': disabled, 'last_check': snapshot, 'recent': health.history(8),
            'meaning': 'Local runtime/gate receipts; silence and deferral are valid states, not accepted reasoning.'}


def describe():
    data = status()
    latest = data['last_check']
    if data['disabled_by']:
        return 'Brain health: background review disabled by ' + ', '.join(data['disabled_by']) + '.'
    if latest is None:
        return 'Brain health: no attention check recorded in this build; runtime ' + ('running.' if data['running'] else 'not running.')
    reasons = (latest.get('blocks') or [latest['reason']])
    from services.mind.life_state import REASONS as life_reasons
    labels = {**life_reasons, 'minimum_gap': 'waiting for the existing five-minute review interval',
              'hourly_limit': 'the hourly review budget is used', 'retry_backoff': 'waiting before retrying a failed review',
              'startup_failed': 'the attention loop failed during startup', 'nothing_pending': 'no new review is pending',
              'check_failed': 'the last attention check was unavailable', 'executive_disabled': 'executive review is switched off'}
    return (f"Brain health: attention task {'running' if data['running'] else 'not running'}; "
            f"last check {latest['state']} ({'; '.join(labels.get(reason, reason.replace('_', ' ')) for reason in reasons)}).")


async def run():
    global _loop, _wake, _task
    from services.mind.executive import executive
    from services.mind import evening
    from services.mind.cognitive_health import health, REASONS
    current_task = asyncio.current_task()
    if running():
        return  # Only the existing lifecycle owner runs this loop.
    _task = current_task
    _loop, _wake = asyncio.get_running_loop(), asyncio.Event()
    terminal = ('stopped', 'stopped')
    try:
        await asyncio.to_thread(health.record, 'attention', 'starting', 'starting')
        await asyncio.to_thread(evening.stop)  # Retire legacy queues inside the protected lifecycle.
        _wake.set()
        while True:
            try:
                await asyncio.wait_for(_wake.wait(), timeout=60)
            except TimeoutError:
                pass
            _wake.clear()
            try:
                if await asyncio.to_thread(available):
                    await asyncio.to_thread(health.record, 'attention', 'reviewing', 'ready')
                    result = await executive.review(datetime.now(), busy=False)
                    result_state = result.get('status', 'unavailable')
                    reason = result.get('reason', result_state)
                    await asyncio.to_thread(health.record, 'attention',
                                          'completed' if result_state == 'completed' else 'waiting',
                                          reason if reason in REASONS else 'unavailable')
                else:
                    blocks = _last_blocks or ['attention_unavailable']
                    await asyncio.to_thread(health.record, 'attention', 'waiting', blocks[0], {'blocks': blocks})
            except Exception as error:
                await asyncio.to_thread(health.record, 'attention', 'unavailable', 'check_failed')
                logger.debug('Event-driven attention deferred (%s)', type(error).__name__)
    except asyncio.CancelledError:
        terminal = ('stopped', 'cancelled')
        raise
    except Exception as error:
        terminal = ('failed', 'startup_failed')
        logger.warning('Cognitive attention startup failed (%s)', type(error).__name__)
    finally:
        if _task is current_task:
            _loop, _wake, _task = None, None, None
        await asyncio.to_thread(health.record, 'attention', *terminal)
