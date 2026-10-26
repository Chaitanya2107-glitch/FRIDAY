"""Bounded ordinary-chat clarifications with original question/source provenance."""
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

from core.config import config
from core.logger import logger
from services.automation.results import ActionResult
from services.mind.cognition import cognition
from services.mind.reasoning_store import fingerprint
from services.mind.temporal_memory import TemporalMemory, answer_date_phrase, anchored_dates
from services.mind import reference_context

TTL_SECONDS = 15 * 60
clock = datetime.now
REPORT = re.compile(r"(?:my|the) ([\w '\u2019-]{2,100}?) (?:was|is|has been|got) (?:postponed|rescheduled|moved)[.!]*$", re.I)
STATUS = {'follow-up status', 'followup status', 'did you save that date', 'did you save the date'}
CANCEL = {'cancel', 'stop', 'never mind', 'nevermind', 'no thanks', 'no'}
DATE_START = re.compile(r"^(?:today\b|tomorrow\b|tonight\b|yesterday\b|in \d|\d|"
    r"next\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|"
    r"january\b|february\b|march\b|april\b|may\b|june\b|july\b|august\b|"
    r"september\b|october\b|november\b|december\b)", re.I)


def _date_like(text):
    for _ in range(3):
        text = re.sub(r"^(?:(?:i think|maybe|perhaps|probably|possibly|not|no|on|for|is it)\s+|"
            r"(?:(?:it|that)(?:['’]s| is|['’]ll be| will be| isn['’]t| is not)|the date is)"
            r"(?: (?:scheduled|set))?\s+)", '', text.strip(), flags=re.I)
    return bool(DATE_START.match(text))


def _reply(text, candidates, noted):
    names = [row['subject'] for row in candidates]
    if len(text) > 240:
        prefix = re.split(r'[, :]', text, maxsplit=1)[0]
        return [], '', bool(reference_context.choices(prefix, names) or _date_like(text[:120]))
    source = {'text': text, 'noted': noted.isoformat()}
    if phrase := answer_date_phrase(source):
        return ([0] if len(names) == 1 else []), phrase, True
    parts = re.split(r",\s*|:\s+|\s+(?:is|will be)\s+(?:on|for)\s+|\s+on\s+", text, maxsplit=1, flags=re.I)
    if len(parts) == 2:
        choices = reference_context.choices(parts[0], names)
        phrase = answer_date_phrase({**source, 'text': parts[1]})
        return choices, phrase, bool(choices or phrase or _date_like(parts[1]))
    # Speech transcripts often omit commas. Only an explicitly offered name may
    # precede a date; never infer a target from recency or from a date token alone.
    for boundary in re.finditer(r'\s+(?=\S)', text):
        choices = reference_context.choices(text[:boundary.start()], names)
        suffix = text[boundary.end():]
        phrase = answer_date_phrase({**source, 'text': suffix})
        if choices and (phrase or _date_like(suffix)):
            return choices, phrase, True
    choices = reference_context.choices(text, names)
    return choices, '', bool(choices or _date_like(text))


