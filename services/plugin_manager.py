"""Discover and hot-reload trusted offline plugins without changing FRIDAY's built-ins."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import importlib
import importlib.metadata
import logging
import json
from pathlib import Path
import re
import threading
import time
from types import ModuleType
from uuid import uuid4

from services.event_bus import event_bus
from services.plugin_api import PluginAPI
from services.plugin_manifest import Manifest, read_manifest
from services import plugin_imports
from services.plugin_storage import Settings, user_data_dir

logger = logging.getLogger(__name__)


@dataclass
class PluginState:
    manifest: Manifest
    folder: Path
    fingerprint: str = ''
    enabled: bool = False
    api: PluginAPI | None = None
    module: ModuleType | None = None
    error: str = ''
    warnings: set[str] = field(default_factory=set)
    failures: deque = field(default_factory=deque)


def result(ok: bool, text: str, error: str | None = None, **extra) -> dict:
    return dict(ok=ok, text=text, error=error, **extra)


class PluginManager:
    def __init__(self, plugins_dir: Path | None = None, data_root: Path | None = None,
                 *, bus=None, builtin_matcher=None, notify=None, speak=None, poll_seconds: float = 2):
        self.plugins_dir = (plugins_dir or Path(__file__).resolve().parents[1] / 'plugins').resolve()
        self.data_root = (data_root or user_data_dir()).resolve()
        self.bus = bus or event_bus
        self.builtin_matcher = builtin_matcher or (lambda text: False)
        self.notify = notify or (lambda title, body, urgency='normal': None)
        self.speak = speak or (lambda text: None)
        self.poll_seconds = poll_seconds
        self.states: dict[str, PluginState] = {}
        self.services: dict[str, tuple[str, object]] = {}
        self.settings = Settings(self.data_root / 'plugin-state.json')
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    @staticmethod
    def fingerprint(folder: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo', '.tmp', '.swp'}:
                continue
            if not path.resolve().is_relative_to(folder.resolve()):
                raise ValueError('Plugin files must remain inside the plugin folder')
            digest.update(path.relative_to(folder).as_posix().encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def discover(self) -> dict[str, tuple[Manifest, Path]]:
        found = {}
        for path in sorted(self.plugins_dir.glob('*/plugin.json')):
            if path.parent.name.startswith('_'):
                continue
            try:
                if not path.resolve().is_relative_to(self.plugins_dir):
                    raise ValueError('Manifest must be inside the plugins directory')
                manifest = read_manifest(path)
                if manifest.id in found:
                    raise ValueError(f'Duplicate plugin ID {manifest.id}')
                found[manifest.id] = (manifest, path.parent.resolve())
            except Exception as error:
                logger.error('Skipping bad plugin manifest %s: %s', path.parent.name, error)
        return found

    def scan(self, *, force: bool = False):
        with self.lock:
            found = self.discover()
            for plugin_id in set(self.states) - set(found):
                self._unload(self.states.pop(plugin_id))
            for plugin_id, (manifest, folder) in found.items():
                state = self.states.get(plugin_id)
                if state is None:
                    state = self.states[plugin_id] = PluginState(manifest, folder)
                    state.enabled = self.settings.get(plugin_id, manifest.enabled_by_default)
                try:
                    fingerprint = self.fingerprint(folder)
                    changed = fingerprint != state.fingerprint or folder != state.folder
                    if changed or force:
                        self._unload(state)
                        state.manifest, state.folder = manifest, folder
                        state.fingerprint = fingerprint
                        state.warnings.clear()
                    if state.enabled and (state.api is None or changed or force):
                        self._load(state)
                except Exception as error:
                    self._load_error(state, error)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.scan()
        def watch():
            while not self.stopped.wait(self.poll_seconds):
                try:
                    self.scan()
                except Exception:
                    logger.exception('Plugin discovery scan failed')
        self.thread = threading.Thread(target=watch, name='plugin-discovery', daemon=True)
        self.thread.start()

    def _load(self, state: PluginState):
        plugin_id = state.manifest.id
        try:
            for package in state.manifest.requires:
                try:
                    importlib.metadata.distribution(package)
                except importlib.metadata.PackageNotFoundError:
                    raise ValueError(f'Missing offline dependency: {package}; install it separately before enabling') from None
            importlib.invalidate_caches()
            name = f'_friday_plugin_{plugin_id.replace("-", "_")}_{uuid4().hex}'
            entry = state.folder / state.manifest.entry
            module, loader = plugin_imports.load(name, entry, state.folder)
            state.module = module
            loader.exec_module(module)
            if not callable(getattr(module, 'register', None)):
                raise ValueError('Entry must define register(api)')
            state.api = PluginAPI(self, plugin_id, self.data_root / 'plugins' / plugin_id)
            module.register(state.api)
            self._check_collisions(state)
            state.error = ''
            logger.info('Loaded plugin %s %s', plugin_id, state.manifest.version)
        except Exception as error:
            self._load_error(state, error)

    def _load_error(self, state, error):
        state.error = f'{type(error).__name__}: {error}'
        logger.exception('Plugin load failed [plugin=%s]: %s', state.manifest.id, state.error)
        self._unload(state)
        self.failed(state.manifest.id)

    def _unload(self, state: PluginState):
        api, module = state.api, state.module
        state.api, state.module = None, None
        if api:
            api.stop()
        self.services = {name: value for name, value in self.services.items() if value[0] != state.manifest.id}
        if module:
            try:
                unload = getattr(module, 'unload', None)
                if callable(unload):
                    unload()
            except Exception:
                logger.exception('Plugin unload failed [plugin=%s]', state.manifest.id)
            plugin_imports.forget(module.__name__)

    def failed(self, plugin_id: str):
        with self.lock:
            state = self.states.get(plugin_id)
            if state is None or not state.enabled:
                return
            now = time.monotonic()
            state.failures.append(now)
            while state.failures and state.failures[0] < now - 60:
                state.failures.popleft()
            if len(state.failures) < 5:
                return
            state.enabled = False
            self.settings.set(plugin_id, False)
            state.error = 'Auto-disabled after 5 failures within 60 seconds.'
            if state.api:
                state.api.stop_event.set()
            self.bus.publish('plugin.disabled', dict(plugin_id=plugin_id, reason=state.error, failures=5))
            # Lifecycle cleanup must not make a failed handler wait for its own worker.
            def disable():
                with self.lock:
                    if not state.enabled:
                        self._unload(state)
                try:
                    self.notify('FRIDAY plugin disabled', f'{state.manifest.name}: {state.error}', 'normal')
                except Exception:
                    logger.exception('Plugin disable notification failed [plugin=%s]', plugin_id)
            threading.Thread(target=disable, name=f'disable:{plugin_id}', daemon=True).start()

    def _check_collisions(self, state):
        samples = ['what time is it', 'volume up', 'open calculator', 'settings', 'todo list',
                   'list plugins', 'reload plugins', 'show recent events']
        for command in state.api.commands:
            candidates = samples + command.examples + [p.pattern for p in command.patterns]
            for text in candidates:
                if any(p.fullmatch(text) for p in command.patterns) and self.builtin_matcher(text):
                    self._collision(state, text)

    def _collision(self, state, text):
        warning = f'Built-in wins for command: {text}'
        if warning not in state.warnings:
            state.warnings.add(warning)
            logger.warning('%s [plugin=%s]', warning, state.manifest.id)

    def note_builtin(self, text: str):
        with self.lock:
            for state in self.states.values():
                if state.api and any(p.fullmatch(text) for c in state.api.commands for p in c.patterns):
                    self._collision(state, text)

    @staticmethod
    def _validate_result(value):
        if not isinstance(value, dict) or type(value.get('ok')) is not bool or not isinstance(value.get('text'), str):
            raise ValueError('Handler must return {ok: bool, text: str, error: str | None}')
        if value.get('error') is not None and not isinstance(value['error'], str):
            raise ValueError('Result error must be text or None')
        if 'data' in value and not isinstance(value['data'], dict):
            raise ValueError('Result data must be a dictionary')
        if 'speech' in value and not isinstance(value['speech'], str):
            raise ValueError('Result speech must be text')
        return {'error': None, **value}

    def invoke(self, api, handler, *args, command: bool = False):
        try:
            value = api._call(handler, *args)
            try:
                if command:
                    value = self._validate_result(value)
                json.dumps(value, allow_nan=False)
            except Exception:
                logger.exception('Invalid plugin result [plugin=%s]', api.plugin_id)
                self.failed(api.plugin_id)
                raise
            return value
        except Exception:
            return result(False, f'{api.plugin_id} could not complete that request. Check list plugins.', 'plugin_error')

    def command(self, text: str, *, check_builtin: bool = True) -> dict | None:
        from services.automation.command_words import normalize_command
        text = normalize_command(text) or text.strip().rstrip('.!?').strip()
        if managed := self.management_command(text):
            return managed
        if check_builtin and self.builtin_matcher(text):
            self.note_builtin(text)
            return None
        with self.lock:
            matches = [(state.api, command.handler, match) for state in self.states.values() if state.api and state.enabled
                       for command in state.api.commands for pattern in command.patterns if (match := pattern.fullmatch(text))]
        if matches:
            api, handler, match = matches[0]
            return self.invoke(api, handler, match, command=True)
        return None

    def management_command(self, text: str):
        key = text.casefold()
        if key == 'list plugins':
            rows = self.list_plugins()
            lines = [f"{r['id']} ({r['version']}): {r['status']}; permissions: {', '.join(r['permissions']) or 'none'}"
                     + (f"; {r['error']}" if r['error'] else '') + ''.join(f'; WARNING: {w}' for w in r['warnings']) for r in rows]
            return result(True, '\n'.join(lines) or 'No plugins discovered.', data={'plugins': rows})
        if key == 'show recent events':
            rows = self.bus.recent()
            return result(True, '\n'.join(f"{e['id']} {e['topic']} {e['payload']}" for e in rows) or 'No recent events.', data={'events': rows})
        if key == 'reload plugins':
            self.scan(force=True)
            return result(True, 'Plugins reloaded. Use list plugins to check their status.')
        if match := re.fullmatch(r'(enable|disable) plugin ([a-z][a-z0-9_-]{0,63})', text, re.I):
            return self.set_enabled(match[2].lower(), match[1].lower() == 'enable')
        return None

    def set_enabled(self, plugin_id: str, enabled: bool):
        with self.lock:
            state = self.states.get(plugin_id)
            if not state:
                return result(False, f'Unknown plugin: {plugin_id}', 'not_found')
            self._unload(state)
            self.settings.set(plugin_id, enabled)
            state.enabled, state.error = enabled, ''
            state.failures.clear()
            if enabled:
                self._load(state)
            return result(not bool(state.error), state.error or f'Plugin {plugin_id} {"enabled" if enabled else "disabled"}.',
                          'load_failed' if state.error else None)

    def list_plugins(self):
        with self.lock:
            return [dict(**state.manifest.model_dump(), enabled=state.enabled,
                         status='loaded' if state.api and state.enabled else 'failed' if state.enabled else 'disabled',
                         error=state.error, warnings=sorted(state.warnings),
                         commands=[dict(patterns=[p.pattern for p in c.patterns], help=c.help, examples=c.examples)
                                   for c in state.api.commands] if state.api else []) for state in self.states.values()]

    def provide(self, plugin_id, name, obj, *, owner=None):
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', name):
            raise ValueError('Invalid service name')
        with self.lock:
            state = self.states.get(plugin_id)
            if owner is not None and (not state or state.api is not owner or owner.stop_event.is_set()):
                raise RuntimeError('Plugin generation was unloaded')
            if name in self.services and self.services[name][0] != plugin_id:
                raise ValueError(f'Service already provided: {name}')
            self.services[name] = plugin_id, obj

    def get_service(self, name):
        with self.lock:
            owner = self.services.get(name)
            state = self.states.get(owner[0]) if owner else None
            return owner[1] if state and state.enabled and state.api and not state.api.stop_event.is_set() else None

    def route(self, plugin_id, path, request):
        with self.lock:
            state = self.states.get(plugin_id)
            api = state.api if state and state.enabled else None
            handler = api.routes.get(path) if api else None
        return self.invoke(api, handler, request) if handler else None

    def action(self, plugin_id, action_id, payload):
        with self.lock:
            state = self.states.get(plugin_id)
            api = state.api if state and state.enabled else None
            handler = api.actions.get(action_id) if api else None
        return self.invoke(api, handler, payload, command=True) if handler else result(False, 'This plugin action is no longer available.', 'not_found')

    def close(self):
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(3)
        with self.lock:
            for state in self.states.values():
                self._unload(state)
