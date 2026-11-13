import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.remote.audit import Audit
from services.remote.commands import Registry, build_registry, no_args
from services.remote.pairing import Pairing
from services.remote.security import Denied, key_id
from services.remote.service import RemoteService


def new_phone():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return key, dict(id=key_id(pem), public_key=pem)


def test_pairing_token_once_and_expiry(remote):
    _, device = new_phone()
    grant = remote.service.pairing.issue('https://laptop.example.ts.net')
    body = dict(token=grant['token'], name='New phone', public_key=device['public_key'])
    row, _ = remote.service.pairing.begin(body, remote.service.magic_dns)
    assert row['id'] not in remote.service.pairing.devices
    with pytest.raises(Denied, match='pairing_token'):
        remote.service.pairing.begin(body, remote.service.magic_dns)
    grant = remote.service.pairing.issue('https://laptop.example.ts.net')
    remote.now[0] += 120
    body['token'] = grant['token']
    with pytest.raises(Denied, match='pairing_token'):
        remote.service.pairing.begin(body, remote.service.magic_dns)


def test_laptop_must_approve_before_activation(remote):
    key, device = new_phone()
    entered, release = threading.Event(), threading.Event()
    def confirm(question):
        assert 'New phone' in question
        entered.set()
        return release.wait(3)
    remote.service.confirm = confirm
    grant = remote.service.pairing.issue('https://laptop.example.ts.net')
    body = json.dumps(dict(token=grant['token'], name='New phone', public_key=device['public_key'], pin='123456')).encode()
    try:
        response = remote.client.post('/remote/v1/pair', content=body,
            headers=remote.signed('POST', '/remote/v1/pair', body, key=key, device=device))
        assert response.status_code == 200 and entered.wait(2)
        assert device['id'] not in remote.service.pairing.devices
        assert remote.client.get('/remote/v1/status', headers=remote.signed(key=key, device=device)).status_code == 404
        release.set()
        for _ in range(100):
            if device['id'] in remote.service.pairing.devices:
                break
            time.sleep(.01)
        assert device['id'] in remote.service.pairing.devices
        remote.service.pairing.get(device['id'])  # Wait for publication under the store guard.
        saved = json.loads(remote.service.pairing.path.read_text())['devices']
        assert {'id', 'name', 'public_key', 'created', 'last_seen', 'scopes'} <= set(saved[-1])
        assert remote.client.post('/remote/v1/pair', content=body,
            headers=remote.signed('POST', '/remote/v1/pair', body, key=key, device=device)).status_code == 404
    finally:
        release.set()


