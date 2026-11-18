"""Explicitly private commitment storage owned by TemporalMemory, never its evidence APIs."""
from contextlib import contextmanager
from datetime import datetime
import json
import math
import uuid

from .goals_parser import validate


def stamp(now=None):
    return (now or datetime.now()).timestamp() if not isinstance(now, (int, float)) else float(now)


def schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS private_coaching_sources(id TEXT PRIMARY KEY,text TEXT NOT NULL,created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS private_coaching_commitments(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,
        source_key TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS private_coaching_revisions(commitment_id INTEGER NOT NULL,revision INTEGER NOT NULL,
        source_key TEXT NOT NULL,body TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(commitment_id,revision));
      CREATE TABLE IF NOT EXISTS private_goal_logs(id TEXT PRIMARY KEY,commitment_id INTEGER NOT NULL,value REAL NOT NULL,
        at REAL NOT NULL,source_links TEXT NOT NULL DEFAULT '[]');
      CREATE TABLE IF NOT EXISTS private_goal_marks(key TEXT PRIMARY KEY,at REAL NOT NULL);
    ''')


@contextmanager
def database(memory):
    with memory.store._lock, memory.store._connect() as db:
        db.execute('PRAGMA secure_delete=ON')
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        yield db


def row(value):
    return {key: value[key] for key in ('id', 'kind', 'source_key', 'revision', 'created', 'updated')} | {'definition': json.loads(value['body'])}


def commitments(memory, kind='goal'):
    if kind not in {'goal', 'study_block', None}:
        raise ValueError('Unknown private commitment kind.')
    with database(memory) as db:
        values = db.execute('SELECT * FROM private_coaching_commitments' + (' WHERE kind=?' if kind else '') + ' ORDER BY id',
                            (kind,) if kind else ()).fetchall()
    return [row(value) for value in values]


def save(memory, definition, source, *, kind='goal', identity=None, expected_revision=None, now=None):
    if kind == 'goal':
        validate(definition)
    elif kind == 'study_block':
        if set(definition) != {'goal_id', 'goal_revision', 'start', 'end'} or type(definition['goal_id']) is not int or type(definition['goal_revision']) is not int:
            raise ValueError('Invalid study-block source.')
        start, end = datetime.fromisoformat(definition['start']), datetime.fromisoformat(definition['end'])
        if not 300 <= (end - start).total_seconds() <= 14400:
            raise ValueError('Invalid study-block bounds.')
    else:
        raise ValueError('Unknown private commitment kind.')
    if not isinstance(source, str) or not 1 <= len(source.strip()) <= 2000 or any(ord(c) < 32 and c not in '\n\t' for c in source):
        raise ValueError('A confirmed local source is required.')
    body = json.dumps(definition, sort_keys=True, allow_nan=False)
    if len(body.encode()) > 8000:
        raise ValueError('Private commitment is too large.')
    at, key = stamp(now), 'coaching_source:' + uuid.uuid4().hex
    with database(memory) as db:
        if kind == 'study_block':
            goal = db.execute("SELECT revision FROM private_coaching_commitments WHERE id=? AND kind='goal'", (definition['goal_id'],)).fetchone()
            if not goal or goal['revision'] != definition['goal_revision']:
                raise ValueError('The goal changed. Request a fresh block proposal.')
            for existing in db.execute("SELECT body FROM private_coaching_commitments WHERE kind='study_block'"):
                planned = json.loads(existing['body'])
                if definition['start'] < planned['end'] and definition['end'] > planned['start']:
                    raise ValueError('This private study block now overlaps another block.')
        old = db.execute('SELECT * FROM private_coaching_commitments WHERE id=?', (identity,)).fetchone() if identity else None
        if identity is not None and (not old or old['kind'] != kind or expected_revision != old['revision']):
            raise ValueError('The goal changed. Review a fresh proposal.')
        if not old and db.execute('SELECT COUNT(*) FROM private_coaching_commitments WHERE kind=?', (kind,)).fetchone()[0] >= (100 if kind == 'goal' else 500):
            raise ValueError('Private commitment storage is full; remove an old goal or block first.')
        db.execute('INSERT INTO private_coaching_sources VALUES(?,?,?)', (key, source, at))
        revision = old['revision'] + 1 if old else 1
        if old:
            db.execute('UPDATE private_coaching_commitments SET source_key=?,body=?,revision=?,updated=? WHERE id=?',
                       (key, body, revision, at, identity))
        else:
            identity = db.execute('INSERT INTO private_coaching_commitments(kind,source_key,body,revision,created,updated) VALUES(?,?,?,?,?,?)',
                                  (kind, key, body, revision, at, at)).lastrowid
        db.execute('INSERT INTO private_coaching_revisions VALUES(?,?,?,?,?)', (identity, revision, key, body, at))
        result = row(db.execute('SELECT * FROM private_coaching_commitments WHERE id=?', (identity,)).fetchone())
    return result


def logs(memory, identity):
    with database(memory) as db:
        values = db.execute('SELECT * FROM private_goal_logs WHERE commitment_id=? ORDER BY at,id', (identity,)).fetchall()
    return [dict(value, source_links=json.loads(value['source_links'])) for value in values]


def log(memory, identity, value, *, event_id=None, now=None, source_links=()):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1000000:
        raise ValueError('Log a positive amount up to one million.')
    if event_id is not None and (not isinstance(event_id, str) or not 8 <= len(event_id) <= 100 or not all(c.isalnum() or c in '_-' for c in event_id)):
        raise ValueError('Use a valid log receipt id.')
    identity, key, at = int(identity), event_id or uuid.uuid4().hex, stamp(now)
    with database(memory) as db:
        found = db.execute("SELECT * FROM private_coaching_commitments WHERE id=? AND kind='goal'", (identity,)).fetchone()
        if not found or json.loads(found['body'])['source']['kind'] != 'manual':
            raise ValueError('This goal uses automatic measurement. Confirm a manual source before logging.')
        old = db.execute('SELECT * FROM private_goal_logs WHERE id=?', (key,)).fetchone()
        if old and (old['commitment_id'] != identity or old['value'] != value):
            raise ValueError('A log receipt cannot be reused for a different amount or goal.')
        if not old:
            db.execute('INSERT INTO private_goal_logs VALUES(?,?,?,?,?)', (key, identity, value, at, json.dumps(list(source_links))))
    return key


def linked(value, device):
    if isinstance(value, dict):
        devices = value.get('devices')
        return value.get('device') == device or isinstance(devices, list) and device in devices or any(linked(v, device) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(linked(item, device) for item in value)
    return isinstance(value, str) and (value == 'phone:' + device or value.startswith('phone:' + device + ':'))


def forget_phone(memory, device):
    with database(memory) as db:
        for value in db.execute('SELECT id,source_links FROM private_goal_logs').fetchall():
            if linked(json.loads(value['source_links']), device):
                db.execute('DELETE FROM private_goal_logs WHERE id=?', (value['id'],))
        for value in db.execute("SELECT * FROM private_coaching_commitments WHERE kind='goal'").fetchall():
            definition = json.loads(value['body'])
            if definition['source'].get('device') == device:
                definition['source_suspended'] = True
                db.execute('UPDATE private_coaching_commitments SET body=? WHERE id=?', (json.dumps(definition, sort_keys=True), value['id']))
        db.execute("DELETE FROM private_goal_marks WHERE key NOT LIKE 'goal-weekly:%'")


def marked(memory, key):
    with database(memory) as db:
        return db.execute('SELECT 1 FROM private_goal_marks WHERE key=?', (key,)).fetchone() is not None


def mark(memory, key, now=None):
    with database(memory) as db:
        inserted = db.execute('INSERT OR IGNORE INTO private_goal_marks VALUES(?,?)', (key, stamp(now))).rowcount
        db.execute('DELETE FROM private_goal_marks WHERE at<?', (stamp(now) - 366 * 86400,))
    return bool(inserted)
