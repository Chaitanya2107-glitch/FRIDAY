"""Confirmed, private, deterministic care preferences and owner-entered logs."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import re
import sqlite3
import threading
import uuid

from core.config import config
from services.presence.trust import accepted, declined

TYPES = {'sleep', 'breaks', 'eye_rest', 'water', 'stretch', 'wind_down', 'phone_use', 'wellbeing', 'weekly_review'}
CATEGORIES = {'study', 'coding', 'documents', 'social', 'entertainment', 'gaming', 'communication', 'shopping', 'other', 'music', 'media', 'ai'}
lock = threading.RLock()


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Use HH:MM times.')
    return value


def in_window(definition, now):
    a, b = definition['window']
    # An overnight window belongs to its starting weekday.
    day = (now - timedelta(days=1)).weekday() if a > b and now.strftime('%H:%M') < b else now.weekday()
    return day in definition['days'] and (a <= now.strftime('%H:%M') < b if a < b else now.strftime('%H:%M') >= a or now.strftime('%H:%M') < b)


def validate(value):
    keys = {'type', 'limit', 'window', 'days', 'cap', 'categories', 'apps', 'context', 'voice'}
    if not isinstance(value, dict) or set(value) - {'wake'} != keys or value['type'] not in TYPES:
        raise ValueError('Choose a known care type and its finite settings.')
    if not isinstance(value['window'], list) or len(value['window']) != 2 or clock(value['window'][0]) == clock(value['window'][1]):
        raise ValueError('Choose a nonempty reminder window.')
    if not isinstance(value['days'], list) or not value['days'] or len(value['days']) > 7 or any(type(d) is not int or d not in range(7) for d in value['days']):
        raise ValueError('Choose weekdays from Monday through Sunday.')
    if type(value['cap']) is not int or not 1 <= value['cap'] <= 8 or type(value['voice']) is not bool:
        raise ValueError('Use a daily cap from 1 to 8 and a voice choice.')
    if value['type'] in {'sleep', 'wind_down'}:
        clock(value['limit'])
        if value['type'] == 'sleep':
            clock(value.get('wake'))
            if value['limit'] == value['wake']:
                raise ValueError('Choose a nonempty protected sleep window for block planning.')
    elif type(value['limit']) is not int or not 1 <= value['limit'] <= 1440:
        raise ValueError('Choose an interval or limit from 1 to 1440 minutes.')
    if value['context'] not in {'any', 'study', 'class'}:
        raise ValueError('Choose any, study or class windows.')
    if not isinstance(value['categories'], list) or len(value['categories']) > 12 or any(not isinstance(c, str) or c not in CATEGORIES for c in value['categories']):
        raise ValueError('Choose known categories explicitly.')
    if not isinstance(value['apps'], list) or len(value['apps']) > 20 or any(not isinstance(a, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', a) or len(a) > 200 for a in value['apps']):
        raise ValueError('Choose Android package names explicitly.')
    if value['type'] == 'phone_use' and not (value['categories'] or value['apps']):
        raise ValueError('Choose which phone categories or apps I may mention first.')
    return value


class CareStore:
    def __init__(self, path=None):
        self.path = path or config.MEMORY_DIR / 'mind' / 'care.db'

    @contextmanager
    def db(self):
        with lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA secure_delete=ON')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS care_settings(kind TEXT PRIMARY KEY,definition TEXT NOT NULL,enabled_at REAL NOT NULL,revision INTEGER NOT NULL,trust TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS care_pending(id INTEGER PRIMARY KEY,body TEXT NOT NULL,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS care_entries(id TEXT PRIMARY KEY,kind TEXT NOT NULL,at REAL NOT NULL,amount REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS care_notices(id TEXT PRIMARY KEY,kind TEXT NOT NULL,day TEXT NOT NULL,sent REAL NOT NULL,slot TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,answer TEXT);
                CREATE TABLE IF NOT EXISTS care_followups(id TEXT PRIMARY KEY,due REAL NOT NULL,expires REAL NOT NULL,kind TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS care_reviews(week TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS care_counts(day TEXT,kind TEXT,count INTEGER NOT NULL,PRIMARY KEY(day,kind));
            ''')
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    yield db
            finally:
                db.close()

    def settings(self, kind=None):
        if not self.path.is_file():
            return None if kind else []
        with self.db() as db:
            rows = db.execute('SELECT * FROM care_settings' + (' WHERE kind=?' if kind else ''), (kind,) if kind else ()).fetchall()
        result = [{**dict(r), 'definition': validate(json.loads(r['definition'])), 'trust': json.loads(r['trust'])} for r in rows]
        return (result[0] if result else None) if kind else result

    def pending(self, now=None, include_expired=False):
        if not self.path.is_file():
            return None
        with self.db() as db:
            row = db.execute('SELECT body,expires FROM care_pending').fetchone()
        if row and row['expires'] <= (now or datetime.now()).timestamp():
            return dict(expired=True) if include_expired else None
        return json.loads(row['body']) if row else None

    def stage(self, body, now=None):
        now = now or datetime.now()
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO care_pending VALUES(1,?,?)', (json.dumps(body, allow_nan=False), now.timestamp() + 600))

    def cancel(self):
        if not self.path.is_file():
            return
        with self.db() as db:
            db.execute('DELETE FROM care_pending')

    def confirm(self, definition, now=None):
        validate(definition)
        now = now or datetime.now()
        with self.db() as db:
            old = db.execute('SELECT revision FROM care_settings WHERE kind=?', (definition['type'],)).fetchone()
            trust = dict(level='ask', streak=0, promotion_offered=False)
            db.execute('INSERT OR REPLACE INTO care_settings VALUES(?,?,?,?,?)', (definition['type'], json.dumps(definition), now.timestamp(),
                       old[0] + 1 if old else 1, json.dumps(trust)))
            db.execute('DELETE FROM care_pending')
        return definition

    def disable(self, kind):
        if kind not in TYPES:
            raise ValueError('Choose a known care type.')
        with self.db() as db:
            db.execute('DELETE FROM care_settings WHERE kind=?', (kind,))
            db.execute('DELETE FROM care_followups WHERE kind=?', (kind,))
            db.execute("UPDATE care_notices SET answer='cancelled' WHERE kind=? AND answer IS NULL", (kind,))
            db.execute('DELETE FROM care_pending')
        if kind == 'eye_rest':
            from services.proactive.watcher import _save_state
            _save_state(eye_breaks=False)

    def log(self, kind, amount=1, now=None):
        if kind not in TYPES or type(amount) not in (int, float) or not 0 <= amount <= 1440:
            raise ValueError('Invalid private care entry.')
        now = now or datetime.now()
        if not self.settings(kind):
            raise ValueError('Confirm this care type before logging it.')
        with self.db() as db:
            db.execute('INSERT INTO care_entries VALUES(?,?,?,?)', (uuid.uuid4().hex, kind, now.timestamp(), amount))

    def entries(self, start, end, kind=None):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM care_entries WHERE at>=? AND at<?' + (' AND kind=?' if kind else ''),
                    (start.timestamp(), end.timestamp(), kind) if kind else (start.timestamp(), end.timestamp()))]

    def claim(self, candidate, now, context=None):
        from .care_safeguard import active
        if active(now):
            return None
        with self.db() as db:
            row = db.execute('SELECT * FROM care_settings WHERE kind=?', (candidate['type'],)).fetchone()
            if not row:
                return None
            definition = validate(json.loads(row['definition']))
            count = db.execute('SELECT count FROM care_counts WHERE kind=? AND day=?', (candidate['type'], now.date().isoformat())).fetchone()
            if (candidate.get('revision') != row['revision'] or not in_window(definition, now)
                    or context is not None and definition['context'] not in {'any', context}
                    or (count[0] if count else 0) >= definition['cap']):
                return None
            if candidate['key'].startswith('followup:'):
                followup = db.execute('SELECT due,expires FROM care_followups WHERE id=?', (candidate['key'].split(':', 1)[1],)).fetchone()
                if not followup or not followup['due'] <= now.timestamp() < followup['expires']:
                    return None
            identity = uuid.uuid4().hex
            try:
                db.execute('INSERT INTO care_notices VALUES(?,?,?,?,?,?,NULL)', (identity, candidate['type'], now.date().isoformat(), now.timestamp(),
                           candidate['key'], json.dumps(candidate, allow_nan=False)))
            except sqlite3.IntegrityError:
                return None
            db.execute('INSERT INTO care_counts VALUES(?,?,1) ON CONFLICT(day,kind) DO UPDATE SET count=count+1', (now.date().isoformat(), candidate['type']))
            return identity

    def answer(self, identity, choice, now=None):
        if choice not in {'remind15', 'leave', 'accept', 'done'} or not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise ValueError('Choose a current private care question.')
        now = now or datetime.now()
        with self.db() as db:
            row = db.execute('SELECT * FROM care_notices WHERE id=? AND answer IS NULL AND sent>?', (identity, now.timestamp() - 900)).fetchone()
            setting = db.execute('SELECT * FROM care_settings WHERE kind=?', (row['kind'],)).fetchone() if row else None
            if not row or not setting or not in_window(json.loads(setting['definition']), now):
                raise ValueError('That care question is unavailable or outside your window.')
            trust = json.loads(setting['trust'])
            trust = declined(trust) if choice == 'leave' else accepted(trust)
            db.execute('UPDATE care_settings SET trust=? WHERE kind=?', (json.dumps(trust), row['kind']))
            db.execute('UPDATE care_notices SET answer=? WHERE id=?', (choice, identity))
            if choice == 'remind15':
                db.execute('INSERT INTO care_followups VALUES(?,?,?,?)', (uuid.uuid4().hex, now.timestamp() + 900, now.timestamp() + 1800, row['kind']))
        return dict(recorded=True)


def store():
    return CareStore()


def propose(kind, now=None, data=None):
    from .coaching_metrics import baseline
    now = now or datetime.now()
    if kind not in TYPES:
        raise ValueError('Choose a known care type.')
    observed = baseline(kind, now, data)
    if kind in {'water', 'stretch'}:
        entries = store().entries(now - timedelta(days=7), now, kind)
        gaps = [(b['at'] - a['at']) / 60 for a, b in zip(entries, entries[1:]) if datetime.fromtimestamp(a['at']).date() == datetime.fromtimestamp(b['at']).date()]
        from statistics import median
        observed['suggested'] = round(median(gaps)) if gaps else None
        observed['source'] = 'your manual care logs' if gaps else 'no observed interval; choose your own'
    limit = 20 if kind == 'eye_rest' else 1 if kind in {'wellbeing', 'weekly_review'} else observed['suggested']
    definition = dict(type=kind, limit=limit, window=observed.get('window', ['20:00', '22:00']) if kind in {'wellbeing', 'weekly_review'} else observed.get('window'),
                      days=[6] if kind == 'weekly_review' else list(range(7)), cap=1, categories=[], apps=[], context='any', voice=False)
    if kind == 'sleep':
        definition['wake'] = observed.get('wake')
    return dict(definition=definition, baseline=observed)


def preview(proposal):
    d, b = proposal['definition'], proposal.get('baseline', {})
    window = ' to '.join(d['window']) if d.get('window') else 'not chosen'
    detail = f"{d['type'].replace('_', ' ')}: {'bedtime ' if d['type'] in {'sleep', 'wind_down'} else 'limit/interval '}{d['limit'] if d.get('limit') is not None else 'choose one'}"
    if d['type'] == 'sleep':
        detail += f"; protected sleep until {d.get('wake') or 'choose a wake time'} for block planning (not a health recommendation)"
    names = ', '.join(d.get('categories', []) + d.get('apps', [])) or 'none'
    return (f"{detail}. Window {window}; weekdays {d['days']} (Monday=0); daily cap {d['cap']}. "
            f"Baseline: {b.get('source', 'your chosen values')}, {b.get('days', 0)} observed days. "
            + (f"Phone mentions permitted only for: {names}; context {d['context']}; voice {'on' if d['voice'] else 'off'}. " if d['type'] == 'phone_use' else '')
            + 'Starts at Ask. Confirm with yes, change the values, or cancel. No apps will be blocked.')


def status(now=None):
    now = now or datetime.now()
    row = store().settings('wellbeing')
    from .care_safeguard import active
    entries = store().entries(now.replace(hour=0, minute=0, second=0, microsecond=0), now + timedelta(microseconds=1), 'wellbeing') if row else []
    return dict(wellbeing=dict(confirmed=bool(row), can_log=bool(row and in_window(row['definition'], now) and not active(now)), logged_today=bool(entries)))


def log_wellbeing(score, now=None):
    now = now or datetime.now()
    if type(score) is not int or not 1 <= score <= 5 or not status(now)['wellbeing']['can_log']:
        raise ValueError('Confirm wellbeing check-in first, and use 1 to 5 inside your chosen window.')
    # A later tap replaces today's self-report; it does not create a streak or infer mood.
    data = store()
    with data.db() as db:
        low = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        db.execute("DELETE FROM care_entries WHERE kind='wellbeing' AND at>=?", (low,))
        db.execute('INSERT INTO care_entries VALUES(?,?,?,?)', (uuid.uuid4().hex, 'wellbeing', now.timestamp(), score))
    return dict(recorded=True, score=score)


def phone_question(now=None):
    now = now or datetime.now()
    from .care_safeguard import active
    if active(now):
        return dict(pending=False)
    setting = store().settings('phone_use')
    if not setting or not in_window(setting['definition'], now):
        return dict(pending=False)
    with store().db() as db:
        row = db.execute("SELECT id,payload FROM care_notices WHERE kind='phone_use' AND answer IS NULL AND sent>? ORDER BY sent DESC LIMIT 1", (now.timestamp() - 900,)).fetchone()
    return dict(pending=True, id=row['id'], text=json.loads(row['payload'])['text'], choices=['remind15', 'leave']) if row else dict(pending=False)


def answer_notice(identity, choice, now=None):
    from .care_safeguard import active
    if active(now):
        raise ValueError('Coaching is paused.')
    return store().answer(identity, choice, now)


def forget_phone(device):
    # Source-derived reviews and unhandled questions are regenerated from remaining data.
    with store().db() as db:
        db.execute('UPDATE care_settings SET revision=revision+1')
        db.execute('DELETE FROM care_reviews')
        db.execute('DELETE FROM care_pending')
        db.execute('DELETE FROM care_notices')
        db.execute('DELETE FROM care_followups')
