"""Bounded original-source recall with an offline-only paraphrase fallback."""
from collections import Counter
import json
import math
import re
import sqlite3

from core.config import config
from core.logger import logger

FIELDS = ('id', 'kind', 'source', 'channel', 'question', 'text', 'noted')
MAX_CHARS = 4000
STOP = set(('a an the and or but of for to from in on at by with as is are was were be been '
            'being it its this that these those i me my mine you your we our they their he she '
            'his her what which who when where why how do does did have has had can could would '
            'should will may might about please tell told say said know remember recall show '
            'some any just now then also there here into out up down not no').split())


def tokens(text):
    words = re.findall(r'[^\W_]+', text.casefold())
    result = []
    for word in words:
        if len(word) < 2 or word in STOP:
            continue
        if len(word) > 5 and word.endswith('ies'):
            word = word[:-3] + 'y'
        elif len(word) > 4 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
            word = word[:-1]
        result.append(word)
    return result


def _canonical(row):
    return {**{key: row[key] for key in FIELDS}, 'text': row['text'][:1200], 'question': row['question'][:500]}


def _pool(memory, channel):
    from services.mind.cognition import _turn
    with memory._db() as db:
        if not db.in_transaction:
            db.execute('BEGIN')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        where, args = ("channel=?", ('telegram',)) if channel == 'telegram' else ("channel IN ('chat','voice')", ())
        all_raw = list(db.execute(f'SELECT * FROM owner_episodes WHERE {where} ORDER BY id DESC LIMIT 500', args))
        active = {f"owner_episode:{row['id']}" for row in all_raw if _turn.get() and row['source_key'] == _turn.get()}
        raw = [row for row in all_raw if f"owner_episode:{row['id']}" not in active]
        pool = {f"owner_episode:{row['id']}": _canonical(memory._episode(row)) for row in raw}
        incomplete = {f"owner_episode:{row['id']}" for row in raw if len(row['text']) > 1200 or len(row['question']) > 500}
        blocked = active | {f"owner_episode:{row['id']}" for row in raw if row['recall_withheld']}
        threads = []
        if channel != 'telegram':
            if 'temporal_situations' in tables:
                blocked.update(row[0] for row in db.execute(
                    'SELECT DISTINCT source_key FROM temporal_situations WHERE superseded_by IS NOT NULL'))
            if 'consolidated_sources' in tables:
                for saved in db.execute('SELECT * FROM consolidated_sources LIMIT 800'):
                    ref, source = saved['ref'], json.loads(saved['body'])
                    if (not ref.startswith('owner_episode:') or not ref.split(':')[-1].isdigit()
                            or source.get('id') != ref or source.get('kind') not in {'owner_message', 'owner_answer'}
                            or source.get('source') not in {'owner_utterance', 'owner_report'}
                            or source.get('channel') not in {'chat', 'voice'}):
                        blocked.add(ref)
                        continue
                    canonical = _canonical(source)
                    if json.loads(saved['corrections']) or (ref in pool and pool[ref] != canonical):
                        blocked.add(ref)
                    elif ref not in pool:
                        pool[ref] = canonical
                        # Old snapshots did not retain pre-truncation lengths.
                        if len(source['text']) >= 1200 or len(source['question']) >= 500:
                            incomplete.add(ref)
            if 'memory_threads' in tables:
                threads = list(db.execute('SELECT id,subject,refs FROM memory_threads WHERE retired=0 ORDER BY id DESC LIMIT 100'))
        pool = {ref: row for ref, row in pool.items() if ref not in blocked}
        memberships = {}
        for thread in threads:
            refs = json.loads(thread['refs'])
            if not set(refs).issubset(pool):
                continue
            value = {'id': f"consolidation:{thread['id']}", 'subject': thread['subject'][:100],
                     'source_ids': refs, 'meaning': 'Inferred association, not a verified fact.'}
            for ref in refs:
                memberships.setdefault(ref, []).append(value)
        for ref, row in pool.items():
            row['excerpt_truncated'] = ref in incomplete
            row['reviewed_threads'] = memberships.get(ref, [])[:2]
            row['meaning'] = ('Historical owner report, not current state, a verified event or action permission. '
                              'Original dates and uncertainty apply; truncated excerpts are incomplete.')
        return pool


