"""Synthetic local inquiry only: no owner data, OS delivery, commands or cloud inference."""
import asyncio
import copy
import json
import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import logger
from core.config import config
from providers.ollama.runtime import runtime
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.cognition import redact
from services.mind.inquiry import Inquiry


async def main():
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    import providers.failover as failover
    actual_complete = failover.complete_with_failover
    generations = []
    async def capture(*args, **kwargs):
        try:
            result = await actual_complete(*args, **kwargs)
        except Exception as error:
            generations.append({'error': type(error).__name__, 'detail': redact(str(error))[:1200]})
            raise
        generations.append({'provider': result.provider, 'model': result.model, 'content': result.content})
        return result
    failover.complete_with_failover = capture
    with tempfile.TemporaryDirectory(prefix='friday-inquiry-probe-') as folder:
        store = Cognition(Path(folder) / 'synthetic.db')
        control = Inquiry(store)
        now = datetime.now()
        data = {'day': now.date().isoformat(), 'now': now.isoformat(),
                'evidence': {'task:1': {'kind': 'task', 'title': 'Finish a synthetic project report',
                            'status': 'blocked', 'blocker': 'Waiting for review notes', 'source': 'owner_report'}},
                'present': {'busy': False, 'idle': 15, 'speaking': False, 'listening': False,
                            'pending': False, 'mic_in_use': False, 'commitment_soon': False},
                'preferences': {'on': True, 'paused_until': 0}, 'past': [], 'future': {}, 'history': []}
        control.snapshot = lambda current: copy.deepcopy(data)
        started = time.monotonic()
        first = await control.propose(now, explicit=True, intention='Ask one useful question about this report')
        results = [{'phase': 'before_answer', 'question': first['say'] if first else None,
                    'decision': control.status(now)['last_decision'], 'seconds': round(time.monotonic() - started, 2)}]
        if first:
            answer = 'My teammate will send the review notes tomorrow afternoon.'
            BrainMemory(store).remember(answer, question=first['say'], source='synthetic-answer', channel='chat', now=now)
            control.mark(first['inquiry_id'], 'answered')
            data['evidence'].update(BrainMemory(store).evidence())
            data['past'] = ['owner_episode:1']
            data['history'] = [{'question': first['say'], 'answer': answer, 'state': 'answered'}]
            started = time.monotonic()
            following = await control.propose(now, explicit=True, intention='Only ask if a different useful gap remains')
            results.append({'phase': 'after_answer', 'question': following['say'] if following else None,
                            'decision': control.status(now)['last_decision'], 'seconds': round(time.monotonic() - started, 2)})
        print(json.dumps({'local_only': True, 'reasoning_enabled': config.REASONING_ENABLED,
                          'cognition_enabled': config.COGNITION_ENABLED, 'notifications_sent': 0, 'commands_run': 0,
                          'results': results, 'synthetic_generations': generations}, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            async with asyncio.timeout(105):
                await main()
        finally:
            await runtime.close()
    asyncio.run(run())
