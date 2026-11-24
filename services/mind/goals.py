"""Owner-confirmed quantified commitments and private arithmetic; no model path."""
from datetime import datetime, timedelta
import re
import threading

from services.automation.command_words import strip_leading_filler

from . import goals_math as maths, goals_parser as parser, goals_sources as storage
from .temporal_memory import TemporalMemory

_pending = {}
_lock = threading.RLock()
YES = {'yes', 'yes please', 'confirm'}
NO = {'no', 'no thanks', 'cancel'}


def _memory(store=None):
    if store is None:
        from .cognition import cognition
        store = cognition
    return TemporalMemory(store)


def _key(store=None, session='local'):
    return (str(_memory(store).store.path.resolve()), session)


def pending(*, store=None, session='local', now=None):
    with _lock:
        value = _pending.get(_key(store, session))
        return bool(value and value['expires'] > (now or datetime.now()).timestamp())


def cancel_pending(*, store=None, session='local'):
    with _lock:
        _pending.pop(_key(store, session), None)


def _reply(text, ok=True, *, awaiting=False, win=False):
    from .wording import plain
    return dict(ok=ok, text=plain({'kind': 'goal_coaching', 'answer': text}), awaiting_reply=awaiting, win=win)


def _number(value):
    return f'{value:.1f}'.rstrip('0').rstrip('.')


def preview(definition):
    cadence = definition['cadence']
    when = ('by ' + definition['deadline']) if not cadence else ('each selected day' if cadence['period'] == 'day' else 'each week') + (
        ' (weekdays)' if cadence['days'] == list(range(5)) else '')
    src = definition['source']; kind = src['kind']
    source = ('manual logs' if kind == 'manual' else 'recorded focus minutes for ' + (src.get('label') or src.get('category')) if kind == 'focus'
              else 'read-only Health Connect daily step totals (not steps since the setup time)' if kind == 'steps' else 'recorded entries to ' + src['place'])
    window = definition['review_window']
    return (f"Track {_number(definition['target'])} {definition['unit']} for {definition['title']} {when}. "
            f"Measure with {source}. Weekly check-in: {parser.DAY_NAMES[window['day']].title()} {window['start']}–{window['end']}. "
            'Data stays local and outside every model. Missing automatic data stays unavailable. No signal or permission is enabled. '
            'Save this goal? Yes or no.')


def _draft(definition, text, now, memory, key, old=None):
    parser.validate(definition)
    with _lock:
        _pending[key] = dict(kind='goal', definition=definition, source=text, expires=now.timestamp() + 120,
                             identity=old['id'] if old else None, revision=old['revision'] if old else None)
    return _reply(preview(definition), awaiting=True)


def _get(memory, identity):
    value = next((row for row in memory.private_commitments() if row['id'] == int(identity)), None)
    if value is None:
        raise ValueError('That private goal is not available.')
    return value


def _measure(row, start, end, memory, measure):
    definition = row['definition']
    start = max(start, datetime.fromtimestamp(definition.get('source_since', row['created'])))
    if start >= end:
        return 0.0 if definition['source']['kind'] == 'manual' else None
    if definition.get('source_suspended'):
        return None
    if definition['source']['kind'] == 'manual':
        return sum(item['value'] for item in memory.private_logs(row['id']) if start.timestamp() <= item['at'] < end.timestamp())
    if measure is None:
        from .coaching_metrics import measure
    return measure(definition['source'], start, end)


def _progress(row, now, memory, measure=None, *, weekly=False):
    definition = dict(row['definition'])
    created = datetime.fromtimestamp(row['created'])
    if weekly and (definition.get('cadence') or {}).get('period') == 'day':
        definition['target'] *= len(definition['cadence']['days'])
        definition['cadence'] = dict(definition['cadence'], period='week')
    start, end = maths.window(definition, now, created)
    stop = min(now + timedelta(microseconds=1), end)
    if definition['cadence']:
        day, values = start.replace(hour=0, minute=0, second=0, microsecond=0), []
        while day < stop:
            if day.weekday() in definition['cadence']['days']:
                values.append(_measure(row, max(day, start), min(day + timedelta(days=1), stop), memory, measure))
            day += timedelta(days=1)
        done = None if any(value is None for value in values) else sum(values)
    else:
        done = _measure(row, start, stop, memory, measure)
    return maths.progress(definition, done, now, created)


