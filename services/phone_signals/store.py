"""Per-device SQLite telemetry with retention, dedupe and forget fencing."""
import json
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager

from services.remote.security import Denied


class PhoneStore:
    def __init__(self, path: Path, *, clock=time.time, retention_days=30):
        if type(retention_days) is not int or not 1 <= retention_days <= 365:
            raise ValueError('Retention must be 1–365 days.')
        self.path, self.clock, self.days = Path(path).absolute(), clock, retention_days
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA secure_delete=ON')
        db.execute('CREATE TABLE IF NOT EXISTS phone_events (device TEXT NOT NULL, id TEXT NOT NULL, '
                   'timestamp REAL NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(device,id))')
        db.execute('CREATE INDEX IF NOT EXISTS phone_time ON phone_events(timestamp)')
        db.execute('CREATE TABLE IF NOT EXISTS phones (device TEXT PRIMARY KEY, generation INTEGER NOT NULL DEFAULT 0, '
                   'heartbeat REAL, metadata TEXT)')
        try:
            with db:
                yield db
        finally:
            db.close()

    def purge(self, db):
        cutoff = self.clock() - self.days * 86400
        db.execute('DELETE FROM phone_events WHERE timestamp < ?', (cutoff,))
        db.execute('UPDATE phones SET heartbeat=NULL, metadata=NULL WHERE heartbeat < ?', (cutoff,))

    def generation(self, db, device):
        db.execute('INSERT OR IGNORE INTO phones(device) VALUES(?)', (device,))
        return db.execute('SELECT generation FROM phones WHERE device=?', (device,)).fetchone()[0]

    def ingest(self, device, rows, generation):
        stored, acknowledged = [], []
        now = self.clock()
        with self.lock, self.connect() as db:
            self.purge(db)
            if generation != self.generation(db, device):
                raise Denied('phone_generation')
            for row in rows:
                if row['timestamp'] > now + 300 or row['timestamp'] < now - 31 * 86400:
                    raise Denied('phone_time')
                if row['type'] == 'app_usage' and (row['payload']['end'] > now + 300 or row['payload']['start'] < now - 31 * 86400):
                    raise Denied('phone_time')
                if row['type'] == 'app_usage' and abs(row['payload']['end'] - row['timestamp']) > 300:
                    raise Denied('phone_time')
                observed = row['payload'].get('start', row['payload'].get('time', row['timestamp']))
                if observed > now + 300 or observed < now - 31 * 86400:
                    raise Denied('phone_time')
                acknowledged.append(row['id'])
                if min(observed, row['timestamp']) < now - self.days * 86400:
                    continue  # Acknowledge expired backlog without retaining it.
                encoded = json.dumps(row['payload'], sort_keys=True, separators=(',', ':'), allow_nan=False)
                previous = db.execute('SELECT timestamp,type,payload FROM phone_events WHERE device=? AND id=?', (device, row['id'])).fetchone()
                if previous:
                    if previous != (row['timestamp'], row['type'], encoded):
                        raise Denied('phone_id_conflict')
                    continue
                db.execute('INSERT INTO phone_events VALUES(?,?,?,?,?)', (device, row['id'], row['timestamp'], row['type'], encoded))
                stored.append(row)
        return acknowledged, stored

    def heartbeat(self, device, metadata):
        with self.lock, self.connect() as db:
            self.purge(db)
            generation = self.generation(db, device)
            db.execute('UPDATE phones SET heartbeat=?,metadata=? WHERE device=?',
                       (self.clock(), json.dumps(metadata, allow_nan=False), device))
        return generation

    def status(self, device):
        with self.lock, self.connect() as db:
            self.purge(db)
            row = db.execute('SELECT heartbeat,metadata,generation FROM phones WHERE device=?', (device,)).fetchone()
            count = db.execute('SELECT COUNT(*) FROM phone_events WHERE device=?', (device,)).fetchone()[0]
        return dict(last_heartbeat=row[0] if row else None, metadata=json.loads(row[1]) if row and row[1] else None,
                    generation=row[2] if row else 0, stored_events=count, retention_days=self.days)

    def forget(self, device):
        with self.lock, self.connect() as db:
            generation = self.generation(db, device) + 1
            db.execute('DELETE FROM phone_events WHERE device=?', (device,))
            db.execute('UPDATE phones SET generation=?,heartbeat=NULL,metadata=NULL WHERE device=?', (generation, device))
        # Only an opaque generation tombstone remains; old in-flight batches cannot resurrect data.
        return generation
