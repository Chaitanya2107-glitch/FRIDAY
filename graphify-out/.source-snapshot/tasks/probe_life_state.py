"""Synthetic local life-state review: no owner sources, transport or commands."""
import asyncio
import copy
import json
import logging
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind import cognition_context, executive, life_state, reasoning
from services.mind.cognition import Cognition
from services.mind.inquiry import Inquiry
from services.mind.life_state import LifeState
from services.mind.reasoning_store import ReasoningStore


async def main():
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    from providers import failover
    actual_complete = failover.complete_with_failover
    generations = []
    async def capture(*args, **kwargs):
        started = time.monotonic()
        try:
            result = await actual_complete(*args, **kwargs)
        except Exception as error:
            generations.append({'error': type(error).__name__})
            raise
        generations.append({'provider': result.provider, 'model': result.model,
                            'seconds': round(time.monotonic() - started, 2), 'content': result.content})
        return result
    failover.complete_with_failover = capture
    now = datetime(2026, 10, 20, 15)
    live = {'activity': 'coding', 'away': False, 'mode_name': 'normal', 'idle_band': 'present'}
    known = {'task:1': {'kind': 'task', 'id': 1, 'title': 'Finish a synthetic project report',
                      'status': 'active', 'blocker': 'Waiting for teammate review notes'}}
    with tempfile.TemporaryDirectory(prefix='friday-life-state-probe-') as folder:
        store = Cognition(Path(folder) / 'brain.db')
        local = LifeState(store)
        behavior = local.assess(now, known, live, {'on': False})
        life_state.current = lambda *a, **kw: copy.deepcopy(behavior)
        cognition_context.live_state = lambda: dict(live)
        executive.attention_state = lambda: {**live, 'life_state': copy.deepcopy(behavior)}
        reasoning.cognition = store
        evidence = ReasoningStore(store)
        evidence.evidence = lambda: copy.deepcopy(known)
        reasoning.reasoning_store = evidence
        control = executive.ExecutiveControl(store)
        control._known = lambda: copy.deepcopy(known)
        started = time.monotonic()
        reviewed = await control.review(now)
        inquiry = Inquiry(store)
        inquiry.snapshot = lambda when: {'evidence': copy.deepcopy(known), 'present': {'pending': False, 'idle': 10},
                                        'preferences': {'on': False}, 'history': [], 'life_state': copy.deepcopy(behavior)}
        before = len(generations)
        question = await inquiry.propose(now)
        print(json.dumps({'local_only': True, 'notifications_sent': 0, 'commands_run': 0,
            'seconds': round(time.monotonic() - started, 2), 'life_state': behavior,
            'quiet_executive_review': reviewed, 'saved_conclusions': evidence.conclusions(now, known),
            'automatic_question': question, 'inquiry_model_calls_while_quiet': len(generations) - before,
            'synthetic_generations': generations}, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            async with asyncio.timeout(70):
                await main()
        finally:
            await runtime.close()
    asyncio.run(run())
