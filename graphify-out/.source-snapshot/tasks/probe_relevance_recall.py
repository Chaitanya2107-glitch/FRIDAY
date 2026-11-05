"""Frozen synthetic retrieval evaluation; no actions or notifications."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logger import logger
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.consolidation import Consolidation, MemoryThread
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate

SOURCES = ('services/files/embed.py', 'services/mind/recall.py', 'services/mind/recall_review.py', 'services/mind/brain_memory.py', 'services/mind/consolidation.py',
           'services/mind/temporal_memory.py', 'services/mind/life_state.py', 'services/mind/reasoning_store.py',
           'services/mind/reasoning.py', 'services/mind/executive.py', 'services/mind/language.py',
           'services/mind/review_schema.py', 'services/mind/inquiry.py', 'services/mind/talk.py')
NOW = datetime(2026, 10, 21, 12)


def hashes():
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in SOURCES}


def archive(memory, ids):
    saved = Consolidation(memory.store)
    with saved._db() as db:
        saved.save(db, [MemoryThread(subject='Synthetic reviewed fixture', evidence=list(ids))],
                   NOW, memory.evidence(limit=50))


async def evaluate(corpus, *, semantic=False):
    with tempfile.TemporaryDirectory(prefix='friday-recall-eval-') as folder:
        store = Cognition(Path(folder) / 'synthetic.db')
        memory, labels = BrainMemory(store), {}
        for index, row in enumerate(corpus['sources']):
            ident = memory.remember(row['text'], question=row.get('question', ''),
                channel=row.get('channel', 'chat'), now=NOW + timedelta(minutes=index))
            labels[row['id']] = f'owner_episode:{ident}'
        for pair in corpus['threads']:
            archive(memory, [labels[label] for label in pair])
        temporal = TemporalMemory(store)
        known = memory.evidence(limit=50)
        value = TemporalUpdate(source=labels['exam_old'], quote=known[labels['exam_old']]['text'],
            subject='acoustics exam', status='planned', date_phrase='tomorrow', start=None, end=None, supersedes=[])
        value = temporal.resolve([value], known)[0]
        with temporal._db() as db:
            temporal.save(db, [value], NOW, known)
        update = value.model_copy(update={'source': labels['exam_new'], 'quote': known[labels['exam_new']]['text'],
            'status': 'postponed', 'date_phrase': '', 'start': None, 'end': None, 'supersedes': list(temporal.evidence())})
        with temporal._db() as db:
            temporal.save(db, [update], NOW + timedelta(hours=1), {**known, **temporal.evidence()})
        for index in range(200):
            memory.remember(f'Routine weather observation {index}.', now=NOW + timedelta(hours=2, minutes=index))
        reverse = {value: key for key, value in labels.items()}
        results = []
        for query in corpus['queries']:
            started = time.perf_counter()
            if semantic:
                rows = await memory.recall_checked(query['query'], channel=query.get('channel', 'chat'), limit=3)
            else:
                rows = memory.recall(query['query'], channel=query.get('channel', 'chat'), limit=3)
            elapsed = (time.perf_counter() - started) * 1000
            found = [reverse.get(row['id'], row['id']) for row in rows]
            expected = query['relevant']
            results.append({'query': query['query'], 'channel': query.get('channel', 'chat'),
                'expected': expected, 'returned': found, 'hit_at_3': bool(set(found) & set(expected)) if expected else None,
                'negative_abstained': not found if not expected else None,
                'excluded_source_returned': bool(set(found) & set(query.get('excluded', []))),
                'elapsed_ms': round(elapsed, 3), 'encoded_chars': len(json.dumps(rows, ensure_ascii=False))})
        positive = [row for row in results if row['expected']]
        negative = [row for row in results if not row['expected']]
        memory.store.clear()
        forgot = memory.recall('diaphragm pump') == []
        return {'results': results, 'positive_queries': len(positive),
                'positive_hits_at_3': sum(row['hit_at_3'] for row in positive),
                'negative_queries': len(negative), 'negative_abstentions': sum(row['negative_abstained'] for row in negative),
                'superseded_sources_returned': sum(row['excluded_source_returned'] for row in results),
                'forget_verified': forgot}


def retention():
    with tempfile.TemporaryDirectory(prefix='friday-recall-retention-') as folder:
        memory = BrainMemory(Cognition(Path(folder) / 'synthetic.db'))
        first = memory.remember('The barometer case may need a thinner felt lining.', now=NOW)
        second = memory.remember('Possibly the lower hinge.', question='Which part of the barometer case may be loose?', now=NOW)
        archive(memory, [f'owner_episode:{first}', f'owner_episode:{second}'])
        for index in range(501):
            memory.remember(f'Unrelated weather observation {index}', now=NOW + timedelta(minutes=index + 1))
        restored = BrainMemory(Cognition(memory.store.path))
        rows = restored.recall('barometer felt lining')
        return bool(rows and rows[0]['id'] == f'owner_episode:{first}' and rows[0]['reviewed_threads']
                    and f'owner_episode:{first}' not in restored.evidence(limit=50))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=Path('tasks/recall_holdout_v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--semantic', action='store_true', help='Use offline installed embedding weights')
    protocols = parser.add_mutually_exclusive_group()
    protocols.add_argument('--compact-candidate', action='store_true',
                        help='Offline experiment only: replace the referent check for this disposable probe')
    protocols.add_argument('--lexical-candidate', action='store_true',
                           help='Offline experiment only: check isolated synonym words')
    args = parser.parse_args()
    if (args.compact_candidate or args.lexical_candidate) and not args.semantic:
        parser.error('Experimental candidates require --semantic')
    if args.compact_candidate:
        from services.mind import recall_review
        from tasks.compact_recall_candidate import supports
        recall_review.supports = supports
    if args.lexical_candidate:
        from services.mind import recall_review
        from tasks.lexical_recall_candidate import supports
        recall_review.supports = supports
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    from services.files import embed
    embedding_calls = []
    original_encode = embed.encode_local
    def measured_encode(texts, **kwargs):
        embedding_calls.append(len(texts))
        return original_encode(texts, **kwargs)
    if args.semantic:
        embed.encode_local = measured_encode
    else:
        def lexical_only(texts):
            raise RuntimeError('Lexical-only evaluation')
        embed.encode_local = lexical_only
    before = hashes()
    experimental = args.compact_candidate or args.lexical_candidate
    candidate_path = Path('tasks/lexical_recall_candidate.py' if args.lexical_candidate else 'tasks/compact_recall_candidate.py')
    candidate_hash = hashlib.sha256(candidate_path.read_bytes()).hexdigest() if experimental else None
    review_calls, warmup = [], {}
    from providers import failover
    from providers.ollama.runtime import runtime
    original_complete = failover.complete_with_failover
    async def counted_complete(*params, **options):
        record = {'provider': params[0], 'purpose': options.get('purpose'),
                  'synthetic_input': json.loads(params[1][0].content)}
        review_calls.append(record)
        response = await original_complete(*params, **options)
        record['synthetic_response'] = response.content
        return response
    failover.complete_with_failover = counted_complete
    async def measured_evaluation():
        if args.semantic:
            started = time.perf_counter()
            try:
                async with asyncio.timeout(45):
                    await asyncio.to_thread(embed.encode_local, ['Synthetic quality-probe warmup'])
                    await runtime.prepare_model()
                warmup['seconds'] = round(time.perf_counter() - started, 3)
            except Exception as error:
                warmup['error_type'] = type(error).__name__
        try:
            return await evaluate(json.loads(args.corpus.read_text(encoding='utf-8')), semantic=args.semantic)
        finally:
            await runtime.close()
    scores = asyncio.run(measured_evaluation())
    output = {'method': 'literal selection plus locally checked semantic candidate' if args.semantic else 'bounded lexical BM25-style ranking',
        'review_protocol': ('experimental isolated words' if args.lexical_candidate else
                            'experimental compact mapping' if args.compact_candidate else 'production'),
        'candidate_sha256': candidate_hash,
        'generative_model_calls': len(review_calls), 'review_calls': review_calls, 'quality_probe_warmup': warmup,
        'commands_run': 0, 'notifications_sent': 0, 'sources': before,
        'corpus_sha256': hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        **scores,
        'retention_restart_verified': retention()}
    output['embedding_calls'] = len(embedding_calls)
    output['embedding_batch_sizes'] = embedding_calls
    output['sources_unchanged'] = before == hashes()
    output['candidate_unchanged'] = (not experimental or candidate_hash ==
                                   hashlib.sha256(candidate_path.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in output.items() if key not in {'results', 'sources', 'review_calls'}}))
    # Missed positive paraphrases are measured, not silently excluded or called passing.
    sys.exit(0 if output['sources_unchanged'] and output['candidate_unchanged'] and output['forget_verified'] and output['retention_restart_verified']
             and not output['superseded_sources_returned']
             and output['positive_hits_at_3'] == output['positive_queries']
             and output['negative_abstentions'] == output['negative_queries'] else 1)
