"""Keep existing workspace tasks visible alongside the drop-in JSON todo plugin."""
from __future__ import annotations

import asyncio

from .productivity import TrackerPlugin
from services.plugin_runtime import current_manager


class TodoPlugin(TrackerPlugin):
    def __init__(self, store=None):
        super().__init__('todo', store)

    def service(self):
        manager = current_manager()
        return manager.get_service('todo') if manager else None

    def widget(self, limit: int = 6):
        legacy = super().widget(limit)
        todos = self.service()
        if todos is None:
            return legacy
        plugin = todos.widget()
        plugin['text'] += ' · ' + legacy['text']
        plugin['items'] = (plugin['items'] + legacy['items'])[:limit]
        return plugin

    async def action(self, action, item='', value='', revision=None):
        todos = self.service()
        if todos and (action == 'add' or item.startswith('plugin-')):
            try:
                return await asyncio.to_thread(todos.change, 'add' if action == 'add' else 'done',
                                               value if action == 'add' else item.removeprefix('plugin-'))
            except Exception:
                todos.api.log.exception('Island todo action failed [plugin=todo]')
                todos.api.manager.failed('todo')
                return {'ok': False, 'text': 'Plugin todo could not be saved. Check list plugins.', 'error': 'plugin_error'}
        if item.startswith('plugin-'):
            return {'ok': False, 'text': 'Todo plugin is disabled. Enable it and refresh.', 'error': 'unavailable'}
        return await super().action(action, item, value, revision)

    async def command(self, text):
        manager = current_manager()
        if manager:
            # Bare tracker commands are Island built-ins; new plugin verbs follow them.
            if text.strip().casefold() not in {'todo', 'todo list', 'todo progress'}:
                value = await asyncio.to_thread(manager.command, text)
                if value is not None:
                    return value
        return await super().command(text)