def _describe(row, result):
    definition = row['definition']
    text = f"Goal {row['id']} — {definition['title']}: "
    from services.mind.graph_sources import goal_connections
    names = goal_connections(row['id'])
    linked = ' Connected to ' + ', '.join(names) + '.' if names else ''
    if result['unavailable']:
        return text + 'measurement unavailable. No zero or completion was inferred. Confirm another source or a manual source to log progress.' + linked
    noun = 'logged' if definition['source']['kind'] == 'manual' else 'recorded'
    text += f"{_number(result['done'])}/{_number(result['target'])} {result['unit']} {noun}; {_number(result['remaining'])} remaining. "
    if definition['cadence']:
        text += 'For this ' + ('week' if definition['cadence']['period'] == 'week' else 'day') + '. '
        if not result['due_today']:
            text += 'Today is outside your selected days. '
    else:
        text += 'Deadline ' + definition['deadline'] + '. '
    if result['needed_per_day'] is not None:
        text += f"Needed from here: {_number(result['needed_per_day'])} {result['unit']} per remaining selected day. "
    elif result['remaining']:
        text += 'The recorded period has ended; there are no remaining days in it. '
    if result['projected_finish']:
        text += 'At the recorded average pace, projected finish ' + result['projected_finish'] + '; an estimate, not a promise. '
    if result['shortfall'] > 0 and result['remaining']:
        text += f"{_number(result['shortfall'])} {result['unit']} below a straight-line plan through completed days. Options: move the date, reduce the target, or ask for study-block proposals. "
    elif result['slack'] > 0:
        text += f"{_number(result['slack'])} {result['unit']} above a straight-line plan through completed days. "
    return text.strip() + linked


def _win(row, result, memory, now):
    if result['done'] is None or result['done'] <= 0:
        return False
    quarter = min(4, int(4 * result['done'] / result['target']))
    key = f"win:{row['id']}:{row['revision']}:{result['start']}:{quarter}"
    return storage.mark(memory, key, now)


def log_progress(identity, value, *, event_id=None, now=None, store=None, measure=None):
    now = now or datetime.now(); memory = _memory(store)
    memory.log_private_progress(identity, value, event_id=event_id, now=now)
    row = _get(memory, identity)
    result = _progress(row, now, memory, measure)
    return _reply(_describe(row, result) + ' A missed day is just a missing entry, not a judgement.', win=_win(row, result, memory, now))


def _scene(now=None):
    from services.plugin_runtime import current_manager
    manager = current_manager()
    scene = manager.get_service('scenes') if manager else None
    active = manager.invoke(scene.api, scene.status).get('active') if scene else None
    from services.presence.engine import current
    presence = current(now)
    if presence.get('state') == 'asleep' and presence.get('data_available') and presence.get('confidence', 0) >= .6:
        return 'sleep'
    if active:
        return active
    from services.automation.modes import active as legacy_mode
    return (legacy_mode() or {}).get('name')


def _slots(now, memory, minutes, classes=None, scene=None, sleep=None):
    if classes is None:
        from services.schedule_adapter import classes_on
        classes = classes_on
    blocks = [row['definition'] for row in memory.private_commitments('study_block')]
    return maths.free_slots(now, minutes, classes=classes, blocks=blocks, sleep=sleep or ('23:00', '07:00'),
                            scene=_scene(now) if scene is None else scene)


def private_turn(text, *, store=None, session='local', now=None):
    clean = strip_leading_filler(text).strip().rstrip('.!?')
    with _lock:
        if _pending.get(_key(store, session)):
            return True  # Unrecognised/expired setup replies must not reach a model.
    if re.match(r'^add goal(?: (?:low|normal|high))?\s*:', clean, re.I):
        return False  # Existing unquantified workspace goals retain their command grammar.
    if re.fullmatch(r'(?:my coaching goals|show my coaching goals|weekly goal review|goal progress|goal \d+(?: progress)?|log .+ for goal \d+|'
                    r'use .+ for goal \d+|'
                    r'(?:change|move|replace|suggest study blocks for) goal \d+.*|goal \d+ (?:source|review) .+)', clean, re.I):
        return True
    if re.match(r'^(?:(?:my goal is|track goal|add goal)\b|goal:)', clean, re.I):
        return True
    if re.match(r'^(?:finish|complete|solve|study|focus|gym|visit|walk|run|practice|read)\b.*\b' + parser.AMOUNT + r'\b.*\b(?:by|every|daily|weekly|per|a week)\b', clean, re.I):
        return True
    try:
        return parser.parse(clean) is not None
    except ValueError:
        return True


