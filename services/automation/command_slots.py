"""Bounded slot normalization over FRIDAY's existing local records."""

import re
import sqlite3

from services.automation import command_words as words

_CALENDAR_WORDS = {'tmr': 'tomorrow', 'tmrw': 'tomorrow', 'tmrrow': 'tomorrow', 'tomorow': 'tomorrow',
                   'tommorow': 'tomorrow', 'todai': 'today', 'tonite': 'tonight', 'mon': 'monday',
                   'tue': 'tuesday', 'tues': 'tuesday', 'wed': 'wednesday', 'thu': 'thursday',
                   'thurs': 'thursday', 'fri': 'friday', 'sat': 'saturday', 'sun': 'sunday'}
_CALENDAR_TOKEN = re.compile(r'(?<!\w)(?:' + '|'.join(_CALENDAR_WORDS) + r')(?!\w)', re.I)


def calendar(phrase):
    phrase = ' '.join(phrase.casefold().split())
    return _CALENDAR_TOKEN.sub(lambda match: _CALENDAR_WORDS[match[0].casefold()], phrase)


def has_command_tail(text):
    from services.automation.command_typos import correct_command_typo

    parts = words.split_steps(text)
    for part in parts[1:]:
        part = words.strip_leading_filler(part)
        if words.first_word(correct_command_typo(part) or part) in words.STEP_STARTERS:
            return True
    return False


def entity(name, kinds=(), *, view=None, fuzzy=True):
    from services.mind.graph import graph

    return (graph.view() if view is None else view).resolve(name, kinds, fuzzy=fuzzy)


def course(name, *, view=None, native_only=False):
    from services.proactive import timetable

    target = name.strip(' \"\'').casefold()
    if re.fullmatch(r'[a-z]( [a-z]){1,7}', target):
        target = target.replace(' ', '')
    subjects = timetable.subjects()
    matches = {subject for subject in subjects
               if target == subject.casefold() or target in {alias.casefold() for alias in timetable.aliases(subject)}}
    if matches or native_only:
        return next(iter(matches)) if len(matches) == 1 else None
    from services.automation.intent import remote_request
    from services.remote.context import remote_origin, conversation_only
    from services.screen_watch.commands import local_request
    if remote_request.get() or remote_origin.get() or conversation_only.get() or not local_request.get():
        return None
    try:
        rows = entity(name, ('course',), view=view)
    except (OSError, sqlite3.Error):
        return None
    if len(rows) == 1:
        label = rows[0]['name']
        aliases = {label.casefold(), *(alias.casefold() for alias in rows[0]['aliases'])}
        saved = {subject for subject in subjects if subject.casefold() in aliases}
        return next(iter(saved)) if len(saved) == 1 else label if not saved else None
    return None


def clarification(text):
    """Ask only for recognizable requests whose required argument is absent."""
    text = words.normalize_command(text)
    if re.fullmatch(r'(?:open|launch|close|quit|start)(?: (?:the|my))?(?: (?:app|application|program))?', text, re.I):
        return 'Which app do you mean?'
    if re.fullmatch(r'(?:message|text|ping|whatsapp|send a whatsapp)(?: (?:someone|on whatsapp|to))?', text, re.I):
        return 'Who should I message on WhatsApp, and what should I say?'
    if re.fullmatch(r'(?:move|push|shift|postpone|reschedule)(?: (?:my|the))? (?:deadline|assignment|homework)(?: to .+)?', text, re.I):
        return 'Which deadline do you want to move?'
    if re.fullmatch(r'(?:move|push|shift|postpone|reschedule) .+? (?:to|until|for)', text, re.I):
        return 'What is the new date for that deadline?'
    if re.fullmatch(r'(?:who teaches|who is the (?:instructor|teacher|faculty) for|when is my class for)', text, re.I):
        return 'Which course do you mean?'
    if re.fullmatch(r'(?:set (?:the )?|change (?:the )?)?(?:volume|brightness)(?: (?:to|at))', text, re.I):
        return 'What percentage should I set?'
    if re.fullmatch(r'remind me(?: to .+)?', text, re.I):
        return 'When should I remind you?' if ' to ' in text.casefold() else 'When, and what should I remind you about?'
    return None