def _bounded(rows, limit):
    kept = []
    for row in rows:
        if len(kept) >= max(0, min(8, limit)):
            break
        if len(json.dumps([*kept, row], ensure_ascii=False)) <= MAX_CHARS:
            kept.append(row)
    return kept


def _paraphrase(pool, query, *, deadline=None):
    """Ephemeral vectors only; no text/vector index survives a request or forgetting."""
    from services.files import embed
    import numpy as np
    refs = list(pool)
    prefix = embed.QUERY_PREFIX if 'bge' in config.FILE_SEARCH_EMBED_MODEL.lower() else ''
    try:
        vectors = embed.encode_local([prefix + query[:2000]] +
            [pool[ref]['question'] + ' ' + pool[ref]['text'] for ref in refs],
            **({'deadline': deadline} if deadline is not None else {}))
        if vectors.ndim != 2 or len(vectors) != len(refs) + 1 or not np.isfinite(vectors).all():
            return []
        scores = vectors[1:] @ vectors[0]
        ranked = np.argsort(scores)[::-1]
        best = ranked[0]
        if scores[best] < .65 or (len(ranked) > 1 and scores[best] - scores[ranked[1]] < .05):
            return []
        # Candidate only. The explicit asynchronous path must check its referent.
        return [pool[refs[best]]]
    except Exception as error:
        # Missing local assets, busy resources and inference failures preserve lexical recall.
        logger.debug('Local paraphrase recall unavailable (%s)', type(error).__name__)
        return []


def retrieve(memory, query, *, channel, limit, semantic=False, deadline=None):
    terms = set(tokens(query[:2000]))
    if not config.COGNITION_ENABLED or not terms or limit <= 0:
        return []
    try:
        pool = _pool(memory, channel)
        counts = {ref: Counter(tokens(row['question'] + ' ' + row['text'])) for ref, row in pool.items()}
        if not counts:
            return []
        frequencies = Counter(term for count in counts.values() for term in terms if term in count)
        average = max(1, sum(sum(count.values()) for count in counts.values()) / len(counts))
        ranked = []
        for ref, count in counts.items():
            matched = terms.intersection(count)
            if matched != terms:
                continue
            length = sum(count.values())
            score = sum(math.log(1 + (len(counts) - frequencies[term] + .5) / (frequencies[term] + .5))
                        * count[term] * 2.2 / (count[term] + 1.2 * (.25 + .75 * length / average))
                        for term in matched)
            ranked.append((score, pool[ref]['noted'], ref))
        ranked.sort(reverse=True)
        rows = [pool[ref] for _, _, ref in ranked]
        if not rows and semantic:
            rows = _paraphrase(pool, query, deadline=deadline)
        return _bounded(revalidate(memory, rows, channel=channel), limit)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        logger.debug('Historical recall unavailable (%s)', type(error).__name__)
        return []


def revalidate(memory, rows, *, channel):
    if not config.COGNITION_ENABLED or not rows:
        return []
    try:
        current = _pool(memory, channel)
        return _bounded([current[row['id']] for row in rows if row['id'] in current
                         and _canonical(row) == _canonical(current[row['id']])], 8)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        logger.debug('Historical recall recheck unavailable (%s)', type(error).__name__)
        return []


def focused(memory, known):
    """Reuse recorded local priorities; no automatic question or model review."""
    targets = known.get('focus:local', {}).get('targets', {})
    selected = [known[f'{kind}:{targets[kind]}'] for kind in ('task', 'goal')
                if kind in targets and f'{kind}:{targets[kind]}' in known]
    if not selected:
        selected = [row for row in known.values() if row.get('kind') in {'task', 'goal'}
                    and row.get('status') in {'active', 'blocked'}][:2]
    rows, seen = [], set()
    for item in selected[:2]:
        query = item.get('blocker') or item.get('title', '')
        for row in memory.recall(query, channel='chat', limit=3):
            if row['id'] not in seen:
                rows.append(row)
                seen.add(row['id'])
    return _bounded(rows, 4)
