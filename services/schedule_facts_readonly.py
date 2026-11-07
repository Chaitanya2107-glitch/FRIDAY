"""Read existing schedule authority without initializing or migrating any DB."""
from contextlib import contextmanager
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3

from services.memory.schedule import Fact, parse
from services.mind.cognition import cognition, redact
from services.mind.reasoning_store import fingerprint


@contextmanager
def readonly(path):
    path = Path(path).resolve()
    if not path.is_file():
        yield None
        return
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only = ON')
        yield db
    finally:
        db.close()


def facts(memory_path=None, cognition_path=None):
    from services.memory.semantic import semantic_memory
    from services.proactive import timetable
    known, result = {}, []
    with readonly(memory_path or semantic_memory.db_path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} if db else set()
        for table, prefix in [('memories', 'memory'), ('schedule_facts', 'schedule')]:
            if table not in tables:
                continue
            source = 'source' if table == 'memories' else "'told' AS source"
            for index, row in enumerate(db.execute(f'SELECT id, text, created_at, {source} FROM {table} ORDER BY id DESC')):
                ref = f"{prefix}:{row['id']}"
                if index < 20 and row['source'] != 'episode':
                    known[ref] = dict(kind='owner_fact' if row['source'] == 'told' else 'learned_guess',
                        quote=redact(row['text'][:1200]), noted=row['created_at'],
                        certainty='confirmed' if row['source'] == 'told' else 'uncertain')
                if row['source'] == 'told':
                    try:
                        fact = parse(row['text'], datetime.fromisoformat(row['created_at']), ref)
                    except (ValueError, TypeError):
                        continue
                    if fact:
                        result.append(fact)
    with readonly(cognition_path or cognition.path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} if db else set()
        if 'reasoning_conclusions' not in tables:
            return sorted(result, key=lambda f: (f.noted.timestamp(), f.key), reverse=True)
        if 'reasoning_facts' in tables:
            for row in db.execute('SELECT id, quote, certainty, noted FROM reasoning_facts WHERE active=1'):
                ref = f"reasoning_fact:{row['id']}"
                known[ref] = dict(kind='owner_fact', id=ref, quote=redact(row['quote']),
                                  certainty=row['certainty'], noted=row['noted'])
        known['timetable'] = dict(kind='weekly_template', classes=timetable.load()[:40])
        for row in db.execute("SELECT id, body, refs, noted FROM reasoning_conclusions WHERE status='applied'"):
            body, refs = json.loads(row['body']), json.loads(row['refs'])
            effect = body['effect']
            if effect['type'] != 'class_availability':
                continue
            if any(not (ref == 'timetable' or ref.startswith(('reasoning_fact:', 'memory:', 'schedule:'))) for ref in refs):
                raise ValueError('Unsupported applied class constraint; schedule unavailable')
            if any(ref not in known or fingerprint(known[ref]) != stamp for ref, stamp in refs.items()):
                continue  # The existing authority also rejects changed/deleted evidence.
            if type(effect['available']) is not bool or not refs:
                raise ValueError('Invalid applied class constraint')
            result.append(Fact(f"reasoning:{row['id']}", body['text'], datetime.fromisoformat(row['noted']),
                date.fromisoformat(body['start']), date.fromisoformat(body['end']), effect['available'], effect['subject']))
    return sorted(result, key=lambda f: (f.noted.timestamp(), f.key), reverse=True)
