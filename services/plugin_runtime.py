"""FRIDAY adapters for the plugin host; importing this module has no side effects."""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from contextvars import ContextVar

from services.automation.command_words import normalize_command
from services.automation.results import ActionResult
from services.plugin_manager import PluginManager

logger = logging.getLogger(__name__)
_manager: PluginManager | None = None
_lock = threading.RLock()
plugin_result = ContextVar('friday_plugin_result', default=None)


def is_smart_clipboard_command(message: str) -> bool:
    """The installed plugin owns these exact phrases, including older built-ins."""
    text = normalize_command(message)
    return bool(_manager and _manager.get_service('smart_clipboard') is not None
                and re.fullmatch(r"clipboard (?:on|off)|what(?:'|’)?s on my clipboard|(?:solve|convert) clipboard|clean clipboard link",
                                 text, re.I))


def builtin_matches(message: str) -> bool:
    """Parse only. Never execute a built-in to test whether it owns a command."""
    from services.scene_runtime import owns
    if owns(message):
        return False
    from services.automation import intent
    from services.productivity import commands as tracker_commands
    from services.mind import cognition_commands, execution_commands, reasoning_commands
    from services.computation import commands as computation_commands
    text = normalize_command(message)
    # This opt-in local search replaces the legacy file/cloud-context matcher.
    manager = current_manager()
    search = manager.get_service('semantic_search') if manager else None
    if search is not None and search.match_command(message):
        return False
    if is_smart_clipboard_command(text):
        return False
    if text.casefold() in {'list plugins', 'reload plugins', 'show recent events', 'settings'}:
        return True
    if re.fullmatch(r'(?:enable|disable) plugin [a-z][a-z0-9_-]{0,63}', text, re.I):
        return True
    return bool(intent.clock_answer(text) or intent._match_local_step(text)
                or tracker_commands.match_command(text) or cognition_commands.match_command(text)
                or execution_commands.match_command(text) or reasoning_commands.match_command(text)
                or computation_commands.match_command(text))


def current_manager() -> PluginManager | None:
    return _manager


def start(loop=None) -> PluginManager:
    global _manager
    with _lock:
        if _manager is None:
            def notify(title, body, urgency='normal'):
                from services.reminders.service import show_toast
                show_toast(title, body, mirror_telegram=False, urgency=urgency)

            def speak(text):
                if loop and not loop.is_closed():
                    async def say():
                        try:
                            from services.voice.tts import tts
                            await tts.speak(text, local_only=True)
                        except Exception:
                            logger.exception('Plugin offline speech unavailable')
                    asyncio.run_coroutine_threadsafe(say(), loop)

            _manager = PluginManager(builtin_matcher=builtin_matches, notify=notify, speak=speak)
            _manager.start()
        return _manager


def stop():
    global _manager
    with _lock:
        manager, _manager = _manager, None
    if manager:
        manager.close()


async def try_command(text: str) -> ActionResult | None:
    manager = current_manager()
    if manager:
        value = await asyncio.to_thread(manager.command, text)
        if value is not None:
            action = ActionResult(value['ok'], value['text'], repeatable=False, speech=value.get('speech'))
            plugin_result.set(action)
            return action
    return None


async def try_private_search(text: str, *, remote: bool = False) -> ActionResult | None:
    """Dispatch before legacy file/AI context; snippets never enter history or logs."""
    manager = current_manager()
    search = manager.get_service('semantic_search') if manager else None
    match = search.match_command(text) if search is not None else None
    if match is None:
        return None
    if remote:
        return ActionResult(False, 'Search your private documents at the laptop only.', repeatable=False, speech='')
    value = await asyncio.to_thread(manager.invoke, search.api, search.command, match, command=True)
    action = ActionResult(value['ok'], value['text'], memory_message='Local search handled privately.',
                          repeatable=False, speech='')
    plugin_result.set(action)
    return action


def note_builtin(text: str):
    if manager := current_manager():
        manager.note_builtin(normalize_command(text))
