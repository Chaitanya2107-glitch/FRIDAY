"""Source-linked, revisable interpretations of owner commitments; never tool authority."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition, redact


class TemporalUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    source: str = Field(pattern=r'^owner_episode:[1-9][0-9]*$')
    quote: str = Field(min_length=3, max_length=1200)
    subject: str = Field(min_length=2, max_length=100)
    status: Literal['planned', 'uncertain', 'postponed', 'completed', 'cancelled']
    date_phrase: str = Field(max_length=120)
    start: str | None
    end: str | None
    supersedes: list[str] = Field(max_length=1)

    @model_validator(mode='after')
    def bounds(self):
        if (self.start is None) != (self.end is None):
            raise ValueError('Date bounds must both be present or both be null')
        if self.start is not None:
            start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
            if (start.isoformat(), end.isoformat()) != (self.start, self.end) or not 0 <= (end - start).days <= 366:
                raise ValueError('Invalid commitment date window')
            if not self.date_phrase.strip():
                raise ValueError('Dated interpretations need an original date phrase')
        if not self.subject.strip() or not self.quote.strip():
            raise ValueError('Blank commitment or source quote')
        if self.status == 'uncertain' and self.supersedes:
            raise ValueError('An uncertain interpretation cannot withdraw a commitment')
        return self


def ambiguous_weekday(phrase, noted):
    clean = re.sub(r'^(?:to|on|for)\s+', '', ' '.join(phrase.casefold().strip().split()))
    weekday = noted.strftime('%A').casefold()
    if re.fullmatch(weekday + r'(?: (?:morning|afternoon|evening|night))?', clean):
        return True
    if clean.startswith(weekday + ' '):
        from services.proactive.deadlines import parse_due, AutomationError
        try:
            parse_due(clean, noted)  # Reuse supported clock syntax, without adopting its week choice.
            return True
        except (AutomationError, ValueError, OverflowError):
            pass
    return False


def anchored_dates(phrase, noted):
    """Validate exact date expressions against their ORIGINAL local receipt date.

    Ambiguous periods have no invented day. Interpretation of language and subject
    relationships belongs to the existing model review, not this calendar check.
    """
    clean = ' '.join(phrase.casefold().strip().split())
    clean = re.sub(r'^(?:to|on|for)\s+', '', clean)
    offsets = {'today': 0, 'tonight': 0, 'tomorrow': 1, 'yesterday': -1,
               'day after tomorrow': 2, 'the day after tomorrow': 2}
    relative = re.fullmatch(r'(.+?)(?: (?:morning|afternoon|evening|night))?', clean)
    word = relative[1] if relative else clean
    if word in offsets:
        day = noted.date() + timedelta(days=offsets[word])
        return day.isoformat(), day.isoformat()
    if match := re.fullmatch(r'in (\d{1,3}) (days?|weeks?)', clean):
        amount = int(match[1]) * (7 if match[2].startswith('week') else 1)
        if amount > 366:
            return None
        day = noted.date() + timedelta(days=amount)
        return day.isoformat(), day.isoformat()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:(?: to | through | until )\d{4}-\d{2}-\d{2})?', clean):
        values = re.findall(r'\d{4}-\d{2}-\d{2}', clean)
        return date.fromisoformat(values[0]).isoformat(), date.fromisoformat(values[-1]).isoformat()
    # Reuse FRIDAY's existing named-date/calendar parser for a single dated phrase.
    # "Next Friday" is deliberately unresolved because its week is ambiguous.
    if clean.startswith('next ') or ambiguous_weekday(clean, noted):
        return None
    from services.proactive.deadlines import parse_due, AutomationError
    try:
        due = parse_due(clean, noted)
    except (AutomationError, ValueError, OverflowError):
        return None
    # A bare clock has no explicit calendar date; never turn it into a day here.
    if not re.search(r'[a-z]|\d[/-]\d', clean) or re.fullmatch(r'(?:at |by )?\d{1,2}(?::\d{2})?\s*(?:am|pm)?', clean):
        return None
    return due.date().isoformat(), due.date().isoformat()


def subject_key(text):
    return ' '.join(redact(text).casefold().split())


def recover_date_phrase(quote, noted):
    """Recover a single supported calendar span, never intent, correction scope or certainty."""
    pattern = re.compile(r'\b(?:(?:the )?day after tomorrow|today|tonight|tomorrow|yesterday|'
        r'(?:mon|tues|wednes|thurs|fri|satur|sun)day|in \d{1,3} (?:days?|weeks?)|\d{4}-\d{2}-\d{2})'
        r'(?: (?:morning|afternoon|evening|night))?\b', re.I)
    matches = list(pattern.finditer(quote))
    rest = pattern.sub('', quote)
    if re.search(r'\d|\b(?:no|not|never|next|last|from|until|before|after|or|instead|postponed|moved|week|month|year)\b', rest, re.I):
        return ''
    candidates = []
    for match in matches:
        try:
            bounds = anchored_dates(match[0], noted)
        except ValueError:
            return ''
        if not bounds:
            return ''
        candidates.append((match[0], bounds))
    return candidates[0][0] if candidates and len({bounds for _, bounds in candidates}) == 1 else ''


def rescheduled_date_phrase(quote, noted):
    """Exact new target; None means absent, '' means invalid or ambiguous."""
    matches = list(re.finditer(r'\b(?:moved|postponed|rescheduled)\b[^.!?]*?\bto\s+([^.!?]+)', quote, re.I))
    if not matches:
        return None
    if '?' in quote or re.search(r'\b(?:no|not|never|if|unless|whether|may|might|could|would|'
                                 r'maybe|perhaps|possibly|previously|originally|earlier|instead)\b', quote, re.I):
        return ''
    if len(matches) != 1:
        return ''
    target = matches[0][1].strip()
    if len(target) > 120:
        return ''
    try:
        return target if anchored_dates(target, noted) or ambiguous_weekday(target, noted) else ''
    except (ValueError, OverflowError):
        return ''


def answer_date_phrase(source):
    """A whole date answer, optionally with a bounded affirmative wrapper."""
    text = source.get('text', '')
    context = source.get('date_clarification', {})
    if context.get('kind') == 'conversation':
        phrase = context.get('date_phrase', '')
        if phrase and len(phrase) <= 120 and phrase in text:
            try:
                bounds = anchored_dates(phrase, datetime.fromisoformat(source['noted']))
                return phrase if bounds and bounds[0] == bounds[1] else ''
            except (ValueError, OverflowError, KeyError):
                return ''
        return ''
    if len(text) > 120:
        return ''
    phrase = text.strip().rstrip('.!').strip()
    wrapper = re.match(r"(?:(?:it|that)(?:['’]s|\s+is|['’]ll\s+be|\s+will\s+be)|"
                       r"the\s+date\s+is)(?:\s+(?:scheduled|set))?\s+", phrase, re.I)
    if wrapper:
        phrase = phrase[wrapper.end():]
    if not phrase:
        return ''
    try:
        bounds = anchored_dates(phrase, datetime.fromisoformat(source['noted']))
        return phrase if bounds and bounds[0] == bounds[1] else ''
    except (ValueError, OverflowError, KeyError):
        return ''


def answer_target(source, known):
    from services.mind.reasoning_store import fingerprint
    context = source.get('date_clarification', {})
    ref = context.get('target')
    old = known.get(ref, {})
    if (source.get('kind') == 'owner_answer' and source.get('channel') in {'chat', 'voice'}
            and not source.get('historical_recall') and source.get('question')
            and (source.get('inquiry_id') or context.get('kind') == 'conversation' and context.get('dialogue_id'))
            and old.get('kind') == 'temporal_interpretation' and not old.get('superseded_by')
            and (context.get('kind') == 'conversation' or not old.get('start') and not old.get('end'))
            and fingerprint(old) == context.get('version')):
        return ref
    return None


class TemporalMemory:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def pending_corrections(known):
        """At most three named rescheduling candidates; only review can accept them."""
        temporal = {ref: row for ref, row in known.items()
                    if ref.startswith('temporal:') and row.get('kind') == 'temporal_interpretation'}
        represented = {(row.get('source'), subject_key(row.get('subject', ''))) for row in temporal.values()}
        episodes = [(ref, row) for ref, row in known.items()
                    if ref.startswith('owner_episode:') and ref.split(':')[-1].isdigit()
                    and row.get('kind') in {'owner_message', 'owner_answer'}
                    and row.get('channel') in {'chat', 'voice'} and not row.get('historical_recall')
                    and row.get('noted')]
        episodes.sort(key=lambda item: (item[1]['noted'], int(item[0].split(':')[-1])), reverse=True)
        pending, covered = {}, set()
        for ref, row in episodes:
            text = row.get('text', '')
            linked = answer_target(row, known) if answer_date_phrase(row) else None
            try:
                if not linked and not rescheduled_date_phrase(text, datetime.fromisoformat(row['noted'])):
                    continue
            except (ValueError, OverflowError):
                continue
            targets = []
            for target, old in temporal.items():
                subject = subject_key(old.get('subject', ''))
                if (subject and target not in covered and not old.get('superseded_by')
                        and old.get('status') in {'planned', 'postponed', 'uncertain'}
                        and row['noted'] > old.get('source_noted', row['noted'])
                        and (ref, subject) not in represented
                        and (target == linked if linked else
                             re.search(r'(?<!\w)' + re.escape(subject) + r'(?!\w)', subject_key(text)))):
                    targets.append(target)
            if targets:
                pending[ref] = targets
                covered.update(targets)
                if len(pending) == 3:
                    break
        return pending

    @staticmethod
    def schema(db):
        db.execute('''CREATE TABLE IF NOT EXISTS temporal_situations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,
            source_key TEXT NOT NULL, subject_key TEXT NOT NULL, superseded_by INTEGER,
            UNIQUE(source_key,subject_key))''')

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            self.schema(db)
            yield db

    @staticmethod
    def _row(row):
        return {**json.loads(row['body']), 'id': f"temporal:{row['id']}",
                'superseded_by': f"temporal:{row['superseded_by']}" if row['superseded_by'] else None}

    def evidence(self):
        if not config.COGNITION_ENABLED:
            return {}
        with self._db() as db:
            rows = db.execute('SELECT * FROM temporal_situations WHERE superseded_by IS NULL ORDER BY id DESC LIMIT 100').fetchall()
        return {f"temporal:{row['id']}": self._row(row) for row in rows}

    def annotate_history(self, known):
        """Changed provenance invalidates conclusions based on superseded dates."""
        with self._db() as db:
            rows = db.execute('SELECT * FROM temporal_situations WHERE superseded_by IS NOT NULL ORDER BY id DESC LIMIT 500').fetchall()
        for raw in rows:
            row = self._row(raw)
            if row['source'] in known:
                entry = known[row['source']]
                entry.setdefault('historical_commitment_revisions', []).append(
                    {'subject': row['subject'], 'replacement': row['superseded_by'],
                     'meaning': 'This commitment/date was superseded; retain this episode only as historical context.'})
        return known

    @staticmethod
    def resolve(updates, known):
        """The model identifies date words; the local calendar does date arithmetic."""
        resolved, seen = [], set()
        for value in updates:
            source = known.get(value.source, {})
            linked = answer_target(source, known)
            if linked and value.supersedes == [linked] and value.status in {'planned', 'postponed'}:
                phrase = answer_date_phrase(source)
                if not phrase or value.quote != source.get('text'):
                    raise ValueError('Date clarification needs an unambiguous whole original answer')
                value = value.model_copy(update={'date_phrase': phrase, 'start': None, 'end': None})
            if (value.supersedes and value.status in {'planned', 'postponed'} and source.get('noted')
                    and value.quote in source.get('text', '')):
                target = rescheduled_date_phrase(value.quote, datetime.fromisoformat(source['noted']))
                if target == '':
                    raise ValueError('Rescheduling target is ambiguous, negated or unsupported')
                if target:
                    value = value.model_copy(update={'date_phrase': target, 'start': None, 'end': None})
                elif (value.date_phrase and value.date_phrase in value.quote and
                      re.search(r'\b(?:moved|postponed|rescheduled)\b.*\bfrom\b', value.quote, re.I)):
                    raise ValueError('An old from-date cannot establish the rescheduled date')
            grounded_phrase = bool(value.date_phrase) and any(
                value.date_phrase in source.get(field, '') for field in ('text', 'question'))
            if (not grounded_phrase and value.status in {'planned', 'uncertain'} and not value.supersedes
                    and source.get('noted') and value.quote in source.get('text', '')):
                phrase = recover_date_phrase(value.quote, datetime.fromisoformat(source['noted']))
                if phrase:
                    value = value.model_copy(update={'date_phrase': phrase, 'start': None, 'end': None})
            if value.date_phrase and source.get('noted') and any(
                    value.date_phrase in source.get(field, '') for field in ('text', 'question')):
                bounds = anchored_dates(value.date_phrase, datetime.fromisoformat(source['noted']))
                value = TemporalUpdate.model_validate({**value.model_dump(),
                    'start': bounds[0] if bounds else None, 'end': bounds[1] if bounds else None})
            key = value.model_dump_json()
            if key not in seen:
                seen.add(key)
                resolved.append(value)
        return resolved

    @staticmethod
    def validate(updates, known):
        seen, withdrawn = set(), set()
        for value in updates:
            source = known.get(value.source, {})
            if (source.get('historical_recall') or source.get('kind') not in {'owner_answer', 'owner_message'} or source.get('channel') not in {'chat', 'voice'}
                    or value.quote not in source.get('text', '')):
                raise ValueError('Temporal interpretation must quote a local owner episode')
            if (value.source, subject_key(value.subject)) in seen:
                raise ValueError('Duplicate commitment in this report')
            seen.add((value.source, subject_key(value.subject)))
            represented = [row for row in known.values() if row.get('kind') == 'temporal_interpretation'
                           and row.get('source') == value.source and subject_key(row.get('subject', '')) == subject_key(value.subject)]
            if represented and all(represented[0].get(k) == v for k, v in value.model_dump().items()):
                continue  # identical accepted revision can be retried after restart
            if source.get('date_clarification', {}).get('kind') == 'conversation':
                target = answer_target(source, known)
                if (not target or value.supersedes != [target] or value.status not in {'planned', 'postponed'}
                        or value.quote != source.get('text') or value.date_phrase != answer_date_phrase(source)):
                    raise ValueError('A conversation answer must retain its verified original question and target')
            if value.supersedes and value.status in {'planned', 'postponed'}:
                named = re.search(r'(?<!\w)' + re.escape(subject_key(value.subject)) + r'(?!\w)',
                                  subject_key(source.get('text', '')))
                explicit = re.search(r'\b(?:moved|postponed|rescheduled)\b', source.get('text', ''), re.I)
                answer = answer_date_phrase(source)
                if answer or not named and not explicit:
                    if (value.supersedes != [answer_target(source, known)] or not answer
                            or value.date_phrase != answer or value.quote != source.get('text')):
                        raise ValueError('A short date correction needs its verified current inquiry target')
            phrase = value.date_phrase
            if phrase and not any(phrase in source.get(field, '') for field in ('text', 'question')):
                raise ValueError('Date phrase must occur in the original answer or paired question')
            if value.start is not None:
                original = datetime.fromisoformat(source['noted'])
                if anchored_dates(phrase, original) != (value.start, value.end):
                    raise ValueError('Date must be unambiguous and anchored to the original source date; otherwise use null bounds')
            for ref in value.supersedes:
                old = known.get(ref, {})
                if (not ref.startswith('temporal:') or old.get('kind') != 'temporal_interpretation'
                        or subject_key(old.get('subject', '')) != subject_key(value.subject)
                        or old.get('superseded_by') or ref in withdrawn or value.status == 'uncertain'
                        or source['noted'] <= old['source_noted']):
                    raise ValueError('Correction must explicitly target the same earlier commitment')
                withdrawn.add(ref)

    def save(self, db, updates, now, known):
        """Use the caller's guarded report transaction; preserve original evidence."""
        if not updates:
            return
        if not config.COGNITION_ENABLED:
            raise ValueError('Cognition was disabled')
        from services.mind.brain_memory import BrainMemory
        BrainMemory.schema(db)
        self.schema(db)
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        self.validate(updates, known)
        for value in updates:
            source = known[value.source]
            original = db.execute('SELECT * FROM owner_episodes WHERE id=?', (int(value.source.split(':')[1]),)).fetchone()
            from services.mind.brain_memory import BrainMemory
            if not original:
                raise ValueError('Owner source was forgotten during review')
            actual = BrainMemory._episode(original)
            if any(actual[key][:bound] != source[key] for key, bound in (('text', 1200), ('question', 500))):
                raise ValueError('Owner source changed during review')
            if actual['noted'] != source['noted'] or actual['channel'] != source['channel']:
                raise ValueError('Owner source provenance changed during review')
            if actual.get('inquiry_id') != source.get('inquiry_id'):
                raise ValueError('Owner answer inquiry changed during review')
            key = subject_key(value.subject)
            existing = db.execute('SELECT body FROM temporal_situations WHERE source_key=? AND subject_key=?',
                                  (value.source, key)).fetchone()
            if existing:
                saved = json.loads(existing['body'])
                if any(saved.get(k) != v for k, v in value.model_dump().items()):
                    raise ValueError('An existing interpretation cannot be silently rewritten')
                continue
            if source.get('date_clarification'):
                if source['date_clarification'].get('kind') == 'conversation':
                    from services.mind.dialogue import Dialogue
                    context = Dialogue.answer_context(db, actual)
                else:
                    from services.mind.inquiry import Inquiry
                    context = Inquiry.date_answer_context(db, actual.get('inquiry_id'), actual['question'], actual['noted'])
                if context != source['date_clarification']:
                    raise ValueError('Date clarification inquiry changed during review')
            if not value.supersedes and value.status != 'uncertain' and db.execute(
                    'SELECT 1 FROM temporal_situations WHERE subject_key=? AND superseded_by IS NULL', (key,)).fetchone():
                raise ValueError('Existing commitment needs an explicit correction target')
            for ref in value.supersedes:
                old = db.execute('SELECT * FROM temporal_situations WHERE id=? AND superseded_by IS NULL',
                                 (int(ref.split(':')[1]),)).fetchone()
                if not old or self._row(old) != known[ref]:
                    raise ValueError('Commitment changed during review')
            body = {**value.model_dump(), 'kind': 'temporal_interpretation', 'source_noted': source['noted'],
                    'source_question': source['question'], 'noted': now.isoformat(),
                    'meaning': 'Interpretation of an owner report; not independent verification or action permission.'}
            if source.get('inquiry_id'):
                body['source_inquiry_id'] = source['inquiry_id']
            ident = db.execute('INSERT INTO temporal_situations(body,source_key,subject_key) VALUES(?,?,?)',
                               (redact(json.dumps(body)), value.source, key)).lastrowid
            for ref in value.supersedes:
                db.execute('UPDATE temporal_situations SET superseded_by=? WHERE id=?', (ident, int(ref.split(':')[1])))
                db.execute('UPDATE owner_episodes SET recall_withheld=1 WHERE id=?',
                           (int(known[ref]['source'].split(':')[1]),))
                from services.mind.consolidation import Consolidation
                Consolidation.correct(db, known[ref]['source'], value.source, source, key)
        # Preserve all active commitments; bound only superseded revision history.
        db.execute('DELETE FROM temporal_situations WHERE superseded_by IS NOT NULL AND id NOT IN '
                   '(SELECT id FROM temporal_situations ORDER BY id DESC LIMIT 500)')

    def snapshot(self, now=None, limit=20):
        now = now or datetime.now()
        view = {'as_of': now.date().isoformat(), 'past': [], 'current': [], 'upcoming': [], 'unresolved': [], 'closed': []}
        for row in self.evidence().values():
            status, start, end = row['status'], row['start'], row['end']
            group = ('closed' if status in {'completed', 'cancelled'} else
                     'unresolved' if status == 'uncertain' or not start else
                     'past' if end < view['as_of'] else 'upcoming' if start > view['as_of'] else 'current')
            view[group].append(row)
        remaining = max(0, min(20, limit))
        for group in ('current', 'upcoming', 'unresolved', 'past', 'closed'):
            if group == 'upcoming':
                view[group].sort(key=lambda row: row['start'])
            view[group] = view[group][:remaining]
            remaining -= len(view[group])
            # Original records/history retain full quotes; shared prompts stay bounded.
            view[group] = [{**row, 'quote': row['quote'][:300], 'source_question': row['source_question'][:150]}
                           for row in view[group]]
        return view

    def history(self, subject):
        if not config.COGNITION_ENABLED:
            return []
        with self._db() as db:
            rows = db.execute('SELECT * FROM temporal_situations WHERE subject_key=? ORDER BY id DESC LIMIT 50',
                              (subject_key(subject),)).fetchall()
        return [self._row(row) for row in rows]


temporal_memory = TemporalMemory(cognition)


def situation(now=None):
    from services.mind.cognition_context import operational_state
    try:
        return {**temporal_memory.snapshot(now, limit=6), 'runtime': operational_state()}
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.debug('Shared situation unavailable (%s)', type(error).__name__)
        return {'status': 'unavailable'}
