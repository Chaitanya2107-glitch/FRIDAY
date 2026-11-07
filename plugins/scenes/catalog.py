"""Editable scene files, validated completely before any action can run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from services import settings_store


def key(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9 _-]{0,47}', name.strip()):
        raise ValueError('Use a scene name with letters, numbers, spaces, _ or - (48 characters maximum).')
    return re.sub(r'[ _-]+', '_', name.strip().lower())


def phrase(text: str) -> str:
    from services.automation.command_words import normalize_command
    return ' '.join((normalize_command(text) or text.strip()).casefold().split())


class Catalog:
    def __init__(self, api, registry, defaults: Path):
        self.api, self.registry = api, registry
        self.folder = api.data_dir / 'scenes'
        self.folder.mkdir(parents=True, exist_ok=True)
        # Copy once, so removing a default is respected on later starts.
        marker = self.folder / '.defaults-installed'
        if not marker.exists():
            for path in defaults.glob('*.json'):
                target = self.folder / path.name
                if not target.exists():
                    settings_store.save(target, json.loads(path.read_text(encoding='utf-8')))
            settings_store.publish(marker, b'1')
        self.scenes, self.errors = {}, {}
        self.reload()

    def validate(self, value):
        if not isinstance(value, dict):
            raise ValueError('A scene must be a JSON object.')
        allowed = {'name', 'aliases', 'description', 'actions', 'restore', 'confirm_first_run',
                   'triggers', 'distractions', 'close_without_asking', 'duration_minutes'}
        if unknown := set(value) - allowed:
            raise ValueError('Unknown scene fields: ' + ', '.join(sorted(unknown)))
        scene = {'aliases': [], 'description': '', 'restore': True, 'confirm_first_run': True,
                 'close_without_asking': False, 'triggers': [], 'distractions': [], **value}
        slug = key(scene.get('name'))
        if not isinstance(scene.get('actions'), list) or len(scene['actions']) > 64:
            raise ValueError('actions must be a list of at most 64 actions.')
        for field in ['restore', 'confirm_first_run', 'close_without_asking']:
            if type(scene[field]) is not bool:
                raise ValueError(field + ' must be true or false.')
        if not isinstance(scene['description'], str) or len(scene['description']) > 1000:
            raise ValueError('description must be text, at most 1000 characters.')
        for field in ['aliases', 'distractions']:
            if (not isinstance(scene[field], list) or len(scene[field]) > 32
                    or any(not isinstance(s, str) or not s.strip() or len(s) > 160 for s in scene[field])):
                raise ValueError(field + ' must contain up to 32 nonempty names.')
        if any(phrase(alias) in {'yes', 'no', 'cancel', 'end scene'} for alias in scene['aliases']):
            raise ValueError('A scene alias cannot replace a confirmation or end scene.')
        if 'duration_minutes' in scene:
            n = scene['duration_minutes']
            if type(n) not in {int, float} or not 0 < n <= 10080:
                raise ValueError('duration_minutes must be positive, at most seven days.')
        from .triggers import validate_triggers
        validate_triggers(scene['triggers'])
        for action in self.actions(scene):
            self.registry.validate(action)
        if len(self.preview(scene)) > 4000:
            raise ValueError('Scene preview exceeds the island card limit; split this scene into smaller routines.')
        scene['key'] = slug
        return scene

    @staticmethod
    def actions(scene):
        return [dict(type='close_app', name=name) for name in scene['distractions']] + scene['actions']

    def preview(self, scene):
        lines = [scene['name'].title() + ' mode: ' + scene['description']]
        lines.extend(f'{i}. {self.registry.describe(action)}' for i, action in enumerate(self.actions(scene), 1))
        if 'duration_minutes' in scene:
            lines.append(f'End automatically after {scene["duration_minutes"]} minutes.')
        lines.append('Restore reversible settings on exit.' if scene['restore'] else 'Keep changed settings on exit; release scene-only quiet/nudge policy.')
        return '\n'.join(lines)

    def reload(self):
        scenes, errors, aliases = {}, {}, {}
        for path in sorted(self.folder.glob('*.json')):
            value = None
            try:
                if path.is_symlink() or path.resolve().parent != self.folder.resolve():
                    raise ValueError('Scene files must stay inside the scenes directory.')
                if path.stat().st_size > 65536:
                    raise ValueError('Scene file exceeds 64 KB.')
                raw = path.read_bytes()
                value = json.loads(raw.decode('utf-8-sig'))
                scene = self.validate(value)
                if scene['key'] in scenes:
                    raise ValueError('Duplicate scene name: ' + scene['name'])
                for alias in scene['aliases']:
                    if phrase(alias) in aliases:
                        raise ValueError('Duplicate spoken alias: ' + alias)
                scene.update(hash=hashlib.sha256(raw).hexdigest(), path=path)
                scenes[scene['key']] = scene
                aliases.update({phrase(alias): scene['key'] for alias in scene['aliases']})
            except (ValueError, TypeError, OSError) as error:
                errors[path.stem] = str(error)
                if isinstance(value, dict):
                    try:
                        slug = key(value.get('name'))
                        errors[slug] = str(error)
                        for alias in value.get('aliases', []):
                            if isinstance(alias, str) and len(alias) <= 160:
                                aliases.setdefault(phrase(alias), slug)
                    except (ValueError, TypeError):
                        pass
        self.scenes, self.errors, self.aliases = scenes, errors, aliases

    def get(self, name):
        self.reload()
        slug = self.aliases.get(phrase(name)) or key(name)
        if slug not in self.scenes:
            raise ValueError(self.errors.get(slug, f'Scene "{name}" is not available. Say list scenes.'))
        return self.scenes[slug]

    def distractions(self, name, app, add):
        scene = self.get(name)
        self.registry.validate(dict(type='close_app', name=app))
        value = {k: v for k, v in scene.items() if k not in {'key', 'hash', 'path'}}
        value['distractions'] = [s for s in value['distractions'] if phrase(s) != phrase(app)]
        if add:
            value['distractions'].append(app.strip())
        self.validate(value)
        settings_store.save(scene['path'], value)
        self.reload()

    def create(self, name):
        slug = key(name)
        path = self.folder / (slug + '.json')
        if path.exists() or slug in self.scenes:
            raise ValueError('That scene already exists.')
        source = self.get('study')
        value = {k: v for k, v in source.items() if k not in {'key', 'hash', 'path'}}
        value.update(name=name.strip().lower(), aliases=[name.strip().lower() + ' mode'], distractions=[])
        self.validate(value)
        settings_store.save(path, value)
        self.reload()
        return path
