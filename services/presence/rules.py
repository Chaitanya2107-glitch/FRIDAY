"""Finite offline presence-rule grammar and strict local rule definitions."""
import hashlib
import json
import re

STATES = {'at_desk', 'on_phone', 'in_class', 'commuting', 'at_college_free', 'at_home', 'away', 'winding_down', 'asleep'}
DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def fields(value, required=(), optional=()):
    if not isinstance(value, dict) or set(required) - set(value) or set(value) - set(required) - set(optional):
        raise ValueError('Unknown or missing presence rule fields.')


def label(value, limit=80):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or any(ord(c) < 32 for c in value):
        raise ValueError('Use a short nonempty name without control characters.')
    return value.strip()


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Use HH:MM time.')
    return value


def conditions(value):
    fields(value, optional=('days', 'after', 'before', 'in_class'))
    days = value.get('days', 'daily')
    if isinstance(days, str):
        if days not in {'daily', 'weekdays', 'weekends'}:
            raise ValueError('Use daily, weekdays, weekends or named weekdays.')
    elif not isinstance(days, list) or not days or any(day not in DAYS for day in days):
        raise ValueError('Use mon through sun.')
    if ('after' in value) != ('before' in value):
        raise ValueError('Time conditions require both after and before.')
    for key in ('after', 'before'):
        if key in value:
            clock(value[key])
    if 'in_class' in value and type(value['in_class']) is not bool:
        raise ValueError('in_class must be true or false.')


def trigger(value):
    if not isinstance(value, dict):
        raise ValueError('A presence trigger must be an object.')
    if value.get('type') == 'time':
        fields(value, ('type', 'at'))
        clock(value['at'])
        return
    fields(value, ('type', 'event'), ('place', 'state'))
    event = value['event']
    if value['type'] != 'presence' or event not in {'arrive', 'leave', 'enter_state', 'leave_state'}:
        raise ValueError('Use arrive/leave place or enter_state/leave_state.')
    if event in {'arrive', 'leave'}:
        if set(value) != {'type', 'event', 'place'}:
            raise ValueError('Place transitions require one place.')
        label(value['place'])
    elif set(value) != {'type', 'event', 'state'} or value['state'] not in STATES:
        raise ValueError('Use a known presence state.')


def action(value):
    if not isinstance(value, dict):
        raise ValueError('Each rule action must be an object.')
    kind = value.get('type')
    if kind == 'start_scene':
        fields(value, ('type', 'name'))
        from plugins.scenes.catalog import key
        key(value['name'])
    elif kind in {'show_card', 'phone_notice'}:
        fields(value, ('type', 'text'), ('title',))
        label(value['text'], 2000)
        label(value.get('title', 'FRIDAY'), 80)
    elif kind == 'phone_mode':
        fields(value, ('type',), ('ringer', 'dnd'))
        if len(value) != 2 or ('ringer' in value and value['ringer'] not in {'silent', 'vibrate', 'normal'}) or (
                'dnd' in value and value['dnd'] not in {'priority', 'all', 'none'}):
            raise ValueError('Choose one phone ringer or DND mode.')
    elif kind == 'read_due_today':
        fields(value, ('type',))
    else:
        raise ValueError('Only reviewed scene, card, phone notice/mode and due-today actions are supported.')


