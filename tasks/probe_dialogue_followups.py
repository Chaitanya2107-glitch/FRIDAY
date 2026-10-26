"""Frozen synthetic ordinary-chat intake through the installed local generator/critic."""
import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import config
from core.logger import logger

for handler in list(logger.handlers):
    logger.removeHandler(handler)
    handler.close()
logger.addHandler(logging.NullHandler())

from providers import failover
from providers.ollama.runtime import runtime
from services.mind import cognition as cognition_module, cognition_context, dialogue as dialogue_module
from services.mind import executive, reasoning, life_state, talk, review_metrics
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.reasoning_store import ReasoningStore
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate

SOURCES = [
    'services/mind/dialogue.py', 'services/mind/dialogue_review.py',
    'services/mind/brain_memory.py', 'services/mind/temporal_memory.py',
    'services/mind/executive.py', 'services/mind/conversation_context.py',
    'services/mind/cognition_context.py', 'services/mind/reasoning.py', 'services/mind/talk.py',
    'interfaces/api/routes/chat.py', 'interfaces/api/routes/voice.py',
    'providers/failover.py', 'providers/policy.py', 'providers/ollama/client.py',
    'providers/ollama/runtime.py', 'tests/test_dialogue_followups.py', 'tests/test_dialogue_lifecycle.py',
    'services/mind/date_review.py', 'tests/test_first_call_review.py',
]


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


