import json
import sqlite3

import pytest

from services.phone_signals import schema
from services.phone_signals.store import PhoneStore
from services.remote.pin import pin_record
from services.remote.security import Denied


def send(remote, path, body):
    raw = json.dumps(body, separators=(',', ':')).encode()
    return remote.client.post(path, content=raw, headers=remote.signed('POST', path, raw))


def scoped(remote):
    remote.service.pairing.devices[remote.device['id']]['scopes'] = ['safe', 'confirm', 'phone_data']
    remote.service.pairing.devices[remote.device['id']]['pin'] = pin_record('123456')
    remote.service.pairing._save()


def row(remote, kind='screen', payload=None, identity='event_0123456789012345'):
    return dict(id=identity, timestamp=remote.now[0], type=kind,
                payload=payload if payload is not None else dict(state='on', unlock_count=2))


def batch(remote, rows=None, generation=0):
    return dict(generation=generation, events=[row(remote)] if rows is None else rows)


def test_upload_scope_gate_dedupe_and_metadata_bus(remote):
    from services.event_bus import event_bus
    path = '/remote/v1/phone/events'
    assert send(remote, path, batch(remote)).status_code == 404
    scoped(remote)
    before = len(event_bus.recent('phone.event'))
    assert send(remote, path, batch(remote)).json()['stored'] == 1
    assert send(remote, path, batch(remote)).json()['stored'] == 0
    events = event_bus.recent('phone.event')
    assert len(events) == before + 1
    assert events[-1]['payload'] == dict(type='screen', time=remote.now[0], remote_origin=True)
    assert 'unlock_count' not in str(events[-1])
    remote.service.registry.commands.pop('phone_events')
    assert send(remote, path, batch(remote)).status_code == 404


@pytest.mark.parametrize('kind,payload', [
    ('app_usage', dict(package='org.example.editor', label='Editor', category=7, start=1800000000, end=1800000015)),
    ('screen', dict(state='unlocked', unlock_count=3)), ('battery', dict(level=70, charging=True)),
    ('network', dict(transport='wifi', home=True, ssid_hash='a'*64)), ('motion', dict(activity='walking')),
    ('places', dict(place='college', transition='entered')), ('audio_devices', dict(kind='bluetooth', label='Headphones', connected=True)),
    ('media', dict(package='org.example.player', title='A song', artist='An artist')),
    ('notifications', dict(package='org.example.mail', time=1800000000, category='email')),
    ('sleep', dict(date='2026-11-13', minutes=430.5)), ('steps', dict(date='2026-11-13', count=4000)),
    ('interruption', dict(dnd=1, ringer=2)),
])
def test_every_signal_strict_schema(remote, kind, payload):
    scoped(remote)
    assert send(remote, '/remote/v1/phone/events', batch(remote, [row(remote, kind, payload)])).status_code == 200


@pytest.mark.parametrize('extra', ['title', 'text', 'content', 'extras', 'notification_title', 'notification_text', 'latitude', 'longitude', 'sms'])
def test_notification_content_and_extra_fields_rejected(remote, extra):
    scoped(remote)
    payload = dict(package='org.example.mail', time=remote.now[0], category='email', **{extra: 'private'})
    assert send(remote, '/remote/v1/phone/events', batch(remote, [row(remote, 'notifications', payload)])).status_code == 404


@pytest.mark.parametrize('mutation', ['unknown', 'nested', 'oversize', 'bad_time', 'nan', 'many', 'duplicate_id', 'wrong_bool', 'gps'])
def test_invalid_batch_rejected_atomically(remote, mutation):
    scoped(remote)
    value = batch(remote)
    event = value['events'][0]
    if mutation == 'unknown': event['type'] = 'keystrokes'
    elif mutation == 'nested': event['payload']['unknown'] = dict(text='secret')
    elif mutation == 'oversize': event['payload']['state'] = 'a'*3000
    elif mutation == 'bad_time': event['timestamp'] += 301
    elif mutation == 'nan': event['timestamp'] = float('nan')
    elif mutation == 'many': value['events'] = [row(remote, identity=f'event_{i:020}') for i in range(51)]
    elif mutation == 'duplicate_id': value['events'] *= 2
    elif mutation == 'wrong_bool': event['payload']['unlock_count'] = True
    elif mutation == 'gps': event.update(type='places', payload=dict(place='home', transition='entered', latitude=12.4))
    assert send(remote, '/remote/v1/phone/events', value).status_code == 404
    from services.phone_signals.remote import store
    assert store(remote.service).status(remote.device['id'])['stored_events'] == 0


