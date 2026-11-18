"""Optional phone second factor. Approval never executes a laptop action itself."""
import hashlib
import json
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from .commands import fields
from .security import Denied, key_id, public_key, unb64
from .phone_handoff import selected, settings, store

ACTIONS = {'delete_files', 'send_message', 'change_settings'}


def key_args(args):
    fields(args, ('public_key',))
    public_key(args['public_key'])
    return dict(args)


def result_args(args):
    from .transport_store import identifier
    fields(args, ('challenge', 'accepted', 'signature'))
    identifier(args['challenge'])
    if type(args['accepted']) is not bool or not isinstance(args['signature'], str) or len(args['signature']) > 256:
        raise Denied('invalid_approval')
    return dict(args)


def key_status(service, device, args):
    with store(service).db() as db:
        row = db.execute('SELECT public_key FROM approval_keys WHERE device=?', (device['id'],)).fetchone()
    return dict(registered=bool(row), public_key=row['public_key'] if row else None)


def resolve(service, device, args):
    data = store(service)
    with data.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM phone_approvals WHERE id=? AND device=?',
                         (args['challenge'], device['id'])).fetchone()
        key = db.execute('SELECT public_key FROM approval_keys WHERE device=?', (device['id'],)).fetchone()
        if (not row or not key or row['result'] is not None or row['consumed'] or row['epoch'] != service.epoch
                or row['expires_at'] <= service.clock()):
            raise Denied('approval_expired')
        if args['accepted']:
            try:
                public_key(key['public_key']).verify(unb64(args['signature'], 256),
                    (row['canonical'] + '\naccept').encode(), ec.ECDSA(hashes.SHA256()))
            except (InvalidSignature, ValueError):
                raise Denied('invalid_approval') from None
        db.execute('UPDATE phone_approvals SET result=? WHERE id=?',
                   ('accept' if args['accepted'] else 'deny', args['challenge']))
    return dict(recorded=True)


def create(service, action, summary, binding, timeout=60):
    """Return a pending ID only for an enrolled phone actively holding the inbox."""
    if action not in ACTIONS or type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise Denied('approval_action_refused')
    device, data = selected(service), store(service)
    if not device or not data.reachable(device['id']):
        return None
    service.check(service.epoch, device)
    with data.db() as db:
        if not db.execute('SELECT 1 FROM approval_keys WHERE device=?', (device['id'],)).fetchone():
            return None
        identity, expires = uuid.uuid4().hex, int(service.clock() + timeout)
        digest = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        canonical = '\n'.join(('FRIDAY-PHONE-APPROVAL-v1', device['id'], identity, action, digest, str(expires)))
        db.execute('INSERT INTO phone_approvals(id,device,action,canonical,expires_at,epoch) VALUES (?,?,?,?,?,?)',
                   (identity, device['id'], action, canonical, expires, service.epoch))
    data.put(device['id'], 'approval', dict(challenge=identity, action=action, summary=str(summary)[:240],
                                          expires_at=expires, canonical=canonical), ttl=timeout)
    service.audit.write(device=device['id'], command='phone_approval', risk='confirm', result='requested')
    return identity


def take(service, identity):
    data = store(service)
    with data.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM phone_approvals WHERE id=?', (identity,)).fetchone()
        if not row or row['consumed']:
            raise Denied('approval_consumed')
        if row['epoch'] != service.epoch or row['expires_at'] <= service.clock():
            db.execute('UPDATE phone_approvals SET consumed=1 WHERE id=?', (identity,))
            return None
        if row['result'] is None:
            return 'waiting'
        device = service.pairing.get(row['device'])
        service.check_epoch(service.epoch, device)
        db.execute('UPDATE phone_approvals SET consumed=1 WHERE id=?', (identity,))
        return row['result'] == 'accept'


def request(action, summary, timeout=60, *, binding=None, service=None):
    from . import current
    from services.automation.intent import remote_request
    if remote_request.get():
        raise Denied('local_only')
    service = service or current()
    identity = create(service, action, summary, binding or dict(action=action, summary=summary), timeout)
    if identity is None:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answer = take(service, identity)
        if answer != 'waiting':
            service.audit.write(command='phone_approval', risk='confirm', result='accepted' if answer else 'denied' if answer is False else 'timeout')
            return answer
        time.sleep(.25)
    with store(service).db() as db:
        db.execute('UPDATE phone_approvals SET consumed=1 WHERE id=?', (identity,))
    return None


def guard(parsed):
    """Called after the existing local Yes, immediately before the original executor."""
    from . import _service
    from services.automation.intent import remote_request
    service = _service
    if remote_request.get() or not service or settings(service).get('phone_approvals') is not True:
        return True
    action = parsed.get('action', '')
    category = ('delete_files' if action in {'delete_installers', 'organise_folder'} else
                'send_message' if action in {'send_whatsapp', 'phone_reply'} else
                'change_settings' if action in {'set_mode_steps', 'set_mode_quiet', 'delete_mode', 'sarcasm_on', 'sarcasm_off',
                                               'change_companion_settings'} else None)
    if category is None:
        return True
    try:
        answer = request(category, category.replace('_', ' ').capitalize(), binding=parsed, service=service)
        if answer is not None:
            return answer
    except (Denied, OSError):
        pass
    return service.confirm('The phone is unavailable or its approval timed out. Approve this action here?\n'
                           + category.replace('_', ' ').capitalize())
