"""Bounded scalar health receipts, independent of observation-event retention."""

from contextlib import contextmanager
import json
import math
import sqlite3
import time

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition

HISTORY_LIMIT = 100
STATES = {'starting', 'waiting', 'reviewing', 'running', 'completed', 'unavailable',
          'cancelled', 'failed', 'stopped', 'interrupted'}
PHASES = {'startup', 'context', 'generation', 'validation', 'critique', 'source_check', 'persistence'}
REASONS = {'starting', 'in_progress', 'ready', 'silence', 'accepted', 'disabled', 'stopped', 'cancelled',
           'startup_failed', 'check_failed', 'review_failed', 'not_checked', 'unavailable',
           'cognition_disabled', 'reasoning_disabled', 'review_disabled', 'executive_disabled',
           'busy', 'typing', 'owner_request_active', 'attention_unavailable', 'state_unavailable',
           'gaming', 'call', 'speaking', 'listening', 'pending_reply', 'owner_away',
           'conversation_disabled', 'conversation_paused', 'learned_cooldown', 'commitment_imminent',
           'attempt_timeout', 'provider_error', 'source_changed', 'acceptance_refused',
           'validation_failed', 'incomplete_output', 'evidence_rejected', 'startup_timeout',
           'budget_timeout', 'process_interrupted', 'idle', 'deferred', 'superseded',
           'minimum_gap', 'hourly_limit', 'review_in_progress', 'retry_backoff', 'nothing_pending'}
NUMBERS = {'elapsed_ms', 'lease_budget_ms', 'inference_budget_ms', 'rejections',
           'total_duration_ms', 'load_duration_ms', 'prompt_eval_duration_ms', 'eval_duration_ms',
           'prompt_eval_count', 'prompt_eval_cached_count', 'eval_count', 'wall_ms',
           'prompt_chars', 'response_chars', 'call', 'residency_query_ms', 'model_load_ms',
           'ensure_running_ms', 'residency_check_ms', 'load_wall_ms',
           'server_ready_ms', 'resident_check_ms', 'model_load_request_ms'}


def sanitized(data):
    """Strict metadata allowlist; no arbitrary source/error/provider strings."""
    result = {}
    if not isinstance(data, dict):
        return result
    for key, value in data.items():
        if key in NUMBERS:
            if value is None or type(value) in {int, float} and 0 <= value <= 1e20 and math.isfinite(value):
                result[key] = value
        elif key in {'phase'} and isinstance(value, str) and value in PHASES:
            result[key] = value
        elif key in {'reason', 'status', 'review_error'} and isinstance(value, str):
            result[key] = value if value in REASONS | STATES | {'received', 'stop', 'length', 'load', 'unload'} else 'unavailable'
        elif key == 'stage' and isinstance(value, str) and value in {'memory_relatedness', 'memory_label'}:
            result[key] = value
        elif key == 'done_reason' and (value is None or isinstance(value, str) and value in {'stop', 'length', 'load', 'unload'}):
            result[key] = value
        elif key == 'was_resident' and (value is None or type(value) is bool):
            result[key] = value
        elif key == 'accepted' and isinstance(value, dict):
            result[key] = {k: v for k, v in value.items() if k in {'situations', 'memories', 'conclusions'}
                           and type(v) is int and 0 <= v <= 100}
        elif key == 'startup':
            result[key] = sanitized(value)
        elif key == 'calls' and isinstance(value, list):
            result[key] = [sanitized(row) for row in value[:6] if isinstance(row, dict)]
        elif key == 'blocks' and isinstance(value, (list, tuple)):
            result[key] = list(dict.fromkeys(v for v in value if isinstance(v, str) and v in REASONS))[:12]
    return result


class CognitiveHealth:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS executive_settings '
                       '(id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, epoch INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO executive_settings VALUES(1,1,0)')
            db.execute('''CREATE TABLE IF NOT EXISTS cognitive_health (
                component TEXT PRIMARY KEY, runtime TEXT NOT NULL, at REAL NOT NULL,
                state TEXT NOT NULL, reason TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS cognitive_health_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, component TEXT NOT NULL,
                runtime TEXT NOT NULL, at REAL NOT NULL, state TEXT NOT NULL,
                reason TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.commit()
            yield db

    def epoch(self):
        with self._db() as db:
            return db.execute('SELECT epoch FROM executive_settings WHERE id=1').fetchone()[0]

    def record(self, component, state, reason, details=None, *, expected_epoch=None):
        if not config.COGNITION_ENABLED:
            return False
        if component not in {'attention', 'review'} or state not in STATES or reason not in REASONS:
            raise ValueError('Unsupported cognitive health state')
        payload = json.dumps(sanitized(details or {}), allow_nan=False)
        stamp = time.time()
        try:
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                epoch = db.execute('SELECT epoch FROM executive_settings WHERE id=1').fetchone()[0]
                if expected_epoch is not None and epoch != expected_epoch:
                    return False
                old = db.execute('SELECT * FROM cognitive_health WHERE component=?', (component,)).fetchone()
                changed = not old or (old['runtime'], old['state'], old['reason'], old['payload']) != (
                    self.store.runtime, state, reason, payload)
                if not changed and stamp - old['at'] < 30:
                    return True
                db.execute('INSERT INTO cognitive_health VALUES(?,?,?,?,?,?) ON CONFLICT(component) DO UPDATE SET '
                           'runtime=excluded.runtime,at=excluded.at,state=excluded.state,reason=excluded.reason,payload=excluded.payload',
                           (component, self.store.runtime, stamp, state, reason, payload))
                if changed:
                    db.execute('INSERT INTO cognitive_health_history(component,runtime,at,state,reason,payload) VALUES(?,?,?,?,?,?)',
                               (component, self.store.runtime, stamp, state, reason, payload))
                    db.execute('DELETE FROM cognitive_health_history WHERE id NOT IN '
                               '(SELECT id FROM cognitive_health_history ORDER BY id DESC LIMIT ?)', (HISTORY_LIMIT,))
            return True
        except (OSError, sqlite3.Error, ValueError):
            logger.debug('Cognitive health receipt unavailable')
            return False

    def latest(self, component):
        if not config.COGNITION_ENABLED:
            return None
        try:
            with self._db() as db:
                row = db.execute('SELECT * FROM cognitive_health WHERE component=?', (component,)).fetchone()
            if row is None:
                return None
            result = {**json.loads(row['payload']), 'state': row['state'], 'reason': row['reason'], 'at': row['at'],
                      'current_runtime': row['runtime'] == self.store.runtime,
                      'age_seconds': round(max(0, time.time() - row['at']), 2)}
            if row['runtime'] != self.store.runtime and result['state'] in {'starting', 'running', 'reviewing'}:
                result.update(state='interrupted', reason='process_interrupted', elapsed_ms=None)
            elif result['state'] == 'running':
                result['elapsed_ms'] = round(max(0, time.time() - row['at']) * 1000, 2)
            return result
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return None

    def history(self, limit=10):
        if not config.COGNITION_ENABLED:
            return []
        try:
            with self._db() as db:
                rows = db.execute('SELECT component,at,state,reason FROM cognitive_health_history '
                                  'ORDER BY id DESC LIMIT ?', (max(0, min(20, limit)),)).fetchall()
            return [dict(row) for row in rows]
        except (OSError, sqlite3.Error):
            return []


health = CognitiveHealth(cognition)
