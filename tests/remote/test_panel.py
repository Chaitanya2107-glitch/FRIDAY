import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.remote import app_shell, panel, streams
from services.remote.commands import Command, no_args
from services.remote.pairing import Pairing
from services.remote.pin import pin_record
from services.remote.security import Denied, RequestProofs, signing_bytes


def post(remote, path, body):
    raw = json.dumps(body).encode()
    return remote.client.post(path, content=raw, headers=remote.signed('POST', path, raw))


def enroll_pin(remote):
    device = remote.service.pairing.devices[remote.device['id']]
    device.update(pin=pin_record('123456'), scopes=['safe', 'confirm'])
    remote.service.pairing._save()
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append('lock') or {}, 'confirm', no_args)
    return calls


def approve(remote, challenge, pin='123456'):
    return post(remote, '/remote/v1/approve', dict(challenge=challenge, approval=dict(pin=pin)))


def test_shared_vectors():
    vectors = json.loads((Path(__file__).parents[1] / 'remote_vectors.json').read_text(encoding='utf-8'))
    for row in vectors:
        assert signing_bytes(row['method'], row['path'], row['body'].encode(), row['timestamp'], row['nonce']).decode() == row['canonical']
        proofs = RequestProofs(clock=lambda: int(row['timestamp']))
        proofs.verify(dict(id='vector', public_key=row['public_key']), row['method'], row['path'], row['body'].encode(),
                      {'x-timestamp': row['timestamp'], 'x-nonce': row['nonce'], 'x-signature': row['signature']})


def test_pin_single_use_and_command_binding(remote):
    calls = enroll_pin(remote)
    challenge = remote.command('lock_pc').json()
    assert challenge['pin_required'] and not calls
    assert approve(remote, challenge['challenge']).json()['result'] == 'completed'
    assert calls == ['lock']
    assert approve(remote, challenge['challenge']).status_code == 404
    assert calls == ['lock']
    assert b'123456' not in remote.service.pairing.path.read_bytes()


def test_pin_three_attempt_persistent_lockout(remote):
    calls = enroll_pin(remote)
    for _ in range(3):
        challenge = remote.command('lock_pc').json()['challenge']
        assert approve(remote, challenge, '000000').status_code == 404
    restored = Pairing(remote.service.directory, clock=lambda: remote.now[0])
    assert restored.get(remote.device['id'])['pin']['locked_until'] == remote.now[0] + 600
    challenge = remote.command('lock_pc').json()['challenge']
    assert approve(remote, challenge).status_code == 404 and not calls
    remote.now[0] += 601
    challenge = remote.command('lock_pc').json()['challenge']
    assert approve(remote, challenge).status_code == 200 and calls == ['lock']


@pytest.mark.parametrize('change', ['expired', 'kill', 'revoke'])
def test_pin_fences(remote, change):
    calls = enroll_pin(remote)
    challenge = remote.command('lock_pc').json()['challenge']
    if change == 'expired':
        remote.now[0] += 61
    elif change == 'kill':
        remote.service.trip()
    else:
        remote.service.revoke(remote.device['id'])
    assert approve(remote, challenge).status_code == 404 and not calls


@pytest.mark.parametrize('name', ['status', 'schedule', 'activity', 'device'])
def test_read_endpoints_require_gate_signature_and_allowlist(remote, name):
    remote.service.registry.commands[name] = Command(lambda *_: {'test': name}, 'safe', no_args)
    path = '/remote/v1/' + name
    assert remote.client.get(path).status_code == 404
    assert remote.client.get(path, headers=remote.signed(path=path)).json() == {'test': name}
    remote.service.registry.commands.pop(name)
    assert remote.client.get(path, headers=remote.signed(path=path)).status_code == 404


def test_shell_bootstraps_only_through_owner_gate(remote, monkeypatch, tmp_path):
    monkeypatch.setattr(app_shell, 'ROOT', tmp_path)
    (tmp_path / 'index.html').write_text('<!doctype html><title>Phone</title>')
    path = '/remote/app/'
    assert remote.client.get(path).status_code == 404
    headers = {'Tailscale-User-Login': 'owner@example.test'}
    response = remote.client.get(path, headers=headers)
    assert response.status_code == 200 and 'frame-ancestors' in response.headers['Content-Security-Policy']
    assert remote.client.get('/remote/app/unknown.js', headers=headers).status_code == 404
    assert remote.client.post(path, headers=headers).status_code == 404
    headers['Tailscale-User-Login'] = 'stranger@example.test'
    assert remote.client.get(path, headers=headers).status_code == 404
    headers['Tailscale-User-Login'] = 'owner@example.test'
    remote.service.trip()
    assert remote.client.get(path, headers=headers).status_code == 404


def test_pair_with_pin_requires_laptop_consent(remote):
    grant = remote.service.issue_pairing()
    # Use an independent candidate public key to avoid an existing-device collision.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from services.remote.security import key_id
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    body = dict(token=grant['token'], public_key=pem, name='PIN phone', pin='654321')
    remote.service.confirm = lambda _: False
    raw = json.dumps(body).encode()
    device = dict(id=key_id(pem))
    result = remote.client.post('/remote/v1/pair', content=raw,
                               headers=remote.signed('POST', '/remote/v1/pair', raw, key=key, device=device))
    assert result.status_code == 200 and result.json()['proof']
    assert key_id(pem) not in remote.service.pairing.devices