def handle(text, now=None, *, store=None, measure=None, classes=None, scene=None, sleep=None, session='local'):
    now = now or datetime.now(); memory = _memory(store); key = _key(store, session)
    clean = strip_leading_filler(text).strip().rstrip('.!?'); lower = clean.lower()
    with _lock:
        waiting = _pending.get(key)
        if waiting and waiting['expires'] <= now.timestamp():
            _pending.pop(key, None); waiting = None
    if waiting and lower in YES | NO:
        with _lock:
            _pending.pop(key, None)
        if lower in NO:
            return _reply('Nothing added or changed.')
        try:
            if waiting['kind'] == 'goal':
                if 'source_since' in waiting['definition']:
                    waiting['definition']['source_since'] = now.timestamp()
                row = memory.save_private_commitment(waiting['definition'], waiting['source'], identity=waiting['identity'],
                    expected_revision=waiting['revision'], now=now)
                return _reply(f"Goal {row['id']} saved privately. " + _describe(row, _progress(row, now, memory, measure)))
            if waiting['kind'] == 'block':
                row = _get(memory, waiting['identity'])
                slot = waiting['slot']; start = datetime.fromisoformat(slot['start'])
                if row['revision'] != waiting['revision'] or start < now or not any(s['start'] == slot['start'] and s['end'] == slot['end'] for s in _slots(start, memory, slot['minutes'], classes, scene, sleep)):
                    return _reply('The goal or free slot changed. Request fresh block proposals.', False)
                definition = dict(goal_id=row['id'], goal_revision=row['revision'], start=slot['start'], end=slot['end'])
                memory.save_private_commitment(definition, waiting['source'], kind='study_block', now=now)
                return _reply('Private study block saved for ' + slot['start'].replace('T', ' ') + '. It does not start a timer or scene automatically.')
            return _reply('Choose add block 1, 2 or 3 first; I will show it and ask before adding anything.', False)
        except (ValueError, OSError) as error:
            return _reply(str(error), False)
    try:
        if lower in {'my coaching goals', 'show my coaching goals', 'weekly goal review', 'goal progress'}:
            rows = memory.private_commitments()
            return _reply('\n'.join(_describe(row, _progress(row, now, memory, measure)) for row in rows[:20]) or 'No private quantified goals are confirmed yet.')
        if match := re.fullmatch(r'goal (\d+)(?: progress)?', clean, re.I):
            row = _get(memory, match[1]); return _reply(_describe(row, _progress(row, now, memory, measure)))
        if match := re.fullmatch(r'log (' + parser.AMOUNT + r')(?: (problems?|pages?|minutes?|hours?|steps?|visits?|sessions?|km))? for goal (\d+)', clean, re.I):
            row = _get(memory, match[3]); value = parser.amount(match[1]); unit = match[2]
            if unit and parser.UNITS[unit.lower()] != row['definition']['unit']:
                raise ValueError('That log unit does not match this goal.')
            return log_progress(row['id'], value * (60 if unit and unit.lower().startswith('hour') else 1), now=now, store=store, measure=measure)
        if match := re.fullmatch(r'change goal (\d+) target to (' + parser.AMOUNT + r')', clean, re.I):
            row = _get(memory, match[1]); definition = dict(row['definition'], target=parser.amount(match[2]))
            return _draft(definition, clean, now, memory, key, row)
        if match := re.fullmatch(r'move goal (\d+) deadline to (.+)', clean, re.I):
            row = _get(memory, match[1])
            if row['definition']['cadence']:
                raise ValueError('This goal uses a cadence. Replace it with an explicit deadline goal if you want to change that.')
            return _draft(dict(row['definition'], deadline=parser.deadline(match[2], now)), clean, now, memory, key, row)
        match = re.fullmatch(r'use (.+) for goal (\d+)', clean, re.I)
        alternate = re.fullmatch(r'goal (\d+) source (.+)', clean, re.I)
        if match or alternate:
            identity, wording = (match[2], match[1]) if match else (alternate[1], alternate[2])
            row = _get(memory, identity)
            return _draft(dict(row['definition'], source=parser.source_phrase(wording), source_since=now.timestamp(), source_suspended=False), clean, now, memory, key, row)
        if match := re.fullmatch(r'replace goal (\d+) with (.+)', clean, re.I):
            row = _get(memory, match[1]); definition = parser.parse(match[2], now)
            if definition is None or definition['unit'] != row['definition']['unit']:
                raise ValueError('Use a quantified replacement with the same unit, or create a separate goal.')
            if definition['source'] != row['definition']['source']:
                definition['source_since'] = now.timestamp()
            return _draft(definition, clean, now, memory, key, row)
        if match := re.fullmatch(r'goal (\d+) review on (' + '|'.join(parser.DAY_NAMES) + r') (\d\d:\d\d) to (\d\d:\d\d)', clean, re.I):
            row = _get(memory, match[1]); window = dict(day=parser.DAY_NAMES.index(match[2].lower()), start=match[3], end=match[4])
            return _draft(dict(row['definition'], review_window=window), clean, now, memory, key, row)
        if match := re.fullmatch(r'suggest study blocks for goal (\d+)(?: for (\d+) minutes)?', clean, re.I):
            row = _get(memory, match[1]); slots = _slots(now, memory, int(match[2] or 25), classes, scene, sleep)
            if not slots:
                return _reply('No eligible free slot was found. Classes, sleep, exam scenes and saved blocks are excluded.')
            with _lock:
                _pending[key] = dict(kind='slots', identity=row['id'], revision=row['revision'], slots=slots, expires=now.timestamp() + 120)
            bounds = ('Planning uses your confirmed sleep window ' + sleep[0] + '–' + sleep[1] + '.' if sleep else
                      'Planning bounds: proposals07:00–22:00; default23:00–07:00 exclusion. These are reviewable planning bounds, not observed sleep.')
            return _reply(bounds + '\n' + '\n'.join(f"{i + 1}. {slot['start'].replace('T', ' ')} to {slot['end'][11:16]}" for i, slot in enumerate(slots)) + '\nSay add block 1, 2 or 3. Nothing is added yet.', awaiting=True)
        if waiting and waiting['kind'] == 'slots' and (match := re.fullmatch(r'add block ([1-3])', clean, re.I)):
            index = int(match[1]) - 1
            if index >= len(waiting['slots']):
                raise ValueError('Choose one of the displayed block numbers.')
            slot = waiting['slots'][index]
            with _lock:
                _pending[key] = dict(kind='block', identity=waiting['identity'], revision=waiting['revision'], slot=slot,
                                     source=clean, expires=now.timestamp() + 120)
            return _reply('Add a private study block ' + slot['start'].replace('T', ' ') + ' to ' + slot['end'][11:16] + '? Yes or no.', awaiting=True)
        definition = parser.parse(clean, now)
        if definition is not None:
            return _draft(definition, clean, now, memory, key)
        if private_turn(clean, store=store, session=session):
            return _reply('Use a quantified goal such as finish 100 DSA problems by Dec 15, study 2 hours every weekday, or gym 3 times a week.', False)
        return None
    except (ValueError, OSError) as error:
        return _reply(str(error), False)


