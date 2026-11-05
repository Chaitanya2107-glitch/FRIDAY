"""Local extractive memory: inferred connections, immutable dated owner sources."""
import json
from contextlib import contextmanager

from pydantic import BaseModel, ConfigDict, Field

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition, redact


class MemoryThread(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    subject: str = Field(min_length=3, max_length=100)
    evidence: list[str] = Field(min_length=2, max_length=4)


def original(source):
    """Keep the actual reviewed excerpt, not a model-written factual recap."""
    return {key: source[key] for key in ('id', 'kind', 'source', 'channel', 'question', 'text', 'noted')}


def replacement(source, known):
    latest = set(source.get('memory_replacements', []))
    for revision in source.get('historical_commitment_revisions', []):
        current = known.get(revision['replacement'], {}).get('source')
        if not current:
            from services.mind.temporal_memory import subject_key
            candidates = {row['source'] for row in known.values() if row.get('kind') == 'temporal_interpretation'
                          and subject_key(row['subject']) == subject_key(revision['subject'])}
            if len(candidates) == 1:
                current = next(iter(candidates))
        if not latest and not current:
            raise ValueError('Historical commitment needs its available latest correction before consolidation')
        if current:
            latest.add(current)
    return latest


class Consolidation:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def schema(db):
        db.execute('''CREATE TABLE IF NOT EXISTS consolidated_sources (
            ref TEXT PRIMARY KEY, body TEXT NOT NULL, corrections TEXT NOT NULL DEFAULT '{}')''')
        db.execute('''CREATE TABLE IF NOT EXISTS memory_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT UNIQUE NOT NULL,
            subject TEXT NOT NULL, refs TEXT NOT NULL, noted TEXT NOT NULL,
            retired INTEGER NOT NULL DEFAULT 0)''')

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            self.schema(db)
            yield db

    @staticmethod
    def validate(values, known):
        used = set()
        for value in values:
            refs = value.evidence
            if not value.subject.strip() or len(set(refs)) != len(refs):
                raise ValueError('Memory threads need a topic and distinct sources')
            if used.intersection(refs):
                raise ValueError('Do not repeat a source in multiple proposed threads')
            used.update(refs)
            texts = set()
            for ref in refs:
                source = known.get(ref, {})
                if (not ref.startswith('owner_episode:') or not ref.split(':')[-1].isdigit()
                        or source.get('kind') not in {'owner_message', 'owner_answer'}
                        or source.get('channel') not in {'chat', 'voice'} or source.get('id') != ref
                        or not source.get('text', '').strip()):
                    raise ValueError('Memory threads must cite original local owner episodes, never summaries or guesses')
                latest = replacement(source, known)
                if not latest.issubset(refs):
                    raise ValueError('A historical source must include its latest owner correction')
                texts.add((source.get('question', '').strip().casefold(), source['text'].strip().casefold()))
            if len(texts) < 2:
                raise ValueError('Repeated identical utterances do not establish a useful connection')

    def source_evidence(self, limit=12):
        if not config.COGNITION_ENABLED:
            return {}
        with self._db() as db:
            rows = db.execute('SELECT * FROM consolidated_sources ORDER BY json_extract(body,\'$.noted\') DESC,ref DESC LIMIT ?',
                              (max(1, min(50, limit)),)).fetchall()
        return {row['ref']: {**json.loads(row['body']), **({'memory_replacements': sorted(set(json.loads(row['corrections']).values()))}
                if row['corrections'] != '{}' else {})} for row in rows}

    @staticmethod
    def _corrections(db, ref):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='temporal_situations'").fetchone():
            return {}
        replacements = {}
        for old in db.execute('SELECT subject_key,superseded_by FROM temporal_situations WHERE source_key=? AND superseded_by IS NOT NULL', (ref,)):
            target = old['superseded_by']
            for _ in range(501):
                row = db.execute('SELECT body,superseded_by FROM temporal_situations WHERE id=?', (target,)).fetchone()
                if not row:
                    raise ValueError('Correction provenance is no longer available')
                if not row['superseded_by']:
                    replacements[old['subject_key']] = json.loads(row['body'])['source']
                    break
                target = row['superseded_by']
            else:
                raise ValueError('Correction chain exceeds retained history')
        return replacements

    def save(self, db, values, now, known):
        if not values:
            return
        if not config.COGNITION_ENABLED:
            raise ValueError('Cognition was disabled')
        from services.mind.brain_memory import BrainMemory
        from services.mind.reasoning_store import fingerprint
        self.schema(db)
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        BrainMemory.schema(db)
        self.validate(values, known)
        for value in values:
            refs = sorted(value.evidence)
            for ref in refs:
                source = original(known[ref])
                archived = db.execute('SELECT * FROM consolidated_sources WHERE ref=?', (ref,)).fetchone()
                actual = db.execute('SELECT * FROM owner_episodes WHERE id=?', (int(ref.split(':')[1]),)).fetchone()
                withheld = bool(actual and actual['recall_withheld'])
                if actual:
                    actual = BrainMemory._episode(actual)
                    actual.update(text=actual['text'][:1200], question=actual['question'][:500])
                elif archived:
                    actual = json.loads(archived['body'])
                if actual != source or (archived and json.loads(archived['body']) != source):
                    raise ValueError('Memory source changed or was forgotten during review')
                latest = replacement(known[ref], known)
                corrections = {**(json.loads(archived['corrections']) if archived else {}), **self._corrections(db, ref)}
                if withheld and not corrections:
                    raise ValueError('Recall-withheld source lacks retained correction provenance')
                if set(corrections.values()) != latest:
                    raise ValueError('Memory correction changed during review')
                db.execute('INSERT OR IGNORE INTO consolidated_sources(ref,body,corrections) VALUES(?,?,?)',
                           (ref, redact(json.dumps(source)), json.dumps(corrections)))
            signature = fingerprint({ref: original(known[ref]) for ref in refs})
            if db.execute('SELECT 1 FROM memory_threads WHERE signature=?', (signature,)).fetchone():
                continue
            for row in db.execute('SELECT id,refs FROM memory_threads WHERE retired=0').fetchall():
                if set(refs).intersection(json.loads(row['refs'])):
                    db.execute('UPDATE memory_threads SET retired=1 WHERE id=?', (row['id'],))
            db.execute('INSERT INTO memory_threads(signature,subject,refs,noted) VALUES(?,?,?,?)',
                       (signature, redact(value.subject.strip()), json.dumps(refs), now.isoformat()))
        db.execute('DELETE FROM memory_threads WHERE id NOT IN (SELECT id FROM memory_threads ORDER BY id DESC LIMIT 100)')
        self._prune(db)
        logger.debug('Memory consolidation accepted %s extractive thread proposals', len(values))

    @staticmethod
    def _prune(db):
        threads = list(db.execute('SELECT id,refs FROM memory_threads ORDER BY id'))
        links = {r[0]: json.loads(r[1]) for r in db.execute('SELECT ref,corrections FROM consolidated_sources')}
        while True:
            needed = {ref for row in threads for ref in json.loads(row['refs'])}
            pending = list(needed)
            while pending:
                for target in links.get(pending.pop(), {}).values():
                    if target not in needed:
                        needed.add(target)
                        pending.append(target)
            if len(needed) <= 800:
                break
            # Bound provenance too; evict an entire oldest thread rather than break its correction links.
            db.execute('DELETE FROM memory_threads WHERE id=?', (threads.pop(0)['id'],))
        for row in db.execute('SELECT ref FROM consolidated_sources').fetchall():
            if row[0] not in needed:
                db.execute('DELETE FROM consolidated_sources WHERE ref=?', (row[0],))

    @classmethod
    def correct(cls, db, old_ref, new_ref, source, subject):
        """Called inside the temporal correction transaction; never infer a correction."""
        cls.schema(db)
        if not db.execute('SELECT 1 FROM consolidated_sources WHERE ref=?', (old_ref,)).fetchone():
            return
        db.execute('INSERT OR IGNORE INTO consolidated_sources(ref,body) VALUES(?,?)',
                   (new_ref, redact(json.dumps(original(source)))))
        affected = set()
        for row in db.execute('SELECT ref,corrections FROM consolidated_sources').fetchall():
            links = json.loads(row['corrections'])
            if row['ref'] == old_ref or links.get(subject) == old_ref:
                links[subject] = new_ref
                affected.add(row['ref'])
                db.execute('UPDATE consolidated_sources SET corrections=? WHERE ref=?', (json.dumps(links), row['ref']))
        for row in db.execute('SELECT id,refs FROM memory_threads WHERE retired=0').fetchall():
            if affected.intersection(json.loads(row['refs'])):
                db.execute('UPDATE memory_threads SET retired=1 WHERE id=?', (row['id'],))
        cls._prune(db)

    def evidence(self, limit=4):
        if not config.COGNITION_ENABLED:
            return {}
        with self._db() as db:
            sources = {r['ref']: {**json.loads(r['body']), **({'memory_replacements': sorted(set(json.loads(r['corrections']).values()))}
                       if r['corrections'] != '{}' else {})} for r in db.execute('SELECT * FROM consolidated_sources')}
            rows = db.execute('SELECT * FROM memory_threads WHERE retired=0 ORDER BY id DESC LIMIT ?',
                              (max(1, min(20, limit)),)).fetchall()
        return {f"consolidation:{row['id']}": {'kind': 'memory_summary', 'source': 'inferred_grouping',
            'subject': row['subject'], 'evidence': json.loads(row['refs']), 'noted': row['noted'],
            'excerpts': [{**sources[ref], 'text': sources[ref]['text'][:600],
                          'question': sources[ref]['question'][:200],
                          'excerpt_truncated': len(sources[ref]['text']) > 600 or len(sources[ref]['question']) > 200}
                         for ref in json.loads(row['refs'])],
            'meaning': 'Extractive historical owner reports, not verified/current facts. Topic is inferred. '
                       'Preserve original dates, questions and uncertainty; a plan or answer proves no action. '
                       'Snapshots retain the reviewed original excerpt (text up to 1200, question up to 500 characters). '
                       'Truncated excerpts are incomplete; never infer missing qualifications.'}
            for row in rows if all(ref in sources for ref in json.loads(row['refs']))}

    def status(self):
        with self._db() as db:
            counts = {bool(r[0]): r[1] for r in db.execute('SELECT retired,COUNT(*) FROM memory_threads GROUP BY retired')}
            sources = db.execute('SELECT COUNT(*) FROM consolidated_sources').fetchone()[0]
        return {'active': counts.get(False, 0), 'retired': counts.get(True, 0), 'sources': sources,
                'thread_limit': 100, 'method': 'locally reviewed extractive grouping'}


consolidation = Consolidation(cognition)