def test_wrong_curve_and_corrupt_store_fail_closed(tmp_path):
    store = Pairing(tmp_path)
    key = ec.generate_private_key(ec.SECP384R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    grant = store.issue('https://laptop.example.ts.net')
    with pytest.raises(Denied, match='invalid_key'):
        store.begin(dict(token=grant['token'], name='Phone', public_key=pem), 'laptop.example.ts.net')
    store.path.write_text('broken data')
    damaged = Pairing(tmp_path)
    with pytest.raises(Denied):
        damaged.issue('https://laptop.example.ts.net')
    assert store.path.read_text() == 'broken data'


def test_nonloopback_config_and_actual_bind_refused(remote, monkeypatch, tmp_path):
    remote.service.bound_addresses = lambda: ['0.0.0.0']
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    assert not remote.service.registered
    from core.config import config
    from interfaces.api.app import create_app
    monkeypatch.setattr(config, 'API_HOST', '0.0.0.0')
    monkeypatch.setattr(config, 'MEMORY_DIR', tmp_path)
    app = create_app()
    assert not any(getattr(route, 'path', '').startswith('/remote/') for route in app.routes)
    assert not app.state.remote.registered and 'loopback' in app.state.remote.warning


def test_default_off_restart_and_source_update(remote):
    restarted = RemoteService(remote.service.directory, 8000, tailscale=remote.service.tailscale,
                              notify=remote.notices.append, bound_addresses=lambda: ['127.0.0.1'])
    assert restarted.owner_login == 'owner@example.test'
    assert not restarted.enabled.is_set()
    remote.service.source_state = lambda: ('changed',)
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    assert not remote.service.enabled.is_set() and 'update' in remote.service.warning


def test_kill_wins_against_enable_and_reset_failure(remote):
    entered, release = threading.Event(), threading.Event()
    real_enable = remote.service.tailscale.enable
    def enable(port):
        entered.set()
        assert release.wait(3)
        return real_enable(port)
    remote.service.tailscale.enable = enable
    with ThreadPoolExecutor(max_workers=2) as executor:
        enabling = executor.submit(remote.service.enable, confirmed=True)
        assert entered.wait(2)
        killing = executor.submit(remote.service.disable)
        for _ in range(100):
            if remote.service.stopped.is_set():
                break
            time.sleep(.005)
        assert remote.service.stopped.is_set() and not remote.service.status()['enabled']
        release.set()
        with pytest.raises(Denied):
            enabling.result(3)
        assert killing.result(3)['enabled'] is False
    remote.service.tailscale.reset = lambda: (_ for _ in ()).throw(Denied('mock_reset_failure'))
    assert remote.service.disable()['serve_reset'] is False
    assert not remote.service.enabled.is_set()


def test_risk_is_mandatory_for_every_registration():
    registry = Registry()
    with pytest.raises(TypeError):
        registry.register('unsafe', lambda: None, validate=no_args)
    with pytest.raises(ValueError):
        registry.register('unsafe', lambda: None, risk='unknown', validate=no_args)
    assert all(command.risk in {'safe', 'confirm', 'blocked'} for command in build_registry().commands.values())


def test_audit_rotation_and_no_payloads(remote, tmp_path):
    audit = Audit(tmp_path, max_bytes=350, clock=lambda: 1)
    for _ in range(8):
        audit.write(device=remote.device['id'], command='status', risk='safe', result='completed', source='100.64.1.2')
    assert audit.path.with_name('audit.jsonl.1').exists()
    assert audit.path.stat().st_size <= 350
    assert len(audit.recent()) <= 20
    raw = b'{"command":"add_note","args":{"text":"NEVER_AUDIT_THIS_SECRET"}}'
    # Reject before the fixed note store is touched, then inspect the actual transport log.
    headers = remote.signed('POST', '/remote/v1/commands', raw)
    headers['Tailscale-User-Login'] = 'stranger'
    assert remote.client.post('/remote/v1/commands', content=raw, headers=headers).status_code == 404
    assert 'NEVER_AUDIT_THIS_SECRET' not in remote.service.audit.path.read_text()


def test_deep_json_and_encoded_paths_refused(remote):
    raw = b'[' * 1100 + b'0' + b']' * 1100
    assert remote.client.post('/remote/v1/commands', content=raw,
        headers=remote.signed('POST', '/remote/v1/commands', raw)).status_code == 404
    assert remote.client.get('/remote/v1/%73tatus', headers=remote.signed()).status_code == 404


def test_revocation_during_cli_check_is_rechecked(remote, monkeypatch):
    original = remote.service.live
    def live():
        state = original()
        remote.service.pairing.revoke('Phone')
        return state
    monkeypatch.setattr(remote.service, 'live', live)
    with pytest.raises(Denied, match='device_unknown'):
        remote.service.check(remote.service.epoch, remote.device)


def test_note_writer_and_revocation_cannot_invert_locks(remote, monkeypatch):
    from contextlib import contextmanager
    from services import settings_store
    from services.remote import handlers
    note_guard, revoke_guard = threading.Event(), threading.Event()
    outcomes = []

    class TimedLock:
        def __init__(self):
            self.lock = threading.RLock()
        def __enter__(self):
            if not self.lock.acquire(timeout=2):
                raise RuntimeError('Pairing/JSON lock inversion')
        def __exit__(self, *args):
            self.lock.release()
    remote.service.pairing.lock = TimedLock()
    original_save = remote.service.pairing._save
    def save():
        revoke_guard.set()  # revoke holds Pairing and is about to wait for the JSON guard.
        original_save()
    monkeypatch.setattr(remote.service.pairing, '_save', save)

    @contextmanager
    def writer_guard():
        with settings_store.lock:
            note_guard.set()
            assert revoke_guard.wait(3)
            yield
    monkeypatch.setattr(handlers, 'effect_lock', lambda command: writer_guard())
    def write():
        try:
            remote.service.run_effect(remote.device, 'add_note', {'text': 'must not be written'}, remote.service.epoch)
            outcomes.append('written')
        except Denied:
            outcomes.append('refused')
        except Exception as error:
            outcomes.append(type(error).__name__)
    def revoke():
        assert note_guard.wait(3)
        remote.service.revoke('Phone')
        outcomes.append('revoked')
    writer = threading.Thread(target=write, daemon=True)
    revoker = threading.Thread(target=revoke, daemon=True)
    writer.start(); revoker.start()
    writer.join(5); revoker.join(5)
    assert not writer.is_alive() and not revoker.is_alive()
    assert sorted(outcomes) == ['refused', 'revoked']


def test_revoke_literal_name_preserves_punctuation(remote):
    import asyncio
    from services.remote.local import try_command
    remote.service.pairing.devices[remote.device['id']]['name'] = 'Phone!'
    result = asyncio.run(try_command('revoke Phone!'))
    assert result.success and remote.device['id'] not in remote.service.pairing.devices


def test_failed_revoke_save_cannot_restore_queued_authority_after_repair(remote, monkeypatch):
    from services.remote.commands import Command, no_args
    remote.service.pairing.devices[remote.device['id']]['scopes'] = ['safe', 'confirm']
    authorised = remote.service.pairing.get(remote.device['id'])
    epoch = remote.service.epoch
    save = remote.service.pairing._save
    def fail():
        raise OSError('mock publication failure')
    monkeypatch.setattr(remote.service.pairing, '_save', fail)
    with pytest.raises(OSError):
        remote.service.revoke('Phone')
    monkeypatch.setattr(remote.service.pairing, '_save', save)
    grant = remote.service.pairing.issue('https://laptop.example.ts.net')
    new, _ = remote.service.pairing.begin(dict(token=grant['token'], name='Phone', public_key=remote.pem), remote.service.magic_dns)
    remote.service.pairing.activate(new['id'])
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append(True) or {}, 'confirm', no_args)
    with pytest.raises(Denied):
        remote.service.run_effect(authorised, 'lock_pc', {}, epoch, {}, remote.now[0] + 60)
    assert calls == []


