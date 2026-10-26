"""Synthetic local executive review; no owner sources, notifications or commands."""
import asyncio
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import config
from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind import cognition_context, executive, reasoning
from services.mind.cognition import Cognition
from services.mind.brain_memory import BrainMemory
from services.mind.reasoning_store import ReasoningStore
from services.mind.temporal_memory import TemporalMemory


async def main(*, initial='My synthetic calculus exam is tomorrow',
               correction='My synthetic calculus exam was postponed to Friday', followup=None):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    from providers import failover
    original = failover.complete_with_failover
    generations = []
    async def capture(*args, **kwargs):
        started = time.monotonic()
        result = await original(*args, **kwargs)
        generations.append({'provider': result.provider, 'model': result.model,
                            'seconds': round(time.monotonic() - started, 2), 'content': result.content})
        return result
    failover.complete_with_failover = capture
    # All source/attention adapters below are synthetic and process-local.
    cognition_context.live_state = lambda: {'activity': 'idle', 'away': False}
    executive.attention_state = lambda: {'activity': 'idle', 'away': False}
    with tempfile.TemporaryDirectory(prefix='friday-temporal-probe-') as folder:
        store = Cognition(Path(folder) / 'brain.db')
        reasoning.cognition = store
        episode, memory = BrainMemory(store), TemporalMemory(store)
        known = lambda: {**memory.evidence(), **episode.evidence()}
        source_store = ReasoningStore(store)
        source_store.evidence = known
        reasoning.reasoning_store = source_store
        control = executive.ExecutiveControl(store)
        control._known = known
        now = datetime(2026, 10, 20, 15)
        episode.remember(initial, source='synthetic-first', now=now)
        started = time.monotonic()
        first = await control.review(now)
        first_view = memory.snapshot(now)
        results = [{'phase': 'initial', 'result': first, 'situation': first_view}]
        if first_view['upcoming']:
            correction_at = now.replace(hour=16)
            episode.remember(correction, source='synthetic-correction', now=correction_at)
            second = await control.review(correction_at)
            results.append({'phase': 'correction', 'result': second, 'situation': memory.snapshot(correction_at),
                            'history': memory.history(first_view['upcoming'][0]['subject'])})
            if followup:
                followup_at = now.replace(hour=17)
                episode.remember(followup, source='synthetic-followup', now=followup_at)
                third = await control.review(followup_at)
                results.append({'phase': 'followup', 'result': third, 'situation': memory.snapshot(followup_at),
                                'history': memory.history(first_view['upcoming'][0]['subject'])})
        print(json.dumps({'local_only': True, 'notifications_sent': 0, 'commands_run': 0,
                          'seconds': round(time.monotonic() - started, 2), 'results': results,
                          'generations': generations}, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            async with asyncio.timeout(150):
                await main()
        finally:
            await runtime.close()
    asyncio.run(run())
