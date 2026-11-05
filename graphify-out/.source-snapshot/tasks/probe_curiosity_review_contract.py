"""Frozen synthetic candidate: compare old/neutral contracts and an answered negative control."""
import asyncio
import copy
import json
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind import notifications
from services.mind.cognition import Cognition

NEUTRAL = ('Return ONLY JSON with a decisions array. Each entry needs the supplied id, a send boolean, and a reason. '
           'Choose send true for a useful suitable notice, or false when it should be withheld; the reason must support that choice.')
LEGACY = 'Return ONLY JSON {"decisions":[{"id":"0","send":false,"reason":"Short evidence-based rationale"}]}.'


async def main():
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    baseline = json.loads((Path(__file__).parent / 'curiosity-final-live-probe.json').read_text(encoding='utf-16'))
    question = json.loads(next(item['content'] for item in baseline['synthetic_generations'] if item['purpose'] == 'inquiry'))
    now = datetime.fromtimestamp(baseline['results'][0]['decision']['created'])
    context = {'live': {'waiting_for_answer': False, 'activity': 'coding'}, 'busy': False,
               'question_preferences': {'on': True}, 'life_state': {'can_initiate': True},
               'workspace': {'tasks': [{'kind': 'task', 'title': "Prepare the project report for today's 18:00 handoff",
                    'status': 'blocked', 'blocker': 'Waiting for review notes, with no expected arrival time recorded',
                    'source': 'owner_report',
                    'steps': ['If notes arrive before 17:00, incorporate the edits before handoff.',
                              'If they arrive later, prepare the draft for handoff and flag the pending review.']}]},
               'reasoning': {'facts': [], 'conclusions': []}}
    candidate = notifications.Candidate(question['question'], 'question', public=False,
                  basis={'sources': question['basis'], 'reason': question['reason'], 'purpose': question['purpose']})
    original = notifications.PROMPT
    from providers import failover
    actual = failover.complete_with_failover
    providers = []
    async def capture(*args, **kwargs):
        result = await actual(*args, **kwargs)
        providers.append({'provider': result.provider, 'model': result.model})
        return result
    failover.complete_with_failover = capture
    cases = []
    with tempfile.TemporaryDirectory(prefix='friday-review-contract-') as folder:
        notifications.cognition = Cognition(Path(folder) / 'brain.db')
        for name, neutral, answered in [('legacy_useful', False, False), ('neutral_useful', True, False),
                                        ('neutral_answer_already_known', True, True)]:
            current = copy.deepcopy(context)
            if answered:
                current['remembered_facts'] = ['The owner already answered this exact question: review notes will arrive tomorrow afternoon. Prepare the draft for handoff today and flag the pending review.']
            async def snapshot(when):
                return copy.deepcopy(current)
            notifications._context = snapshot
            notifications.PROMPT = original.replace(LEGACY, NEUTRAL) if neutral else original.replace(NEUTRAL, LEGACY)
            try:
                choices = await notifications._reason([candidate], now, {})
                cases.append({'case': name, 'decisions': [choice.model_dump() for choice in choices]})
            except Exception as error:
                cases.append({'case': name, 'error': type(error).__name__})
    print(json.dumps({'local_only': True, 'notifications_sent': 0, 'commands_run': 0,
                      'frozen_question': question['question'], 'cases': cases, 'providers': providers}, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            async with asyncio.timeout(65):
                await main()
        finally:
            await runtime.close()
    asyncio.run(run())
