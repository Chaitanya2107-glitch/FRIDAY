import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from services.remote.security import Denied, b64, unb64


def test_signature_body_method_and_path_are_bound(remote):
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 200
    raw = b'{"command":"status"}'
    headers = remote.signed('POST', '/remote/v1/commands', raw)
    assert remote.client.post('/remote/v1/commands', content=raw + b' ', headers=headers).status_code == 404
    assert remote.client.post('/remote/v1/commands', content=raw, headers=remote.signed()).status_code == 404
    assert remote.client.get('/remote/v1/status', headers=remote.signed(path='/remote/v1/pair/status')).status_code == 404


def test_webcrypto_raw_signature_supported(remote):
    headers = remote.signed()
    r, s = decode_dss_signature(unb64(headers['X-Signature']))
    headers['X-Signature'] = b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    assert remote.client.get('/remote/v1/status', headers=headers).status_code == 200


def test_replay_and_timestamp_skew(remote):
    headers = remote.signed()
    assert remote.client.get('/remote/v1/status', headers=headers).status_code == 200
    assert remote.client.get('/remote/v1/status', headers=headers).status_code == 404
    for offset in (-61, 61):
        assert remote.client.get('/remote/v1/status', headers=remote.signed(timestamp=int(remote.now[0]) + offset)).status_code == 404
    assert remote.client.get('/remote/v1/status', headers=remote.signed(timestamp=int(remote.now[0]) - 60)).status_code == 200


def test_nonce_claim_is_atomic(remote):
    headers = {k.lower(): v for k, v in remote.signed().items()}
    def attempt(_):
        try:
            remote.service.proofs.verify(remote.device, 'GET', '/remote/v1/status', b'', headers)
            return True
        except Denied:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 1


def test_five_bad_signatures_lock_and_notify(remote):
    bad = ec.generate_private_key(ec.SECP256R1())
    for _ in range(5):
        assert remote.client.get('/remote/v1/status', headers=remote.signed(key=bad)).status_code == 404
    assert remote.notices and '10 minutes' in remote.notices[-1]
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    remote.now[0] += 601
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 200


def test_device_rate_limit(remote):
    for _ in range(30):
        assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 200
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    remote.now[0] += 61
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 200


@pytest.mark.parametrize('field,value', [('Host', 'evil.test'), ('Tailscale-User-Login', 'stranger@example.test'), ('Origin', 'https://evil.test')])
def test_identity_gate_and_generic_refusal(remote, field, value):
    headers = remote.signed()
    headers[field] = value
    response = remote.client.get('/remote/v1/status', headers=headers)
    assert response.status_code == 404 and response.json() == {'detail': 'Not Found'}
    assert remote.service.audit.recent()[-1]['result'] == ('identity_refused' if field != 'Origin' else 'origin_refused')


def test_duplicate_headers_queries_body_cap_and_proxy_escape(remote):
    headers = list(remote.signed().items()) + [('X-Device-Id', remote.device['id'])]
    assert remote.client.get('/remote/v1/status', headers=headers).status_code == 404
    assert remote.client.get('/remote/v1/status?token=secret', headers=remote.signed()).status_code == 404
    raw = b'x' * 16385
    assert remote.client.post('/remote/v1/commands', content=raw, headers=remote.signed('POST', '/remote/v1/commands', raw)).status_code == 404
    assert remote.client.post('/api/v1/chat', headers={'Tailscale-User-Login': 'owner@example.test'}).status_code == 404
    assert remote.client.post('/api/v1/chat', headers={'X-Forwarded-For': '100.64.1.1'}).status_code == 404
    assert remote.client.post('/api/v1/chat').status_code == 200


def test_funnel_and_cli_failure_refuse(remote):
    remote.cli.funnel = True
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    assert not remote.service.enabled.is_set()
    assert 'FUNNEL' in remote.service.warning and remote.notices
    assert all(call[:2] == ['funnel', 'status'] for call in remote.cli.calls if call[0] == 'funnel')


def test_cli_failure_refuses_while_enabled(remote):
    remote.cli.error = True
    assert remote.service.enabled.is_set()
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    assert remote.service.audit.recent()[-1]['result'] == 'tailscale_unavailable'


@pytest.mark.parametrize('stdout', ['not-json', '{"state":"on"}', '{"AllowFunnel":{"laptop:443":"unknown"}}'])
def test_unknown_funnel_state_refuses(remote, stdout):
    from types import SimpleNamespace
    original = remote.cli.run
    def run(args, **kwargs):
        if args[1:3] == ['funnel', 'status']:
            return SimpleNamespace(returncode=0, stdout=stdout)
        return original(args, **kwargs)
    remote.service.tailscale.runner = run
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404


def test_off_endpoint_fences_before_worker_is_queued(remote, monkeypatch):
    import asyncio
    original = asyncio.to_thread
    async def queued(function, *args, **kwargs):
        if getattr(function, '__self__', None) is remote.service and getattr(function, '__name__', '') == 'disable':
            assert remote.service.stopped.is_set() and not remote.service.enabled.is_set()
            return {'enabled': False, 'serve_reset': False}
        return await original(function, *args, **kwargs)
    monkeypatch.setattr(asyncio, 'to_thread', queued)
    assert remote.client.post('/api/v1/remote/off').status_code == 200
    assert not remote.service.status()['enabled']


def test_revoke_and_kill_are_immediate(remote):
    remote.service.revoke('Phone')
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    assert remote.client.post('/api/v1/remote/off').json()['enabled'] is False
    assert ['serve', 'reset'] in remote.cli.calls
    assert not remote.service.enabled.is_set()
    assert remote.service.pairing.grant is None and not remote.service.approvals.pending


def test_unknown_and_blocked_commands(remote):
    for command in ('unknown', 'shell', 'exec', 'read_file', 'install', 'change_pairing', 'disable_kill_switch'):
        assert remote.command(command).status_code == 404
    row = remote.service.audit.recent()[-1]
    assert row['risk'] == 'blocked'
    assert remote.command('status').json()['result'] == 'completed'


def test_audit_failure_latches_off_without_repeated_notices(remote, monkeypatch):
    token = remote.service.kill_token
    def unavailable(**kwargs):
        raise OSError('mock audit failure')
    monkeypatch.setattr(remote.service.audit, 'write', unavailable)
    remote.client.get('/remote/v1/status', headers=remote.signed())
    assert remote.service.stopped.is_set() and not remote.service.enabled.is_set()
    assert remote.service.kill_token is not token and 'audit' in remote.service.warning
    assert remote.client.get('/remote/v1/status', headers=remote.signed()).status_code == 404
    assert len(remote.notices) == 1
