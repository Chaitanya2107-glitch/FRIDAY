"""Trusted action providers; unknown/forbidden JSON actions fail before execution."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import re
import threading
from typing import Callable


class Skipped(RuntimeError):
    """An optional local capability is unavailable; other actions can continue."""


FORBIDDEN = {'shell', 'exec', 'execute', 'command_line', 'powershell', 'cmd', 'shutdown',
             'restart', 'reboot', 'sleep', 'hibernate', 'sign_out', 'signout', 'logoff',
             'delete', 'delete_file', 'remove_file', 'file_delete', 'run_shell', 'lock'}


@dataclass
class Action:
    do: Callable
    undo: Callable
    preview: Callable
    validate: Callable
    prepare: Callable | None = None
    cleanup: bool = False


class Registry:
    def __init__(self, api):
        self.api, self.providers = api, {}
        self.lock = threading.RLock()
        self.context = threading.local()
        self.commands = {}

    @property
    def owner(self):
        return getattr(self.context, 'owner', '')

    @contextmanager
    def owned(self, owner):
        previous = self.owner
        self.context.owner = owner
        try:
            yield
        finally:
            self.context.owner = previous

    def register(self, name, provider):
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name)
                or name in FORBIDDEN or any(p in FORBIDDEN for p in name.split('_'))):
            raise ValueError('Forbidden scene action type: ' + str(name))
        if not callable(getattr(provider, 'do', None)) or not callable(getattr(provider, 'undo', None)):
            raise ValueError('An action provider must define do(params) and undo(token).')
        with self.lock:
            if name in self.providers:
                raise ValueError('Action type already registered: ' + name)
            self.providers[name] = provider

    def get(self, name):
        if not isinstance(name, str) or name in FORBIDDEN:
            raise ValueError('Forbidden scene action type: ' + str(name))
        with self.lock:
            if name not in self.providers:
                raise ValueError('Unknown scene action type: ' + name)
            return self.providers[name]

    def unregister(self, name, provider):
        """Extension unload removes only its own object, never a newer generation."""
        with self.lock:
            if self.providers.get(name) is provider:
                del self.providers[name]

    def allow_command(self, plugin_id, patterns):
        """Trusted plugins explicitly opt finite command patterns into scenes."""
        if not isinstance(plugin_id, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', plugin_id) or plugin_id == 'scenes':
            raise ValueError('Use a plugin ID other than scenes (recursive scenes are forbidden).')
        if isinstance(patterns, str):
            patterns = [patterns]
        with self.lock:
            self.commands.setdefault(plugin_id, []).extend(re.compile(p, re.I) for p in patterns)

    def validate(self, action):
        if not isinstance(action, dict) or not isinstance(action.get('type'), str):
            raise ValueError('Each action needs a type and named parameters.')
        json.dumps(action, allow_nan=False)
        provider = self.get(action['type'])
        params = {k: v for k, v in action.items() if k != 'type'}
        if validate := getattr(provider, 'validate', None):
            validate(params)
        return provider, params

    def describe(self, action):
        provider, params = self.validate(action)
        preview = getattr(provider, 'preview', None)
        return str(preview(params)) if preview else action['type'].replace('_', ' ') + ': ' + json.dumps(params)
