"""Island adapters for FRIDAY's existing shared tracker; no separate data store."""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal

from .plugins import Manifest


class TrackerPlugin:
    def __init__(self, kind: Literal['todo', 'habit'], store=None):
        if kind not in {'todo', 'habit'}:
            raise ValueError('Unknown tracker plugin')
        self.kind, self._store = kind, store
        self.manifest = Manifest('todo' if kind == 'todo' else 'habit_tracker',
                                 'Todos' if kind == 'todo' else 'Habits', (kind,))

    @property
    def store(self):
        if self._store is None:
            from services.productivity.store import tracker
            self._store = tracker
        return self._store

    def snippet(self) -> str:
        return ''  # The capsule stays quiet; progress belongs in the widget.

    def rows(self, snapshot: dict) -> list[dict]:
        if self.kind == 'habit':
            return [h for h in snapshot['habits'] if not h['archived']]
        return [t for t in snapshot['tasks'] if t['status'] not in {'completed', 'cancelled'}]

    def widget(self, limit: int = 6) -> dict:
        data = self.store.snapshot()
        rows = self.rows(data)
        items = []
        if self.kind == 'habit':
            due = [h for h in rows if date.fromisoformat(data['date']).weekday() in h['weekdays']]
            done = sum(data['date'] in h['checks'] for h in due)
            summary = f'{done}/{len(due)} checked in today' if due else 'No habits scheduled today'
            rows.sort(key=lambda h: (h not in due, data['date'] in h['checks'], h['id']))
            for habit in rows[:limit]:
                checked = data['date'] in habit['checks']
                scheduled = habit in due
                state = 'Done today' if checked else 'Not yet' if scheduled else 'Rest day'
                items.append({'id': str(habit['id']), 'label': habit['name'],
                              'detail': f"{state} · {habit['streak']} day streak",
                              'action': {'label': 'Undo' if checked else 'Check in',
                                         'action': 'uncheck' if checked else 'check',
                                         'item': str(habit['id']), 'revision': habit['revision'],
                                         'value': data['date'], 'disabled': not scheduled}})
        else:
            summary = f'{len(rows)} open task{ "s" if len(rows) != 1 else ""}' if rows else 'All clear. Add your next task.'
            for task in rows[:limit]:
                remaining = len(task['steps']) - task['cursor']
                detail = 'Finish planned steps in FRIDAY' if remaining > 0 else task['status'].capitalize()
                if task['due']:
                    detail += f" · Due {task['due']}"
                items.append({'id': str(task['id']), 'label': task['title'], 'detail': detail,
                              'action': {'label': 'Done', 'action': 'complete', 'item': str(task['id']),
                                         'revision': task['updated'],
                                         'disabled': remaining > 0 or task['status'] != 'active'}})
        if len(rows) > limit:
            summary += f' · Showing {limit} of {len(rows)}; search by name in {self.kind} commands'
        return {'title': self.manifest.name, 'text': summary, 'items': items,
                'input': {'label': 'New habit' if self.kind == 'habit' else 'New todo',
                          'placeholder': 'A small daily habit…' if self.kind == 'habit' else 'Something to do…',
                          'action': 'add', 'max_length': 160}}

    def _act(self, action: str, item: str = '', value: str = '', revision=None) -> dict:
        if action == 'add':
            if item or revision is not None:
                raise ValueError('Invalid add action.')
            if self.kind == 'habit':
                self.store.save_habit(value, list(range(7)))
            else:
                self.store.save_task(value)
            return {'ok': True, 'text': 'Habit added.' if self.kind == 'habit' else 'Todo added.'}
        allowed = {'check', 'uncheck'} if self.kind == 'habit' else {'complete'}
        if action not in allowed or not item.isascii() or not item.isdigit() or len(item) > 12:
            raise ValueError('Unknown tracker action or item.')
        expected = (int,) if self.kind == 'habit' else (int, float)
        if type(revision) not in expected:
            raise ValueError('Refresh the item before changing it.')
        data = self.store.snapshot()
        row = next((r for r in self.rows(data) if str(r['id']) == item), None)
        if row is None:
            raise ValueError('That item is no longer available. Refresh the list.')
        if self.kind == 'habit':
            if value != data['date']:
                raise ValueError('The day changed. Refresh before checking in.')
            self.store.check(row['id'], value, action == 'check', revision=revision)
            text = 'Checked in for today.' if action == 'check' else 'Check-in undone.'
        else:
            if len(row['steps']) > row['cursor']:
                raise ValueError('This task has unfinished steps. Complete them in FRIDAY.')
            self.store.task_action(row['id'], 'completed', 'Owner marked complete in FRIDAY Island.', revision=revision)
            text = 'Todo completed.'
        return {'ok': True, 'text': text}

    async def action(self, action: str, item: str = '', value: str = '', revision=None) -> dict:
        try:
            return await asyncio.to_thread(self._act, action, item, value, revision)
        except ValueError as error:
            return {'ok': False, 'text': str(error)}
        except ImportError:
            return {'ok': False, 'text': 'FRIDAY’s productivity module is unavailable in this checkout.'}

    def _command(self, text: str) -> dict:
        parts = text.strip().split(maxsplit=1)
        tail = parts[1] if len(parts) > 1 else ''
        parts = tail.split(maxsplit=1)
        verb, query = (parts[0], parts[1] if len(parts) > 1 else '') if parts else ('', '')
        if not tail or tail.casefold() in {'list', 'progress'}:
            widget = self.widget(limit=20)
            lines = [widget['text'], *[f"#{r['id']} {r['label']} · {r['detail']}" for r in widget['items']]]
            return {'ok': True, 'text': '\n'.join(lines)}
        if verb.casefold() == 'add':
            return self._act('add', value=query)
        verbs = {'check': 'check', 'uncheck': 'uncheck', 'undo': 'uncheck'} if self.kind == 'habit' else {'done': 'complete', 'complete': 'complete'}
        if verb.casefold() in verbs:
            data = self.store.snapshot()
            matches = [r for r in self.rows(data) if (f"#{r['id']}" == query.strip()
                       or r['name' if self.kind == 'habit' else 'title'].casefold() == query.strip().casefold())]
            if len(matches) != 1:
                raise ValueError('Use the full name or #ID from the list to choose one item.')
            row = matches[0]
            return self._act(verbs[verb.casefold()], str(row['id']), data['date'],
                             row['revision' if self.kind == 'habit' else 'updated'])
        if self.kind == 'todo':
            return self._act('add', value=tail)
        raise ValueError('Use habit add <name>, habit check <name or #ID>, or habit undo <name or #ID>.')

    async def command(self, text: str) -> dict:
        try:
            return await asyncio.to_thread(self._command, text)
        except ValueError as error:
            return {'ok': False, 'text': str(error)}
        except ImportError:
            return {'ok': False, 'text': 'FRIDAY’s productivity module is unavailable in this checkout.'}

    def suggestions(self, text: str) -> list[dict]:
        parts = text.strip().split(maxsplit=1)
        tail = parts[1] if len(parts) > 1 else ''
        parts = tail.split(maxsplit=1)
        verb, query = (parts[0], parts[1] if len(parts) > 1 else '') if parts else ('', '')
        verbs = {'check', 'undo', 'uncheck'} if self.kind == 'habit' else {'done', 'complete'}
        if verb.casefold() in verbs:
            data = self.store.snapshot()
            rows = self.rows(data)
            key = 'name' if self.kind == 'habit' else 'title'
            return [{'text': f"{self.kind} {verb.casefold()} #{r['id']}", 'detail': r[key]}
                    for r in rows if query.casefold() in r[key].casefold() or query == f"#{r['id']}"][:6]
        examples = [f'{self.kind} list', f'{self.kind} add ']
        examples += [f'{self.kind} check ', f'{self.kind} undo '] if self.kind == 'habit' else [f'{self.kind} done ']
        return [{'text': c, 'detail': 'Tracker command'} for c in examples if c.startswith(text.casefold().strip())]
