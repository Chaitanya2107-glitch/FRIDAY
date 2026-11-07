"""Early local handoff for loaded focus/scenes, ahead of legacy modes and AI."""
import asyncio
from contextvars import ContextVar
from pathlib import Path
import re

from services.automation.command_words import normalize_command
from services.automation.results import ActionResult

PRIVATE_MEMORY = 'Local focus/scene request handled privately.'
_private_turn = ContextVar('private_focus_scene_turn', default=False)


def begin_turn():
    _private_turn.set(False)


def private_turn():
    return _private_turn.get()


def installed(name):
    return (Path(__file__).resolve().parents[1] / 'plugins' / name / 'main.py').is_file()


def unavailable_owner(text, scenes, focus):
    text = normalize_command(text)
    if focus is None and installed('focus') and re.fullmatch(
            r'focus(?: \d+(?:\.\d+)?)?|start focus timer \d+(?:\.\d+)? minutes?|pomodoro|(?:pause|resume|stop) focus|how long is left|focus status|focus stats (?:today|this week)', text, re.I):
        return 'focus'
    if scenes is None and installed('scenes') and re.fullmatch(
            r'.+ mode|start .+ scene|end scene|list scenes|preview .+|what scene is active|(?:add|remove) .+ distractions|create scene .+', text, re.I):
        return 'scenes'
    return None


def services():
    from services.plugin_runtime import current_manager
    manager = current_manager()
    return manager, manager.get_service('scenes') if manager else None, manager.get_service('focus') if manager else None


def pending():
    _, scenes, _ = services()
    return bool(scenes and scenes.awaiting())


def owns(text):
    _, scenes, focus = services()
    return bool(focus and focus.matches(text) or scenes and scenes.matches(text) or unavailable_owner(text, scenes, focus))


async def try_command(text, *, remote=False):
    manager, scenes, focus = services()
    debug = normalize_command(text) == 'show recent events' and (scenes or focus)
    service = focus if focus and focus.matches(text) else scenes if scenes and scenes.matches(text) else None
    missing = unavailable_owner(text, scenes, focus)
    if service is None and missing:
        _private_turn.set(True)
        return ActionResult(False, f'The local {missing} plugin is unavailable. Check list plugins.',
                            memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
    if service is None and not debug:
        if not remote and scenes and scenes.awaiting():
            scenes.dismiss_pending()
        return None
    _private_turn.set(True)
    if remote:
        return ActionResult(False, 'Focus and scene controls are available only on this computer.',
                            memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
    if debug:
        value = await asyncio.to_thread(manager.management_command, 'show recent events')
    else:
        value = await asyncio.to_thread(manager.invoke, service.api, service.handle_command, text, command=True)
    return ActionResult(value['ok'], value['text'], memory_message=PRIVATE_MEMORY,
                        repeatable=False, speech='' if debug else value.get('speech', value['text']))
