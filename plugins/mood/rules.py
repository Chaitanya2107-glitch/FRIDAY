"""Small, atomic data-only rule loader. Invalid edits never erase good rules."""
import json
import math
from string import Formatter

from services.event_bus import validate_topic

MOODS = ('idle', 'happy', 'curious', 'worried', 'alarmed', 'sleepy', 'dozing',
         'focused', 'alert', 'celebrating', 'waving')


def number(value, low=0, high=3600):
    return type(value) in {int, float} and math.isfinite(value) and low <= value <= high


def validate(row):
    if not isinstance(row, dict) or row.get('mood') not in MOODS:
        raise ValueError('Unknown mood')
    if (type(row.get('priority', 0)) is not int
            or not number(row.get('duration_s', 5)) or row.get('duration_s', 5) == 0
            or type(row.get('sticky', False)) is not bool
            or not number(row.get('cooldown_s', 60), 0, 86400)
            or not number(row.get('min_idle_s', 0), 0, 86400)):
        raise ValueError('Invalid duration, priority, sticky, cooldown or idle threshold')
    message = row.get('message', '')
    if not isinstance(message, str) or len(message) > 4000:
        raise ValueError('Invalid message')
    # Only simple named fields: no attribute/index traversal or format mini-language.
    for _, field, spec, conversion in Formatter().parse(message):
        if field is not None and (not field.isidentifier() or spec or conversion):
            raise ValueError('Use simple message fields such as {percent}')
    until = row.get('until', [])
    match = row.get('match', {})
    if not isinstance(until, list) or not isinstance(match, dict):
        raise ValueError('Invalid until/match')
    for topic in until:
        validate_topic(topic)
    for key, values in match.items():
        if (not isinstance(key, str) or not isinstance(values, list) or not values
                or any(type(v) not in {str, int, bool} for v in values)):
            raise ValueError('Match values must be nonempty lists of literals')
    return dict(row)


class Rules:
    def __init__(self, path, log):
        self.path, self.log, self.content = path, log, None
        self.rows, self.late_night = [], None
        self.reload()

    def reload(self):
        try:
            if not self.path.resolve().is_relative_to(self.path.parent.resolve()):
                raise ValueError('Rules must remain inside the plugin folder')
            if self.path.stat().st_size > 131072:
                raise ValueError('Rules file is too large')
            content = self.path.read_text(encoding='utf-8-sig')
            if content == self.content:
                return
            self.content = content
            data = json.loads(content)
            if (not isinstance(data, dict) or data.get('version') != 1
                    or not isinstance(data.get('rules'), list) or len(data['rules']) > 100):
                raise ValueError('Expected version 1 and at most 100 rules')
            rows = []
            for value in data['rules']:
                row = validate(value)
                validate_topic(row.get('event'))
                rows.append(row)
            late = data.get('late_night')
            if late is not None:
                late = validate(late)
                start, end = late.get('start_hour', 1), late.get('end_hour', 6)
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= 24:
                    raise ValueError('Invalid late-night hours')
            self.rows, self.late_night = rows, late
            self.log.debug('Loaded %d Mochi rules', len(rows))
        except (OSError, ValueError, TypeError) as error:
            self.log.warning('Keeping last valid Mochi rules: %s', error)


def message(template, payload):
    class Fields(dict):
        def __missing__(self, key):
            return '?'
    fields = Fields({k: str(v)[:120] for k, v in payload.items() if type(v) in {str, int, float, bool}})
    return template.format_map(fields)[:60]
