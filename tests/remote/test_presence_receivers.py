import hashlib
import json
from datetime import datetime, timedelta

import pytest

from services.presence import phone
from services.presence.triage import TriageStore
from services.remote.security import Denied
from services.remote.phone_handoff import store


def post(remote, operation, value):
    path = '/remote/v1/' + operation
    raw = json.dumps(value, separators=(',', ':')).encode()
    return remote.client.post(path, content=raw, headers=remote.signed('POST', path, raw))


def grant(remote):
    remote.service.pairing.devices[remote.device['id']]['scopes'].append('phone_data')
    remote.service.pairing._save()


def heartbeat(remote, **caps):
    return post(remote, 'phone/heartbeat', dict(battery=None, app_version='test', last_sync=remote.now[0], signals=['notifications'],
                  capabilities=dict(phone_modes=False, notification_snooze=False, vip=[], urgent=[], **caps)))


def test_new_metadata_is_scoped_private_deduplicated_and_forgotten(remote):
    now = datetime.fromtimestamp(remote.now[0])
    data = TriageStore(remote.service.directory.parent / 'phone' / 'triage.db')
    data.context('study', now - timedelta(seconds=1))
    payload = dict(package='org.example.chat', category='msg', time=remote.now[0], notification_id='a' * 64, event='posted', importance=3)
    row = dict(id='event_' + 'a' * 20, timestamp=remote.now[0], type='notifications', payload=payload)
    batch = dict(generation=0, events=[row])
    assert post(remote, 'phone/events', batch).status_code == 404
    grant(remote)
    assert post(remote, 'phone/events', batch).json()['stored'] == 1
    assert post(remote, 'phone/events', batch).json()['stored'] == 0
    outcome = dict(row, id='event_' + 'b' * 20, payload=dict(payload, event='opened', reason=1))
    assert post(remote, 'phone/events', dict(batch, events=[outcome])).status_code == 200
    assert data.belief(remote.device['id'], payload['package'], 'study', now) == (3, 3)
    assert payload['package'] not in remote.service.audit.path.read_text()
    from services.phone_signals.remote import forget
    forget(remote.service, remote.device, {})
    with data.db() as db:
        assert db.execute('SELECT COUNT(*) FROM triage_beliefs').fetchone()[0] == 0


def test_caps_are_strict_and_controls_need_fresh_grant(remote):
    grant(remote)
    assert heartbeat(remote).status_code == 200
    with pytest.raises(Denied):
        phone.send('mode', {'owner': 'presence:' + 'a' * 32, 'ringer': 'silent'})
    value = dict(battery=None, app_version='test', last_sync=remote.now[0], signals=[], capabilities=dict(
                 phone_modes=True, notification_snooze=False, vip=[], urgent=[]))
    assert post(remote, 'phone/heartbeat', value).status_code == 200
    identity = phone.send('mode', {'owner': 'presence:' + 'a' * 32, 'ringer': 'silent'})
    message = next(r for r in store(remote.service).inbox(remote.device['id']) if r['id'] == identity)
    assert message['type'] == 'phone_mode' and message['payload']['token'] == hashlib.sha256(('presence:' + 'a' * 32).encode()).hexdigest()[:32]
    assert message['payload']['value'] == 0
    assert phone.cancel(identity)
    value['capabilities']['text'] = 'never accepted'
    assert post(remote, 'phone/heartbeat', value).status_code == 404


def test_old_phone_does_not_receive_unknown_p5_policy(remote):
    grant(remote)
    with pytest.raises(Denied):
        phone.send('triage_policy', dict(situation='study', vip=[], urgent=[], blocked=[], snooze=False))
    identity = phone.send('notice', dict(text='A reviewed notice.', owner='presence:' + 'a' * 32))
    message = next(r for r in store(remote.service).inbox(remote.device['id']) if r['id'] == identity)
    assert message['type'] == 'text' and ':' not in message['payload']['owner']
