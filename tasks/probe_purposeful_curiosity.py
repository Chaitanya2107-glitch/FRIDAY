"""Synthetic purposeful-curiosity probe: installed local model, isolated sources, no delivery or commands."""
import asyncio
import copy
import json
import logging
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import logger
from core.config import config
from providers.ollama.runtime import runtime
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.cognition import redact
from services.mind.inquiry import Inquiry
from services.mind import inquiry as inquiry_module, notifications


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
        generations.append({'provider': result.provider, 'model': result.model, 'purpose': kwargs.get('purpose'), 'content': result.content})
        return result
    failover.complete_with_failover = capture
    with tempfile.TemporaryDirectory(prefix='friday-purposeful-curiosity-probe-') as folder:
        store = Cognition(Path(folder) / 'synthetic.db')
        control = Inquiry(store)
        inquiry_module.inquiry = control
        notifications.cognition = store
        now = datetime.now()
        if '--replay-first' in sys.argv:
            baseline = json.loads((Path(__file__).parent / 'curiosity-final-live-probe.json').read_text(encoding='utf-16'))
            now = datetime.fromtimestamp(baseline['results'][0]['decision']['created'])
        if '--neutral-review' in sys.argv:
            notifications.PROMPT = notifications.PROMPT.replace(
                'Return ONLY JSON {"decisions":[{"id":"0","send":false,"reason":"Short evidence-based rationale"}]}.',
                'Return ONLY JSON with a decisions array. Each entry needs the supplied id, a send boolean, and a reason. '
                'Choose send true for a useful suitable notice, or false when it should be withheld; the reason must support that choice.')
        data = {'day': now.date().isoformat(), 'now': now.isoformat(),
                'evidence': {'task:1': {'kind': 'task', 'title': 'Finish a synthetic project report',
                            'status': 'blocked', 'blocker': 'Waiting for review notes', 'source': 'owner_report'}},
                'present': {'busy': False, 'idle': 15, 'speaking': False, 'listening': False,
                            'pending': False, 'mic_in_use': False, 'commitment_soon': False},
                'preferences': {'on': True, 'paused_until': 0}, 'past': [], 'future': {}, 'history': []}
        if '--focused' in sys.argv:
            data['evidence']['task:1'].update(
                title="Prepare the project report for today's 18:00 handoff",
                blocker='Waiting for review notes, with no expected arrival time recorded',
                steps=['If notes arrive before 17:00, incorporate the edits before handoff.',
                       'If they arrive later, prepare the draft for handoff and flag the pending review.'])
            data['evidence']['focus:local'] = {'kind': 'focus', 'targets': {'task': 1}, 'source': 'owner_selection'}
        control.snapshot = lambda current: copy.deepcopy(data)
        async def review_context(current):
            return {'live': {'waiting_for_answer': False, 'activity': 'coding'}, 'busy': False,
                    'question_preferences': {'on': True}, 'life_state': {'can_initiate': True},
                    'workspace': {'tasks': [data['evidence']['task:1']]},
                    'reasoning': {'facts': [], 'conclusions': []}}
        notifications._context = review_context
        started = time.monotonic()
        first = await control.propose(now)
        results = [{'phase': 'before_answer', 'question': first['say'] if first else None,
                    'decision': control.status(now)['last_decision'], 'seconds': round(time.monotonic() - started, 2)}]
        if first:
            answer = 'My teammate will send the review notes tomorrow afternoon.'
            BrainMemory(store).remember(answer, question=first['say'], source='synthetic-answer', channel='chat', now=now)
            control.mark(first['inquiry_id'], 'answered')
            data['evidence'].update(BrainMemory(store).evidence())
            data['past'] = ['owner_episode:1']
            data['history'] = [{'question': first['say'], 'answer': answer, 'state': 'answered',
                                'gap': first['purpose']['gap'],
                                'gap_version': control.status(now)['last_decision']['gap_version']}]
            started = time.monotonic()
            before = len(generations)
            following = await control.propose(now + timedelta(hours=1))
            results.append({'phase': 'after_answer_automatic', 'model_calls': len(generations) - before,
                            'question': following['say'] if following else None,
                            'decision': control.status(now)['last_decision'], 'seconds': round(time.monotonic() - started, 2)})
            data['evidence']['task:1']['blocker'] = 'Review notes arrived; now waiting for manager approval, with no ETA.'
            started = time.monotonic()
            changed = await control.propose(now + timedelta(hours=2))
            results.append({'phase': 'changed_blocker_automatic', 'question': changed['say'] if changed else None,
                            'decision': control.status(now)['last_decision'], 'seconds': round(time.monotonic() - started, 2)})
        print(json.dumps({'local_only': True, 'reasoning_enabled': config.REASONING_ENABLED,
                          'cognition_enabled': config.COGNITION_ENABLED, 'notifications_sent': 0, 'commands_run': 0,
                          'results': results, 'synthetic_generations': generations,
                          'private_review_events': [dict(event) for event in store.recent(20) if event['kind'] == 'notification_decision']}, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            async with asyncio.timeout(110):
                await main()
        finally:
            await runtime.close()
    asyncio.run(run())
