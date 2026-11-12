"""Narrow integrations; no free-text commands, arbitrary paths or plugin dispatch."""
from datetime import datetime
from pathlib import PureWindowsPath
from contextlib import nullcontext
import hashlib
import json
import os
import re

from .commands import text_args
from .security import Denied


def status(service, device, args):
    return service.status()


def today_schedule(service, device, args):
    from services.proactive import timetable
    return dict(text=timetable.today_line(datetime.now()))


def next_class(service, device, args):
    from services.proactive import timetable
    return dict(text=timetable.next_class(datetime.now()))


def read_todos(service, device, args):
    from services.productivity import commands
    value = commands.run({'action': 'tasks'}, remote=True)
    return dict(ok=value.success, text=value.message)


def add_note(service, device, args):
    from services.memory import notes
    notes_snapshot()
    return dict(text=notes.add(args['text']))


def delete_note(service, device, args):
    from services.memory import notes
    return dict(text=notes.delete(args['number']))


def clear_notes(service, device, args):
    from services.memory import notes
    return dict(text=notes.clear())


def plugin_service(name):
    from services.plugin_runtime import current_manager
    manager = current_manager()
    value = manager.get_service(name) if manager else None
    if value is None:
        raise Denied('feature_unavailable')
    return manager, value


def start_focus(service, device, args):
    manager, focus = plugin_service('focus')
    return manager.invoke(focus.api, lambda: focus.start(args['minutes'], label='Remote focus', owner='remote'))


def stop_focus(service, device, args):
    manager, focus = plugin_service('focus')
    return manager.invoke(focus.api, focus.stop)


def set_scene(service, device, args):
    manager, scenes = plugin_service('scenes')

    def activate():
        with scenes.lock:
            scenes.ensure_active()
            if scenes.needs_recovery or scenes.pending:
                raise Denied('scene_needs_local_review')
            scene = scenes.catalog.get(args['name'])
            if scenes.api.settings.get('approved_scenes', {}).get(scene['key']) != scene['hash']:
                raise Denied('scene_needs_local_review')
            # Safe remote scenes may only adjust transient notification/focus state.
            safe = {'quiet_mode', 'start_focus'}
            if any(action['type'] not in safe for action in scenes.catalog.actions(scene)):
                raise Denied('scene_risk')
            if scenes.active and any(entry['type'] not in safe for entry in scenes.active['entries']):
                raise Denied('scene_undo_risk')
            return scenes._start(scene)  # Use the validated snapshot; request() would load a second scene.
    def reviewed():
        try:
            return activate()
        except (Denied, ValueError, OSError):
            return dict(ok=False, text='This scene needs local review or contains an effect unavailable remotely.', error='remote_scene_refused')
    return manager.invoke(scenes.api, reviewed)


def lock_pc(service, device, args):
    import ctypes
    if not ctypes.windll.user32.LockWorkStation():
        raise Denied('lock_failed')
    return dict(text='Lock requested.')


def sleep_pc(service, device, args):
    import ctypes
    if not ctypes.windll.powrprof.SetSuspendState(False, True, False):
        raise Denied('sleep_failed')
    return dict(text='Sleep requested.')


DENIED_APPS = {'cmd', 'powershell', 'pwsh', 'terminal', 'windows terminal', 'python', 'pythonw',
               'wscript', 'cscript', 'mshta', 'rundll32', 'regsvr32', 'regedit', 'settings', 'wt',
               'bash', 'wsl', 'conhost', 'install', 'installer', 'msiexec', 'shutdown'}


def app_args(args):
    name = text_args('name', 60)(args)['name'].casefold()
    from services.automation.system_control import APP_REGISTRY
    if (name not in APP_REGISTRY or name in DENIED_APPS
            or not re.fullmatch(r'[a-z0-9][a-z0-9 _-]*', name)):
        raise Denied('app_not_allowed')
    target = APP_REGISTRY[name]
    if str(target).lower().endswith('.lnk'):
        from services.automation.app_finder import shortcut_target
        target = shortcut_target(target)
    leaf = PureWindowsPath(str(target)).stem.casefold()
    if not str(target).lower().endswith('.exe') or leaf in DENIED_APPS:
        raise Denied('app_not_allowed')
    return dict(name=name)


def resolved_app(args):
    from services.automation.system_control import APP_REGISTRY
    target = APP_REGISTRY[app_args(args)['name']]
    if str(target).lower().endswith('.lnk'):
        from services.automation.app_finder import shortcut_target
        target = shortcut_target(target)
    return str(target)


def notes_snapshot():
    from services.memory import notes
    try:
        raw = notes.path.read_bytes() if notes.path.exists() else b'[]'
        data = json.loads(raw)
        if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get('text'), str) for row in data):
            raise ValueError()
        return hashlib.sha256(raw).hexdigest()
    except (ValueError, OSError, RecursionError):
        raise Denied('notes_unavailable') from None


def approval_binding(command, args):
    if command == 'open_app':
        return dict(target=resolved_app(args))
    if command in {'delete_note', 'clear_notes'}:
        return dict(notes_revision=notes_snapshot())
    if command == 'send_message':
        from core.config import config
        return dict(recipient=config.TELEGRAM_USER_ID, bot=hashlib.sha256(config.TELEGRAM_BOT_TOKEN.encode()).hexdigest())
    return {}


def effect_lock(command):
    from services import settings_store
    return settings_store.lock if command in {'add_note', 'delete_note', 'clear_notes'} else nullcontext()


def open_app(service, device, args):
    target = args['_approved_target']
    os.startfile(target)  # A pinned registered executable; no user path or arguments.
    return dict(text='Opening ' + args['name'] + '.')


def send_message(service, device, args):
    from core.config import config
    from services.telegram import capabilities, client
    if not capabilities.ready():
        raise Denied('message_unavailable')
    # Avoid Telegram's command handler, which consumes its pending file context.
    client.send_long(config.TELEGRAM_USER_ID, args['text'])
    return dict(text='Message sent to your configured Telegram chat.')


async def ask_friday(service, device, args):
    from .context import conversation_only
    from interfaces.api.routes.chat import ChatRequest, chat
    token = conversation_only.set(True)
    try:
        reply = await chat(ChatRequest(message=args['text']))
        return dict(text=reply.response)
    finally:
        conversation_only.reset(token)
