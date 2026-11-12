import hashlib
import json
import threading
import time
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.webauthn import AttestationObject, AttestedCredentialData, AuthenticatorData

from scripts.remote_sign_test import Client
from services.remote.context import remote_origin
from services.remote.security import b64, key_id


def pair_start(remote):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    device = dict(id=key_id(pem), public_key=pem)
    qr = remote.service.pairing.issue('https://laptop.example.ts.net')
    raw = json.dumps(dict(token=qr['token'], name='Passkey phone', public_key=pem)).encode()
    response = remote.client.post('/remote/v1/pair/begin', content=raw,
        headers=remote.signed('POST', '/remote/v1/pair/begin', raw, key=key, device=device))
    assert response.status_code == 200
    return key, device, qr, response.json()


def registration(options, *, verified=True, origin='https://laptop.example.ts.net'):
    key = ec.generate_private_key(ec.SECP256R1())
    identity = b'new-uv-credential'
    credential = AttestedCredentialData.create(bytes(16), identity, ES256.from_cryptography_key(key.public_key()))
    flags = AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.AT | (AuthenticatorData.FLAG.UV if verified else 0)
    data = AuthenticatorData.create(hashlib.sha256(b'laptop.example.ts.net').digest(), flags, 0, credential)
    attestation = AttestationObject.create('none', data, {})
    client = json.dumps(dict(type='webauthn.create', origin=origin, crossOrigin=False, challenge=options['publicKey']['challenge'])).encode()
    return dict(id=b64(identity), rawId=b64(identity), type='public-key',
                response=dict(clientDataJSON=b64(client), attestationObject=b64(attestation)), clientExtensionResults={})


@pytest.mark.parametrize('kind', ['valid', 'no_uv', 'wrong_origin', 'laptop_no'])
def test_real_registration_and_laptop_decision(remote, kind):
    key, device, _, options = pair_start(remote)
    answered = threading.Event()
    def confirm(question):
        answered.set()
        return kind != 'laptop_no'
    remote.service.confirm = confirm
    result = registration(options, verified=kind != 'no_uv',
        origin='https://evil.test' if kind == 'wrong_origin' else 'https://laptop.example.ts.net')
    raw = json.dumps(dict(registration=result)).encode()
    response = remote.client.post('/remote/v1/pair', content=raw,
        headers=remote.signed('POST', '/remote/v1/pair', raw, key=key, device=device))
    if kind in {'no_uv', 'wrong_origin'}:
        assert response.status_code == 404 and not answered.is_set()
    else:
        assert response.status_code == 200 and answered.wait(2)
        for _ in range(100):
            if device['id'] not in remote.service.pairing.pending:
                break
            time.sleep(.01)
        if kind == 'valid':
            active = remote.service.pairing.get(device['id'])
            assert active['approval']['credential'] and active['scopes'] == ['safe', 'confirm']
        else:
            assert device['id'] not in remote.service.pairing.devices


def test_pairing_proof_rejects_tampering(remote):
    identity = remote.device['id']
    proof = remote.service.pairing.proof(identity, 'paired', 'request-nonce')
    response = dict(state='paired', proof=proof)
    client = Client.__new__(Client)
    client.identity = identity
    expected = remote.service.pairing.fingerprint()
    client.verify_server(response, 'request-nonce', expected)
    for nonce, fingerprint in [('wrong-nonce', expected), ('request-nonce', 'sha256:' + '0' * 64)]:
        with pytest.raises(ValueError):
            client.verify_server(response, nonce, fingerprint)
    response['state'] = 'awaiting_laptop'
    with pytest.raises(ValueError):
        client.verify_server(response, 'request-nonce', expected)
    response['state'] = 'paired'
    proof['payload']['device_id'] = 'wrong-device'
    with pytest.raises(ValueError):
        client.verify_server(response, 'request-nonce', expected)
    proof['payload']['device_id'] = identity
    proof['signature'] = b64(b'not a signature')
    with pytest.raises((ValueError, InvalidSignature)):
        client.verify_server(response, 'request-nonce', expected)


def test_unsafe_scene_refusals_do_not_disable_plugin(remote, tmp_path, monkeypatch):
    from scenes_support import make_scenes, put_scene
    from services import plugin_runtime
    host = make_scenes(tmp_path)
    try:
        put_scene(host, name='unsafe', actions=[dict(type='open_app', name='chrome')])
        scene = host.engine.catalog.get('unsafe')
        host.api.settings.set('approved_scenes', {scene['key']: scene['hash']})
        monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: host.manager)
        for name in ('unsafe', 'missing', '../invalid'):
            for _ in range(5):
                response = remote.command('set_scene', {'name': name})
                assert response.status_code == 200 and response.json()['result'] == 'refused'
        assert host.manager.failures == [] and host.desktop.calls == []
        assert remote.service.audit.recent()[-1]['result'] == 'refused'
    finally:
        host.engine.close()
        host.manager.bus.close()


