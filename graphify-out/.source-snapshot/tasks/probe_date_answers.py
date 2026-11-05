"""Synthetic offered question -> real talk intake -> local executive/critic; no delivery."""
import argparse
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import logger
from providers import failover
from providers.ollama.runtime import runtime
from services.mind import cognition as cognition_module, cognition_context, executive, reasoning, talk, reviews
from services.mind import brain_memory as episode_module, inquiry as inquiry_module, life_state
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.curiosity import gaps
from services.mind.inquiry import Inquiry, Decision
from services.mind.reasoning_store import ReasoningStore
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
from probe_relevance_recall import hashes


async def run(case):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    calls = []
    original = failover.complete_with_failover
    async def capture(*args, **kwargs):
        record = {'purpose': kwargs.get('purpose')}
        calls.append(record)
        started = time.monotonic()
        response = await original(*args, **kwargs)
        record.update(provider=response.provider, model=response.model, content=response.content,
                      seconds=round(time.monotonic() - started, 3))
        return response
    failover.complete_with_failover = capture
    with tempfile.TemporaryDirectory(prefix='friday-date-answer-') as folder:
        store = Cognition(Path(folder) / 'synthetic.db')
        episodes, temporal, inquiry = BrainMemory(store), TemporalMemory(store), Inquiry(store)
        now = datetime(2026, 10, 20, 15)
        quote = f"My {case['subject']} was postponed"
        ident = episodes.remember(quote, now=now)
        value = TemporalUpdate(source=f'owner_episode:{ident}', quote=quote, subject=case['subject'],
            status='postponed', date_phrase='', start=None, end=None, supersedes=[])
        with temporal._db() as db:
            temporal.save(db, [value], now, episodes.evidence())
        known = lambda: {**temporal.evidence(), **episodes.evidence()}
        gap = gaps(temporal.evidence())[0]
        question = case.get('question', f"What is the exact date of your {case['subject']}?")
        job = inquiry.claim('synthetic-date-clarification', now, True)
        decision = Decision(ask=True, question=question, topic=case['subject'], basis=['temporal:1'],
            reason='An exact date changes the preparation plan.', purpose={'gap': gap['id'],
                'decision': 'Choose which day to propose preparation for the assessment.',
                'if_answer_a': {'answer': 'October 27', 'next_step': 'Propose preparation before October 27.'},
                'if_answer_b': {'answer': 'November 3', 'next_step': 'Propose preparation before November 3.'},
                'usefulness': 'changes_decision'})
        inquiry._validate(decision, {'evidence': known(), 'curiosity': {'gaps': [gap]}}, now)
        assert inquiry.finish(job, 'queued', decision.reason, now, decision, known(), gap)
        inquiry.mark(job['id'], 'submitted')
        if case.get('stale'):
            with temporal._db() as db:
                body = json.loads(db.execute('SELECT body FROM temporal_situations WHERE id=1').fetchone()[0])
                body['noted'] = '2026-10-20T15:00:01'
                db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
        # Process-local adapters isolate owner files and feedback, retaining real answer intake.
        talk.path = Path(folder) / 'talk.json'
        talk._save({'on': True, 'pending': {'where': 'asked', 'at': now.timestamp(), 'question': question,
                    'inquiry_id': job['id'], 'offered': True}})
        talk._learn_answer = lambda *a: None
        talk.life.feel = lambda *a: None
        talk._evening = lambda: SimpleNamespace(heard=lambda *a: None)
        talk.mic_in_use = lambda: False
        reviews.evidence = lambda *a, **kw: None
        cognition_module.cognition = store
        episode_module.brain_memory = episodes
        inquiry_module.inquiry = inquiry
        life_state.life_state = life_state.LifeState(store)
        cognition_context.live_state = lambda: {'activity': 'idle', 'away': False}
        executive.attention_state = lambda: {'activity': 'idle', 'away': False}
        memory = ReasoningStore(store)
        memory.evidence = known
        reasoning.reasoning_store = memory
        reasoning.cognition = store
        received = now + timedelta(seconds=30)
        heard = talk.hear(case['answer'], now=received.timestamp())
        answer = next(row for row in episodes.evidence().values() if row['kind'] == 'owner_answer')
        control = executive.ExecutiveControl(store)
        control._known = known
        started = time.monotonic()
        result = await control.review(now + timedelta(days=case.get('review_days', 0), minutes=2))
        history = TemporalMemory(Cognition(store.path)).history(case['subject'])
        expected = case['expected']
        passed = (heard == 'answered' and
            (len(history) == 1 and history[0]['start'] is None if expected is None else
             result['status'] == 'completed' and len(history) == 2 and history[0]['start'] == history[0]['end'] == expected
             and history[0]['source_question'] == question and history[1]['superseded_by'] == history[0]['id']))
        return {'case': case, 'expectations_met': bool(passed), 'result': result, 'history': history,
                'answer': answer, 'calls': calls, 'seconds': round(time.monotonic() - started, 3),
                'notifications_sent': 0, 'commands_run': 0, 'question_origin': 'synthetic approved/offered inquiry; not delivered'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--case', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case = next(row for row in json.loads(args.fixtures.read_text(encoding='utf-8'))['cases'] if row['id'] == args.case)
    before = hashes()
    async def main():
        try:
            async with asyncio.timeout(90):
                return await run(case)
        finally:
            await runtime.close()
    result = asyncio.run(main())
    result.update(sources=before, sources_unchanged=before == hashes(),
                  fixture_sha256=hashlib.sha256(args.fixtures.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in {'history', 'answer', 'calls', 'sources'}}))
    sys.exit(0 if result['expectations_met'] and result['sources_unchanged'] else 1)
