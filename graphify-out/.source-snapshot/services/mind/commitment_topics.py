"""Read-only short questions about one explicitly selected saved commitment."""
import re
import sqlite3
from datetime import date, datetime

from core.config import config
from core.logger import logger
from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.mind.cognition import cognition, _channel, _turn
from services.mind.reasoning_store import fingerprint
from services.mind.temporal_memory import TemporalMemory, subject_key
from services.mind.workspace import Workspace
from services.mind import reference_context as context

KIND = 'commitment_topic'
clock = datetime.now
QUESTIONS = {
    **dict.fromkeys(('when is it', 'when is that', 'when is it again', 'when is that again',
                     'when is it now', 'what is its date', 'what is the new date',
                     'what date is it on', 'what date is that on'), 'date'),
    **dict.fromkeys(('how many days left', 'how many days are left', 'how many days until it',
                     'how many days until that'), 'countdown'),
    **dict.fromkeys(('what was the previous date', 'what was its previous date',
                     'what was the old date', 'what was it before', 'previous date'), 'previous'),
}
NAMED = (
    ('date', r'when is (.+?)(?: again| now)?'),
    ('date', r'what is the (?:new |saved )?date (?:for|of) (.+)'),
    ('countdown', r'how many days (?:left (?:for|until)|until) (.+)'),
    ('previous', r'what was the (?:previous|old) date (?:for|of) (.+)'),
)
RESERVED = {'it', 'that', 'this', 'one', 'first', 'second', 'third', 'fourth', 'fifth',
            'last', 'latest', 'current', 'other'}


def _reply(success: bool, message: str) -> ActionResult:
    return ActionResult(success, message, repeatable=False,
                        memory_message='Local saved commitment question; no commitment or task changed.')


def _epoch(db) -> int:
    from services.mind.dialogue import Dialogue
    return Dialogue._epoch(db)


def _remote() -> bool:
    from services.automation.intent import remote_request
    return remote_request.get() or _channel.get() == 'telegram'


def _current_turn(db) -> bool:
    turn = _turn.get()
    if not turn:
        return True  # Internal callers have no foreground request to supersede.
    latest = db.execute("SELECT turn_id FROM events WHERE kind='request' AND channel IN ('chat','voice') "
                        'ORDER BY id DESC LIMIT 1').fetchone()
    return latest is not None and latest['turn_id'] == turn