def weekly_candidates(now=None, *, store=None, measure=None):
    now = now or datetime.now(); memory = _memory(store)
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    key = 'goal-weekly:' + week
    if storage.marked(memory, key):
        return []
    rows = []
    for row in memory.private_commitments():
        window = row['definition']['review_window']
        if now.weekday() == window['day'] and window['start'] <= now.strftime('%H:%M') < window['end']:
            rows.append(row)
    if not rows:
        return []
    text = 'Your weekly goal check-in. ' + ' '.join(_describe(row, _progress(row, now, memory, measure, weekly=True)) for row in rows[:3])
    return [dict(key=key, text=_reply(text)['text'], kind='goal_weekly', reason='Your confirmed weekly review window is open.', question=False)]


def mark_weekly_sent(key, now=None, *, store=None):
    return storage.mark(_memory(store), key, now)


def forget_phone(device, *, store=None):
    memory = _memory(store)
    memory.forget_private_phone(device)
    from .outcome_learning import OutcomeLearning
    OutcomeLearning(memory.store).forget_private_phone(device)
    with _lock:
        for key in [key for key in _pending if key[0] == str(memory.store.path.resolve())]:
            _pending.pop(key, None)


def status(now=None):
    now = now or datetime.now()
    memory = _memory()
    values = []
    for row in memory.private_commitments():
        progress = _progress(row, now, memory)
        definition = row['definition']
        values.append(dict(id=row['id'], title=definition['title'], unit=definition['unit'],
                           manual=definition['source']['kind'] == 'manual', done=progress['done'], target=progress['target']))
    return dict(goals=values)


def manual_tap(identity, value, receipt, *, device_id=None, now=None):
    from .care_safeguard import active
    if active(now):
        raise ValueError('Coaching is paused.')
    now = now or datetime.now()
    memory = _memory()
    storage.log(memory, identity, value, event_id=receipt, now=now,
                source_links=[dict(device=device_id)] if device_id else [])
    row = _get(memory, identity)
    result = _progress(row, now, memory)
    if _win(row, result, memory, now):
        from services.event_bus import event_bus
        event_bus.publish('mood.set', dict(mood='celebrating', duration_s=4, priority=1), plugin_id='coaching')
    return dict(recorded=True)
