"""Offline morning/night briefings. Services are looked up at use time."""
from services import briefing_context
from services.briefing_runtime import ALIASES

from .content import Builder
from .delivery import Briefings


def register(api):
    builder = Builder(api, battery=briefing_context.battery)
    briefings = Briefings(api, builder, desktop=briefing_context.desktop)
    api.provide('briefings', briefings)
    api.on_command(ALIASES, lambda match: briefings.handle_command(match.string),
                   help='A short local morning or night brief; skip or snooze the current brief.',
                   examples=['brief me', 'morning brief', 'night brief', 'skip', 'snooze 30'])
    api.on_command(r'(?!)', lambda match: briefings.handle_command(match.string), help='Reply to the current brief.')
    briefings.answer_command = api.commands[-1]
    briefings.sync_commands()
    for action in ('skip', 'snooze', 'sleep'):
        api.on_action(action, lambda payload, action=action: briefings.respond(action, payload))
    api.subscribe('*', briefings.event)
    api.every(30, briefings.tick)
