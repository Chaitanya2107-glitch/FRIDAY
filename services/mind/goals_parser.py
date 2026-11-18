"""Finite quantified goal grammar; unrecognised language never becomes a guess."""
from datetime import date, datetime
import math
import re

from services.automation.command_words import strip_leading_filler

NUMBERS = dict(zip(('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'), range(1, 13)))
AMOUNT = r'(?:\d+(?:\.\d+)?|' + '|'.join(NUMBERS) + ')'
UNITS = {'problem': 'problems', 'problems': 'problems', 'page': 'pages', 'pages': 'pages',
         'step': 'steps', 'steps': 'steps', 'minute': 'minutes', 'minutes': 'minutes',
         'min': 'minutes', 'mins': 'minutes', 'hour': 'minutes', 'hours': 'minutes',
         'time': 'visits', 'times': 'visits', 'visit': 'visits', 'visits': 'visits',
         'session': 'sessions', 'sessions': 'sessions', 'km': 'km', 'kilometres': 'km'}
DAY_NAMES = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


def amount(text):
    value = float(NUMBERS[text.lower()]) if text.lower() in NUMBERS else float(text)
    if not math.isfinite(value) or not 0 < value <= 1000000:
        raise ValueError('Use a positive target up to one million.')
    return value


def deadline(text, now=None):
    now = now or datetime.now()
    clean = text.strip().rstrip('.!?')
    value = None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', clean):
        value = date.fromisoformat(clean)
    else:
        for fmt in ('%b %d %Y', '%B %d %Y', '%d %b %Y', '%d %B %Y', '%b %d', '%B %d', '%d %b', '%d %B'):
            try:
                parsed = datetime.strptime(clean.replace(',', ''), fmt)
                value = parsed.date() if '%Y' in fmt else parsed.replace(year=now.year).date()
                if '%Y' not in fmt and value < now.date():
                    value = value.replace(year=now.year + 1)
                break
            except ValueError:
                continue
    if value is None or value < now.date() or (value - now.date()).days > 3660:
        raise ValueError('Use an unambiguous future date, for example 2026-12-15.')
    return value.isoformat()


def source(value):
    if not isinstance(value, dict) or value.get('kind') not in {'manual', 'focus', 'steps', 'visits'}:
        raise ValueError('Choose manual, focus minutes, Health Connect steps, or named-place visits.')
    kind = value['kind']
    allowed = {'kind'} | ({'label', 'category'} if kind == 'focus' else {'device'} if kind == 'steps' else {'place', 'device'} if kind == 'visits' else set())
    if set(value) - allowed or kind == 'focus' and len(set(value) & {'label', 'category'}) != 1 or kind == 'visits' and not value.get('place'):
        raise ValueError('Use one explicit measurement source.')
    for key, item in value.items():
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= (160 if key == 'device' else 80) or any(ord(c) < 32 for c in item):
            raise ValueError('Use short source names without control characters.')
    return dict(value)


