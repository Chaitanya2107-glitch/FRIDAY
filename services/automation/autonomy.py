"""Owner-approved autonomy and compensating actions for local effects."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
import time
from uuid import uuid4

from core.config import config
from services import settings_store

ASK, TELL, SILENT = LEVELS = ('ask', 'do_and_tell', 'just_do')
LABELS = dict(zip(LEVELS, ('Ask first', 'Do and tell', 'Just do')))
# P0-visible app/message/power effects stay at Ask. Local bulk moves already need review.
CONFIRM_ACTIONS = frozenset({'open_app', 'send_message', 'organise_folder', 'lock_pc', 'sleep_pc',
                             'shutdown_pc', 'restart_pc', 'delete_note', 'clear_notes', 'phone_forget'})
MAX_RUNS = 200
OFFER_SECONDS = 120
undo_lock = Lock()
_current = ContextVar('autonomy_current_receipt', default=None)
_EPOCH = uuid4().hex


def file_path():
    return config.MEMORY_DIR / 'autonomy.json'


def read_file(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('The autonomy log is too large.')
    return json.loads(path.read_text(encoding='utf-8'))


def load(path=None):
    path = file_path() if path is None else Path(path)
    with settings_store.lock:
        try:
            value = read_file(path)
        except FileNotFoundError:
            return dict(version=1, rules=[], runs=[], actions={})
        if (not isinstance(value, dict) or value.get('version') != 1
                or not isinstance(value.get('rules'), list) or len(value['rules']) > 100
                or not isinstance(value.get('runs'), list) or len(value['runs']) > MAX_RUNS
                or not isinstance(value.get('actions', {}), dict)
                or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                       or not isinstance(row.get('tokens'), list) for row in value['runs'])
                or any(not isinstance(row, dict) or row.get('level') not in LEVELS
                       or type(row.get('streak')) is not int or row['streak'] < 0
                       for row in value.get('actions', {}).values())):
            raise ValueError('The autonomy log is damaged and was preserved.')
        value.setdefault('actions', {})
        return value


def update(edit, path=None):
    path = file_path() if path is None else Path(path)
    with settings_store.lock:
        state = load(path)
        result = edit(state)
        settings_store.save(path, state)
        return result


def level(row, risky=False):
    value = row.get('level', ASK)
    return ASK if risky or value not in LEVELS else value


def next_level(row):
    current = LEVELS.index(level(row))
    return LEVELS[current + 1] if current < len(LEVELS) - 1 else None


def accepted(row):
    return {**row, 'streak': int(row.get('streak', 0)) + 1}


def declined(row):
    current = LEVELS.index(level(row))
    return {**row, 'level': LEVELS[max(0, current - 1)], 'streak': 0}


def can_offer(row, risky=False, *, skill=None):
    target = next_level(row)
    offered = row.get('promotion_offered') if target == TELL else row.get('silence_offered', True)
    return (not risky and target is not None and int(row.get('streak', 0)) >= 3 and not offered
            and (not skill or capped_level(skill, row, target) == target))


def mark_offer(row):
    target = next_level(row)
    return {'promotion_offered' if target == TELL else 'silence_offered': True}


def _policy(state, action):
    return state['actions'].setdefault(action, {'level': ASK, 'streak': 0, 'promotion_offered': False})


def action_level(action):
    if action in CONFIRM_ACTIONS:
        return ASK
    return capped_level(action, load()['actions'].get(action, {}))


def capped_level(action, row, target=None):
    choice = target or level(row)
    if choice == ASK:
        return ASK
    from services.mind.self_model import ceiling
    return LEVELS[min(LEVELS.index(choice), ceiling(action))]


def append_run(state, row):
    if len(state['runs']) >= MAX_RUNS:
        oldest = next((run for run in state['runs'] if run.get('status') not in {'running', 'undoing'}), None)
        if oldest is None:
            raise ValueError('Finish a running action before starting another.')
        state['runs'].remove(oldest)
    state['runs'].append(row)


class Receipt:
    def __init__(self, action, *, tokens=(), origin='owner'):
        self.action = action
        self.id = uuid4().hex
        self.origin = origin
        self.tokens = list(tokens)
        self.status = 'completed'
        update(lambda state: append_run(state, dict(id=self.id, action=action, at=time.time(), origin=origin,
                                                    status='running', tokens=self.tokens, undone=False, epoch=_EPOCH)))

    def checkpoint(self, tokens):
        self.tokens = list(tokens)
        update(lambda state: _run(state, self.id).update(tokens=self.tokens))

    def add(self, token):
        self.checkpoint([*self.tokens, token])


def _run(state, identity):
    return next(row for row in state['runs'] if row['id'] == identity)


def _owner_origin():
    from services.learning.origin import current_actor
    from services.remote.context import remote_origin
    from services.automation.intent import remote_request
    if remote_request.get() or remote_origin.get():
        return 'remote'
    return 'automatic' if current_actor() == 'automatic' else 'owner'


@contextmanager
def record(action, *, tokens=(), origin=None, learn=True):
    nested = _current.get() is not None
    receipt = Receipt(action, tokens=tokens, origin='component' if nested else origin or _owner_origin())
    current = _current.set(receipt)
    try:
        yield receipt
    except BaseException:
        receipt.status = 'failed'
        raise
    finally:
        _current.reset(current)
        def finish(state):
            _run(state, receipt.id).update(status=receipt.status, tokens=receipt.tokens)
            if learn and receipt.origin == 'owner' and action not in CONFIRM_ACTIONS:
                row = _policy(state, action)
                row.update(accepted(row) if receipt.status == 'completed' else {'streak': 0})
        update(finish)


def current_receipt(action):
    receipt = _current.get()
    return receipt if receipt and receipt.action == action else None


def reject(action):
    if action in CONFIRM_ACTIONS:
        return ASK
    def change(state):
        row = _policy(state, action)
        row.update(declined(row))
        return row['level']
    return update(change)


def automatic_feedback(identity, yes):
    def apply_feedback(state):
        row = next((run for run in reversed(state['runs']) if run['id'] == identity), None)
        if (not row or row.get('origin') != 'automatic' or time.time() - row['at'] > OFFER_SECONDS
                or row.get('status') != 'completed' or row.get('reviewed') or row.get('demoted') or row.get('undone')):
            return None
        action = row['action']
        policy = _policy(state, action)
        if action in CONFIRM_ACTIONS or yes and level(policy) != TELL:
            return None
        policy.update(accepted(policy) if yes else declined(policy))
        row['reviewed'] = True
        if not yes:
            row['demoted'] = True
            if state.get('offer', {}).get('action') == action:
                state.pop('offer', None)
        return action
    if not (action := update(apply_feedback)):
        return None
    if yes:
        return offer_text(action, 'I’ll remember that timing worked.')
    return f'I’ll keep {action.replace("_", " ")} at {LABELS[action_level(action)]}.'


def reject_latest_automatic():
    row = last_run()
    return automatic_feedback(row['id'], False) if row and row.get('origin') == 'automatic' else None


def offer_text(action, text, *, risky=False):
    """Append a single owner question to an existing action result."""
    if risky or action in CONFIRM_ACTIONS or _owner_origin() != 'owner':
        return text
    with settings_store.lock:
        state = load()
        row = _policy(state, action)
        if not can_offer(row, skill=action) or active_offer(state):
            return text
        target = next_level(row)
        row.update(mark_offer(row))
        state['offer'] = dict(action=action, target=target, epoch=_EPOCH, expires=time.time() + OFFER_SECONDS)
        settings_store.save(file_path(), state)
    return f'{text}\nUse {LABELS[target]} for {action.replace("_", " ")}? Say yes or no.'


def active_offer(state=None):
    try:
        state = load() if state is None else state
    except (OSError, ValueError):
        return None
    offer = state.get('offer')
    if (isinstance(offer, dict) and offer.get('epoch') == _EPOCH and offer.get('target') in LEVELS
            and isinstance(offer.get('action'), str) and type(offer.get('expires')) in {float, int}
            and offer['expires'] > time.time()):
        return offer
    return None


def answer_offer(yes):
    def answer(state):
        offer = active_offer(state)
        state.pop('offer', None)
        if offer is None or yes is None:
            return None
        action, target = offer['action'], offer['target']
        row = _policy(state, action)
        if (yes and action not in CONFIRM_ACTIONS and target == next_level(row) and row['streak'] >= 3
                and capped_level(action, row, target) == target):
            row.update(level=target, streak=0)
            if target == TELL:
                row['silence_offered'] = row.get('silence_offered', False)
        elif not yes:
            row.update(declined(row))
        return f'{action.replace("_", " ").capitalize()} is at {LABELS[ASK if action in CONFIRM_ACTIONS else capped_level(action, row)]}.'
    return update(answer)


def last_run():
    return next((row for row in reversed(load()['runs'])
                 if not row.get('undone') and row.get('origin') not in {'remote', 'component'}
                 and row.get('status') != 'cancelled'
                 and (row.get('status') != 'failed' or row.get('tokens'))), None)


def demote(run):
    def change(state):
        row = _run(state, run['id'])
        if row.get('demoted'):
            return
        policy = (next((rule for rule in state['rules'] if rule['id'] == row['rule']), None)
                  if 'rule' in row else _policy(state, row['action']))
        if policy is not None:
            policy.update(declined(policy))
        row['demoted'] = True
        if state.get('offer', {}).get('action') == row.get('action'):
            state.pop('offer', None)
    update(change)


def file_identity(path):
    info = path.stat(follow_symlinks=False)
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def move_token(source, target):
    return dict(type='file_move', source=str(source.absolute()), target=str(target.absolute()),
                identity=file_identity(source))


def move_no_overwrite(source, target):
    try:
        os.rename(source, target)
    except OSError as error:
        if getattr(error, 'winerror', None) != 17:
            raise
        from win32file import MoveFileEx
        from win32con import MOVEFILE_COPY_ALLOWED
        MoveFileEx(str(source), str(target), MOVEFILE_COPY_ALLOWED)
        if source.exists():
            raise OSError('Windows left the original in place. Both copies were kept.')


def _restore_file(token):
    source, target = Path(token['source']), Path(token['target'])
    if (not source.is_absolute() or not target.is_absolute() or source == target
            or source.is_symlink() or target.is_symlink()
            or target.parent.resolve() != target.parent or source.parent.resolve() != source.parent):
        raise ValueError('The original or current location changed.')
    if not target.exists() and source.is_file() and file_identity(source) == token.get('identity'):
        return f'{source.name} is already back.'
    if source.exists() or not target.is_file() or file_identity(target) != token.get('identity'):
        raise ValueError('The file changed or its original location is occupied.')
    move_no_overwrite(target, source)
    return f'Moved {source.name} back.'


def telegram_token(chat_id, messages):
    return dict(type='telegram', chat=chat_id, messages=list(messages or []),
                bot=hashlib.sha256(config.TELEGRAM_BOT_TOKEN.encode()).hexdigest())


def _retract_telegram(token):
    from services.telegram import client
    if (not config.TELEGRAM_BOT_TOKEN or token['chat'] != config.TELEGRAM_USER_ID
            or token['bot'] != hashlib.sha256(config.TELEGRAM_BOT_TOKEN.encode()).hexdigest()):
        raise ValueError('The Telegram destination changed.')
    if not token['messages']:
        raise ValueError('Telegram did not provide a message ID.')
    message = token['messages'][-1]
    if type(message) is not int or message <= 0:
        raise ValueError('Telegram did not provide a valid message ID.')
    try:
        deleted = client.call('deleteMessage', chat_id=token['chat'], message_id=message)
    except client.TelegramError:
        deleted = False
    if deleted is not True:
        raise ValueError('Telegram did not confirm the retraction. The message may already have been seen.')
    return 'Retracted the Telegram message. It may already have been seen.'


def _restore(token):
    kind = token['type']
    if kind == 'file_move':
        return _restore_file(token)
    if kind == 'reminder':
        from services.reminders.service import reminders
        if str(Path(reminders.db_path).resolve()) != token['db']:
            raise ValueError('The active reminder database changed.')
        return reminders.undo_created(token['id'], token['created'])
    if kind in {'focus', 'scene'}:
        from services.scene_runtime import services
        manager, scenes, focus = services()
        service = focus if kind == 'focus' else scenes
        if service is None:
            raise ValueError(f'Enable the {kind} plugin to restore this action.')
        def restore():
            with service.lock:
                if kind == 'focus':
                    # Tick while holding the lock before deciding whether a timer is still live.
                    if service.status().get('session_id') != token['id']:
                        return 'That focus timer already ended or changed.'
                    result = service.stop()
                else:
                    if not service.active or service.active.get('id') != token['id']:
                        return 'That scene already ended or changed.'
                    result = service.end('command_undo', restore=True)
                if not result['ok']:
                    raise ValueError(result['text'])
                return result['text']
        return manager.invoke(service.api, restore, command=True)
    if kind == 'telegram':
        return _retract_telegram(token)
    if kind == 'app_process':
        from services.automation.app_finder import close_owned
        return close_owned(token)
    if kind == 'unavailable':
        raise ValueError('I have no safe way to undo that action.')
    raise ValueError('This effect has no safe reversal.')


def undo_latest(expected=None):
    with undo_lock:
        row = last_run()
        if row is None or expected is not None and row['id'] != expected:
            return False, 'No FRIDAY action to undo.'
        if row.get('status') == 'awaiting_confirmation' or row.get('status') == 'running' and row.get('epoch') == _EPOCH:
            return False, 'That action has not finished yet.'
        if 'rule' in row:
            from services.presence.commands import controller
            manager, scene, presence = controller()
            if not presence:
                return False, 'Enable the scenes plugin to undo that presence action.'
            if not manager.invoke(scene.api, presence.can_undo):
                return False, 'That presence action already ended or changed.'
            value = manager.invoke(scene.api, presence.undo, {'run': row['id']}, command=True)
            return value['ok'], value['text']
        demote(row)
        tokens = list(row.get('tokens', []))
        if not tokens:
            return False, 'I have no safe way to undo that action.'
        notes = []
        try:
            while tokens:
                token = tokens[-1]
                notes.append(_restore(token))
                if token['type'] == 'telegram' and len(token['messages']) > 1:
                    token = {**token, 'messages': token['messages'][:-1]}
                    tokens[-1] = token
                else:
                    tokens.pop()
                update(lambda state: _run(state, row['id']).update(tokens=tokens, undone=not tokens))
        except (OSError, ValueError, KeyError, TypeError) as error:
            return False, ' '.join([*notes, str(error)])
        return True, ' '.join(notes)
