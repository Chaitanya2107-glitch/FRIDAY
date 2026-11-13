"""Finite, metadata-first wire schemas. Unknown fields always fail closed."""
import json
import math
import re

from services.remote.commands import fields
from services.remote.security import Denied

SIGNALS = {'app_usage', 'screen', 'battery', 'network', 'motion', 'places', 'audio_devices',
           'media', 'notifications', 'sleep', 'steps', 'interruption'}


def string(value, limit=120):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(not c.isprintable() for c in value):
        raise Denied('phone_schema')
    return value


def number(value, low=0, high=10**12):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise Denied('phone_schema')
    return value


def integer(value, low=0, high=2**31-1):
    if type(value) is not int:
        raise Denied('phone_schema')
    return number(value, low, high)


def boolean(value):
    if type(value) is not bool:
        raise Denied('phone_schema')


def choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise Denied('phone_schema')


def signal_list(value):
    if not isinstance(value, list) or len(value) > len(SIGNALS) or any(type(v) is not str or v not in SIGNALS for v in value) or len(set(value)) != len(value):
        raise Denied('phone_schema')


def payload(kind, data):
    if not isinstance(data, dict) or len(json.dumps(data, allow_nan=False).encode()) > 2048:
        raise Denied('phone_payload')
    required = {
        'app_usage': ('package', 'label', 'category', 'start', 'end'),
        'screen': ('state', 'unlock_count'), 'battery': ('level', 'charging'),
        'network': ('transport', 'home'), 'motion': ('activity',),
        'places': ('place', 'transition'), 'audio_devices': ('kind', 'label', 'connected'),
        'media': ('package', 'title', 'artist'), 'notifications': ('package', 'time', 'category'),
        'sleep': ('date', 'minutes'), 'steps': ('date', 'count'),
        'interruption': ('dnd', 'ringer'),
    }
    if kind not in required:
        raise Denied('phone_type')
    fields(data, required[kind], ('ssid_hash',) if kind == 'network' else ())
    for name in ('package', 'label', 'place', 'title', 'artist', 'category'):
        if name in data and not (name == 'category' and kind == 'app_usage'):
            string(data[name], 200 if name == 'package' else 120)
    if kind == 'app_usage':
        integer(data['category'], -1, 8)
        number(data['start']); number(data['end'])
        if data['end'] < data['start'] or data['end'] - data['start'] > 86400:
            raise Denied('phone_interval')
    elif kind == 'screen':
        choice(data['state'], {'on', 'off', 'unlocked'}); integer(data['unlock_count'])
    elif kind == 'battery':
        integer(data['level'], 0, 100); boolean(data['charging'])
    elif kind == 'network':
        choice(data['transport'], {'wifi', 'mobile', 'offline', 'other'}); boolean(data['home'])
        if 'ssid_hash' in data and (not isinstance(data['ssid_hash'], str) or not re.fullmatch('[a-f0-9]{64}', data['ssid_hash'])):
            raise Denied('phone_schema')
        if data['transport'] != 'wifi' and ('ssid_hash' in data or data['home']):
            raise Denied('phone_schema')
    elif kind == 'motion':
        choice(data['activity'], {'still', 'walking', 'in_vehicle'})
    elif kind == 'places':
        choice(data['transition'], {'entered', 'left'})
    elif kind == 'audio_devices':
        choice(data['kind'], {'headphones', 'bluetooth'})
        boolean(data['connected'])
    elif kind == 'notifications':
        number(data['time'])  # No title/text/content or arbitrary nested payload can pass fields().
    elif kind in {'sleep', 'steps'}:
        from datetime import date
        string(data['date'], 10)
        try:
            if date.fromisoformat(data['date']).isoformat() != data['date']:
                raise ValueError()
        except ValueError:
            raise Denied('phone_schema') from None
        if kind == 'sleep':
            number(data['minutes'], 0, 1440)
        else:
            integer(data['count'], 0, 300000)
    elif kind == 'interruption':
        integer(data['dnd'], 0, 4); integer(data['ringer'], 0, 2)
    return data


def events(args):
    fields(args, ('events', 'generation'))
    integer(args['generation'])
    if not isinstance(args['events'], list) or not 1 <= len(args['events']) <= 50:
        raise Denied('phone_batch')
    ids = set()
    for row in args['events']:
        fields(row, ('id', 'timestamp', 'type', 'payload'))
        string(row['id'], 64)
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', row['id']) or row['id'] in ids:
            raise Denied('phone_id')
        ids.add(row['id'])
        number(row['timestamp'])
        choice(row['type'], SIGNALS)
        try:
            payload(row['type'], row['payload'])
        except (ValueError, TypeError, OverflowError):
            raise Denied('phone_schema') from None
    return args


def heartbeat(args):
    fields(args, ('battery', 'app_version', 'last_sync', 'signals'))
    signal_list(args['signals'])
    if args['battery'] is not None:
        fields(args['battery'], ('level', 'charging'))
        payload('battery', args['battery'])
        if 'battery' not in args['signals']:
            raise Denied('phone_schema')
    string(args['app_version'], 48)
    number(args['last_sync'])
    return args