def validate(value):
    fields(value, ('trigger', 'conditions', 'actions'))
    trigger(value['trigger']); conditions(value['conditions'])
    if not isinstance(value['actions'], list) or not 1 <= len(value['actions']) <= 8:
        raise ValueError('Use one to eight finite actions.')
    for row in value['actions']:
        action(row)
    scene_positions = [i for i, row in enumerate(value['actions']) if row['type'] == 'start_scene']
    if len(scene_positions) > 1 or scene_positions and scene_positions != [0]:
        raise ValueError('A rule may start one scene, as its first action.')
    json.dumps(value, allow_nan=False)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def parse(text):
    """Unknown language returns None; recognized malformed grammar raises ValueError."""
    source = text.strip().rstrip('.!?')
    parts = re.fullmatch(r'when i (reach|arrive at|leave) (.+?) (start .+? mode|tell me what is due today)', source, re.I)
    if parts:
        event = 'leave' if parts[1].lower() == 'leave' else 'arrive'
        place = label(parts[2].lower())
        operation = parts[3]
        actions = [{'type': 'read_due_today'}] if operation.lower() == 'tell me what is due today' else [
            {'type': 'start_scene', 'name': operation[6:-5].strip().lower()}]
        return validate(dict(trigger=dict(type='presence', event=event, place=place), conditions={}, actions=actions))
    parts = re.fullmatch(r'at (\d{1,2})(?::(\d{2}))?\s*(am|pm)? start (.+?) mode', source, re.I)
    if parts:
        hour, minute = int(parts[1]), int(parts[2] or 0)
        if parts[3]:
            if not 1 <= hour <= 12:
                raise ValueError('Use a time from 1 to 12 with am/pm.')
            hour = hour % 12 + (12 if parts[3].lower() == 'pm' else 0)
        return validate(dict(trigger=dict(type='time', at=clock(f'{hour:02}:{minute:02}')), conditions={},
                             actions=[dict(type='start_scene', name=parts[4].lower())]))
    return None


def preview(value):
    tr = value['trigger']
    when = ('At ' + tr['at']) if tr['type'] == 'time' else tr['event'].replace('_', ' ').capitalize() + ' ' + tr.get('place', tr.get('state', '')).replace('_', ' ')
    lines = [when + ':']
    for row in value['actions']:
        kind = row['type']
        lines.append('Start ' + row['name'] + ' mode.' if kind == 'start_scene' else 'Read what is due today.' if kind == 'read_due_today'
                     else 'Set phone ' + next(k + ' to ' + str(v) for k, v in row.items() if k != 'type') if kind == 'phone_mode'
                     else ('Send phone notice: ' if kind == 'phone_notice' else 'Show card: ') + row['text'])
    if value['conditions']:
        lines.append('Conditions: ' + json.dumps(value['conditions'], sort_keys=True))
    lines.append('Starts at Ask. No automatic effect until you confirm a matching occurrence.')
    return '\n'.join(lines)


def eligible(value, now, current):
    cond = value['conditions']
    days = cond.get('days', 'daily')
    if (days == 'weekdays' and now.weekday() >= 5 or days == 'weekends' and now.weekday() < 5
            or isinstance(days, list) and DAYS[now.weekday()] not in days):
        return False
    stamp = now.strftime('%H:%M')
    if 'after' in cond:
        a, b = cond['after'], cond['before']
        if not (a <= stamp < b if a <= b else stamp >= a or stamp < b):
            return False
    if 'in_class' in cond and (current.get('in_class', current.get('state') == 'in_class') is True) != cond['in_class']:
        return False
    return True


def matches(value, now, current, previous):
    tr = value['trigger']
    if not eligible(value, now, current):
        return None
    if tr['type'] == 'time':
        target = now.replace(hour=int(tr['at'][:2]), minute=int(tr['at'][3:]), second=0, microsecond=0)
        return target.isoformat() if 0 <= (now - target).total_seconds() < 300 else None
    if previous is None or not current.get('data_available', False) or current.get('confidence', 0) < .6:
        return None
    if tr['event'] in {'arrive', 'leave'}:
        edge = current.get('transition') or {}
        if type(edge.get('at')) in (int, float) and not 0 <= now.timestamp() - edge['at'] <= 120:
            return None
        if edge.get('event') == tr['event'] and edge.get('place', '').casefold() == tr['place'].casefold():
            return str(edge.get('id') or (edge.get('device', '') + ':' + str(edge.get('at', ''))))
        return None
    before, after = previous.get('state'), current.get('state')
    if before != after and (after if tr['event'] == 'enter_state' else before) == tr['state']:
        return str(current.get('since', now.timestamp())) + ':' + tr['event']
    return None
