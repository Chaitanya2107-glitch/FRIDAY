"""Synthetic local outcome review plus native audio getters; no setters, owner sources or transport."""
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
from services.mind.outcome_learning import OutcomeLearning
from services.automation.system_control import SystemControl
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
    now = datetime(2026, 10, 21, 15)
    live = {'activity': 'coding', 'away': False, 'mode_name': 'normal', 'idle_band': 'present'}
    try:
        native_read = {'status': 'read', 'observed': SystemControl().audio_state(),
                       'meaning': 'Read-only current snapshot. No action performed or action success claimed.'}
    except Exception as error:
        native_read = {'status': 'unavailable', 'error': type(error).__name__}
    with tempfile.TemporaryDirectory(prefix='friday-outcome-probe-') as folder:
        store = Cognition(Path(folder) / 'brain.db')
        outcomes = OutcomeLearning(store)
        for _ in range(2):
            job = outcomes.begin('set_volume', {'volume': 30}, now)
            outcomes.finish(job, {'volume': 70}, True, now)
        known = outcomes.evidence()
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
            'seconds': round(time.monotonic() - started, 2), 'native_read_only_audio': native_read,
            'historical_outcomes': outcomes.context(), 'life_state': behavior,
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