def test_immediate_latch_invalidates_owner_enable_before_cleanup(remote):
    epoch, token = remote.service.epoch, remote.service.kill_token
    remote.service.trip()
    with pytest.raises(Denied):
        remote.service.enable(confirmed=True, expected_epoch=epoch, expected_token=token)
    assert remote.service.stopped.is_set() and not remote.service.status()['enabled']


def test_replaced_pairing_cannot_consume_old_laptop_approval(remote):
    _, candidate = new_phone()
    grant = remote.service.pairing.issue('https://laptop.example.ts.net')
    old, _ = remote.service.pairing.begin(dict(token=grant['token'], name='Old name', public_key=candidate['public_key']), remote.service.magic_dns)
    grant = remote.service.pairing.issue('https://laptop.example.ts.net')
    new, _ = remote.service.pairing.begin(dict(token=grant['token'], name='New name', public_key=candidate['public_key']), remote.service.magic_dns)
    with pytest.raises(Denied, match='pairing_replaced'):
        remote.service.pairing.activate(old['id'], expected_pairing=old['pairing_id'])
    remote.service.pairing.discard_pending(old['id'], old['pairing_id'])
    assert remote.service.pairing.pending_device(new['id'])['name'] == 'New name'
    assert remote.service.pairing.activate(new['id'], expected_pairing=new['pairing_id'])['name'] == 'New name'


def test_kill_is_responsive_while_pairing_lookup_waits(remote, monkeypatch):
    entered, off_done = threading.Event(), threading.Event()
    original = remote.service.pairing.get
    observed, replies = [], []
    def read(identity):
        entered.set()
        observed.append(off_done.wait(3))
        return original(identity)
    monkeypatch.setattr(remote.service.pairing, 'get', read)
    def request():
        try:
            replies.append(remote.client.get('/remote/v1/status', headers=remote.signed()).status_code)
        except Exception as error:
            replies.append(type(error).__name__)
    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    assert entered.wait(3)
    try:
        assert remote.client.post('/api/v1/remote/off').json()['enabled'] is False
    finally:
        off_done.set()
    worker.join(5)
    assert not worker.is_alive() and replies == [404] and all(observed)


def test_kill_latch_does_not_wait_for_service_cleanup_lock(remote):
    holding, release = threading.Event(), threading.Event()
    released, result = [], []
    def hold():
        with remote.service.lock:
            holding.set()
            released.append(release.wait(3))
    def stop():
        result.append(remote.client.post('/api/v1/remote/off').status_code)
    holder = threading.Thread(target=hold, daemon=True)
    stopper = threading.Thread(target=stop, daemon=True)
    holder.start()
    assert holding.wait(3)
    stopper.start()
    assert remote.service.stopped.wait(3)
    try:
        assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    finally:
        release.set()
    holder.join(5); stopper.join(5)
    assert released == [True] and result == [200]


@pytest.mark.parametrize('telegram', [False, True])
def test_local_off_latches_before_cognition_logging_without_changing_telegram(remote, monkeypatch, telegram):
    import asyncio
    from types import SimpleNamespace
    from services.mind import cognition
    from services.automation import intent
    def record(*args, **kwargs):
        assert remote.service.enabled.is_set() is telegram
        return 1
    monkeypatch.setattr(cognition.cognition, 'record', record)
    monkeypatch.setattr(cognition.cognition, 'finish', lambda *args: None)
    @cognition.turn('chat')
    async def response(request):
        return SimpleNamespace(response='private', private=True, action_success=True)
    token = intent.remote_request.set(telegram)
    try:
        asyncio.run(response(SimpleNamespace(message='remote off')))
    finally:
        intent.remote_request.reset(token)


def test_off_endpoint_bypasses_optional_cognition_database(remote, monkeypatch, tmp_path):
    import asyncio
    import httpx
    import services.remote
    from core.config import config
    from interfaces.api.app import create_app
    from services.mind.cognition import cognition
    monkeypatch.setattr(config, 'MEMORY_DIR', tmp_path)
    monkeypatch.setattr(services.remote, 'start_bridge', lambda: remote.service)
    def unavailable(*args, **kwargs):
        raise AssertionError('Kill must not wait for cognition logging')
    monkeypatch.setattr(cognition, 'operation', unavailable)
    app = create_app()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('127.0.0.1', 12345)), base_url='http://localhost:8000') as client:
            return await client.post('/api/v1/remote/off')
    response = asyncio.run(run())
    assert response.status_code == 200 and response.json()['enabled'] is False