def test_remote_focus_start_stop_and_later_done_cannot_trigger_scene(remote, tmp_path, monkeypatch):
    from datetime import datetime
    from scenes_support import make_scenes, put_scene
    from plugins.focus.timer import Focus
    from services.plugin_api import PluginAPI
    from services import plugin_runtime
    host = make_scenes(tmp_path)
    focus_api = PluginAPI(host.manager, 'focus', tmp_path / 'focus')
    focus = Focus(focus_api, clock=SimpleNamespace(now=lambda: datetime.fromtimestamp(remote.now[0])))
    host.manager.services['focus'] = focus
    host.api.subscribe('*', host.engine.event)
    try:
        put_scene(host, name='unsafe', actions=[dict(type='open_app', name='chrome')],
                  triggers=[dict(type='event', topic='focus.*', auto=True)])
        scene = host.engine.catalog.get('unsafe')
        host.api.settings.set('approved_scenes', {scene['key']: scene['hash']})
        monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: host.manager)
        assert remote.command('start_focus', {'minutes': 1}).json()['result'] == 'completed'
        active = focus.data['active']
        assert active['remote_origin'] and active['owner'] == 'remote'
        # Timer completion occurs without a request ContextVar on this test thread.
        assert not remote_origin.get()
        remote.now[0] += 61
        focus.tick()
        events = host.manager.bus.recent('focus.*') + host.manager.bus.recent('mood.*')
        assert events and all(event['payload'].get('remote_origin') for event in events)
        # Deliver deterministically too; the real subscriber has its own worker.
        for event in events:
            host.engine.event(event)
        assert not host.desktop.calls and not host.engine.active
        assert host.api.settings.get('trigger_slots', {}) == {}
    finally:
        focus.close()
        host.api.stop()
        focus_api.stop()
        host.engine.close()
        host.manager.bus.close()


def test_remote_events_only_reach_explicit_passive_subscribers():
    from services.event_bus import EventBus
    from services.remote.context import origin_scope
    bus = EventBus()
    unsafe, display = threading.Event(), threading.Event()
    bus.subscribe('*', lambda event: unsafe.set(), plugin_id='automatic-action')
    bus.subscribe('*', lambda event: display.set(), plugin_id='passive-display', allow_remote=True)
    try:
        with origin_scope(True):
            event = bus.publish('mood.set', {'mood': 'celebrating'})
        assert event['payload']['remote_origin'] is True
        assert display.wait(2) and not unsafe.wait(.05)
        bus.publish('mood.set', {'mood': 'focused'})
        assert unsafe.wait(2)  # Existing local/Telegram dispatch is preserved.
    finally:
        bus.close()


def test_remote_scene_state_timed_end_and_idle_keep_origin(remote, tmp_path, monkeypatch):
    from scenes_support import make_scenes, put_scene
    from plugins.scenes.engine import Scenes
    from pathlib import Path
    from services import plugin_runtime
    host = make_scenes(tmp_path)
    restored = None
    try:
        put_scene(host, name='remote quiet', actions=[], duration_minutes=1)
        scene = host.engine.catalog.get('remote quiet')
        host.api.settings.set('approved_scenes', {scene['key']: scene['hash']})
        host.engine.triggers.tick = lambda: None  # This regression controls state/expiry, not wall-clock rules.
        monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: host.manager)
        assert remote.command('set_scene', {'name': 'remote quiet'}).json()['result'] == 'completed'
        assert host.engine.active['remote_origin'] is True
        host.clock.value += 61
        host.engine.tick()  # Periodic state and end happen outside the request context.
        host.engine.tick()  # Subsequent idle reconciliation must retain provenance too.
        assert host.engine.active is None and host.engine.remote_events
        events = host.manager.bus.recent('scene.*')
        assert {'scene.started', 'scene.state', 'scene.ended'} <= {event['topic'] for event in events}
        assert all(event['payload'].get('remote_origin') is True for event in events)
        saved = json.loads(host.engine.path.read_text())
        assert saved['active'] is None and saved['remote_origin'] is True
        restored = Scenes(host.api, host.registry, host.desktop,
            Path(__file__).resolve().parents[2] / 'plugins/scenes/defaults', now=lambda: host.clock.value)
        restored.publish_state()
        assert host.manager.bus.recent('scene.state')[-1]['payload']['remote_origin'] is True
        assert restored.request('remote quiet')['ok']  # Explicit local control establishes a new local state.
        assert not restored.remote_events
        assert not host.manager.bus.recent('scene.started')[-1]['payload'].get('remote_origin')
    finally:
        if restored:
            restored.close()
        host.engine.close()
        host.manager.bus.close()