class Dialogue:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def schema(db):
        db.execute('''CREATE TABLE IF NOT EXISTS dialogue_clarifications (
            id TEXT PRIMARY KEY, origin_id INTEGER NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL, answer_id INTEGER UNIQUE, created REAL NOT NULL, expires REAL NOT NULL)''')

    @contextmanager
    def _db(self):
        from services.mind.brain_memory import BrainMemory
        with self.store._lock, self.store._connect() as db:
            BrainMemory.schema(db)
            TemporalMemory.schema(db)
            self.schema(db)
            db.commit()
            yield db

    @staticmethod
    def _epoch(db):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='executive_settings'").fetchone():
            return db.execute('SELECT epoch FROM executive_settings WHERE id=1').fetchone()[0]
        return 0

    @staticmethod
    def hidden_sources(db):
        """Unresolved reports and intermediate selections cannot become model facts."""
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='dialogue_clarifications'").fetchone():
            return set()
        hidden = {row[0] for row in db.execute('SELECT origin_id FROM dialogue_clarifications')}
        for row in db.execute('SELECT payload FROM dialogue_clarifications'):
            selection = json.loads(row[0]).get('selection')
            if selection:
                hidden.add(int(selection['id'].split(':')[1]))
        return hidden

    @staticmethod
    def _valid(db, row, *, answering=False, now=None):
        from services.mind.brain_memory import BrainMemory
        if row is None:
            raise ValueError('The clarification was cleared')
        payload = json.loads(row['payload'])
        if (not config.COGNITION_ENABLED or payload['epoch'] != Dialogue._epoch(db)
                or answering and (row['state'] != 'awaiting' or not row['created'] <= now.timestamp() <= row['expires'])):
            raise ValueError('That question expired or changed. Repeat the update with its saved name.')
        for expected in [payload['origin'], *([payload['selection']] if payload.get('selection') else [])]:
            actual = db.execute('SELECT * FROM owner_episodes WHERE id=?', (int(expected['id'].split(':')[1]),)).fetchone()
            if not actual or BrainMemory._episode(actual) != expected:
                raise ValueError('The original conversation was cleared or changed. Repeat the update.')
        for expected in payload['candidates']:
            actual = db.execute('SELECT * FROM temporal_situations WHERE id=? AND superseded_by IS NULL',
                                (int(expected['id'].split(':')[1]),)).fetchone()
            if not actual or TemporalMemory._row(actual) != expected:
                raise ValueError('An offered commitment changed. Repeat the update with its saved name.')
        return payload

    @staticmethod
    def answer_context(db, source):
        if not source.get('question') or not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='dialogue_clarifications'").fetchone():
            return None
        row = db.execute('SELECT * FROM dialogue_clarifications WHERE answer_id=?',
                         (int(source['id'].split(':')[1]),)).fetchone()
        if not row:
            return None
        invalid = {'kind': 'conversation', 'dialogue_id': row['id'], 'invalid': True}
        try:
            if row['state'] != 'answered':
                return invalid
            payload = Dialogue._valid(db, row)
            if (source.get('channel') not in {'chat', 'voice'} or source != payload['answer']
                    or source['question'] != payload['question']
                    or not row['created'] <= datetime.fromisoformat(source['noted']).timestamp() <= row['expires']):
                return invalid
            target = next(value for value in payload['candidates'] if value['id'] == payload['target'])
            return {'kind': 'conversation', 'dialogue_id': row['id'], 'target': target['id'],
                    'version': fingerprint(target), 'date_phrase': payload['date_phrase'],
                    'origin': payload['origin']}
        except (ValueError, KeyError, StopIteration):
            return invalid

    def _pending(self, db):
        return db.execute("SELECT * FROM dialogue_clarifications WHERE state='awaiting' ORDER BY created DESC LIMIT 1").fetchone()

    @staticmethod
    def _unreviewed(db):
        return db.execute("SELECT * FROM dialogue_clarifications d WHERE state='answered' AND NOT EXISTS "
            "(SELECT 1 FROM temporal_situations WHERE source_key='owner_episode:'||d.answer_id) "
            'ORDER BY created DESC,rowid DESC LIMIT 1').fetchone()

    def awaiting(self):
        if not config.COGNITION_ENABLED:
            return False
        try:
            with self._db() as db:
                row = self._pending(db)
                if row:
                    self._valid(db, row, answering=True, now=clock())
                return row is not None
        except (ValueError, OSError, sqlite3.Error):
            return False

    def cancel(self):
        with self._db() as db:
            db.execute("UPDATE dialogue_clarifications SET state='cancelled' WHERE state='awaiting'")

    def match_turn(self, text, *, remote=False):
        if remote:
            return None
        raw = text.strip()
        clean = raw.casefold().rstrip('.!?')
        if clean in STATUS:
            return {'kind': 'status'}
        if match := REPORT.fullmatch(raw):
            return {'kind': 'report', 'reference': match[1], 'text': text}
        with self._db() as db:
            row = self._pending(db)
            if not row:
                from services.automation.intent import is_awaiting_confirmation
                if not is_awaiting_confirmation():
                    row = self._unreviewed(db)
            if not row:
                return None
            if clean in CANCEL:
                return {'kind': 'cancel', 'id': row['id']}
            choices, phrase, related = _reply(raw, json.loads(row['payload'])['candidates'], clock())
            if related:
                if row['state'] == 'answered':
                    return {'kind': 'busy', 'id': row['id']}
                return {'kind': 'answer', 'id': row['id'], 'choices': choices, 'phrase': phrase, 'text': text}
            if row['state'] == 'awaiting':
                db.execute("UPDATE dialogue_clarifications SET state='cancelled' WHERE id=?", (row['id'],))
        return None

    @staticmethod
    def _question(candidates):
        if len(candidates) == 1:
            return f"What is the new date for your {candidates[0]['subject']}?"
        return 'Which commitment was postponed: ' + '; '.join(row['subject'] for row in candidates) + '? Reply with its name and new date.'

    def _issue(self, db, origin, candidates, now, *, selection=None):
        question, ident = self._question(candidates), uuid.uuid4().hex
        payload = {'origin': origin, 'candidates': candidates, 'question': question, 'epoch': self._epoch(db)}
        if selection:
            payload['selection'] = selection
        for source in (origin, selection):
            if source:
                db.execute('UPDATE owner_episodes SET recall_withheld=1 WHERE id=?', (int(source['id'].split(':')[1]),))
        targets = {value['id'] for value in candidates}
        for old in db.execute("SELECT id,payload,answer_id FROM dialogue_clarifications WHERE state='answered'").fetchall():
            if json.loads(old['payload']).get('target') in targets:
                db.execute("UPDATE dialogue_clarifications SET state='replaced' WHERE id=?", (old['id'],))
                db.execute('UPDATE owner_episodes SET recall_withheld=1 WHERE id=?', (old['answer_id'],))
        db.execute("UPDATE dialogue_clarifications SET state='replaced' WHERE state='awaiting'")
        db.execute('INSERT INTO dialogue_clarifications VALUES(?,?,?,\'awaiting\',NULL,?,?)',
                   (ident, int(origin['id'].split(':')[1]), json.dumps(payload), now.timestamp(), now.timestamp() + TTL_SECONDS))
        db.execute('DELETE FROM dialogue_clarifications WHERE id NOT IN '
                   '(SELECT id FROM dialogue_clarifications ORDER BY created DESC,rowid DESC LIMIT 100)')
        return question

    def prepare(self, parsed):
        from services.mind.cognition import _turn, _channel
        now = clock()
        if parsed['kind'] == 'status':
            return self.status()
        if not config.COGNITION_ENABLED:
            return ActionResult(False, 'Conversation memory is disabled; the date was not updated.', repeatable=False)
        if parsed['kind'] == 'busy':
            return ActionResult(False, 'Your previous date answer is awaiting local review. Cancel it or repeat the update with its full saved name.', repeatable=False)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if parsed['kind'] == 'cancel':
                existing = db.execute('SELECT * FROM dialogue_clarifications WHERE id=?', (parsed['id'],)).fetchone()
                if not existing or existing['state'] not in {'awaiting', 'answered'}:
                    raise ValueError('The clarification is no longer pending')
                if existing['answer_id'] and db.execute('SELECT 1 FROM temporal_situations WHERE source_key=?',
                        (json.loads(existing['payload'])['answer']['id'],)).fetchone():
                    return ActionResult(False, 'That date was already saved. Tell me a new date to revise it.', repeatable=False)
                db.execute("UPDATE dialogue_clarifications SET state='cancelled' WHERE id=? AND state IN ('awaiting','answered')", (parsed['id'],))
                db.execute('UPDATE owner_episodes SET recall_withheld=1 WHERE id IN '
                           '(SELECT answer_id FROM dialogue_clarifications WHERE id=?)', (parsed['id'],))
                return ActionResult(True, 'Okay, cancelled the date clarification.', repeatable=False)
            if parsed['kind'] == 'report':
                db.execute("UPDATE dialogue_clarifications SET state='replaced' WHERE state='awaiting'")
                candidates = [TemporalMemory._row(row) for row in db.execute(
                    'SELECT * FROM temporal_situations WHERE superseded_by IS NULL ORDER BY id DESC LIMIT 100')]
                candidates = [row for row in candidates if row['status'] in {'planned', 'postponed', 'uncertain'}]
                query = reference_context.key(re.sub(r'^(?:the|my)\s+', '', parsed['reference'], flags=re.I))
                exact = [row for row in candidates if reference_context.key(row['subject']) == query]
                candidates = exact or [row for row in candidates if set(query.split()) <= set(reference_context.key(row['subject']).split())]
                if not candidates or len(candidates) > 5:
                    return ActionResult(False, 'Please repeat the update with its full saved commitment name.', repeatable=False)
                origin = self._remember(db, parsed['text'], now, source=_turn.get(), channel=_channel.get())
                question = self._issue(db, origin, candidates, now)
                return ActionResult(True, question, repeatable=False)
            row = db.execute('SELECT * FROM dialogue_clarifications WHERE id=?', (parsed['id'],)).fetchone()
            if not row:
                raise ValueError('That conversation was cleared. Repeat the update with its saved name.')
            payload = self._valid(db, row, answering=True, now=now)
            if len(parsed['choices']) != 1:
                return ActionResult(False, payload['question'], repeatable=False)
            target = payload['candidates'][parsed['choices'][0]]
            if not parsed['phrase']:
                # A literal offered name can narrow the question, never an uncertain date.
                if reference_context.choices(parsed['text'], [value['subject'] for value in payload['candidates']]) == parsed['choices']:
                    selection = self._remember(db, parsed['text'], now, question=payload['question'], source=_turn.get(), channel=_channel.get())
                    question = self._issue(db, payload['origin'], [target], now, selection=selection)
                    return ActionResult(True, question, repeatable=False)
                return ActionResult(False, 'Please give one definite date for the offered commitment. The date was not updated.', repeatable=False)
            answer = self._remember(db, parsed['text'], now, question=payload['question'], source=_turn.get(), channel=_channel.get())
            payload.update(answer=answer, target=target['id'], date_phrase=parsed['phrase'])
            db.execute("UPDATE dialogue_clarifications SET state='answered',answer_id=?,payload=? WHERE id=? AND state='awaiting'",
                       (int(answer['id'].split(':')[1]), json.dumps(payload), row['id']))
            return row['id']

    @staticmethod
    def _remember(db, text, now, *, question='', source=None, channel='chat'):
        from services.mind.brain_memory import BrainMemory
        from services.mind.cognition import redact
        channel = channel if channel in {'chat', 'voice'} else 'chat'
        source = source or uuid.uuid4().hex
        db.execute('INSERT OR IGNORE INTO owner_episodes(source_key,channel,question,text,noted) VALUES(?,?,?,?,?)',
                   (source, channel, redact(question), redact(text), now.isoformat()))
        row = db.execute('SELECT * FROM owner_episodes WHERE source_key=?', (source,)).fetchone()
        db.execute('DELETE FROM owner_episodes WHERE id IN '
                   '(SELECT id FROM owner_episodes ORDER BY id DESC LIMIT -1 OFFSET 500)')
        return BrainMemory._episode(row)

    async def run(self, parsed):
        import asyncio
        from services.mind.dialogue_review import review
        try:
            result = await asyncio.to_thread(self.prepare, parsed)
            if isinstance(result, ActionResult):
                if parsed['kind'] == 'report' and result.success:
                    from services.mind import talk
                    await asyncio.to_thread(talk.retire_question)
                return result
            await review(self, result)
            return await asyncio.to_thread(self.status, result)
        except (ValueError, OSError, sqlite3.Error):
            return ActionResult(False, 'That conversation expired, changed or could not be saved. The date was not updated; repeat the update with its saved name.', repeatable=False)

    def status(self, ident=None):
        if not config.COGNITION_ENABLED:
            return ActionResult(False, 'Conversation memory is disabled; the date was not updated.', repeatable=False)
        with self._db() as db:
            row = (db.execute('SELECT * FROM dialogue_clarifications WHERE id=?', (ident,)).fetchone() if ident else
                   db.execute("SELECT * FROM dialogue_clarifications ORDER BY created DESC,rowid DESC LIMIT 1").fetchone())
            if row and row['answer_id']:
                payload = json.loads(row['payload'])
                saved = db.execute('SELECT * FROM temporal_situations WHERE source_key=? AND superseded_by IS NULL',
                                   (payload['answer']['id'],)).fetchall()
                target = next(value for value in payload['candidates'] if value['id'] == payload['target'])
                for raw in saved:
                    value = TemporalMemory._row(raw)
                    if (value['subject'] == target['subject'] and value['quote'] == payload['answer']['text']
                            and value['status'] in {'planned', 'postponed'} and value['supersedes'] == [target['id']]
                            and value['source_question'] == payload['question'] and value['source_noted'] == payload['answer']['noted']
                            and value['date_phrase'] == payload['date_phrase'] and value['start']
                            and (value['start'], value['end']) == anchored_dates(payload['date_phrase'], datetime.fromisoformat(payload['answer']['noted']))):
                        try:
                            from services.mind.commitment_topics import CommitmentTopics
                            CommitmentTopics(self.store).remember(value)
                        except (OSError, ValueError, sqlite3.Error):
                            logger.debug('Saved date topic could not be retained')
                        return ActionResult(True, f"Saved your reported date for {value['subject']}: {value['start']}. The previous date is retained in history.", repeatable=False)
            return ActionResult(False, 'The date is not updated. Your answer needs local review, or the clarification has not been completed.', repeatable=False)


dialogue = Dialogue(cognition)
