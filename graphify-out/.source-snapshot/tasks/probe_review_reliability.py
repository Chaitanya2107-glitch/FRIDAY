"""Bounded synthetic local-review comparison, no owner sources or external actions."""
import argparse
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from core.config import config
from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind import cognition_context, executive, life_state, reasoning, review_metrics
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.consolidation import Consolidation
from services.mind.reasoning_store import ReasoningStore
from services.mind.temporal_memory import TemporalMemory

CASES = ('related', 'unrelated', 'commitment', 'related', 'related_variant')


def source_hashes():
    paths = ('services/mind/reasoning.py', 'services/mind/review_schema.py', 'services/mind/review_metrics.py',
             'services/mind/executive.py', 'services/mind/temporal_memory.py',
             'providers/ollama/runtime.py', 'providers/ollama/client.py', 'providers/failover.py')
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in paths}


async def residency():
    ready = await runtime.ready(config.OLLAMA_BASE_URL)
    result = {'server_ready': ready, 'configured_model_resident': None}
    if ready:
        try:
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                response = await client.get(config.OLLAMA_BASE_URL.rstrip('/') + '/api/ps')
                response.raise_for_status()
                result['configured_model_resident'] = any(config.OLLAMA_MODEL in (m.get('name'), m.get('model'))
                    for m in response.json().get('models', []))
        except (httpx.HTTPError, ValueError, TypeError):
            pass
    return result


async def main(args):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    results = []
    output = {'label': args.label, 'model': config.OLLAMA_MODEL, 'local_only': True,
              'commands_run': 0, 'notifications_sent': 0, 'shared_model_unloaded': False, 'results': results,
              'source_hashes': source_hashes()}
    for index, case in enumerate(CASES[:args.cases]):
        before = await residency()
        with tempfile.TemporaryDirectory(prefix='friday-review-reliability-') as folder:
            store = Cognition(Path(folder) / 'synthetic.db')
            episodes, memory, temporal = BrainMemory(store), Consolidation(store), TemporalMemory(store)
            now = datetime(2026, 10, 21, 15) + timedelta(minutes=index * 10)
            if case == 'commitment':
                episodes.remember('My synthetic calculus exam is tomorrow', now=now)
            elif case == 'related_variant':
                episodes.remember('The synthetic thesis draft follows the annotated library outline.', now=now)
                episodes.remember('The conclusion section may be missing from the annotated outline.',
                    question='What might be missing from the outline supporting the synthetic thesis draft?',
                    now=now + timedelta(seconds=1))
            else:
                episodes.remember('The synthetic project report uses figures from the laboratory notes.', now=now)
                if case == 'related':
                    episodes.remember('Two pressure measurements may be missing from the laboratory notes.',
                        question='What information is missing from the laboratory notes for the synthetic report?',
                        now=now + timedelta(seconds=1))
                else:
                    episodes.remember('My favorite sandwich filling is tomato.', now=now + timedelta(seconds=1))
            def known():
                data = {**episodes.evidence(), **temporal.evidence(), **memory.evidence()}
                temporal.annotate_history(data)
                return data
            source = ReasoningStore(store)
            source.evidence = known
            control = executive.ExecutiveControl(store)
            control._known = known
            live = {'activity': 'idle', 'away': False, 'idle_band': 'present'}
            def behavior(noted=None, **kwargs):
                return life_state.LifeState(store).assess(noted or now, kwargs['known'], kwargs['live'],
                                                         {'on': True}, busy=False, mic=False)
            from providers import failover
            actual_complete = failover.complete_with_failover
            requests = []
            generations = []
            async def capture(*request_args, **kwargs):
                requests.append((request_args, kwargs))
                result = await actual_complete(*request_args, **kwargs)
                generations.append({'phase': getattr(review_metrics.active.get(), 'phase', 'negative_control'), 'synthetic_content': result.content})
                return result
            with patch.object(reasoning, 'cognition', store), patch.object(reasoning, 'reasoning_store', source), \
                 patch.object(cognition_context, 'live_state', lambda: dict(live)), \
                 patch.object(executive, 'attention_state', lambda: dict(live)), patch.object(life_state, 'current', behavior), \
                 patch.object(failover, 'complete_with_failover', capture):
                outcome = await control.review(now + timedelta(minutes=2))
            observation = None
            if args.observe_slow and requests and outcome['status'] == 'unavailable':
                request_args, kwargs = requests[0]
                try:
                    response = await actual_complete(*request_args, **{**kwargs, 'attempt_timeout': 35})
                    observation = {'diagnostic_only_never_saved': True, 'metrics': response.metadata,
                                   'synthetic_content': response.content}
                except Exception as error:
                    observation = {'diagnostic_only_never_saved': True, 'error': type(error).__name__}
            negative_control = None
            if case == 'unrelated':
                # Exercise the actual independent reviewer even when generation correctly chose silence.
                proposed = reasoning.CognitiveReport.model_validate({'work_kind': 'memories',
                    'facts': [], 'conclusions': [], 'questions': [],
                    'memories': [{'subject': 'Laboratory notes', 'evidence': ['owner_episode:1', 'owner_episode:2']}]})
                payload = {'review_purpose': 'cognitive_review', 'evidence': known(), 'time': now.isoformat(), 'live': {}}
                try:
                    async with asyncio.timeout(25):
                        with patch.object(failover, 'complete_with_failover', capture):
                            await reasoning.critique(proposed, payload, config.ACTIVE_PROVIDER)
                    negative_control = 'approved_unrelated_group'
                except reasoning.UnsupportedConclusion:
                    negative_control = 'rejected_unrelated_group'
                except Exception:
                    negative_control = 'unavailable'
            saved = memory.evidence()
            situations = list(temporal.evidence().values())
            expected = (bool(saved) and 'may be missing' in json.dumps(saved) if case.startswith('related') else
                        not saved and not situations and negative_control == 'rejected_unrelated_group' if case == 'unrelated' else
                        any(row['start'] == '2026-10-22' and row['status'] == 'planned' for row in situations))
            results.append({'case': case, 'residency_before': before, 'result': outcome,
                'expected_result_observed': bool(expected) and (outcome['status'] == 'completed' or
                    case == 'unrelated' and outcome['status'] == 'unavailable' and
                    (review_metrics.latest(store) or {}).get('reason') == 'evidence_rejected'),
                'unrelated_group_accepted': case == 'unrelated' and bool(saved), 'memory': saved, 'situations': situations,
                'owner_facts_created': len(source.facts()), 'trace': review_metrics.latest(store),
                'outside_budget_observation': observation, 'synthetic_generations': generations,
                'independent_negative_control': negative_control})
            Path(args.output).write_text(json.dumps(output, indent=2), encoding='utf-8')
            print(json.dumps({'case_finished': case, 'status': outcome['status'], 'expected': results[-1]['expected_result_observed'],
                              'milliseconds': (review_metrics.latest(store) or {}).get('elapsed_ms')}), flush=True)
    output['sources_unchanged'] = source_hashes() == output['source_hashes']
    Path(args.output).write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps({'output': args.output, 'cases': [{'case': r['case'], 'status': r['result']['status'],
        'expected': r['expected_result_observed'], 'milliseconds': (r['trace'] or {}).get('elapsed_ms')} for r in results]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='current')
    parser.add_argument('--output', required=True)
    parser.add_argument('--cases', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--observe-slow', action='store_true')
    async def run():
        try:
            async with asyncio.timeout(250):
                await main(parser.parse_args())
        finally:
            await runtime.close()  # stops only a server owned by this probe
    asyncio.run(run())