def test_remote_scene_recovery_card_keeps_origin(remote, tmp_path, monkeypatch):
    from scenes_support import make_scenes, put_scene
    from plugins.scenes.engine import Scenes
    from pathlib import Path
    from services import plugin_runtime, settings_store
    host = make_scenes(tmp_path)
    recovered = None
    try:
        put_scene(host, name='remote quiet', actions=[])
        scene = host.engine.catalog.get('remote quiet')
        host.api.settings.set('approved_scenes', {scene['key']: scene['hash']})
        monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: host.manager)
        assert remote.command('set_scene', {'name': 'remote quiet'}).json()['result'] == 'completed'
        saved = json.loads(host.engine.path.read_text())
        saved['active']['epoch'] = 'previous-process'
        settings_store.save(host.engine.path, saved)
        recovered = Scenes(host.api, host.registry, host.desktop,
            Path(__file__).resolve().parents[2] / 'plugins/scenes/defaults', now=lambda: host.clock.value)
        assert recovered.needs_recovery
        recovered.offer_recovery()
        assert host.manager.bus.recent('ui.card')[-1]['payload']['remote_origin'] is True
    finally:
        if recovered:
            recovered.close()
        host.engine.close()
        host.manager.bus.close()


def test_scene_start_does_not_hold_json_guard_while_waiting_for_focus(remote, monkeypatch):
    from services import plugin_runtime, settings_store
    from services.remote import handlers
    focus_lock = threading.RLock()
    start, focus_owned = threading.Event(), threading.Event()
    observed = []
    def timer_writer():
        assert start.wait(3)
        with focus_lock:
            focus_owned.set()
            acquired = settings_store.lock.acquire(timeout=2)
            observed.append(acquired)
            if acquired:
                settings_store.lock.release()
    def begin(scene):
        start.set()
        assert focus_owned.wait(3)
        with focus_lock:
            return {'ok': True}
    scene = {'key': 'safe', 'hash': 'reviewed'}
    scenes = SimpleNamespace(lock=threading.RLock(), ensure_active=lambda: None, needs_recovery=False,
        pending=None, active=None, _start=begin,
        api=SimpleNamespace(settings=SimpleNamespace(get=lambda *args: {'safe': 'reviewed'})),
        catalog=SimpleNamespace(get=lambda name: scene, actions=lambda scene: [{'type': 'start_focus', 'minutes': 1}]))
    manager = SimpleNamespace(get_service=lambda name: scenes, invoke=lambda api, fn: fn())
    monkeypatch.setattr(plugin_runtime, 'current_manager', lambda: manager)
    writer = threading.Thread(target=timer_writer, daemon=True)
    writer.start()
    assert handlers.set_scene(remote.service, remote.device, {'name': 'safe'})['ok']
    writer.join(5)
    assert not writer.is_alive() and observed == [True]


def test_pairing_copy_uses_private_clipboard(monkeypatch):
    from services.remote import desktop
    from services.automation import clipboard
    calls = []
    monkeypatch.setattr(clipboard, 'set_text', lambda text, **kwargs: calls.append((text, kwargs)))
    assert desktop.copy_pairing('one-time test data')
    assert calls == [('one-time test data', {'private': True})]
    def busy(*args, **kwargs):
        raise clipboard.ClipboardError('busy')
    monkeypatch.setattr(clipboard, 'set_text', busy)
    assert not desktop.copy_pairing('one-time test data')


@pytest.mark.parametrize('accepted', [False, True])
def test_capture_protection_uses_top_level_exclusion(monkeypatch, accepted):
    from unittest.mock import Mock
    from services.remote import desktop
    calls = []
    def ancestor(hwnd, kind):
        calls.append(('root', hwnd, kind))
        return 456
    def affinity(hwnd, flags):
        calls.append(('capture', hwnd, flags))
        return accepted
    monkeypatch.setattr(desktop.ctypes, 'WinDLL', lambda *args, **kwargs: SimpleNamespace(
        GetAncestor=ancestor, SetWindowDisplayAffinity=affinity))
    root = Mock()
    root.winfo_id.return_value = 123
    assert desktop.protect(root) is accepted
    assert calls == [('root', 123, 2), ('capture', 456, 0x11)]


def test_consent_never_reveals_data_if_capture_protection_fails(monkeypatch):
    from unittest.mock import Mock
    import tkinter as tk
    from services.remote import desktop
    root, widget = Mock(), Mock()
    monkeypatch.setattr(tk, 'Tk', lambda: root)
    for name in ('Label', 'Frame', 'Button'):
        monkeypatch.setattr(tk, name, lambda *args, **kwargs: widget)
    monkeypatch.setattr(desktop, 'protect', lambda window: False)
    notices = []
    monkeypatch.setattr(desktop, 'notify', notices.append)
    assert desktop.confirm('Private pairing details') is False
    root.withdraw.assert_called_once()
    root.deiconify.assert_not_called()
    root.mainloop.assert_not_called()
    assert root.destroy.called and notices and 'Private pairing details' not in notices[0]
