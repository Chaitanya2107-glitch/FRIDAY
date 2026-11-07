"""Early local briefing routing, before legacy weather briefing and media skip."""
import asyncio
from pathlib import Path
import re

from services.automation.command_words import normalize_command
from services.automation.results import ActionResult

ALIASES = r"brief me|morning brief|night brief|(?:give me |what's |what is |read me )?(?:my |the |a |today's )?(?:morning |daily )?briefing"


def installed(name='briefings'):
    folder = Path(__file__).resolve().parents[1] / 'plugins' / name
    return (folder / 'main.py').is_file() and (folder / 'plugin.json').is_file()


def schedule_alerts_installed():
    return installed('schedule_alerts')


def service():
    from services.plugin_runtime import current_manager
    manager = current_manager()
    return manager, manager.get_service('briefings') if manager else None


def owns(text):
    _, briefings = service()
    text = normalize_command(text)
    return bool(briefings and briefings.matches(text) or installed() and re.fullmatch(ALIASES, text, re.I))


async def try_command(text, *, remote=False):
    manager, briefings = service()
    text = normalize_command(text)
    if not owns(text):
        return None
    if remote:
        value = dict(ok=False, text='Briefings are available only on this computer.')
    elif briefings is None:
        value = dict(ok=False, text='The local briefings plugin is unavailable. Check list plugins.')
    else:
        value = await asyncio.to_thread(manager.invoke, briefings.api, briefings.handle_command, text, command=True)
    return ActionResult(value['ok'], value['text'], memory_message='Local briefing request handled privately.',
                        repeatable=False, speech='')