def test_phone_status_heartbeat_retention_and_scope_revalidation(remote):
    scoped(remote)
    body = dict(battery=dict(level=50, charging=False), app_version='0.1.0', last_sync=0, signals=['battery', 'screen'])
    assert send(remote, '/remote/v1/phone/heartbeat', body).json()['generation'] == 0
    response = remote.command('phone_status').json()['data']
    assert response['last_heartbeat'] == remote.now[0] and response['metadata']['signals'] == ['battery', 'screen']
    assert send(remote, '/remote/v1/phone/events', batch(remote)).status_code == 200
    remote.now[0] += 31 * 86400
    response = remote.command('phone_status').json()['data']
    assert response['stored_events'] == 0 and response['metadata'] is None
    remote.service.pairing.devices[remote.device['id']]['scopes'].remove('phone_data')
    assert remote.command('phone_status').status_code == 404


def test_forget_requires_confirm_and_fences_old_batches(remote):
    scoped(remote)
    assert send(remote, '/remote/v1/phone/events', batch(remote)).status_code == 200
    challenge = remote.command('phone_forget').json()
    assert challenge['result'] == 'approval_required'
    assert remote.command('phone_status').json()['data']['stored_events'] == 1
    approved = send(remote, '/remote/v1/approve', dict(challenge=challenge['challenge'], approval=dict(pin='123456')))
    assert approved.json()['data'] == dict(forgotten=True, generation=1)
    assert remote.command('phone_status').json()['data']['stored_events'] == 0
    assert send(remote, '/remote/v1/phone/events', batch(remote)).status_code == 404
    assert send(remote, '/remote/v1/phone/events', batch(remote, generation=1)).json()['stored'] == 1
    assert send(remote, '/remote/v1/approve', dict(challenge=challenge['challenge'], approval=dict(pin='123456'))).status_code == 404


def test_dedupe_is_per_device_and_conflicts_rollback(tmp_path):
    now = 1800000000
    store = PhoneStore(tmp_path / 'phone.db', clock=lambda: now)
    event = dict(id='same_event_0123456789', timestamp=now, type='screen', payload=dict(state='on', unlock_count=0))
    assert len(store.ingest('a', [event], 0)[1]) == 1
    assert len(store.ingest('b', [event], 0)[1]) == 1
    with pytest.raises(Denied, match='phone_id_conflict'):
        store.ingest('a', [dict(event, id='new_event_0123456789'), dict(event, payload=dict(state='off', unlock_count=0))], 0)
    assert store.status('a')['stored_events'] == 1
    store.forget('a')
    assert store.status('a')['stored_events'] == 0 and store.status('b')['stored_events'] == 1


def test_phone_data_requested_scope_is_explicit_and_persisted(remote):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from services.remote.pairing import Pairing
    from services.remote.security import key_id
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    token = remote.service.issue_pairing()['token']
    body = dict(token=token, public_key=pem, name='Native', pin='123456', scopes=['phone_data'])
    pending, _ = remote.service.pairing.begin(body, remote.service.magic_dns)
    assert key_id(pem) not in remote.service.pairing.devices
    remote.service.pairing.activate(pending['id'])
    restored = Pairing(remote.service.directory, remote.service.clock)
    assert 'phone_data' in restored.get(pending['id'])['scopes']
    assert 'phone_data' not in restored.get(remote.device['id'])['scopes']
