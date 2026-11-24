"""Durable admission and source receipts for optional, unsolicited lines."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
import hashlib
import json
import sqlite3

from core.logger import logger
from services.mind.cognition import cognition, redact

DAILY_LIMIT = 3
IGNORE_AFTER = 45 * 60
delivery_id = ContextVar('friday_unsolicited_speech_id', default=None)


def current(now, *, input_observed=False):
    from services.activity.categories import categorize
    from services.activity.log import activity_log, idle_seconds
    from services.automation import modes
    from services.mind import care_safeguard, emotion, life_state, rhythm, state, talk
    from services.proactive.watcher import nudges_active
    from services.quiet_mode import enabled

    prefs, mode = talk.load(), modes.active(strict=True) or {}
    daily = rhythm.current(now, laptop_idle=idle_seconds(), input_observed=input_observed)
    scene, _, focused = state.focus_state()
    hours, clock = prefs.get('quiet_hours') or {}, now.strftime('%H:%M')
    start, end = hours.get('start'), hours.get('end')
    quiet_hours = (isinstance(start, str) and isinstance(end, str) and
                   (start <= clock < end if start <= end else clock >= start or clock < end))
    blocks = (
        (scene == 'exam' or mode.get('name') == 'exam', 'exam mode'),
        (scene == 'sleep' or mode.get('name') == 'sleep' or daily['phase'] == 'asleep', 'sleep'),
        (focused or mode.get('name') in {'focus', 'study'}, 'focus'),
        (quiet_hours or enabled() or mode.get('quiet'), 'quiet mode'),
        (not prefs.get('on', True) or prefs.get('paused_until', 0) > now.timestamp(), 'conversation paused'),
        (not nudges_active(now.timestamp()) or care_safeguard.active(now), 'nudges paused'),
    )
    category = categorize('app', activity_log.app, None, activity_log.title, None) if activity_log.app else 'unknown'
    context = life_state.context_key({'activity': category, 'mode_name': mode.get('name', 'normal')}, now)
    mood, _ = state.persona(now, tone=emotion.snapshot(now, daily_rhythm=daily))
    return context, mood, next((reason for blocked, reason in blocks if blocked), '')


class SpeechBudget:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        from services.mind.life_state import LifeState
        with LifeState(self.store)._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS speech_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
                source TEXT, context TEXT NOT NULL, digest TEXT NOT NULL, cause TEXT,
                decision TEXT NOT NULL, charged INTEGER NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS speech_days ON speech_decisions(day,charged)')
            db.execute('CREATE INDEX IF NOT EXISTS speech_source ON speech_decisions(source,charged)')
            yield db

    @staticmethod
    def _remember(db, row, reaction, at):
        if row['context']:
            db.execute('INSERT INTO life_reactions(source,context,reaction,at) VALUES(?,?,?,?) '
                       "ON CONFLICT(source) DO UPDATE SET reaction=excluded.reaction,at=excluded.at "
                       "WHERE life_reactions.reaction='ignored' AND excluded.reaction!='ignored'",
                       (f"speech:{row['id']}", row['context'], reaction, at))

    def decide(self, now, kind, text, *, reason, evidence=None, blocked='', source=None, public=True, context=None,
               input_observed=False):
        from services.mind.life_state import HISTORY_SECONDS, LifeState
        from services.mind.reviews import _clean

        stamp, day = now.timestamp(), now.date().isoformat()
        try:
            try:
                situation, mood, guard = current(now, input_observed=input_observed)
            except (OSError, ValueError, RuntimeError, sqlite3.Error, TypeError) as error:
                logger.debug('Speaking state unavailable (%s)', type(error).__name__)
                situation, mood, guard = 'unknown|normal|unknown', 'unavailable', 'current state unavailable'
            situation = context or situation
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                for row in db.execute("SELECT s.id,s.context,s.at FROM speech_decisions s LEFT JOIN life_reactions r "
                                     "ON r.source='speech:'||s.id WHERE s.decision='submitted' AND s.context!='' "
                                     "AND s.at BETWEEN ? AND ? AND r.id IS NULL",
                                     (stamp - HISTORY_SECONDS, stamp - IGNORE_AFTER)):
                    self._remember(db, row, 'ignored', row['at'])
                db.execute('DELETE FROM life_reactions WHERE at<?', (stamp - HISTORY_SECONDS,))
                engagement = LifeState(self.store).engagement(situation, now, db=db)
                alpha, beta = engagement['alpha'], engagement['beta']
                welcome = alpha / (alpha + beta)
                limit = DAILY_LIMIT if welcome >= .4 else min(DAILY_LIMIT, 2 if welcome >= .25 else 1)
                used = db.execute('SELECT COUNT(*) FROM speech_decisions WHERE day=? AND charged=1', (day,)).fetchone()[0]
                repeats = source and db.execute('SELECT 1 FROM speech_decisions WHERE source=? AND charged=1', (source,)).fetchone()
                block = (guard or blocked or ('already offered' if repeats else '') or
                         ('hard daily limit' if used >= DAILY_LIMIT else 'learned daily limit' if used >= limit else '') or
                         ('learned cooldown' if engagement['cooldown_until'] > stamp else ''))
                cause = dict(reason=redact(reason)[:500] if public else f'Local {kind.replace("_", " ")} event.',
                             evidence=_clean(evidence or {}), mood=mood, budget_reason=block or 'Within speaking budget',
                             used=used, limit=limit, hard_limit=DAILY_LIMIT, alpha=alpha, beta=beta)
                ident = db.execute('INSERT INTO speech_decisions(at,day,kind,source,context,digest,cause,decision,charged) '
                                   'VALUES(?,?,?,?,?,?,?,?,?)', (stamp, day, kind, source, situation, digest(text),
                                   json.dumps(cause, default=str), 'blocked' if block else 'reserved', int(not block))).lastrowid
                db.execute('DELETE FROM speech_decisions WHERE charged=0 AND at<?', (stamp - 30 * 86400,))
            logger.info('Speaking decision %s (%s): %s. Daily usage %s/%s, hard ceiling %s.',
                        ident, kind, cause['budget_reason'], used, limit, DAILY_LIMIT)
            return None if block else ident
        except (OSError, ValueError, sqlite3.Error) as error:
            logger.warning('Speaking decision withheld because the receipt is unavailable (%s)', type(error).__name__)
            return None

    def finish(self, ident, accepted):
        if ident is None:
            return
        try:
            with self._db() as db:
                db.execute("UPDATE speech_decisions SET decision=? WHERE id=? AND decision='reserved'",
                           ('submitted' if accepted is True else 'failed' if accepted is False else 'attempted', ident))
        except (OSError, sqlite3.Error) as error:
            logger.warning('Speaking delivery receipt unavailable (%s)', type(error).__name__)

    def note_text(self, text):
        """Bind the text accepted by a transport which expands a private notice."""
        ident = delivery_id.get()
        if ident is None:
            return
        try:
            with self._db() as db:
                db.execute("UPDATE speech_decisions SET digest=? WHERE id=? AND decision='reserved' AND cause IS NOT NULL",
                           (digest(text), ident))
        except (OSError, sqlite3.Error) as error:
            logger.debug('Speaking text receipt unavailable (%s)', type(error).__name__)

    def feedback(self, ident, reaction, now=None):
        if type(ident) is not int or reaction not in {'acted_on', 'answered', 'ignored', 'shushed'}:
            return
        stamp = (now or datetime.now()).timestamp()
        try:
            with self._db() as db:
                row = db.execute("SELECT * FROM speech_decisions WHERE id=? AND decision IN ('reserved','submitted','attempted')",
                                 (ident,)).fetchone()
                if row and 0 <= stamp - row['at'] <= 86400:
                    self._remember(db, row, reaction, stamp)
        except (OSError, sqlite3.Error) as error:
            logger.debug('Speaking reaction unavailable (%s)', type(error).__name__)

    def latest_since(self, now, seconds):
        try:
            with self._db() as db:
                row = db.execute("SELECT id FROM speech_decisions WHERE decision IN ('submitted','attempted') "
                                 "AND at BETWEEN ? AND ? ORDER BY id DESC LIMIT 1",
                                 (now.timestamp() - seconds, now.timestamp())).fetchone()
            return row[0] if row else None
        except (OSError, sqlite3.Error):
            return None

    def describe(self, line=''):
        field, value = ('id', int(line[1:])) if line.startswith('#') and line[1:].isdigit() and len(line) < 20 else (
            ('digest', digest(line.strip('\"'))) if line else ('id', None))
        try:
            with self._db() as db:
                row = db.execute(f"SELECT * FROM speech_decisions WHERE decision IN ('submitted','attempted') "
                                 f"AND (? IS NULL OR {field}=?) ORDER BY id DESC LIMIT 1", (value, value)).fetchone()
            cause = json.loads(row['cause']) if row and row['cause'] else None
        except (OSError, ValueError, sqlite3.Error):
            cause = None
        if not cause:
            return 'I have no recorded cause for that line.'
        evidence = ', '.join(f'{key}={value}' for key, value in cause['evidence'].items())
        return (f"Line #{row['id']}. {cause['reason']} " + (f"Evidence: {evidence}. " if evidence else '') +
                f"My mood was {cause['mood']}. {cause['budget_reason']}. I had used {cause['used']} of "
                f"{cause['limit']} allowed lines that day (hard maximum {cause['hard_limit']}, "
                f"welcome counts {cause['alpha']:.2f} in favor and {cause['beta']:.2f} against).")


def digest(text):
    return hashlib.sha256(' '.join(text.casefold().split()).rstrip(' .?!').encode()).hexdigest()


budget = SpeechBudget(cognition)
feedback = budget.feedback
