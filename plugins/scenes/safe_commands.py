"""Finite local parsing; scene text never reaches an AI, routine or shell runner."""
import re

from services.automation.command_words import normalize_command

from .registry import Skipped

DENIED = re.compile(r'\b(?:shut\s*down|restart|reboot|hibernate|sleep|sign[ -]?out|log[ -]?off|lock|delete|erase|wipe|purge|'
                    r'format|powershell|pwsh|cmd|shell|wscript|cscript|mshta|rundll32|regsvr32|install|uninstall)\b|[;|&`\r\n]|\$\(', re.I)


class SceneCommands:
    def __init__(self, api, registry):
        self.api, self.registry = api, registry
        registry.allow_command('hello', r'hello friday')
        registry.allow_command('focus', r'focus(?: \d+)?|start focus timer \d+ minutes|pomodoro|(?:pause|resume|stop) focus|how long is left|focus stats (?:today|this week)')
        registry.allow_command('todo', r'todo (?:add .+|done \d+|remove \d+|clear done)|plugin todos|todos|todo(?: list| show)?')
        registry.allow_command('activity', r'what am i doing|activity summary(?: .+)?|what did i do today|how (?:much time|long) .+|(?:pause|resume) tracking|categori[sz]e .+ as [a-z]+')

    def plan(self, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 1000 or DENIED.search(value):
            raise ValueError('Scene commands cannot use shell syntax, file deletion, scripts, installers or PC power/session commands.')
        text = normalize_command(value)
        manager = self.api.manager
        # Plugin payloads containing "and" belong to their whole-string matcher.
        matches = []
        # Do not take the lifecycle lock while an action holds its own lock.
        # invoke() fences a captured API if it was unloaded after this snapshot.
        for state in tuple(manager.states.values()):
            plugin_api = state.api
            if (plugin_api and state.enabled and getattr(state, 'ready', True)
                    and not plugin_api.stop_event.is_set() and plugin_api.plugin_id != 'scenes'):
                for command in tuple(plugin_api.commands):
                    for pattern in tuple(command.patterns):
                        if match := pattern.fullmatch(text):
                            matches.append((plugin_api, command, match))
        if matches:
            plugin_api, command, match = matches[0]
            if not any(p.fullmatch(text) for p in self.registry.commands.get(plugin_api.plugin_id, [])):
                raise ValueError(f'{plugin_api.plugin_id} has not opted this command into scenes with scene_actions.allow_command().')
            return [('plugin', (plugin_api, command.handler, match))]
        from services.automation import intent
        from services.automation.command_words import split_steps
        parts = split_steps(text)
        if not parts or len(parts) > 16:
            raise ValueError('Use at most sixteen finite local commands.')
        result = []
        for part in parts:
            parsed = intent._match_local_step(part)
            action = self.native(parsed)
            self.registry.validate(action)
            result.append(('action', action))
        return result

    @staticmethod
    def native(parsed):
        if not isinstance(parsed, dict):
            raise ValueError('Unsupported scene command. Use a named action or an explicitly permitted plugin command.')
        kind = parsed.get('action')
        # These are mapped to reversible providers, not the general intent executor.
        if kind in {'open_app', 'close_app', 'minimize_app'}:
            return dict(type=kind, name=parsed.get('app_name') or parsed.get('app') or parsed.get('name', ''))
        if kind == 'set_volume':
            return dict(type='set_volume', percent=parsed.get('level', parsed.get('percent')))
        if kind == 'set_brightness':
            return dict(type='set_brightness', percent=parsed.get('level', parsed.get('percent')))
        if kind in {'mute', 'unmute'}:
            return dict(type='mute', on=kind == 'mute')
        if kind == 'set_mute' and type(parsed.get('mute')) is bool:
            return dict(type='mute', on=parsed['mute'])
        if kind == 'open_url':
            return dict(type='open_url', url=parsed.get('url'))
        if kind in {'open_folder', 'open_path'}:
            return dict(type='open_path', path=parsed.get('path'))
        raise ValueError('Unsupported scene command action: ' + str(kind) + '. Use a named scene action or an explicitly permitted plugin command.')

    def validate(self, params):
        if not isinstance(params, dict) or set(params) != {'text'}:
            raise ValueError('run_command requires only text.')
        self.plan(params['text'])

    def closes(self, params):
        return any(kind == 'action' and action['type'] == 'close_app' for kind, action in self.plan(params['text']))

    def preview(self, params):
        plan = self.plan(params['text'])
        return '; '.join(self.registry.describe(value) if kind == 'action'
                         else 'Run explicitly permitted plugin command: ' + params['text'] + ' (no automatic undo).'
                         for kind, value in plan)

    def prepare(self, params):
        tokens = []
        for kind, value in self.plan(params['text']):
            if kind == 'action':
                provider, p = self.registry.validate(value)
                method = getattr(provider, 'prepare', None)
                tokens.append(dict(type=value['type'], token=method(p) if method else None))
        return tokens

    def run(self, params):
        tokens = []
        try:
            for kind, value in self.plan(params['text']):
                if kind == 'plugin':
                    plugin_api, handler, match = value
                    result = self.api.manager.invoke(plugin_api, handler, match, command=True)
                    if not result['ok']:
                        raise Skipped(result['text'])
                else:
                    provider, p = self.registry.validate(value)
                    tokens.append(dict(type=value['type'], token=provider.do(p)))
        except Exception:
            self.undo(tokens)
            raise
        return tokens

    def undo(self, tokens):
        failures = []
        for value in reversed(tokens):
            if value['token'] is not None:
                try:
                    self.registry.get(value['type']).undo(value['token'])
                except Exception as error:
                    failures.append(value['type'] + ': ' + str(error))
        if failures:
            raise Skipped('; '.join(failures))
