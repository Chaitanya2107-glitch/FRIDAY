"""Whole-string spoken scene controls; no arbitrary command execution."""
import re

from services.automation.command_words import normalize_command

from .catalog import key, phrase
from .engine import result

PATTERNS = {
    'end': r'end scene|exit (?P<name>.+?) mode',
    'list': r'list scenes',
    'preview': r'preview (?P<name>.+?)(?: mode| scene)?',
    'status': r'what scene is active',
    'add': r'add (?P<app>.+?) to (?P<name>.+?) distractions',
    'remove': r'remove (?P<app>.+?) from (?P<name>.+?) distractions',
    'create': r'create scene (?P<name>.+)',
    'start': r'(?:start )?(?P<name>.+?) mode|start (?P<scene>.+?) scene',
}


class Commands:
    def __init__(self, engine):
        self.engine = engine
        self.patterns = {name: re.compile(value, re.I) for name, value in PATTERNS.items()}

    def parse(self, text):
        text = normalize_command(text)
        if text.lower() in {'yes', 'yes please', 'no', 'no thanks', 'cancel'} and self.engine.awaiting():
            return 'answer', text.lower()
        self.engine.catalog.reload()
        if phrase(text) in self.engine.catalog.aliases:
            return 'alias', text
        for name, pattern in self.patterns.items():
            if match := pattern.fullmatch(text):
                if name == 'start' and not match.groupdict().get('scene'):
                    slug = key(match['name'])
                    if slug not in self.engine.catalog.scenes and slug not in self.engine.catalog.errors:
                        continue
                return name, match
        return None, None

    def matches(self, text):
        try:
            return self.parse(text)[0] is not None
        except (ValueError, OSError):
            return any(pattern.fullmatch(normalize_command(text)) for pattern in self.patterns.values())

    def handle(self, text):
        with self.engine.lock:
            self.engine.ensure_active()
            try:
                kind, match = self.parse(text)
                engine = self.engine
                if kind == 'answer':
                    return engine.answer('yes' if match.startswith('yes') else 'no')
                if kind == 'alias':
                    return engine.request(match)
                if kind == 'start':
                    return engine.request(match.groupdict().get('name') or match['scene'])
                if kind == 'end':
                    name = match.groupdict().get('name')
                    if name and engine.active and key(name) != key(engine.active['name']):
                        return result('The active scene is ' + engine.active['name'] + '.', ok=False, error='different_scene')
                    return engine.end()
                if kind == 'status':
                    state = engine.status()
                    return result('Active scene: ' + str(state['active']) + '.' if state['active'] else 'No scene is active.', data=state)
                if kind == 'list':
                    engine.catalog.reload()
                    rows = [f'{s["name"]}: {s["description"]}' for s in engine.catalog.scenes.values()]
                    rows += [name + ': refused — ' + why for name, why in engine.catalog.errors.items()]
                    return result('\n'.join(rows) or 'No scenes are configured.')
                if kind == 'preview':
                    return result(engine.preview(engine.catalog.get(match['name'])))
                if kind in {'add', 'remove'}:
                    engine.catalog.distractions(match['name'], match['app'], kind == 'add')
                    return result('Distraction list updated. The changed scene will ask for confirmation.')
                if kind == 'create':
                    path = engine.catalog.create(match['name'])
                    engine.desktop.open_path(path)
                    return result('Created the scene from study and opened its JSON file in your default editor.')
                return result('That is not a scene command.', ok=False, error='unknown_command')
            except (ValueError, OSError) as error:
                return result(str(error), ok=False, error='invalid_scene')
