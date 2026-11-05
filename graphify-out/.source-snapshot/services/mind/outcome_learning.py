"""Expected versus observed settings; historical receipts never grant action permission."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition, redact

ACTIONS = {'set_volume', 'set_mute', 'start_mode', 'end_mode'}
TERMINAL = {'verified', 'failed', 'unknown'}


def target(action, value):
    if action not in ACTIONS or not isinstance(value, dict):
        raise ValueError('Unsupported outcome target')
    allowed = {'volume', 'muted'} if action == 'set_volume' else {'muted'} if action == 'set_mute' else {'mode'}
    required = 'volume' if action == 'set_volume' else 'muted' if action == 'set_mute' else 'mode'
    if required not in value or set(value) - allowed:
        raise ValueError('Unexpected outcome fields')
    for key, item in value.items():
        if key == 'volume' and (type(item) is not int or not 0 <= item <= 100):
            raise ValueError('Invalid volume observation')
        if key == 'muted' and type(item) is not bool:
            raise ValueError('Invalid mute observation')
        if key == 'mode' and (not isinstance(item, str) or not item.strip() or len(item) > 80 or any(c in item for c in '\r\n\0')):
            raise ValueError('Invalid mode observation')
    return dict(value)


class OutcomeLearning:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS outcome_settings (id INTEGER PRIMARY KEY, epoch INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO outcome_settings VALUES(1,0)')
            db.execute('''CREATE TABLE IF NOT EXISTS action_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, epoch INTEGER NOT NULL,
                action TEXT NOT NULL, expected TEXT NOT NULL, observed TEXT, state TEXT NOT NULL,
                driver_success INTEGER, matched INTEGER, runtime TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL)''')
            db.commit()
            yield db

    def begin(self, action, expected, now=None):
        expected = target(action, expected)
        if not config.COGNITION_ENABLED:
            return None
        stamp = (now or datetime.now()).timestamp()
        try:
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                epoch = db.execute('SELECT epoch FROM outcome_settings WHERE id=1').fetchone()[0]
                token = uuid.uuid4().hex
                ident = db.execute('INSERT INTO action_outcomes(token,epoch,action,expected,state,runtime,created,updated) '
                    'VALUES(?,?,?,?,?,?,?,?)', (token, epoch, action, redact(json.dumps(expected)), 'requested',
                                              self.store.runtime, stamp, stamp)).lastrowid
                db.execute('DELETE FROM action_outcomes WHERE id NOT IN '
                           '(SELECT id FROM action_outcomes ORDER BY id DESC LIMIT 200)')
            return {'id': ident, 'token': token, 'epoch': epoch, 'action': action, 'expected': expected}
        except (OSError, sqlite3.Error) as error:
            logger.warning('Outcome request receipt unavailable (%s)', type(error).__name__)
            return None

    def applied(self, job, now=None):
        if not job or not config.COGNITION_ENABLED:
            return
        try:
            with self._db() as db:
                db.execute("UPDATE action_outcomes SET state='applied',driver_success=1,updated=? WHERE id=? AND token=? "
                    "AND epoch=(SELECT epoch FROM outcome_settings WHERE id=1) AND state='requested'",
                    ((now or datetime.now()).timestamp(), job['id'], job['token']))
        except (OSError, sqlite3.Error) as error:
            logger.warning('Outcome applied receipt unavailable (%s)', type(error).__name__)

    @staticmethod
    def assess(action, expected, observed, driver_success):
        expected = target(action, expected)
        if observed is not None:
            try:
                observed = target(action, observed)
            except ValueError:
                observed = None
        matched = None if observed is None else all(
            key in observed and (abs(observed[key] - value) <= 1 if key == 'volume' else observed[key] == value)
            for key, value in expected.items())
        state = ('failed' if driver_success is False else 'unknown' if driver_success is None or matched is None
                 else 'verified' if matched else 'failed')
        return {'state': state, 'matched': matched, 'observed': observed, 'driver_success': driver_success}

    def finish(self, job, observed, driver_success, now=None):
        if not job or not config.COGNITION_ENABLED:
            return None
        result = self.assess(job['action'], job['expected'], observed, driver_success)
        try:
            with self._db() as db:
                changed = db.execute('UPDATE action_outcomes SET state=?,observed=?,driver_success=?,matched=?,updated=? '
                    "WHERE id=? AND token=? AND action=? AND expected=? AND epoch=(SELECT epoch FROM outcome_settings WHERE id=1) AND state IN ('requested','applied')",
                    (result['state'], redact(json.dumps(result['observed'])) if result['observed'] is not None else None,
                     driver_success, result['matched'], (now or datetime.now()).timestamp(), job['id'], job['token'],
                     job['action'], redact(json.dumps(job['expected'])))).rowcount
                row = db.execute('SELECT * FROM action_outcomes WHERE id=?', (job['id'],)).fetchone() if changed else None
            if row:
                self.store.record('action_outcome', 'system', 'A supported setting action has an outcome receipt.',
                                  status=result['state'], public=False)
                return self._view(row)
        except (OSError, sqlite3.Error) as error:
            logger.warning('Outcome completion receipt unavailable (%s)', type(error).__name__)
        return None

    def _view(self, row):
        state = row['state']
        if state in {'requested', 'applied'} and row['runtime'] != self.store.runtime:
            state = 'unknown'
        return {'id': f"action_outcome:{row['id']}", 'kind': 'action_outcome', 'action': row['action'],
                'state': state, 'expected': json.loads(row['expected']),
                'observed': json.loads(row['observed']) if row['observed'] else None,
                'driver_success': None if row['driver_success'] is None else bool(row['driver_success']),
                'matched': None if row['matched'] is None else bool(row['matched']),
                'noted': datetime.fromtimestamp(row['updated']).isoformat(),
                'scope': 'selected_mode_only' if row['action'] in {'start_mode', 'end_mode'} else 'master_audio_settings_only',
                'meaning': 'Historical setting readback; not current state, physical sound, setup-step verification or task completion.'}

    def recent(self, now=None, limit=20):
        if not config.COGNITION_ENABLED:
            return []
        with self._db() as db:
            rows = db.execute('SELECT * FROM action_outcomes ORDER BY updated DESC,id DESC LIMIT ?', (min(200, max(1, limit)),)).fetchall()
        return [self._view(row) for row in rows]

    @staticmethod
    def family(row):
        return row['action'] + (':' + row['expected']['mode'] if 'mode' in row['expected'] else '')

    def lessons(self, rows=None):
        groups = {}
        for row in self.recent(limit=100) if rows is None else rows:
            groups.setdefault(self.family(row), []).append(row)
        lessons = []
        for family, rows in groups.items():
            streak = []
            for row in rows:
                if row['state'] == 'verified':
                    break
                if row['state'] in TERMINAL:
                    streak.append(row)
            if len(streak) >= 2:
                mode = rows[0]['action'] in {'start_mode', 'end_mode'}
                lessons.append({'id': 'outcome_lesson:' + family, 'kind': 'outcome_lesson', 'family': family,
                    'unverified_streak': len(streak), 'failed': sum(r['state'] == 'failed' for r in streak),
                    'unknown': sum(r['state'] == 'unknown' for r in streak), 'evidence': [r['id'] for r in streak[:2]],
                    'advice': 'Repeated attempts were not verified. Check ' +
                        ('mode state storage and setup errors' if mode else 'the Windows audio endpoint and control permissions') +
                        ' before proposing the same method. No automatic retry or task completion follows.'})
        return lessons[:5]

    def evidence(self):
        rows = self.recent(limit=100)
        lessons = self.lessons(rows)[:3]
        sources = {ref for lesson in lessons for ref in lesson['evidence']}
        return {row['id']: row for row in rows[:6] + [r for r in rows[6:] if r['id'] in sources] + lessons}

    def context(self):
        try:
            rows = self.recent(limit=100)
            return {'status': 'available' if config.COGNITION_ENABLED else 'disabled',
                    'receipts': rows[:6], 'lessons': self.lessons(rows),
                    'scope': 'Historical master-audio settings and selected modes only; not current state or task completion.'}
        except (OSError, sqlite3.Error):
            return {'status': 'unavailable', 'receipts': [], 'lessons': []}

    def describe(self):
        context = self.context()
        if context['status'] != 'available':
            return 'Action outcome memory is ' + context['status'] + '.'
        rows = context['receipts']
        text = ('Latest action check: ' + rows[0]['action'].replace('_', ' ') + ' was ' + rows[0]['state'] +
                ' at ' + rows[0]['noted'] + '. Historical settings only; ask for current status to check again.'
                if rows else 'No supported action outcomes have been recorded yet.')
        for lesson in context['lessons'][:2]:
            text += ' ' + lesson['advice']
        return text

    def advice(self, job):
        if not job:
            return ''
        try:
            return next((row['advice'] for row in self.lessons() if row['family'] == self.family(job)), '')
        except (OSError, sqlite3.Error):
            return ''


outcome_learning = OutcomeLearning(cognition)


def failure_message(action, expected, finding):
    if finding['state'] == 'unknown':
        return 'The setting change was sent, but I could not confirm the resulting state.'
    observed = finding['observed'] or {}
    if 'mode' in expected:
        return redact(f"Mode verification failed: current mode is {observed.get('mode', 'unknown').title()}; requested {expected['mode'].title()}.")
    return 'Audio verification failed: the observed master setting does not match the request.'


def verified_change(action, expected, mutate, read, message):
    """Driver-level boundary: callers mocking the driver also mock its verification."""
    from services.automation.system_control import AutomationError
    job = outcome_learning.begin(action, expected)
    try:
        mutate()
    except BaseException as error:
        outcome_learning.finish(job, None, False if isinstance(error, Exception) else None)
        advice = outcome_learning.advice(job)
        if isinstance(error, AutomationError) and advice:
            raise AutomationError(str(error) + ' ' + advice) from error
        raise
    outcome_learning.applied(job)
    try:
        observed = read()
    except Exception:
        observed = None
    except BaseException:
        outcome_learning.finish(job, None, None)
        raise
    finding = OutcomeLearning.assess(action, expected, observed, True)
    outcome_learning.finish(job, observed, True)
    if finding['state'] != 'verified':
        advice = outcome_learning.advice(job)
        raise AutomationError(failure_message(action, expected, finding) + (' ' + advice if advice else ''))
    return message


def verified_result(job, action, expected, result, read):
    if result.success:
        outcome_learning.applied(job)
    try:
        observed = read()
    except Exception:
        observed = None
    finding = OutcomeLearning.assess(action, expected, observed, bool(result.success))
    outcome_learning.finish(job, observed, bool(result.success))
    message = result.message if not result.success or finding['state'] == 'verified' else failure_message(action, expected, finding)
    if not result.success and finding['matched'] is not True:
        message = failure_message(action, expected, finding) + ' Controller reported: ' + result.message
    advice = outcome_learning.advice(job) if finding['state'] != 'verified' else ''
    return result._replace(success=result.success and finding['state'] == 'verified',
                           message=message + (' ' + advice if advice else ''), repeatable=False)
