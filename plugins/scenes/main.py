"""Offline, previewed Windows routines with a durable reverse-undo journal."""
from pathlib import Path

from .actions import install
from .commands import Commands, PATTERNS
from .desktop import Desktop
from .engine import Scenes
from .registry import Registry

_scenes = None


def register(api, *, desktop=None, now=None):
    global _scenes
    registry = Registry(api)
    desktop = desktop or Desktop(api)
    install(registry, desktop)
    options = {'now': now} if now else {}
    scenes = Scenes(api, registry, desktop, Path(__file__).parent / 'defaults', **options)
    scenes.commands = Commands(scenes)
    _scenes = scenes
    api.provide('scenes', scenes)
    api.provide('scene_actions', registry)
    api.on_command(list(PATTERNS.values()),
                   lambda match: scenes.handle_command(match.string), help='Preview, start and restore local scenes.',
                   examples=['study mode', 'preview study mode', 'end scene', 'list scenes'])
    api.on_command(r'(?!)', lambda match: scenes.handle_command(match.string), help='Exact live scene aliases and pending answers.')
    scenes.alias_command = api.commands[-1]
    scenes.sync_commands()
    api.on_action('answer', scenes.answer_action)
    api.add_route('GET', 'status', lambda request: scenes.status())
    api.subscribe('*', scenes.event)
    api.every(5, scenes.tick)
    if scenes.needs_recovery:
        scenes.offer_recovery()
    scenes.publish_state()


def unload():
    if _scenes:
        _scenes.close()
