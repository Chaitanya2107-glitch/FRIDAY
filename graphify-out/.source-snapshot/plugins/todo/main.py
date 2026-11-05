"""JSON todos shared by commands, the Island widget and authenticated GET routes."""
from datetime import datetime, timezone
import json
import threading

from services import settings_store


class Todos:
    def __init__(self, api):
        self.api, self.path = api, api.data_dir / 'todos.json'
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {'version': 1, 'next_id': 1, 'items': []}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != 1 or type(data.get('next_id')) is not int
                or not isinstance(data.get('items'), list)
                or any(not isinstance(row, dict) or type(row.get('id')) is not int
                       or not isinstance(row.get('text'), str) or type(row.get('done')) is not bool
                       for row in data['items'])):
            raise ValueError('Todos file is damaged. Restore todos.json before changing it.')
        return data

    def snapshot(self):
        with self.lock:
            return self._read()

    def change(self, action, value=''):
        with self.lock:
            self.api._active()
            data = self._read()
            if action == 'add':
                text = str(value).strip()
                if not text or len(text) > 160:
                    return {'ok': False, 'text': 'Use a todo between 1 and 160 characters.', 'error': 'invalid_text'}
                data['items'].append(dict(id=data['next_id'], text=text, done=False,
                                          created_at=datetime.now(timezone.utc).isoformat()))
                data['next_id'] += 1
            elif action in {'done', 'remove'}:
                item = next((row for row in data['items'] if str(row['id']) == str(value)), None)
                if item is None:
                    return {'ok': False, 'text': 'Todo not found. Say plugin todos to see IDs.', 'error': 'not_found'}
                if action == 'done':
                    item['done'] = True
                else:
                    data['items'].remove(item)
            elif action == 'clear_done':
                data['items'] = [row for row in data['items'] if not row['done']]
            else:
                return {'ok': False, 'text': 'Unknown todo action.', 'error': 'invalid_action'}
            settings_store.save(self.path, data)
            self.api.publish('todo.changed', {'action': action, 'items': data['items']})
            return {'ok': True, 'text': 'Todo saved.', 'error': None, 'data': data}

    def command(self, match):
        groups = match.groupdict()
        if groups.get('action'):
            return self.change(groups['action'].lower(), groups.get('value', ''))
        if groups.get('clear'):
            return self.change('clear_done')
        data = self.snapshot()
        text = '\n'.join(f"{row['id']}. [{'x' if row['done'] else ' '}] {row['text']}" for row in data['items'])
        return {'ok': True, 'text': text or 'No plugin todos. Say todo add <text>.', 'error': None, 'data': data}

    def widget(self):
        rows = [row for row in self.snapshot()['items'] if not row['done']]
        return {'title': 'Plugin Todos', 'text': f'{len(rows)} open plugin todos',
                'items': [{'id': f"plugin-{row['id']}", 'label': row['text'], 'detail': 'Plugin todo',
                           'action': {'label': 'Done', 'action': 'complete', 'item': f"plugin-{row['id']}"}}
                          for row in rows[:6]],
                'input': {'label': 'New plugin todo', 'placeholder': 'Something to do…', 'action': 'add', 'max_length': 160}}


def register(api):
    todos = Todos(api)
    api.on_command([r'todo (?P<action>add) (?P<value>.+)', r'todo (?P<action>done|remove) (?P<value>\d+)',
                    r'todo (?P<clear>clear done)', r'(?:plugin todos|todos|todo(?: list| show)?)'],
                   todos.command, help='Add, list, finish, remove or clear completed plugin todos.',
                   examples=['todo add Buy milk', 'plugin todos', 'todo done 1', 'todo remove 1', 'todo clear done', 'todo list'])
    api.provide('todo', todos)
    api.add_route('GET', 'items', lambda request: todos.snapshot())
    api.on_action('add', lambda payload: todos.change('add', payload.get('text', '')))
    api.on_action('done', lambda payload: todos.change('done', payload.get('id', '')))
