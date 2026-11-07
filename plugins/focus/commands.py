"""Whole-string local focus commands and speech-friendly replies."""
import re

from services.automation.command_words import normalize_command

PATTERNS = {
    'start': r'(?:focus(?: (?P<minutes>\d+(?:\.\d+)?))?|start focus timer (?P<duration>\d+(?:\.\d+)?) minutes?)',
    'pomodoro': r'pomodoro',
    'pause': r'pause focus',
    'resume': r'resume focus',
    'stop': r'stop focus',
    'left': r'how long is left|focus status',
    'stats': r'focus stats (?P<range>today|this week)',
}
COMPILED = {kind: re.compile(pattern, re.I) for kind, pattern in PATTERNS.items()}


def result(text, *, ok=True, error=None, data=None):
    value = dict(ok=ok, text=text, speech=text, error=error)
    if data is not None:
        value['data'] = data
    return value


def duration(seconds):
    seconds = max(0, int(seconds + .999999))
    minutes, seconds = divmod(seconds, 60)
    return (f'{minutes} minute{"s" if minutes != 1 else ""}' + (f' {seconds} seconds' if seconds else '')
            if minutes else f'{seconds} seconds')


def parse(text):
    text = normalize_command(text)
    return next(((kind, match) for kind, pattern in COMPILED.items()
                 if (match := pattern.fullmatch(text))), (None, None))


def handle(focus, text):
    kind, match = parse(text)
    if kind is None:
        return result('That is not a focus command.', ok=False, error='unknown_command')
    if kind == 'start':
        return focus.start(float(match['minutes'] or match['duration']) if match['minutes'] or match['duration'] else None)
    if kind == 'pomodoro':
        return focus.start(label='Pomodoro', pomodoro=True)
    if kind in {'pause', 'resume', 'stop'}:
        return getattr(focus, kind)()
    if kind == 'left':
        data = focus.status()
        if data['state'] == 'idle':
            return result('No focus timer is running. Say focus 25 or pomodoro.', data=data)
        return result(f"{data['label']}: {duration(data['remaining_s'])} left"
                      + (' (paused).' if data['state'] == 'paused' else '.'), data=data)
    data = focus.stats(match['range'].lower())
    return result(f"Focus {data['range']}: {duration(data['minutes'] * 60)}; "
                  f"{data['completed']} completed session{'s' if data['completed'] != 1 else ''}"
                  + (f", {data['stopped']} stopped early." if data['stopped'] else '.'), data=data)
