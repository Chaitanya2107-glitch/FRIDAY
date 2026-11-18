"""Private metadata-only notification learning, correlated with the original situation."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading

from services.mind.humour import PRIOR, DECAY

BUSY = {'study', 'class', 'sleep'}
CATEGORY = {'msg': 'chat', 'message': 'chat', 'social': 'chat', 'email': 'chat', 'promo': 'shopping',
            'shopping': 'shopping', 'call': 'calls', 'alarm': 'alarms'}


def bucket(category):
    return CATEGORY.get(category.lower(), 'other')


def score(package, category, importance, situation, belief=PRIOR, vip=(), urgent=()):
    protected = category in {'call', 'alarm', 'missed_call', 'voicemail'} or package in vip or package in urgent
    if protected:
        return dict(score=1.0, urgent=category in {'call', 'alarm', 'missed_call', 'voicemail'} or package in urgent, allow=True)
    a, b = belief
    value = max(0, min(1, .6 * a / (a + b) + .4 * max(0, min(5, importance)) / 5
                         - (.2 if situation in BUSY else 0)))
    return dict(score=round(value, 3), urgent=False, allow=situation not in BUSY or value >= .65)


class TriageStore:
    def __init__(self, path):
        self.path, self.lock = Path(path).absolute(), threading.RLock()

    @contextmanager
    def db(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA secure_delete=ON')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS triage_context(id INTEGER PRIMARY KEY, situation TEXT NOT NULL,start REAL NOT NULL,end REAL);
              CREATE TABLE IF NOT EXISTS triage_notifications(device TEXT NOT NULL,id TEXT NOT NULL,package TEXT NOT NULL,
                category TEXT NOT NULL,situation TEXT NOT NULL,created REAL NOT NULL,score REAL NOT NULL,
                outcome TEXT,context_id INTEGER,allow INTEGER NOT NULL,importance INTEGER NOT NULL DEFAULT 3,
                priority INTEGER NOT NULL DEFAULT 0,urgent INTEGER NOT NULL DEFAULT 0,alerted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(device,id));
              CREATE TABLE IF NOT EXISTS triage_beliefs(device TEXT NOT NULL,package TEXT NOT NULL,situation TEXT NOT NULL,
                alpha REAL NOT NULL,beta REAL NOT NULL,day TEXT NOT NULL,PRIMARY KEY(device,package,situation));
              CREATE TABLE IF NOT EXISTS triage_digests(context_id INTEGER PRIMARY KEY,state TEXT NOT NULL DEFAULT 'pending');
            ''')
            if 'importance' not in {row[1] for row in db.execute('PRAGMA table_info(triage_notifications)')}:
                db.execute('ALTER TABLE triage_notifications ADD COLUMN importance INTEGER NOT NULL DEFAULT 3')
            for column in ('priority', 'urgent', 'alerted'):
                if column not in {row[1] for row in db.execute('PRAGMA table_info(triage_notifications)')}:
                    db.execute(f'ALTER TABLE triage_notifications ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    yield db
            finally:
                db.close()

    def context(self, situation, now):
        if situation not in BUSY | {'free'}:
            raise ValueError('Unknown triage situation')
        with self.db() as db:
            row = db.execute('SELECT * FROM triage_context WHERE end IS NULL ORDER BY id DESC LIMIT 1').fetchone()
            if row and row['situation'] == situation:
                return row['id']
            if row:
                db.execute('UPDATE triage_context SET end=? WHERE id=?', (now.timestamp(), row['id']))
                if row['situation'] in BUSY:
                    db.execute('INSERT OR IGNORE INTO triage_digests(context_id) VALUES(?)', (row['id'],))
            cursor = db.execute('INSERT INTO triage_context(situation,start) VALUES(?,?)', (situation, now.timestamp()))
            db.execute('DELETE FROM triage_notifications WHERE created<?', (now.timestamp() - 30 * 86400,))
            return cursor.lastrowid

    def belief(self, device, package, situation, now):
        with self.db() as db:
            row = db.execute('SELECT * FROM triage_beliefs WHERE device=? AND package=? AND situation=?',
                             (device, package, situation)).fetchone()
            if not row:
                return PRIOR
            days = max(0, (now.date() - datetime.fromisoformat(row['day']).date()).days)
            a, b = (PRIOR[0] + (row['alpha'] - PRIOR[0]) * DECAY ** days,
                    PRIOR[1] + (row['beta'] - PRIOR[1]) * DECAY ** days)
            if days:
                db.execute('UPDATE triage_beliefs SET alpha=?,beta=?,day=? WHERE device=? AND package=? AND situation=?',
                           (a, b, now.date().isoformat(), device, package, situation))
            return a, b

    def ingest(self, records, now=None, *, vip=(), urgent=()):
        now = now or datetime.now()
        for record in sorted(records, key=lambda r: (r['timestamp'], r['payload'].get('event', 'posted') != 'posted')):
            if record['type'] != 'notifications':
                continue
            p, device = record['payload'], record['device']
            identity = p.get('notification_id', record['id'])
            event = p.get('event', 'posted')
            with self.db() as db:
                row = db.execute('SELECT * FROM triage_notifications WHERE device=? AND id=?', (device, identity)).fetchone()
                if event == 'posted':
                    if row:
                        continue
                    context = db.execute('SELECT id,situation FROM triage_context WHERE start<=? AND (end IS NULL OR end>?) '
                                         'ORDER BY id DESC LIMIT 1', (p['time'], p['time'])).fetchone()
                    situation = context['situation'] if context else 'unknown'
                    # Close the DB before a belief read to avoid nested SQLite writer transactions.
                    existing = db.execute('SELECT alpha,beta,day FROM triage_beliefs WHERE device=? AND package=? AND situation=?',
                                          (device, p['package'], situation)).fetchone()
                    belief = PRIOR
                    if existing:
                        days = max(0, (now.date() - datetime.fromisoformat(existing['day']).date()).days)
                        belief = tuple(prior + (existing[i] - prior) * DECAY ** days for i, prior in enumerate(PRIOR))
                    ranked = score(p['package'], p['category'], p.get('importance', 3), situation, belief, vip, urgent)
                    priority = p['category'] in {'call', 'alarm', 'missed_call', 'voicemail'} or p['package'] in vip or p['package'] in urgent
                    db.execute('INSERT INTO triage_notifications VALUES(?,?,?,?,?,?,?,NULL,?,?,?,?,?,0)',
                               (device, identity, p['package'], p['category'], situation, p['time'], ranked['score'],
                                context['id'] if context else None, int(ranked['allow']), p.get('importance', 3), int(priority), int(ranked['urgent'])))
                elif row and row['package'] == p['package'] and row['outcome'] is None:
                    reason = p.get('reason')
                    outcome = 'opened' if event == 'opened' and reason == 1 else 'dismissed' if event == 'dismissed' and reason in {2, 3} else None
                    if outcome is None:
                        continue  # Removal by the app, timeout or our own snooze is not owner rejection.
                    days = 0
                    belief = db.execute('SELECT alpha,beta,day FROM triage_beliefs WHERE device=? AND package=? AND situation=?',
                                        (device, row['package'], row['situation'])).fetchone()
                    if belief:
                        days = max(0, (now.date() - datetime.fromisoformat(belief['day']).date()).days)
                    a, b = (tuple(prior + (belief[i] - prior) * DECAY ** days for i, prior in enumerate(PRIOR)) if belief else PRIOR)
                    a += outcome == 'opened'; b += outcome == 'dismissed'
                    db.execute('INSERT OR REPLACE INTO triage_beliefs VALUES(?,?,?,?,?,?)',
                               (device, row['package'], row['situation'], a, b, now.date().isoformat()))
                    db.execute('UPDATE triage_notifications SET outcome=? WHERE device=? AND id=?', (outcome, device, identity))

    def blocked(self, device, situation, now, *, vip=(), urgent=()):
        with self.db() as db:
            rows = db.execute('SELECT package,category,MAX(importance) AS importance FROM triage_notifications WHERE device=? AND created>? '
                              'GROUP BY package,category', (device, now.timestamp() - 86400)).fetchall()
        return list(dict.fromkeys(r['package'] for r in rows if not score(r['package'], r['category'], r['importance'], situation,
                self.belief(device, r['package'], situation, now), vip, urgent)['allow']))[:30]

    def digests(self, now):
        with self.db() as db:
            contexts = db.execute("SELECT c.* FROM triage_context c JOIN triage_digests d ON c.id=d.context_id "
                                  "WHERE d.state='pending' AND c.end>? ORDER BY c.id", (now.timestamp() - 86400,)).fetchall()
            result = []
            for context in contexts:
                rows = db.execute('SELECT category,COUNT(*) AS n FROM triage_notifications WHERE context_id=? AND allow=0 GROUP BY category',
                                  (context['id'],)).fetchall()
                counts = {}
                for row in rows:
                    key = bucket(row['category']); counts[key] = counts.get(key, 0) + row['n']
                if counts:
                    result.append(dict(id=context['id'], situation=context['situation'], counts=counts, total=sum(counts.values())))
            return result

    def delivered(self, identity):
        with self.db() as db:
            db.execute("UPDATE triage_digests SET state='submitted' WHERE context_id=?", (identity,))

    def alerts(self, now):
        with self.db() as db:
            return [dict(row) for row in db.execute('SELECT device,id,package,category,situation,urgent FROM triage_notifications '
                    'WHERE priority=1 AND alerted=0 AND created>=? ORDER BY urgent DESC,created LIMIT 10', (now.timestamp() - 120,))]

    def alerted(self, device, identity):
        with self.db() as db:
            db.execute('UPDATE triage_notifications SET alerted=1 WHERE device=? AND id=?', (device, identity))

    def decay(self, now):
        with self.db() as db:
            rows = db.execute('SELECT device,package,situation FROM triage_beliefs WHERE day<>?', (now.date().isoformat(),)).fetchall()
        for row in rows:
            self.belief(*row, now)

    def forget(self, device):
        with self.db() as db:
            db.execute('DELETE FROM triage_notifications WHERE device=?', (device,))
            db.execute('DELETE FROM triage_beliefs WHERE device=?', (device,))
            db.execute('DELETE FROM triage_digests')
            db.execute('DELETE FROM triage_context')


def store(path=None):
    from services.activity.timeline import DEFAULT_PATH
    return TriageStore(path or Path(DEFAULT_PATH).with_name('triage.db'))
