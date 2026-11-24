"""Owner-reviewed dates from literal reports and the saved schedule."""

import re
import sqlite3
from datetime import datetime

from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.automation.system_control import AutomationError
from services.mind import reference_context
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate, anchored_dates
from services.proactive import deadline_changes, deadlines

CONTEXT = 'reported_date'
clock = datetime.now
REPORT = re.compile(
    r"^(?:my|the) (?P<reference>[\w \u2019'-]{2,100}?) "
    r"(?P<verb>(?:(?:has been |was |is |got )?(?:moved|rescheduled|postponed) "
    r"(?:from (?P<old>[^!?\r\n]{1,120}?) )?to)|is (?:scheduled|set) for|will be|is) (?P<date>[^!?\r\n]{1,120})$",
    re.I,
)
COMMITMENT = re.compile(r'\b(?:exam|test|assessment|practical|interview|assignment|deadline|appointment|'
                        r'meeting|class|lecture|demo|presentation|project|submission|viva|event)\b', re.I)
UNSURE = re.compile(r'\b(?:not|never|maybe|perhaps|possibly|likely|if|unless|either|or|might|could|instead)\b', re.I)


def _bounds(phrase, noted):
    if UNSURE.search(phrase):
        return None
    try:
        bounds = anchored_dates(phrase, noted)
        return bounds if bounds and bounds[0] == bounds[1] else None
    except (ValueError, OverflowError):
        return None


def match_turn(text, *, remote=False):
    if remote:
        return None
    raw = strip_leading_filler(text).strip()
    if match := REPORT.fullmatch(raw.rstrip('.')):
        if re.search(r'\band (?:i|we|he|she|they)\b', match['date'], re.I):
            return None  # Keep a compound statement in ordinary owner dialogue.
        from services.proactive import class_changes
        if deadlines.match_deadline_change(raw.rstrip('.')) or class_changes.match_command(raw):
            return None
        move = ' to' in match['verb'].casefold()
        if not UNSURE.search(match['reference']) and (move or COMMITMENT.search(match['reference'])):
            return {'reference': match['reference'], 'date': match['date'], 'quote': text,
                    'move': move, 'old': match['old']}
    from services.mind.workspace import workspace
    with workspace._db() as db:
        saved = reference_context.read(db, CONTEXT)
    if not saved:
        return None
    payload = saved['payload']
    if raw.casefold().rstrip('.!?') in {'no', 'cancel', 'never mind'}:
        return {'context': saved, 'cancel': True}
    if payload.get('choices'):
        choices = reference_context.choices(raw, [row['name'] for row in payload['choices']])
        if choices:
            return {'context': saved, 'choices': choices}
    if payload.get('candidate') and (bounds := _bounds(raw.rstrip('.'), clock())):
        return {'context': saved, 'date': raw.rstrip('.'), 'bounds': bounds, 'quote': text}
    return None


def _deadline_candidates(reference):
    from services.college.work import is_exam
    from services.proactive import timetable

    rows = deadlines.load()
    exam = bool(re.search(r'\bexam\b', reference, re.I))
    if exam:
        rows = [row for row in rows if is_exam(row)]
    matches = deadline_changes.resolve(rows, reference)
    if exam and not matches:
        subject = re.sub(r'\bexam\b', '', reference, flags=re.I).strip()
        aliases = [name for name in timetable.subjects()
                   if any(reference_context.key(form) == reference_context.key(subject)
                          for form in timetable.aliases(name))]
        if not subject:
            matches = rows
        elif len(aliases) == 1:
            matches = [row for row in rows if row.get('subject') == aliases[0] or
                       timetable.mentions_subject(row['what'], timetable.aliases(aliases[0]))]
    return [{'name': row['what'], 'deadline': deadline_changes.identity(row)} for row in matches]


def _temporal_candidates(reference):
    from services.mind.dialogue import dialogue

    rows = [row for row in TemporalMemory(dialogue.store).evidence().values()
            if row['status'] in {'planned', 'postponed', 'uncertain'}]
    indices = reference_context.choices(reference, [row['subject'] for row in rows])
    return [{'name': rows[i]['subject'], 'temporal': rows[i]} for i in indices]


def _ask(saved, state, prompt):
    from services.mind.workspace import workspace

    with workspace._db() as db:
        db.execute('BEGIN IMMEDIATE')
        if saved:
            reference_context.require(db, saved)
        reference_context.remember(db, CONTEXT, state)
    return ActionResult(True, prompt, repeatable=False)