@pytest.mark.parametrize('pin', [None, '12345', 'abcdef', 123456])
def test_new_http_pairing_requires_six_digit_pin(remote, pin):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from services.remote.security import key_id
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    grant = remote.service.issue_pairing()
    body = dict(token=grant['token'], public_key=pem, name='Invalid PIN phone')
    if pin is not None:
        body['pin'] = pin
    raw = json.dumps(body).encode()
    assert remote.client.post('/remote/v1/pair', content=raw,
        headers=remote.signed('POST', '/remote/v1/pair', raw, key=key, device=dict(id=key_id(pem)))).status_code == 404
    assert key_id(pem) not in remote.service.pairing.devices


def test_status_partial_sources_and_schedule(remote, monkeypatch):
    from services.college import overview, work
    from services.activity import log
    import psutil
    monkeypatch.setattr(log, 'foreground_app', lambda: 'Editor')
    monkeypatch.setattr(psutil, 'sensors_battery', lambda: SimpleNamespace(percent=83, power_plugged=True))
    monkeypatch.setattr(panel, 'plugin_state', lambda *_: (_ for _ in ()).throw(OSError()))
    class_row = dict(subject='Calculus', faculty='Dr Rao', start='09:00')
    monkeypatch.setattr(overview, 'class_status', lambda *a: dict(today=[class_row], next_class=class_row))
    monkeypatch.setattr(overview, 'overview', lambda *a: dict(due_soon=[]))
    monkeypatch.setattr(work, 'snapshot', lambda section: dict(items=[dict(what=section)]))
    status = remote.client.get('/remote/v1/status', headers=remote.signed()).json()
    assert status['battery']['percent'] == 83 and status['next_class']['faculty'] == 'Dr Rao'
    assert status['scene'] is None and status['errors']['scene'] == 'unavailable'
    schedule = remote.client.get('/remote/v1/schedule', headers=remote.signed(path='/remote/v1/schedule')).json()
    assert schedule['tomorrow'][0]['faculty'] == 'Dr Rao'
    assert schedule['assignments'][0]['what'] == 'deadlines'


def test_self_revocation_is_success_and_fences_future_requests(remote):
    assert remote.command('revoke_self').json()['data']['revoked'] is True
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404


def test_signed_chat_stream_uses_ask_and_never_audits_text(remote, monkeypatch):
    from services.remote import conversation
    from services.automation.intent import remote_request
    async def answer(text):
        assert remote_request.get()
        return SimpleNamespace(content='A streamed answer', provider='mock', model='mock', tokens_used=0)
    monkeypatch.setattr(conversation, 'answer', answer)
    response = post(remote, '/remote/v1/chat', dict(command='ask', args=dict(text='private question')))
    assert response.status_code == 200 and 'event: reply' in response.text and 'A streamed answer' in response.text
    assert 'private question' not in remote.service.audit.path.read_text()
    assert post(remote, '/remote/v1/chat', dict(command='lock_pc', args={})).status_code == 404


def test_event_stream_stops_on_revoke_and_unsubscribes(remote, monkeypatch):
    from services import plugin_runtime
    from services.event_bus import EventBus
    bus = EventBus()
    monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: SimpleNamespace(bus=bus))
    monkeypatch.setattr(panel, 'plugin_state', lambda *_: dict(remaining_s=120, private='secret'))
    auth = dict(device=remote.device, epoch=remote.service.epoch, body={})
    class Request:
        state = SimpleNamespace(remote_auth=auth)
        async def is_disconnected(self):
            return False
    async def run():
        iterator = streams.event_response(remote.service, Request()).body_iterator
        assert 'connected' in await anext(iterator)
        bus.publish('mood.changed', dict(mood='happy', private='secret'))
        frame = await anext(iterator)
        assert 'happy' in frame and 'secret' not in frame
        remote.service.revoke(remote.device['id'])
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        assert not bus._subscriptions
    asyncio.run(run())


def test_stream_projects_only_public_notices_and_schedule_fields(remote, monkeypatch):
    from services import plugin_runtime
    from services.event_bus import EventBus
    from services.friday_island_server import events
    bus = EventBus()
    monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: SimpleNamespace(bus=bus))
    auth = dict(device=remote.device, epoch=remote.service.epoch, body={})
    class Request:
        state = SimpleNamespace(remote_auth=auth)
        async def is_disconnected(self):
            return False
    async def run():
        iterator = streams.event_response(remote.service, Request()).body_iterator
        await anext(iterator)
        events.publish('response', 'private chat')
        events.publish('notification', 'public reminder')
        bus.publish('schedule.due_soon', dict(title='Report', due_at='2026-11-14', secret='hidden'))
        due = await anext(iterator)
        assert 'Report' in due and 'due_at' in due and 'hidden' not in due
        notification = await anext(iterator)
        assert 'public reminder' in notification and 'private chat' not in notification
        remote.service.trip()
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        assert not bus._subscriptions
    asyncio.run(run())
