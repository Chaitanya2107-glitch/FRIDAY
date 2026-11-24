"""Private offline presence queries and narrowly scoped rule confirmations."""
import asyncio

from services.automation import autonomy
from services.automation.command_words import normalize_command
from services.automation.results import ActionResult
from .rules import parse, preview

PRIVATE_MEMORY = 'Presence query or rule handled locally; physical context was not retained.'


def controller():
    from services.plugin_runtime import current_manager
    manager = current_manager()
    scene = manager.get_service('scenes') if manager else None
    return manager, scene, getattr(scene, 'presence', None)


def match_command(message):
    text = normalize_command(message)
    if text.lower() == 'what mode am i in':
        from .engine import current
        # Preserve the existing laptop-only mode answer when no phone has consented signals.
        return bool(current().get('device'))
    if text.lower() in {'where am i', 'what mode am i in', 'list presence rules'} or parse(text) is not None:
        return True
    _, scene, presence = controller()
    if presence is None:
        return False
    if scene and scene.awaiting() and scene.pending['kind'].startswith('presence_'):
        return text.lower() in {'yes', 'yes please', 'no', 'no thanks', 'cancel'}
    if text.lower() in {'no', 'no thanks'} and not scene.awaiting() and presence.can_decline_auto():
        from services.automation.intent import _pending, remote_request
        recent = autonomy.last_run()
        return bool(recent and 'rule' in recent and remote_request.get() not in _pending)
    return False


def run(message):
    from services.automation.intent import remote_request
    if remote_request.get():
        return dict(ok=False, text='Presence rules are available at the laptop only.')
    text = normalize_command(message)
    if text.lower() in {'where am i', 'what mode am i in'}:
        from .engine import current
        value = current()
        if not value.get('data_available'):
            return dict(ok=True, text='Presence is unknown: there are not enough current signals.')
        return dict(ok=True, text=f"My estimate is {value['state'].replace('_', ' ')} ({round(value['confidence'] * 100)}% confidence): {value['reason']}.")
    manager, scene, presence = controller()
    if presence is None:
        return dict(ok=False, text='Enable the local scenes plugin to configure presence rules.')
    def local():
        with scene.lock:
            scene.ensure_active()
            if text.lower() == 'list presence rules':
                rows = presence.store.load()['rules']
                return dict(ok=True, text='\n'.join(preview(row['definition']).splitlines()[0] + ' — ' + row['level'].replace('_', ' ')
                                                   for row in rows[:20]) + (f'\n{len(rows) - 20} more rules are stored in memory/autonomy.json.' if len(rows) > 20 else '')
                            or 'No presence rules have been saved.')
            if text.lower() in {'no', 'no thanks'} and not scene.awaiting():
                return presence.undo()
            definition = parse(text)
            if definition is not None:
                return presence.draft(definition)
            if scene.awaiting() and scene.pending['kind'].startswith('presence_'):
                return scene.answer('yes' if text.lower().startswith('yes') else 'no')
            return dict(ok=False, text='That presence question has expired.')
    return manager.invoke(scene.api, local, command=True)


def _autonomy_command(message):
    from services.automation import intent
    from services.remote.context import remote_origin
    local = not (intent.remote_request.get() or remote_origin.get())
    text = normalize_command(message).lower()
    if text == 'undo that':
        if not local:
            return ActionResult(False, 'Undo for laptop actions is available at the laptop.', PRIVATE_MEMORY, False)
        intent.cancel_pending_confirmation()
        _, scene, _ = controller()
        if scene and scene.awaiting():
            scene.dismiss_pending()
        if autonomy.active_offer():
            autonomy.answer_offer(None)
        ok, reply = autonomy.undo_latest()
        return ActionResult(ok, reply, 'Reversed a local action.', False)
    if not local:
        return None
    _, scene, _ = controller()
    if intent.remote_request.get() in intent._pending or scene and scene.awaiting():
        if autonomy.active_offer():
            autonomy.answer_offer(None)
        return None
    if autonomy.active_offer():
        yes = text in intent.AFFIRMATIVE_REPLIES
        no = text in intent.NEGATIVE_REPLIES
        answer = autonomy.answer_offer(yes if yes or no else None)
        if answer is not None:
            return ActionResult(True, answer, 'Reviewed a local autonomy preference.', False)
    if text in {'no', 'no thanks'}:
        from services.mind import talk
        pending = talk.load().get('pending') or {}
        if pending:
            return None
        reply = autonomy.reject_latest_automatic()
        if reply is not None:
            return ActionResult(True, reply, 'Reviewed a local autonomy preference.', False)
    return None


async def try_command(message):
    try:
        if (normalize_command(message).lower() in {'undo that', 'yes', 'no', 'no thanks'}
                or autonomy.file_path().is_file()):
            if result := await asyncio.to_thread(_autonomy_command, message):
                return result
        if not match_command(message):
            return None
        from services.automation.intent import cancel_pending_confirmation
        cancel_pending_confirmation()
        value = await asyncio.to_thread(run, message)
        return ActionResult(value['ok'], value['text'], PRIVATE_MEMORY, False, speech=value.get('speech', value['text']))
    except (ValueError, OSError, KeyError):
        return ActionResult(False, 'Presence rule refused. Check the rule fields and scene preview.', PRIVATE_MEMORY, False)
