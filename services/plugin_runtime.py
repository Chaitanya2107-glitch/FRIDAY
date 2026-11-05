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
_moods = None
_lock = threading.RLock()
plugin_result = ContextVar('friday_plugin_result', default=None)


def builtin_matches(message: str) -> bool:
    """Parse only. Never execute a built-in to test whether it owns a command."""
    from services.automation import intent
    from services.productivity import commands as tracker_commands
    from services.mind import cognition_commands, execution_commands, reasoning_commands
    from services.computation import commands as computation_commands
    text = normalize_command(message)
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
    global _manager, _moods
    with _lock:
        if _manager is None:
            def notify(title, body, urgency='normal'):
                from services.reminders.service import show_toast
                show_toast(title, body, mirror_telegram=False)

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
            from services.plugin_mood import MoodController
            _moods = MoodController(_manager.bus)
            _manager.start()
        return _manager


def stop():
    global _manager, _moods
    with _lock:
        manager, _manager = _manager, None
        moods, _moods = _moods, None
    if moods:
        moods.close()
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


def note_builtin(text: str):
    if manager := current_manager():
        manager.note_builtin(normalize_command(text))
