"""Small private/local handoff to the optional activity plugin."""
import asyncio
from contextvars import ContextVar
from pathlib import Path
import re

from services.automation.results import ActionResult

PRIVATE_MEMORY = 'Local activity request handled privately.'
_private_turn = ContextVar('private_activity_turn', default=False)


def begin_turn():
    _private_turn.set(False)


def private_turn():
    return _private_turn.get()


def installed():
    # Fail closed during installation too, before the manifest becomes discoverable.
    return (Path(__file__).resolve().parents[1] / 'plugins/activity/main.py').is_file()


def privacy_active():
    # Failed/disabled tracking must never reactivate the legacy title collector.
    return installed() or current() is not None


def current():
    from services.plugin_runtime import current_manager
    manager = current_manager()
    return manager.get_service('activity') if manager else None


async def try_command(text: str, *, remote: bool = False):
    from services.plugin_runtime import current_manager
    from services.automation.command_words import normalize_command
    manager = current_manager()
    if normalize_command(text) == 'show recent events' and privacy_active():
        # Debug events include app labels too: keep them out of history/cloud TTS.
        _private_turn.set(True)
        if remote:
            return ActionResult(False, 'Activity data is available only on this computer.',
                                memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
        try:
            value = await asyncio.to_thread(manager.management_command, 'show recent events')
            return ActionResult(value['ok'], value['text'], memory_message=PRIVATE_MEMORY,
                                repeatable=False, speech='')
        except Exception:
            return ActionResult(False, 'Local event history is unavailable. Check list plugins.',
                                memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
    activity = current()
    if activity is None:
        if not installed():
            return None
        query = normalize_command(text)
        patterns = [r"what am i (?:doing|working on)(?: right now)?|show my current activity|what(?:'s| is) my current (?:app|activity)",
                    r"activity summary.*|what did i do (?:today|yesterday)|summari[sz]e my activity.*",
                    r"how (?:much time|long) .+ (?:today|yesterday|this week|last (?:7|seven) days)",
                    r"(?:pause|resume|stop|start) (?:activity )?tracking(?: my activity)?",
                    r"(?:confirm |cancel )?(?:delete|clear|deletion of|deleting) my activity data|categori[sz]e .+ as [a-z]+"]
        if not any(re.fullmatch(pattern, query, re.I) for pattern in patterns):
            return None
        _private_turn.set(True)
        return ActionResult(False, 'Local activity tracking is unavailable. Check list plugins.',
                            memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
    if not activity.handles(text):
        return None
    _private_turn.set(True)
    if remote:
        return ActionResult(False, 'Activity data is available only on this computer.',
                            memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
    value = await asyncio.to_thread(manager.invoke, activity.api, activity.handle_command, text, command=True)
    return ActionResult(value['ok'], value['text'], memory_message=PRIVATE_MEMORY,
                        repeatable=False, speech=value.get('speech', value['text']))


def suspend_legacy(log):
    """Drop the previous in-memory observation without flushing its raw title."""
    with log._lock:
        log.app = log.title = log.project = log.title_since = log.app_since = None
        log.last_foreground = log.last_app = None
        log.last_window = (None, None)
