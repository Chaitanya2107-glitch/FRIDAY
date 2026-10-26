"""Bounded real local grouping/critique; synthetic sources, no delivery or commands."""
import asyncio
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import config
from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind import cognition_context, executive, reasoning, life_state
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition, redact
from services.mind.consolidation import Consolidation
from services.mind.reasoning_store import ReasoningStore
from services.mind.temporal_memory import TemporalMemory


async def main():
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    from providers import failover
    actual_complete = failover.complete_with_failover
    generations = []
    failed_requests = []
    if '--warm' in sys.argv:
        from providers.base_provider import Message
        started = time.monotonic()
        try:
            result = await actual_complete('ollama', [Message('user', 'Return {"ready":true}.')],
                'Local availability check; no tools or owner data.', 12, temperature=0,
                purpose='cognitive_review', attempt_timeout=30,
                response_schema={'type': 'object', 'properties': {'ready': {'type': 'boolean'}}, 'required': ['ready']})
            generations.append({'phase': 'warm_check', 'provider': result.provider, 'model': result.model,
                'seconds': round(time.monotonic() - started, 2), 'content': result.content})
        except Exception as error:
            generations.append({'phase': 'warm_check', 'error': type(error).__name__,
                'detail': redact(str(error))[:1200], 'seconds': round(time.monotonic() - started, 2)})
    async def capture(*args, **kwargs):
        started = time.monotonic()
        try:
            result = await actual_complete(*args, **kwargs)
        except Exception as error:
            generations.append({'error': type(error).__name__, 'detail': redact(str(error))[:1200],
                                'seconds': round(time.monotonic() - started, 2)})
            failed_requests.append((args, kwargs))
            raise
        generations.append({'provider': result.provider, 'model': result.model, 'purpose': kwargs.get('purpose'),
                            'seconds': round(time.monotonic() - started, 2), 'content': result.content})
        return result
    failover.complete_with_failover = capture
    live = {'activity': 'idle', 'away': False, 'idle_band': 'present'}
    cognition_context.live_state = lambda: dict(live)
    executive.attention_state = lambda: dict(live)
    with tempfile.TemporaryDirectory(prefix='friday-consolidation-probe-') as folder:
        store = Cognition(Path(folder) / 'synthetic.db')
        reasoning.cognition = store
        episodes, memory, temporal = BrainMemory(store), Consolidation(store), TemporalMemory(store)
        def known():
            sources = {**memory.source_evidence(), **episodes.evidence(), **temporal.evidence()}
            temporal.annotate_history(sources)
            return {**sources, **memory.evidence()}
        source_store = ReasoningStore(store)
        source_store.evidence = known
        reasoning.reasoning_store = source_store
        life_state.current = lambda now, **kwargs: life_state.LifeState(store).assess(
            now, kwargs['known'], kwargs['live'], {'on': True}, busy=False, mic=False)
        control = executive.ExecutiveControl(store)
        control._known = known
        now = datetime(2026, 10, 21, 15)
        if '--requirements' in sys.argv:
            episodes.remember('The synthetic project report uses figures from the laboratory notes.', now=now)
            episodes.remember('Two pressure measurements may be missing from the laboratory notes.',
                question='What information is missing from the laboratory notes for the synthetic report?', now=now + timedelta(minutes=1))
        else:
            episodes.remember('For my synthetic project report, the figures depend on the laboratory notes.', now=now)
            episodes.remember('Not yet; they might arrive Friday.',
                question='Has the laboratory sent the notes for your synthetic project report?', now=now + timedelta(minutes=1))
        started = time.monotonic()
        result = await control.review(now + timedelta(minutes=2))
        if '--diagnose' in sys.argv and failed_requests:
            # Observe a slow response outside the review. Never save it or relax production budgets.
            args, kwargs = failed_requests[0]
            diagnostic_started = time.monotonic()
            try:
                diagnostic = await actual_complete(*args, **{**kwargs, 'attempt_timeout': 35})
                generations.append({'phase': 'diagnostic_only', 'provider': diagnostic.provider, 'model': diagnostic.model,
                    'seconds': round(time.monotonic() - diagnostic_started, 2), 'content': diagnostic.content})
            except Exception as error:
                generations.append({'phase': 'diagnostic_only', 'error': type(error).__name__,
                    'detail': redact(str(error))[:1200], 'seconds': round(time.monotonic() - diagnostic_started, 2)})
        before = memory.evidence()
        # Simulate routine episode retention without 500 unrelated observer events.
        with episodes._db() as db:
            db.execute('DELETE FROM owner_episodes')
        restored = Consolidation(Cognition(store.path))
        print(json.dumps({'local_only': True, 'commands_run': 0, 'notifications_sent': 0,
            'configured': {'cognition': config.COGNITION_ENABLED, 'review': config.COGNITIVE_REVIEW_ENABLED},
            'result': result, 'seconds': round(time.monotonic() - started, 2),
            'threads_before_retention': before, 'threads_after_retention_restart': restored.evidence(),
            'status': restored.status(), 'generations': generations}, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            async with asyncio.timeout(100):
                await main()
        finally:
            await runtime.close()
    asyncio.run(run())