def validate(value):
    optional = {'source_suspended', 'source_since'}
    allowed = {'title', 'target', 'unit', 'deadline', 'cadence', 'source', 'review_window'} | optional
    if not isinstance(value, dict) or set(value) - allowed or not allowed - optional <= set(value):
        raise ValueError('Invalid quantified goal fields.')
    title = value['title']
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160 or any(ord(c) < 32 for c in title):
        raise ValueError('Use a short goal title.')
    if type(value['target']) not in (int, float) or not math.isfinite(value['target']) or not 0 < value['target'] <= 1000000:
        raise ValueError('Use a positive target up to one million.')
    if value['unit'] not in set(UNITS.values()):
        raise ValueError('Unsupported measurable unit.')
    if bool(value['deadline']) == bool(value['cadence']):
        raise ValueError('Choose a deadline or cadence.')
    if value['deadline']:
        date.fromisoformat(value['deadline'])
    if value['cadence']:
        cadence = value['cadence']
        if not isinstance(cadence, dict) or set(cadence) != {'period', 'days'} or cadence['period'] not in {'day', 'week'}:
            raise ValueError('Use a daily or weekly cadence.')
        if not isinstance(cadence['days'], list) or not cadence['days'] or any(type(v) is not int or v not in range(7) for v in cadence['days']) or len(set(cadence['days'])) != len(cadence['days']):
            raise ValueError('Choose valid weekdays.')
    src = source(value['source'])
    expected = {'focus': 'minutes', 'steps': 'steps', 'visits': 'visits'}.get(src['kind'])
    if expected and value['unit'] != expected:
        raise ValueError('The measurement source does not match this goal unit.')
    window = value['review_window']
    if not isinstance(window, dict) or set(window) != {'day', 'start', 'end'} or type(window['day']) is not int or window['day'] not in range(7):
        raise ValueError('Choose a weekday and a review time window.')
    for key in ('start', 'end'):
        if not isinstance(window[key], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', window[key]):
            raise ValueError('Use HH:MM review times.')
    if window['start'] >= window['end']:
        raise ValueError('Use a review window within one day.')
    if 'source_suspended' in value and type(value['source_suspended']) is not bool:
        raise ValueError('Invalid source state.')
    if 'source_since' in value and (type(value['source_since']) not in (int, float) or not math.isfinite(value['source_since']) or value['source_since'] < 0):
        raise ValueError('Invalid source start time.')
    return value


def parse(text, now=None):
    raw = strip_leading_filler(text).strip().rstrip('.!?')
    explicit = re.match(r'^(?:my goal is(?: to)?|track goal|add goal|goal:)\s+', raw, re.I)
    raw = re.sub(r'^(?:my goal is(?: to)?|track goal|add goal|goal:)\s+', '', raw, flags=re.I)
    if not explicit and not re.match(r'^(?:finish|complete|solve|read|study|walk|run|focus|gym|go to gym|visit|practice|write)\b', raw, re.I):
        return None
    tail = re.fullmatch(r'(.+?)\s+(?:by (.+)|((?:every weekday|every day|daily|each day|a day|per day|a week|per week|weekly|every week)))', raw, re.I)
    if not tail:
        return None
    body = tail[1]
    parts = re.fullmatch(r'(?:(finish|complete|solve|read|study|walk|run)\s+)?(' + AMOUNT + r')\s+(.+?)\s+(problems?|pages?|steps?|minutes?|mins?|hours?|visits?|sessions?|km|kilometres)', body, re.I)
    if parts:
        verb, count, subject, unit = parts.groups()
        title = ((verb + ' ') if verb and verb.lower() in {'study', 'walk', 'run'} else '') + subject
    else:
        parts = re.fullmatch(r'(.+?)\s+(' + AMOUNT + r')\s+(problems?|pages?|steps?|minutes?|mins?|hours?|times?|visits?|sessions?|km|kilometres)', body, re.I)
        if parts:
            title, count, unit = parts.groups()
        else:
            parts = re.fullmatch(r'(study|read|walk|run)\s+(' + AMOUNT + r')\s+(hours?|minutes?|mins?|pages?|steps?|km|kilometres)', body, re.I)
            if not parts:
                parts = re.fullmatch(r'(?:finish|complete|solve)\s+(' + AMOUNT + r')\s+(problems?|pages?)', body, re.I)
                if not parts:
                    return None
                count, unit = parts.groups(); title = unit.lower()
            else:
                title, count, unit = parts.groups()
    unit = unit.lower()
    target = amount(count) * (60 if unit.startswith('hour') else 1)
    unit = UNITS[unit]
    cadence = None
    due = deadline(tail[2], now) if tail[2] else None
    if tail[3]:
        wording = tail[3].lower()
        cadence = dict(period='week' if 'week' in wording and 'weekday' not in wording else 'day',
                       days=list(range(5 if 'weekday' in wording else 7)))
    src = {'kind': 'manual'}
    if unit == 'minutes' and title.lower().startswith('study'):
        src = dict(kind='focus', category='study')
    elif unit == 'steps':
        src = dict(kind='steps')
    return validate(dict(title=title.strip(), target=target, unit=unit, deadline=due, cadence=cadence,
                         source=src, review_window=dict(day=6, start='18:00', end='21:00')))


def source_phrase(text):
    clean = text.strip()
    if clean.lower() == 'manual':
        return {'kind': 'manual'}
    if clean.lower() in {'steps', 'health connect steps'}:
        return {'kind': 'steps'}
    match = re.fullmatch(r'focus (category|project) (.{1,80})', clean, re.I)
    if match:
        return source(dict(kind='focus', **{'category' if match[1].lower() == 'category' else 'label': match[2].strip()}))
    match = re.fullmatch(r'visits to (.{1,80})', clean, re.I)
    if match:
        return source(dict(kind='visits', place=match[1].strip()))
    raise ValueError('Use manual, steps, focus category study, focus project DSA, or visits to gym.')