async def run_case(case, folder):
    store = Cognition(folder / 'synthetic.db')
    episodes, temporal = BrainMemory(store), TemporalMemory(store)
    engine = dialogue_module.Dialogue(store)
    received = datetime(2026, 10, 22, 15)
    dialogue_module.clock = lambda: received
    cognition_module.cognition = store
    reasoning.cognition = store
    for flag in ('COGNITION_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'REASONING_ENABLED', 'AI_ASSIST_ONLY'):
        setattr(config, flag, True)  # Process-local synthetic controls; no configuration files are written.
    talk.path = folder / 'talk.json'
    cognition_context.live_state = lambda: {'activity': 'idle', 'away': False}
    executive.attention_state = lambda: {'activity': 'idle', 'away': False,
        'life_state': {'can_review': True, 'review_blocks': []}}
    life_state.current = lambda *args, **kwargs: {'can_review': True, 'review_blocks': [],
        'focus': {'aim': 'resolve_uncertainty', 'basis': []}}
    known = lambda: {**temporal.evidence(), **episodes.evidence()}
    ReasoningStore.evidence = lambda self: known()  # Never read owner facts, integrations or other databases.
    reasoning.reasoning_store = ReasoningStore(store)
    for subject in case['subjects']:
        text = f'My {subject} is on October 24'
        original = received - timedelta(days=2)
        source = episodes.remember(text, now=original)
        value = TemporalUpdate(source=f'owner_episode:{source}', quote=text, subject=subject,
            status='planned', date_phrase='October 24', start=None, end=None, supersedes=[])
        evidence = episodes.evidence()
        with temporal._db() as db:
            temporal.save(db, temporal.resolve([value], evidence), original, evidence)
    calls, turns = [], []
    original_complete = failover.complete_with_failover
    async def capture(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        call = {'phase': 'critique' if 'check_items' in payload else 'generation', 'purpose': kwargs.get('purpose')}
        calls.append(call)
        started = time.monotonic()
        try:
            response = await original_complete(*args, **kwargs)
            call.update(provider=response.provider, model=response.model, content=response.content,
                        metadata=response.metadata, seconds=round(time.monotonic() - started, 3))
            return response
        except Exception as error:
            call.update(error=type(error).__name__, seconds=round(time.monotonic() - started, 3))
            raise
    failover.complete_with_failover = capture
    started = time.monotonic()
    try:
        for entry in case['turns']:
            if isinstance(entry, dict) and entry.get('mutation'):
                if entry['mutation'] == 'forget':
                    store.clear()
                else:
                    with temporal._db() as db:
                        row = db.execute('SELECT * FROM temporal_situations WHERE id=1').fetchone()
                        body = json.loads(row['body'])
                        body['noted'] = received.isoformat()
                        db.execute('UPDATE temporal_situations SET body=? WHERE id=1', (json.dumps(body),))
                continue
            text = entry['text'] if isinstance(entry, dict) else entry
            channel = entry.get('channel', 'chat') if isinstance(entry, dict) else 'chat'
            turn_token = cognition_module._turn.set(uuid.uuid4().hex)
            channel_token = cognition_module._channel.set(channel)
            event = store.record('request', channel, 'Synthetic request', status='started')
            try:
                parsed = engine.match_turn(text)
                response = await engine.run(parsed) if parsed else None
                turns.append({'text': text, 'channel': channel, 'received': received.isoformat(),
                    'handled': response is not None, 'success': response.success if response else None,
                    'response': response.message if response else None, 'awaiting_reply': engine.awaiting()})
            finally:
                store.finish(event, 'completed')
                cognition_module._channel.reset(channel_token)
                cognition_module._turn.reset(turn_token)
            received += timedelta(seconds=30)
    finally:
        failover.complete_with_failover = original_complete
    histories = {subject: temporal.history(subject) for subject in case['subjects']}
    selected = histories[case['subject']]
    if case['expected']:
        passed = (len(selected) == 2 and selected[0]['start'] == selected[0]['end'] == case['expected']
            and selected[0]['quote'] == turns[-1]['text'] and selected[0]['source_noted'] == turns[-1]['received']
            and selected[0]['source_question'] in {turn['response'] for turn in turns[:-1]}
            and selected[1]['superseded_by'] == selected[0]['id'] and turns[-1]['success']
            and any(call.get('phase') == 'critique' for call in calls)
            and all(call.get('provider') == 'ollama' and call['purpose'] == 'cognitive_review' for call in calls)
            and all(len(rows) == 1 for subject, rows in histories.items() if subject != case['subject']))
    else:
        expected_count = 0 if any(isinstance(value, dict) and value.get('mutation') == 'forget' for value in case['turns']) else 1
        passed = all(len(rows) == expected_count for rows in histories.values()) and not calls
    return {'id': case['id'], 'expectations_met': bool(passed), 'seconds': round(time.monotonic() - started, 3),
            'turns': turns, 'calls': calls, 'history': histories, 'review': review_metrics.latest(store),
            'notifications_sent': 0, 'external_actions': 0}


async def main(args):
    fixture_bytes = args.fixtures.read_bytes()
    fixtures = json.loads(fixture_bytes)
    before, results, warmup = hashes(), [], None
    cases = [case for case in fixtures['cases'] if not args.case or case['id'] == args.case]
    if not cases:
        raise ValueError('No matching frozen fixture')
    try:
        if args.warmup:
            started = time.monotonic()
            async with asyncio.timeout(60):
                warmup = await runtime.prepare_model()
            warmup['wall_seconds'] = round(time.monotonic() - started, 3)
            warmup['condition'] = 'Explicit prompt-free readiness before this warm-model probe; production budgets are unchanged.'
        for round_number in range(args.rounds):
            for case in cases:
                with tempfile.TemporaryDirectory(prefix='ordinary-followup-probe-', dir=ROOT / 'tasks') as folder:
                    directory = Path(folder).resolve()
                    assert directory.is_relative_to((ROOT / 'tasks').resolve())
                    async with asyncio.timeout(90):
                        result = await run_case(case, directory)
                    result['round'] = round_number + 1
                    results.append(result)
                    print(json.dumps({key: result[key] for key in ('id', 'round', 'expectations_met', 'seconds')}), flush=True)
    finally:
        await runtime.close()
    result = {'sources': before, 'sources_unchanged': before == hashes(),
        'fixture_sha256': hashlib.sha256(fixture_bytes).hexdigest(), 'results': results,
        'warmup': warmup,
        'model_changed': False, 'owner_data_used': False, 'settings_written': False}
    args.output.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    return all(row['expectations_met'] for row in results) and result['sources_unchanged']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, default=ROOT / 'tasks/ordinary-followups-live-fixtures.json')
    parser.add_argument('--case')
    parser.add_argument('--warmup', action='store_true', help='Measure a resident model after explicit prompt-free readiness')
    parser.add_argument('--rounds', type=int, choices=[1, 2], default=1,
                        help='Repeat frozen isolated cases in one process to measure cold and warm behavior')
    parser.add_argument('--output', type=Path, default=ROOT / 'tasks/ordinary-followups-live.json')
    arguments = parser.parse_args()
    sys.exit(0 if asyncio.run(main(arguments)) else 1)
