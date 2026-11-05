"""Frozen phase-6 holdout controls; temporary stores, installed local model only.

Run explicitly, never from the watcher. No forced unload or production prompt tuning.
Each executive workflow retains its normal lease; the separate critic control is a
diagnostic call (25s cap), never persisted and never counted as an executive save.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tasks.probe_review_reliability import residency, source_hashes
from core.config import config
from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind import cognition_context, executive, life_state, reasoning, review_metrics
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.consolidation import Consolidation
from services.mind.reasoning_store import ReasoningStore
from services.mind.temporal_memory import TemporalMemory

# Frozen before the first live run. These become regression controls after use,
# not permanently unseen examples. Labels/subjects never enter generation evidence.
CASES = (
    dict(id='bicycle_parts', related=True, subject='Synthetic bicycle repair', sources=[
        ('My synthetic bicycle repair needs a replacement brake cable.', ''),
        ('The replacement brake cable may be the wrong length for my synthetic bicycle.', '')]),
    dict(id='paired_answer', related=True, subject='Synthetic costume sewing', sources=[
        ('I am sewing a synthetic stage costume from the blue pattern.', ''),
        ('The sleeve allowance may be missing.', 'What might be missing from the blue pattern for your synthetic stage costume?')]),
    dict(id='paraphrase', related=True, subject='Synthetic museum captions', sources=[
        ('I am preparing captions for the synthetic pottery exhibit.', ''),
        ('The labels for that synthetic ceramics display may lack the maker names.', '')]),
    dict(id='negated_shared_problem', related=True, subject='Synthetic telescope alignment', sources=[
        ('My synthetic telescope alignment is unreliable.', ''),
        ('Cleaning the lens did not fix my synthetic telescope alignment.', '')]),
    dict(id='bank_homonym', related=False, subject='Synthetic bank account transfer', sources=[
        ('My synthetic bank account transfer may be delayed.', ''),
        ('The river bank in my synthetic landscape sketch needs darker shading.', '')]),
    dict(id='java_homonym', related=False, subject='Synthetic Java compiler issue', sources=[
        ('My synthetic Java program fails to compile.', ''),
        ('I enjoy photographs of the volcanoes on the island of Java.', '')]),
    dict(id='unrelated_answer', related=False, subject='Synthetic aquarium filter', sources=[
        ('My synthetic aquarium filter may need a new cartridge.', ''),
        ('Pistachio.', 'Which ice cream flavour do you prefer?')]),
    dict(id='unrelated_plain', related=False, subject='Synthetic choir rehearsal', sources=[
        ('I cannot find the sheet music for the synthetic choir rehearsal.', ''),
        ('My favourite chess opening is the Sicilian defence.', '')]),
)


def verdict(expected, observed):
    if observed == 'unavailable':
        return observed
    return {True: {'approved': 'correct_approval', 'rejected': 'false_rejection'},
            False: {'approved': 'false_approval', 'rejected': 'correct_rejection'}}[expected][observed]


def load_cases(path=None):
    if path is None:
        return CASES
    cases = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 16:
        raise ValueError('A control corpus needs 1-16 cases')
    ids = set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {'id', 'related', 'subject', 'sources'}
                or type(case['related']) is not bool
                or not isinstance(case['id'], str) or not case['id'] or case['id'] in ids
                or not isinstance(case['subject'], str) or not 3 <= len(case['subject']) <= 100
                or not isinstance(case['sources'], list) or not 2 <= len(case['sources']) <= 4):
            raise ValueError('Invalid control case')
        ids.add(case['id'])
        for row in case['sources']:
            if (not isinstance(row, list) or len(row) != 2
                    or not all(isinstance(value, str) for value in row)
                    or not row[0].strip() or len(row[0]) > 600 or len(row[1]) > 200):
                raise ValueError('Control sources must fit exact retained excerpts')
    return cases


def preserved(saved, originals):
    excerpts = {row['id']: row for group in saved.values() for row in group['excerpts']}
    return set(excerpts) == set(originals) and all(
        all(excerpts[ref].get(key) == row[key] for key in ('text', 'question', 'noted'))
        for ref, row in originals.items())


def summarize(rows):
    startup = {key: {'count': 0, 'wall_ms': []} for key in ('nonresident', 'resident', 'unknown')}
    for row in rows:
        load = (row.get('trace') or {}).get('startup', {})
        state = load.get('was_resident')
        group = startup['resident' if state is True else 'nonresident' if state is False else 'unknown']
        group['count'] += 1
        if load.get('wall_ms') is not None:
            group['wall_ms'].append(load['wall_ms'])
    return {'cases': len(rows), 'workflow_expectations_met': sum(row['workflow_ok'] for row in rows),
            'unrelated_groups_saved': sum(row['unrelated_group_saved'] for row in rows),
            'controls': dict(Counter(row['control'] for row in rows)), 'startup': startup}


async def run_case(case, index):
    before = await residency()
    with tempfile.TemporaryDirectory(prefix='friday-holdout-') as folder:
        store = Cognition(Path(folder) / 'synthetic.db')
        episodes, memory, temporal = BrainMemory(store), Consolidation(store), TemporalMemory(store)
        now = datetime(2026, 10, 21, 15) + timedelta(minutes=index * 10)
        for offset, (text, question) in enumerate(case['sources']):
            episodes.remember(text, question=question, now=now + timedelta(seconds=offset))
        originals = episodes.evidence()
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
        actual = failover.complete_with_failover
        generations = []
        async def capture(*args, **kwargs):
            response = await actual(*args, **kwargs)
            generations.append({'phase': getattr(review_metrics.active.get(), 'phase', 'diagnostic_control'),
                                'synthetic_content': response.content, 'metrics': response.metadata})
            return response
        with patch.object(reasoning, 'cognition', store), patch.object(reasoning, 'reasoning_store', source), \
             patch.object(cognition_context, 'live_state', lambda: dict(live)), \
             patch.object(executive, 'attention_state', lambda: dict(live)), \
             patch.object(life_state, 'current', behavior), patch.object(failover, 'complete_with_failover', capture):
            outcome = await control.review(now + timedelta(minutes=2))
            # Critique the same frozen grouping for positives AND negatives, even
            # when generation chooses silence. Never save this supplied proposal.
            proposal = reasoning.CognitiveReport.model_validate({'work_kind': 'memories', 'conclusions': [], 'questions': [],
                'memories': [{'subject': case['subject'], 'evidence': sorted(originals)}]})
            payload = {'review_purpose': 'cognitive_review', 'evidence': originals, 'time': now.isoformat(), 'live': {}}
            error_type = None
            try:
                async with asyncio.timeout(25):
                    await reasoning.critique(proposal, payload, config.ACTIVE_PROVIDER)
                observed = 'approved'
            except reasoning.UnsupportedConclusion:
                observed = 'rejected'
            except Exception as error:
                observed, error_type = 'unavailable', type(error).__name__
        saved, situations, facts = memory.evidence(), temporal.evidence(), source.facts()
        workflow_ok = (bool(saved) and preserved(saved, originals) and outcome['status'] == 'completed'
                       if case['related'] else not saved and
                       (outcome['status'] == 'completed' or
                        (review_metrics.latest(store) or {}).get('reason') == 'evidence_rejected'))
        return {'case': case['id'], 'expected_related': case['related'], 'residency_before': before,
                'result': outcome, 'workflow_ok': bool(workflow_ok and not situations and not facts),
                'unrelated_group_saved': not case['related'] and bool(saved),
                'control': verdict(case['related'], observed), 'control_error_type': error_type,
                'memory': saved, 'situations': situations, 'owner_facts_created': len(facts),
                'trace': review_metrics.latest(store), 'synthetic_generations': generations}


async def main(args):
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    corpus_path = getattr(args, 'corpus', None)
    cases = load_cases(corpus_path)
    corpus = json.dumps(cases, sort_keys=True).encode()
    hashes = source_hashes()
    output = {'suite': Path(corpus_path).stem if corpus_path else 'phase6-holdout-v1',
              'corpus_sha256': hashlib.sha256(corpus).hexdigest(),
              'source_hashes': hashes, 'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'model': config.OLLAMA_MODEL, 'local_only': True, 'commands_run': 0,
              'notifications_sent': 0, 'shared_model_unloaded': False, 'finished': False, 'results': []}
    path = Path(args.output)
    def write():
        output['summary'] = summarize(output['results'])
        output['sources_unchanged'] = source_hashes() == hashes
        path.write_text(json.dumps(output, indent=2), encoding='utf-8')
    write()
    try:
        async with asyncio.timeout(600):
            for index, case in enumerate(cases[:args.cases]):
                row = await run_case(case, index)
                output['results'].append(row)
                write()
                print(json.dumps({key: row[key] for key in ('case', 'workflow_ok', 'control')}), flush=True)
        output['finished'] = True
    except BaseException as error:
        output['error_type'] = type(error).__name__
        raise
    finally:
        write()
        await runtime.close()  # existing ownership rule: never stops a shared server
    print(json.dumps(output['summary']), flush=True)
    return output['sources_unchanged'] and all(row['workflow_ok'] and row['control'] in {
        'correct_approval', 'correct_rejection'} for row in output['results'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--corpus', type=Path, help='Frozen JSON corpus; defaults to the original regression cases')
    parser.add_argument('--cases', type=int, choices=range(1, 17), default=None)
    sys.exit(0 if asyncio.run(main(parser.parse_args())) else 1)
