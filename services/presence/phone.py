"""Finite owner-reviewed companion effects; no new remote execution endpoint."""
import re
import hashlib
from datetime import datetime

from services.remote.security import Denied


def _device():
    from services.remote import current
    from services.remote.phone_handoff import selected, store
    service = current()
    device = selected(service)
    if not device:
        raise Denied('choose_native_phone')
    service.check(service.epoch, device)
    return service, device, store(service)


def capabilities(service, device):
    from services.phone_signals.remote import store
    row = store(service).status(device['id'])
    if not row.get('last_heartbeat') or service.clock() - row['last_heartbeat'] > 900:
        return {}
    return (row.get('metadata') or {}).get('capabilities', {})


def send(kind, payload, ttl=900):
    from services.automation.intent import remote_request
    if remote_request.get():
        raise Denied('local_only')
    service, device, data = _device()
    caps = capabilities(service, device)
    if kind in {'mode', 'phone_mode'}:
        owner = payload.get('owner', payload.get('token', payload.get('restore_owner')))
        if isinstance(owner, str) and re.fullmatch(r'presence:[a-f0-9]{32}', owner):
            owner = hashlib.sha256(owner.encode()).hexdigest()[:32]
        if not isinstance(owner, str) or not re.fullmatch('[A-Za-z0-9_-]{16,80}', owner):
            raise Denied('phone_mode_owner')
        restore = 'restore_owner' in payload or payload.get('restore') is True
        if not restore and caps.get('phone_modes') is not True:
            raise Denied('phone_mode_not_granted')
        mode = payload.get('mode') or ('dnd' if 'dnd' in payload else 'ringer')
        value = payload.get('value')
        if value is None:
            value = ({'silent': 0, 'vibrate': 1, 'normal': 2}.get(payload.get('ringer')) if mode == 'ringer'
                     else {'all': 1, 'priority': 2, 'none': 3, 'alarms': 4}.get(payload.get('dnd')))
        if restore:
            value = 1 if mode == 'dnd' else 2
        if mode not in {'dnd', 'ringer'} or type(value) is not int or value not in (range(1, 5) if mode == 'dnd' else range(3)):
            raise Denied('phone_mode_value')
        kind, payload = 'phone_mode', dict(mode=mode, value=value, token=owner, restore=restore,
                                          until=service.clock() + min(ttl, 86400))
    elif kind == 'notice':
        text = payload.get('text')
        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
            raise Denied('phone_notice')
        owner = str(payload.get('owner', ''))
        if re.fullmatch(r'presence:[a-f0-9]{32}', owner):
            owner = hashlib.sha256(owner.encode()).hexdigest()[:32]
        payload = dict(text=text, kind='presence', title='FRIDAY')
        if owner:
            if not re.fullmatch('[A-Za-z0-9_-]{1,80}', owner):
                raise Denied('phone_notice_owner')
            payload['owner'] = owner
        if 'notification_snooze' not in caps:
            kind = 'text'  # A P4 inbox must not be poisoned by an unknown P5 message type.
    elif kind == 'triage_policy':
        if 'notification_snooze' not in caps:
            raise Denied('phone_update_required')
        if payload.get('situation') not in {'study', 'class', 'sleep', 'free'}:
            raise Denied('triage_policy')
        payload = dict(payload, until=min(service.clock() + 90, payload.get('until', service.clock() + 90)))
        payload['snooze'] = payload.get('snooze') is True and caps.get('notification_snooze') is True
    elif kind == 'notice_cancel':
        if 'notification_snooze' not in caps:
            raise Denied('phone_update_required')
        if not isinstance(payload.get('cancel_owner'), str) or len(payload['cancel_owner']) > 80:
            raise Denied('phone_notice')
    else:
        raise Denied('phone_effect_unknown')
    with service.effects:
        service.check(service.epoch, device)
        identity = data.put(device['id'], kind, payload, ttl=min(ttl, 86400))
    if kind in {'text', 'notice'}:
        from services.mind.speech_budget import budget
        budget.note_text(payload['text'])
    return identity


def cancel(identity):
    service, device, data = _device()
    with data.db() as db:
        row = db.execute('SELECT type,payload,delivered FROM outbox WHERE device=? AND id=?', (device['id'], identity)).fetchone()
        if not row:
            return False
        import json
        payload = json.loads(row['payload'])
        if row['delivered'] is None:
            db.execute('DELETE FROM outbox WHERE id=? AND device=?', (identity, device['id']))
            return True
    if row['type'] == 'phone_mode':
        send('mode', dict(restore_owner=payload['token'], mode=payload['mode']))
        return True
    if row['type'] == 'notice' and payload.get('owner'):
        send('notice_cancel', dict(cancel_owner=payload['owner']))
        return True  # Cancels the visible notification; cannot undo reading it.
    return False