def awaiting():
    from services.mind.workspace import workspace

    try:
        with workspace._db() as db:
            return reference_context.read(db, CONTEXT) is not None
    except (ValueError, OSError, sqlite3.Error):
        return False


def clear():
    from services.mind.workspace import workspace

    with workspace._db() as db:
        reference_context.clear(db, CONTEXT)


def run(parsed):
    try:
        return _prepare(parsed)
    except (AutomationError, ValueError, OSError, sqlite3.Error):
        return ActionResult(False, 'I could not verify that date. What is the saved commitment name and exact date?',
                            repeatable=False)


def _prepare(parsed):
    from services.automation.intent import _ask_first
    from services.mind.workspace import workspace

    now = clock()
    saved = parsed.get('context')
    if saved:
        with workspace._db() as db:
            reference_context.require(db, saved)
        if parsed.get('cancel'):
            clear()
            return ActionResult(True, 'Okay, cancelled the date change.', repeatable=False)
        state = saved['payload']
        offered = state.pop('choices', [])
        indices = parsed.get('choices')
        if indices and len(indices) != 1:
            return ActionResult(False, 'Which exact saved commitment did you mean?', repeatable=False)
        candidate = offered[indices[0]] if indices else state['candidate']
        if 'bounds' in parsed:
            state.update(date=parsed['date'], bounds=parsed['bounds'], quote=parsed['quote'], noted=now.isoformat())
    else:
        candidates = _deadline_candidates(parsed['reference']) or _temporal_candidates(parsed['reference'])
        state = {**parsed, 'noted': now.isoformat(), 'bounds': _bounds(parsed['date'], now)}
        if len(candidates) > 1:
            offered = candidates[:5]
            subjects = ', '.join(f"{i}. {row['name']}" for i, row in enumerate(offered, 1))
            return _ask(None, {**state, 'choices': offered}, f'Which saved commitment moved? {subjects}')
        if not candidates and parsed['move']:
            return ActionResult(False, 'Which saved commitment moved?', repeatable=False)
        candidate = candidates[0] if candidates else {'name': parsed['reference']}
    if not state['bounds']:
        if 'deadline' in candidate:
            return _ask(saved, {**state, 'candidate': candidate}, f"What is the exact new date for {candidate['name']}?")
        clear()
        return ActionResult(False, f"What exact date should I use for {candidate['name']}? Repeat the name with its date.",
                            repeatable=False)
    clear()
    state['candidate'] = candidate
    date = state['bounds'][0]
    preview = date
    if old := candidate.get('deadline'):
        due = deadline_changes.changed_due(state['date'], datetime.fromisoformat(old['due']),
                                           datetime.fromisoformat(state['noted']))
        if due.date().isoformat() != date or due <= now:
            return ActionResult(False, 'What future date should I use?', repeatable=False)
        state['when'] = f"{date} at {due.strftime('%I:%M %p')}"
        preview = due.strftime('%Y-%m-%d at %I:%M %p')
    return _ask_first({'type': 'system', 'action': 'confirm_reported_date', 'state': state},
                      f"Save the date for {candidate['name']} as {preview}? Reply yes or no.")


def confirm(state):
    from services.mind.cognition import _channel
    from services.mind.dialogue import dialogue

    candidate = state['candidate']
    if old := candidate.get('deadline'):
        return deadline_changes.run({'action': 'move_deadline', 'reference': old['what'], 'expected': old,
                                     'when': state['when'], 'quote': state['quote'], 'old': state.get('old')})
    try:
        noted, now = datetime.fromisoformat(state['noted']), clock()
        name, old = candidate['name'], candidate.get('temporal')
        with dialogue._db() as db:
            db.execute('BEGIN IMMEDIATE')
            source = dialogue._remember(db, state['quote'], noted, channel=_channel.get())
            dates = state['bounds']
            update = TemporalUpdate(source=source['id'], quote=source['text'], subject=name,
                                    status='postponed' if state['move'] else 'planned', date_phrase=state['date'],
                                    start=dates[0], end=dates[1], supersedes=[old['id']] if old else [])
            evidence = {source['id']: source}
            if old:
                evidence[old['id']] = old
            TemporalMemory(dialogue.store).save(db, [update], now, evidence)
        return ActionResult(True, f"Saved the date for {name} as {dates[0]}.", repeatable=False)
    except (ValueError, OSError, sqlite3.Error):
        return ActionResult(False, 'That commitment changed or could not be verified. Give me its current name and date.',
                            repeatable=False)
