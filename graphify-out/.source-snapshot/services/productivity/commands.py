"""Explicit tracker commands; free-text names are preserved verbatim."""
import re
import sqlite3
from datetime import date

from services.automation.command_words import normalize_command, strip_leading_filler
from services.automation.results import ActionResult
from services.productivity.store import tracker

PATTERNS = {
    'add_habit': r'(?:add|track|create) (?:a )?habit\s*:\s*(?P<name>.+)',
    'check': r'(?:check|complete|check in) habit\s*:\s*(?P<name>.+)',
    'uncheck': r'(?:uncheck|undo) habit\s*:\s*(?P<name>.+)',
    'add_task': r'(?:add|create) (?:a )?(?:todo|to-do|to do)\s*:\s*(?P<name>.+)',
    'finish_task': r'(?:complete|finish) (?:todo|to-do|to do)\s*:\s*(?P<name>.+)',
    'habits': r'habit progress|(?:show|list) my tracked habits',
    'tasks': r'(?:show|list) my (?:todos|to-dos|to do list|to-do list)',
    'open_habits': r'(?:open |show )?(?:my )?habit tracker(?: app)?',
    'open_tasks': r'(?:open |show )?(?:my )?(?:todo|to-do|to do) (?:app|list)',
    'open_today': r'(?:open |show )?(?:my )?(?:productivity app|daily dashboard)',
}


def match_command(message: str) -> dict | None:
    stem, separator, payload = message.strip().partition(':')
    # Only command scaffolding is normalized, never a stored name or title.
    source = strip_leading_filler(stem).strip() + separator + payload if separator else normalize_command(message)
    for action, pattern in PATTERNS.items():
        if match := re.fullmatch(pattern, source, re.I):
            return {'action': action, **match.groupdict()}
    return None


def run(parsed: dict, *, remote: bool = False) -> ActionResult:
    try:
        action = parsed['action']
        if action.startswith('open_'):
            if remote:
                return ActionResult(False, 'Open the tracker at the laptop; its window is local.', repeatable=False)
            from interfaces.productivity.launcher import launch
            launch({'open_habits': 'habits', 'open_tasks': 'tasks', 'open_today': 'today'}[action])
            return ActionResult(True, 'Opening your FRIDAY habit tracker and to-do app.', repeatable=False)
        if action == 'add_habit':
            tracker.save_habit(parsed['name'], list(range(7)))
            reply = f'Added daily habit "{parsed["name"].strip()}" to your tracker.'
        elif action == 'add_task':
            tracker.save_task(parsed['name'])
            reply = f'Added "{parsed["name"].strip()}" to your FRIDAY tasks.'
        else:
            data = tracker.snapshot()
            if action in {'check', 'uncheck', 'finish_task'}:
                kind = 'tasks' if action == 'finish_task' else 'habits'
                matches = [r for r in data[kind] if r.get('name', r.get('title', '')).casefold() == parsed['name'].strip().casefold()
                           and (not r.get('archived') if kind == 'habits' else r['status'] not in {'completed', 'cancelled'})]
                if len(matches) != 1:
                    raise ValueError('Use one exact active habit/task name. Open the tracker to review your list.')
                item = matches[0]
                if action == 'finish_task':
                    tracker.task_action(item['id'], 'completed', 'Owner reported completion through FRIDAY.', item['updated'])
                else:
                    tracker.check(item['id'], data['date'], action == 'check', item['revision'])
                reply = 'Saved your completion report.' if action != 'uncheck' else 'Unchecked that habit for today.'
            elif action == 'habits':
                reply = '\n'.join(f'{h["name"]}: {"done today" if data["date"] in h["checks"] else "pending" if date.today().weekday() in h["weekdays"] else "rest day"}, {h["streak"]} day streak'
                                  for h in data['habits'] if not h['archived']) or 'No tracked habits yet. Say add habit: <name>.'
            elif action == 'tasks':
                reply = '\n'.join(f'{t["title"]}: {t["status"]}' + (f', due {t["due"]}' if t['due'] else '') for t in data['tasks']) or 'No to-dos yet. Say add todo: <name>.'
            else:
                raise ValueError('Unknown tracker command.')
        return ActionResult(True, reply, repeatable=False)
    except (ValueError, OSError, sqlite3.Error) as error:
        return ActionResult(False, str(error), repeatable=False)