class CommitmentTopics:
    def __init__(self, store):
        self.workspace = Workspace(store)

    @staticmethod
    def _candidates(db, reference: str) -> list[dict]:
        query = context.key(reference).removeprefix('my ').removeprefix('the ')
        if not query or query.isdigit() or query in RESERVED:
            return []
        # ponytail: scan all active subjects so a display cutoff cannot hide ambiguity.
        rows = [TemporalMemory._row(row) for row in db.execute(
            'SELECT * FROM temporal_situations WHERE superseded_by IS NULL')]
        exact = [row for row in rows if context.key(row['subject']) == query]
        return exact or [row for row in rows if set(query.split()) <= set(context.key(row['subject']).split())]

    def clear(self) -> None:
        with self.workspace._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if _current_turn(db):
                context.clear(db, KIND)

    def match_turn(self, text: str, *, remote: bool = False) -> dict | None:
        if remote or _remote() or len(text) > 240:
            return None
        raw = context.key(strip_leading_filler(text).strip())
        question = QUESTIONS.get(raw)
        named, switch = None, re.fullmatch(r'what about (.+)', raw)
        for mode, pattern in NAMED:
            if match := re.fullmatch(pattern, raw):
                named = {'question': mode, 'reference': match[1]}
                break
        if switch:
            named = {'question': 'date', 'reference': switch[1]}
        cancel = raw in {'cancel', 'never mind', 'nevermind', 'forget this topic'}
        if not (question or named or cancel):
            return None
        with self.workspace._db() as db:
            saved = context.read(db, KIND)
            if question:
                return {'question': question, 'context': saved}
            if cancel and saved:
                from services.automation.intent import is_awaiting_confirmation
                if not is_awaiting_confirmation():
                    return {'question': 'cancel', 'context': saved}
            if named and config.COGNITION_ENABLED:
                TemporalMemory.schema(db)
                if self._candidates(db, named['reference']) or switch and saved:
                    return named
        return None

    def remember(self, expected: dict) -> None:
        """Bind only an exact already-committed revision, never generated prose."""
        if not config.COGNITION_ENABLED or _remote():
            return
        with self.workspace._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not _current_turn(db):
                return
            TemporalMemory.schema(db)
            row = db.execute('SELECT * FROM temporal_situations WHERE id=? AND superseded_by IS NULL',
                             (int(expected['id'].split(':')[1]),)).fetchone()
            if row and TemporalMemory._row(row) == expected:
                context.remember(db, KIND, {'target': expected['id'], 'version': fingerprint(expected), 'epoch': _epoch(db)})

    def run(self, parsed: dict) -> ActionResult:
        if _remote():
            return _reply(False, 'Saved commitment topics are available at the laptop.')
        if not config.COGNITION_ENABLED:
            return _reply(False, 'Conversation memory is disabled. Ask again with the saved commitment name after enabling it.')
        try:
            with self.workspace._db() as db:
                db.execute('BEGIN IMMEDIATE')
                if not _current_turn(db):
                    return _reply(False, 'A newer local request changed the conversation. Ask again with its saved name.')
                TemporalMemory.schema(db)
                if 'reference' in parsed:
                    matches = self._candidates(db, parsed['reference'])
                    if len(matches) != 1:
                        context.clear(db, KIND)
                        return _reply(False, 'Please ask again with one full saved commitment name; I cannot choose a topic from that reference.')
                    target = matches[0]
                    context.remember(db, KIND, {'target': target['id'], 'version': fingerprint(target), 'epoch': _epoch(db)})
                else:
                    saved = parsed.get('context')
                    if not saved:
                        return _reply(False, 'Which saved commitment? Ask with its name, for example: when is my robotics exam?')
                    context.require(db, saved)
                    if parsed['question'] == 'cancel':
                        context.clear(db, KIND)
                        return _reply(True, 'Okay, cleared the current commitment topic. Its saved date is unchanged.')
                    expected = saved['payload']
                    row = db.execute('SELECT * FROM temporal_situations WHERE id=? AND superseded_by IS NULL',
                                     (int(expected['target'].split(':')[1]),)).fetchone()
                    target = TemporalMemory._row(row) if row else None
                    if (expected['epoch'] != _epoch(db) or target is None or fingerprint(target) != expected['version']):
                        context.clear(db, KIND)
                        return _reply(False, 'That saved topic changed or was cleared. Ask again with its full name.')
                return self._answer(db, target, parsed['question'])
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            logger.debug('Saved commitment topic unavailable')
            return _reply(False, 'The saved topic is unavailable, changed or expired. Ask again with its full name.')

    @staticmethod
    def _answer(db, target: dict, question: str) -> ActionResult:
        if question == 'previous':
            links = target['supersedes']
            previous = (db.execute('SELECT * FROM temporal_situations WHERE id=?',
                                  (int(links[0].split(':')[1]),)).fetchone() if links else None)
            old = TemporalMemory._row(previous) if previous else None
            if (old is None or old['superseded_by'] != target['id']
                    or subject_key(old['subject']) != subject_key(target['subject'])):
                return _reply(False, 'The previous saved date is unavailable for this commitment.')
            target = old
        label = 'Previous saved report' if question == 'previous' else 'Last saved report'
        message = f"{label} for {target['subject']}: {target['status']}"
        start, end = target['start'], target['end']
        if start:
            message += f" on {start}" if start == end else f" from {start} to {end}"
        else:
            message += '; no definite date is saved'
        if question == 'countdown':
            if target['status'] != 'planned' or not start or start != end:
                return _reply(False, message + '. A countdown needs one definite planned date.')
            days = (date.fromisoformat(start) - clock().date()).days
            unit = 'day' if abs(days) == 1 else 'days'
            message += (f' ({days} {unit} from today)' if days > 0 else ' (today)' if days == 0
                        else f' ({abs(days)} {unit} ago; completion is unknown)')
        return _reply(True, message + '.')


topics = CommitmentTopics(cognition)
