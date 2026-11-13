"""Finite command registry; risk is mandatory and arbitrary routing is unavailable."""
from dataclasses import dataclass
from typing import Callable, Literal

from .security import Denied

Risk = Literal['safe', 'confirm', 'blocked']


@dataclass(frozen=True)
class Command:
    handler: Callable | None
    risk: Risk
    validate: Callable
    scope: str | None = None


class Registry:
    def __init__(self):
        self.commands: dict[str, Command] = {}

    def register(self, identity: str, handler: Callable | None, *, risk: Risk, validate: Callable, scope=None):
        if risk not in {'safe', 'confirm', 'blocked'} or (risk != 'blocked' and not callable(handler)):
            raise ValueError('Every command requires a valid risk level and handler.')
        if identity in self.commands:
            raise ValueError('Command already registered.')
        if scope not in {None, 'phone_data'}:
            raise ValueError('Unknown device scope.')
        self.commands[identity] = Command(handler, risk, validate, scope)

    def get(self, identity):
        if not isinstance(identity, str) or identity not in self.commands:
            raise Denied('unknown_command')
        return self.commands[identity]


def fields(args, required=(), optional=()):
    if not isinstance(args, dict) or set(args) - set(required) - set(optional) or set(required) - set(args):
        raise Denied('invalid_arguments')
    return dict(args)


def no_args(args):
    return fields(args)


def text_args(key, limit):
    def validate(args):
        fields(args, (key,))
        value = args[key]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or '\x00' in value:
            raise Denied('invalid_arguments')
        return {key: value.strip()}
    return validate


def focus_args(args):
    fields(args, optional=('minutes',))
    minutes = args.get('minutes', 25)
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise Denied('invalid_arguments')
    return dict(minutes=minutes)


def note_number(args):
    fields(args, ('number',))
    if type(args['number']) is not int or not 1 <= args['number'] <= 100000:
        raise Denied('invalid_arguments')
    return dict(args)


def build_registry():
    from . import handlers
    from . import panel
    registry = Registry()
    for identity, handler, validate in (
        ('status', panel.status, no_args), ('schedule', panel.schedule, no_args),
        ('events', panel.events, no_args), ('activity', panel.activity, no_args),
        ('device', panel.this_device, no_args), ('revoke_self', panel.revoke_self, no_args),
        ('ask', handlers.ask_friday, text_args('text', 4000)),
        ('today_schedule', handlers.today_schedule, no_args),
        ('next_class', handlers.next_class, no_args), ('start_focus', handlers.start_focus, focus_args),
        ('stop_focus', handlers.stop_focus, no_args), ('set_scene', handlers.set_scene, text_args('name', 48)),
        ('read_todos', handlers.read_todos, no_args), ('add_note', handlers.add_note, text_args('text', 4000)),
        ('ask_friday', handlers.ask_friday, text_args('text', 4000)),
    ):
        registry.register(identity, handler, risk='safe', validate=validate)
    for identity, handler, validate in (
        ('lock_pc', handlers.lock_pc, no_args), ('sleep_pc', handlers.sleep_pc, no_args),
        ('open_app', handlers.open_app, handlers.app_args), ('send_message', handlers.send_message, text_args('text', 4000)),
        ('delete_note', handlers.delete_note, note_number), ('clear_notes', handlers.clear_notes, no_args),
    ):
        registry.register(identity, handler, risk='confirm', validate=validate)
    for identity in ('shell', 'exec', 'read_file', 'write_file', 'install', 'change_settings', 'change_pairing', 'disable_kill_switch'):
        registry.register(identity, None, risk='blocked', validate=no_args)
    from services.phone_signals.remote import register
    register(registry)
    return registry
