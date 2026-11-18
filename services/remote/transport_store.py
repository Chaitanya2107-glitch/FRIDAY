"""Durable, device-bound delivery and at-most-once command receipts. No chat log."""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from .security import Denied

MAX_TTL = 86400
DEFAULT_TTL = 900
MESSAGE_TYPES = {'text', 'link', 'file', 'ring', 'approval', 'notice', 'notice_cancel', 'triage_policy', 'phone_mode'}
QUEUABLE = {'start_focus', 'stop_focus', 'set_scene', 'add_note', 'ring_laptop', 'phone_handoff'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', value):
        raise Denied('invalid_identity')
    return value


def expiry(created, expires, now):
    if (type(created) not in (int, float) or type(expires) not in (int, float)
            or not math.isfinite(created) or not math.isfinite(expires)
            or created > now + 60 or not 0 < expires - created <= MAX_TTL or expires <= now):
        raise Denied('expired_message')


class TransportStore:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path).absolute(), clock
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS outbox (
                  id TEXT PRIMARY KEY, device TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL,
                  created REAL NOT NULL, expires_at REAL NOT NULL, delivered REAL);
                CREATE INDEX IF NOT EXISTS inbox_device ON outbox(device,created);
                CREATE TABLE IF NOT EXISTS receipts (
                  device TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL, expires_at REAL NOT NULL,
                  state TEXT NOT NULL, result TEXT, PRIMARY KEY(device,id));
                CREATE TABLE IF NOT EXISTS inbox_seen(device TEXT PRIMARY KEY, time REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS approval_keys(device TEXT PRIMARY KEY, public_key TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS phone_approvals (
                  id TEXT PRIMARY KEY, device TEXT NOT NULL, action TEXT NOT NULL, canonical TEXT NOT NULL,
                  expires_at REAL NOT NULL, epoch INTEGER NOT NULL, result TEXT, consumed INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS transfers (
                  id TEXT PRIMARY KEY, device TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL,
                  sha256 TEXT NOT NULL, offset INTEGER NOT NULL, direction TEXT NOT NULL,
                  expires_at REAL NOT NULL, complete INTEGER NOT NULL DEFAULT 0);
            ''')

    @contextmanager
    def db(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA secure_delete=ON')
            try:
                with db:
                    yield db
            finally:
                db.close()

    def put(self, device, kind, payload, ttl=DEFAULT_TTL):
        if kind not in MESSAGE_TYPES or type(ttl) not in (int, float) or not 0 < ttl <= MAX_TTL:
            raise Denied('invalid_message')
        raw = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        if len(raw.encode()) > 8192:
            raise Denied('message_too_large')
        now, identity = self.clock(), uuid.uuid4().hex
        with self.db() as db:
            self.purge(db)
            if db.execute('SELECT count(*) FROM outbox WHERE device=? AND delivered IS NULL', (device,)).fetchone()[0] >= 200:
                raise Denied('outbox_full')
            db.execute('INSERT INTO outbox VALUES (?,?,?,?,?,?,NULL)', (identity, device, kind, raw, now, now + ttl))
        return identity

    def purge(self, db):
        db.execute('DELETE FROM outbox WHERE expires_at<=?', (self.clock(),))
        # Keep command tombstones after expiry: a delayed retry must not execute again.
        db.execute('DELETE FROM receipts WHERE expires_at<?', (self.clock() - MAX_TTL,))
        db.execute('DELETE FROM phone_approvals WHERE expires_at<?', (self.clock() - MAX_TTL,))

    def inbox(self, device):
        with self.db() as db:
            self.purge(db)
            db.execute('INSERT OR REPLACE INTO inbox_seen VALUES (?,?)', (device, self.clock()))
            rows = db.execute('SELECT id,type,payload,created,expires_at FROM outbox '
                              'WHERE device=? AND delivered IS NULL ORDER BY created,rowid LIMIT 10', (device,)).fetchall()
        return [dict(row, payload=json.loads(row['payload'])) for row in rows]

    def ack(self, device, identities):
        if not isinstance(identities, list) or not 1 <= len(identities) <= 10:
            raise Denied('invalid_ack')
        with self.db() as db:
            self.purge(db)
            for identity in identities:
                identifier(identity)
                db.execute('UPDATE outbox SET delivered=? WHERE device=? AND id=? AND expires_at>?',
                           (self.clock(), device, identity, self.clock()))
        return dict(acknowledged=identities)

    def reachable(self, device):
        with self.db() as db:
            row = db.execute('SELECT time FROM inbox_seen WHERE device=?', (device,)).fetchone()
        return bool(row and self.clock() - row['time'] < 75)

    def claim(self, device, body):
        identifier(body['id'])
        expiry(body['created'], body['expires_at'], self.clock())
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest,state,result FROM receipts WHERE device=? AND id=?', (device, body['id'])).fetchone()
            if row:
                if row['digest'] != digest:
                    raise Denied('queue_identity_conflict')
                return json.loads(row['result']) if row['state'] == 'completed' else dict(result='uncertain')
            db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,NULL)',
                       (device, body['id'], digest, body['expires_at'], 'running'))
        return None

    def finish(self, device, identity, result):
        with self.db() as db:
            db.execute('UPDATE receipts SET state=?,result=? WHERE device=? AND id=?',
                       ('completed', json.dumps(result, allow_nan=False), device, identity))

    def forget(self, device):
        with self.db() as db:
            for table in ('outbox', 'inbox_seen', 'approval_keys', 'phone_approvals', 'transfers'):
                db.execute(f'DELETE FROM {table} WHERE device=?', (device,))
            # Keep only receipt hashes/tombstones so stale queued actions cannot resurrect.
            db.execute("UPDATE receipts SET result=NULL,state='running' WHERE device=?", (device,))
