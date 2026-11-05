"""SQLite outbox state for explicit reminders; delivery is an acknowledged outcome."""

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from contextlib import closing
from pathlib import Path

LEASE_SECONDS = 180
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Claim:
    reminder: object
    token: str
    attempts: int
    desktop_status: str
    telegram_status: str


class DeliveryState:
    def _delivery_schema(self, conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS reminder_delivery (
            reminder_id INTEGER PRIMARY KEY, snapshot_text TEXT NOT NULL, snapshot_due REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', token TEXT, lease_until REAL,
            attempts INTEGER NOT NULL DEFAULT 0, next_retry REAL,
            reason TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '[]',
            decision_id TEXT NOT NULL DEFAULT '', fingerprint TEXT NOT NULL DEFAULT '',
            desktop_status TEXT NOT NULL DEFAULT 'pending', telegram_status TEXT NOT NULL DEFAULT 'pending',
            speech_status TEXT NOT NULL DEFAULT 'pending', updated_at REAL NOT NULL
        )""")

    def _claim_due(self, now_ts, limit=1000):
        from services.reminders.service import Reminder
        with self._connect() as conn:
            self._delivery_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            # A reschedule invalidates both a review and all previous channel acknowledgements.
            conn.execute("""DELETE FROM reminder_delivery WHERE NOT EXISTS
                (SELECT 1 FROM reminders r WHERE r.id=reminder_id
                 AND r.text=snapshot_text AND r.due_at=snapshot_due)""")
            conn.execute("""INSERT OR IGNORE INTO reminder_delivery
                (reminder_id,snapshot_text,snapshot_due,updated_at)
                SELECT id,text,due_at,? FROM reminders WHERE delivered_at IS NULL AND due_at<=?""",
                         (now_ts, now_ts))
            # Crashing while submitting has an unknowable outcome; never silently duplicate it.
            conn.execute("""UPDATE reminder_delivery SET status='uncertain',token=NULL,
                reason='Submission interrupted; delivery may have occurred. Explicit retry required.',
                next_retry=NULL,updated_at=? WHERE status='submitting' AND lease_until<=?""", (now_ts, now_ts))
            conn.execute("""UPDATE reminder_delivery SET status='retry',token=NULL,next_retry=?,updated_at=?
                WHERE status='reviewing' AND lease_until<=?""", (now_ts, now_ts, now_ts))
            rows = conn.execute("""SELECT r.id,r.text,r.due_at,d.attempts,d.desktop_status,d.telegram_status
                FROM reminders r JOIN reminder_delivery d ON r.id=d.reminder_id
                WHERE r.delivered_at IS NULL AND r.due_at<=?
                AND d.status IN ('pending','retry','deferred','withheld')
                AND d.desktop_status!='uncertain' AND d.telegram_status!='uncertain'
                AND (d.next_retry IS NULL OR d.next_retry<=?) ORDER BY r.due_at,r.id LIMIT ?""",
                (now_ts, now_ts, limit)).fetchall()
            claims = []
            for row in rows:
                token = uuid.uuid4().hex
                conn.execute("""UPDATE reminder_delivery SET status='reviewing',token=?,lease_until=?,
                    updated_at=? WHERE reminder_id=?""", (token, now_ts + LEASE_SECONDS, now_ts, row[0]))
                claims.append(Claim(Reminder(*row[:3]), token, row[3], row[4], row[5]))
        return claims

    def _active(self, claim):
        with self._connect() as conn:
            return bool(conn.execute("""SELECT 1 FROM reminders r JOIN reminder_delivery d ON r.id=d.reminder_id
                WHERE r.id=? AND r.text=? AND r.due_at=? AND r.delivered_at IS NULL
                AND d.token=? AND d.lease_until>?""",
                (claim.reminder.id, claim.reminder.text, claim.reminder.due_at, claim.token, time.time())).fetchone())

    def _state(self, claim, **values):
        """CAS on token AND source snapshot: stale workers cannot acknowledge newer owner intent."""
        values['updated_at'] = time.time()
        with self._connect() as conn:
            return conn.execute(f"""UPDATE reminder_delivery SET {','.join(k+'=?' for k in values)}
                WHERE reminder_id=? AND token=? AND EXISTS (SELECT 1 FROM reminders r
                WHERE r.id=reminder_id AND r.text=snapshot_text AND r.due_at=snapshot_due)""",
                (*values.values(), claim.reminder.id, claim.token)).rowcount == 1

    def _decision(self, claim, review):
        return self._state(claim, reason=review.reason[:1000], evidence=json.dumps(review.evidence, default=str),
                           decision_id=str(review.decision_id or ''), fingerprint=review.fingerprint)

    def _hold(self, claim, review):
        status = {'defer': 'deferred', 'suppress': 'withheld'}.get(review.action, 'retry')
        delay = max(5, min(86400, float(review.retry_after_seconds or 60)))
        with self._connect() as conn:
            uncertain = conn.execute("""SELECT 1 FROM reminder_delivery WHERE reminder_id=? AND token=?
                AND (desktop_status='uncertain' OR telegram_status='uncertain')""",
                                    (claim.reminder.id, claim.token)).fetchone()
        if uncertain:
            self._finish_decision(claim, 'uncertain')
            self._state(claim, status='uncertain', token=None, next_retry=None,
                        reason='Submission was uncertain before context changed. Explicit retry required.')
            return
        if self._state(claim, status=status, next_retry=time.time() + delay):
            self._finish_decision(claim, {'deferred': 'deferred', 'withheld': 'suppressed', 'retry': 'unavailable'}[status])
            self._state(claim, token=None)

    def _finish_decision(self, claim, status):
        from services.mind.cognition import cognition
        with self._connect() as conn:
            row = conn.execute("""SELECT decision_id FROM reminder_delivery WHERE reminder_id=? AND token=?
                AND EXISTS (SELECT 1 FROM reminders r WHERE r.id=reminder_id
                AND r.text=snapshot_text AND r.due_at=snapshot_due)""",
                               (claim.reminder.id, claim.token)).fetchone()
        if row and str(row[0]).isdecimal():
            cognition.finish(int(row[0]), status)

    def _failed(self, claim, reason):
        attempts = claim.attempts + 1
        self._finish_decision(claim, 'failed')
        self._state(claim, status='failed' if attempts >= MAX_ATTEMPTS else 'retry',
                    attempts=attempts, reason=reason, token=None,
                    next_retry=None if attempts >= MAX_ATTEMPTS else time.time() + min(3600, 30 * 2 ** (attempts - 1)))

    def _interrupted(self, claim):
        with self._connect() as conn:
            submitting = conn.execute("SELECT status,desktop_status,telegram_status FROM reminder_delivery WHERE reminder_id=? AND token=?",
                                      (claim.reminder.id, claim.token)).fetchone()
        if submitting and (submitting[0] == 'submitting' or 'uncertain' in submitting[1:]):
            self._finish_decision(claim, 'uncertain')
            self._state(claim, status='uncertain', token=None, next_retry=None,
                        reason='Transport interrupted; delivery may have occurred. Explicit retry required.')
        elif submitting and submitting[0] != 'delivered':
            self._finish_decision(claim, 'unavailable')
            self._state(claim, status='retry', token=None, next_retry=time.time() + 60,
                        reason='Reminder review or transport preparation unavailable')

    def _complete(self, claim):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute("""UPDATE reminders SET delivered_at=? WHERE id=? AND text=? AND due_at=?
                AND delivered_at IS NULL AND EXISTS (SELECT 1 FROM reminder_delivery d
                WHERE d.reminder_id=reminders.id AND d.token=? AND d.desktop_status='submitted'
                AND d.telegram_status IN ('submitted','skipped'))""",
                (time.time(), claim.reminder.id, claim.reminder.text, claim.reminder.due_at, claim.token)).rowcount
            if updated:
                conn.execute("UPDATE reminder_delivery SET status='delivered',next_retry=NULL WHERE reminder_id=? AND token=?",
                             (claim.reminder.id, claim.token))
        if updated:
            self._finish_decision(claim, 'submitted')
        return bool(updated)

    def delivery_status(self, limit=20):
        path = Path(self.db_path)
        if not path.exists():
            return []
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            # Read-only status does not migrate or write the database.
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='reminder_delivery'").fetchone():
                return []
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""SELECT d.reminder_id AS id,r.due_at,r.delivered_at,d.status,d.attempts,
                d.next_retry,d.reason,d.evidence,d.decision_id,d.fingerprint,d.desktop_status,d.telegram_status,
                d.speech_status,d.updated_at FROM reminder_delivery d JOIN reminders r ON r.id=d.reminder_id
                AND r.text=d.snapshot_text AND r.due_at=d.snapshot_due
                ORDER BY d.updated_at DESC LIMIT ?""", (max(1, min(100, int(limit))),)).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row['evidence'] = json.loads(row['evidence'])
        return result

    def retry_failed(self):
        with self._connect() as conn:
            self._delivery_schema(conn)
            return conn.execute("""UPDATE reminder_delivery SET status='retry',attempts=0,next_retry=?,
                token=NULL,reason='Owner requested retry',updated_at=?,
                desktop_status=CASE WHEN desktop_status='uncertain' THEN 'pending' ELSE desktop_status END,
                telegram_status=CASE WHEN telegram_status='uncertain' THEN 'pending' ELSE telegram_status END WHERE status IN
                ('failed','uncertain','withheld','deferred','retry') AND EXISTS
                (SELECT 1 FROM reminders r WHERE r.id=reminder_id AND r.delivered_at IS NULL)""",
                (time.time(), time.time())).rowcount
