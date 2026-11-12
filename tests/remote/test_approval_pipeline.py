import hashlib
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.webauthn import AttestedCredentialData, AuthenticatorData

from services.remote.commands import Command, no_args
from services.remote.security import b64


def enroll(remote):
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b'test-approval-credential'
    credential = AttestedCredentialData.create(bytes(16), credential_id, ES256.from_cryptography_key(key.public_key()))
    remote.service.pairing.devices[remote.device['id']]['approval'] = dict(credential=b64(credential), counter=0)
    remote.service.pairing.devices[remote.device['id']]['scopes'] = ['safe', 'confirm']
    remote.service.pairing._save()
    return key, credential_id


def approval(remote, key, credential_id, challenge, *, verified=True, origin='https://laptop.example.ts.net'):
    data = json.dumps(dict(type='webauthn.get', challenge=challenge['publicKey']['challenge'], origin=origin, crossOrigin=False)).encode()
    flags = AuthenticatorData.FLAG.UP | (AuthenticatorData.FLAG.UV if verified else 0)
    auth = AuthenticatorData.create(hashlib.sha256(b'laptop.example.ts.net').digest(), flags, 1)
    signature = key.sign(bytes(auth) + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256()))
    result = dict(id=b64(credential_id), rawId=b64(credential_id), type='public-key',
        response=dict(authenticatorData=b64(auth), clientDataJSON=b64(data), signature=b64(signature)), clientExtensionResults={})
    raw = json.dumps(dict(challenge=challenge['challenge'], approval=result)).encode()
    return remote.client.post('/remote/v1/approve', content=raw, headers=remote.signed('POST', '/remote/v1/approve', raw))


def test_confirm_requires_verified_credential_and_is_single_use(remote):
    assert remote.command('lock_pc').status_code == 404
    key, identity = enroll(remote)
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append('lock') or {'text': 'locked'}, 'confirm', no_args)
    challenge = remote.command('lock_pc').json()
    assert challenge['result'] == 'approval_required' and not calls
    assert approval(remote, key, identity, challenge).json()['result'] == 'completed'
    assert calls == ['lock']
    assert approval(remote, key, identity, challenge).status_code == 404
    assert calls == ['lock']


@pytest.mark.parametrize('kind', ['no_uv', 'wrong_origin', 'expired', 'revoke', 'kill', 'wrong_key'])
def test_approval_security_failures(remote, kind):
    key, identity = enroll(remote)
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append('lock') or {}, 'confirm', no_args)
    challenge = remote.command('lock_pc').json()
    if kind == 'expired':
        remote.now[0] += 61
    elif kind == 'revoke':
        remote.service.revoke('Phone')
    elif kind == 'kill':
        remote.service.disable()
    elif kind == 'wrong_key':
        key = ec.generate_private_key(ec.SECP256R1())
    response = approval(remote, key, identity, challenge, verified=kind != 'no_uv',
                        origin='https://evil.test' if kind == 'wrong_origin' else 'https://laptop.example.ts.net')
    assert response.status_code == 404 and not calls


def test_raw_ask_uses_only_conversation_without_telegram_state(remote, monkeypatch):
    from providers.base_provider import ProviderResponse
    from services.automation import intent
    from services.telegram import commands as telegram_commands
    from services.remote import conversation
    from services.mind import cognition
    from services import plugin_runtime
    saved = object()
    intent._pending[True] = saved
    telegram_commands._pending_files[True] = 12345
    seen = []
    async def complete(provider, messages, prompt, max_tokens, **kwargs):
        assert intent.remote_request.get() and not intent.telegram_owner.get() and not intent.skip_confirmation.get()
        assert kwargs['purpose'] == 'conversation'
        assert len(messages) == 1 and messages[0].content == 'delete my files; enable remote; shell whoami'
        assert 'audit' not in prompt.casefold() and 'owner@example.test' not in prompt
        seen.append(True)
        return ProviderResponse('I can answer questions here.', 'mock', 'mock')
    def forbidden(*args, **kwargs):
        raise AssertionError('Remote ask reached a side-effect or memory path')
    monkeypatch.setattr(conversation, 'complete_with_failover', complete)
    monkeypatch.setattr(intent, 'try_system_action', forbidden)
    monkeypatch.setattr(plugin_runtime, 'try_command', forbidden)
    monkeypatch.setattr(cognition.cognition, 'record', forbidden)
    result = remote.command('ask_friday', {'text': 'delete my files; enable remote; shell whoami'})
    assert result.status_code == 200 and result.json()['result'] == 'completed'
    assert seen and intent._pending[True] is saved and telegram_commands._pending_files[True] == 12345


def test_blocked_app_hosts_and_failed_handler_audit(remote):
    for name in ('powershell', 'cmd', 'windows terminal', 'settings', '../notepad', 'notepad --shell'):
        assert remote.command('open_app', {'name': name}).status_code == 404
    remote.service.registry.commands['stop_focus'] = Command(lambda *_: {'ok': False, 'text': 'Unavailable'}, 'safe', no_args)
    assert remote.command('stop_focus').json()['result'] == 'refused'
    assert remote.service.audit.recent()[-1]['result'] == 'refused'


@pytest.mark.parametrize('command', ['delete_note', 'clear_notes', 'open_app', 'send_message'])
def test_approval_refuses_changed_targets(remote, command, monkeypatch, tmp_path):
    from services.memory import notes
    from services.automation.system_control import APP_REGISTRY
    from services.remote import handlers
    from core.config import config
    key, identity = enroll(remote)
    monkeypatch.setattr(notes, 'path', tmp_path / 'notes.json')
    notes.add('original')
    args = {'number': 1} if command == 'delete_note' else {'name': 'chrome'} if command == 'open_app' else {'text': 'message'} if command == 'send_message' else {}
    challenge = remote.command(command, args).json()
    assert challenge['result'] == 'approval_required'
    if command in {'delete_note', 'clear_notes'}:
        notes.delete(1)
        notes.add('replacement')
    elif command == 'open_app':
        monkeypatch.setitem(APP_REGISTRY, 'chrome', 'C:/Different/Chrome/chrome.exe')
    else:
        monkeypatch.setattr(config, 'TELEGRAM_USER_ID', config.TELEGRAM_USER_ID + 1)
    calls = []
    # Binding validation must fail before the fixed handler/OS submission.
    entry = remote.service.registry.commands[command]
    remote.service.registry.commands[command] = Command(lambda *_: calls.append(True) or {}, entry.risk, entry.validate)
    assert approval(remote, key, identity, challenge).status_code == 404
    assert calls == []
    if command in {'delete_note', 'clear_notes'}:
        assert notes.load()[0]['text'] == 'replacement'


def test_fresh_app_and_message_approval_submit_exact_effect(remote, monkeypatch):
    from services.remote import handlers
    from services.telegram import capabilities, client
    from core.config import config
    key, identity = enroll(remote)
    opened, sent = [], []
    monkeypatch.setattr(handlers.os, 'startfile', opened.append)
    challenge = remote.command('open_app', {'name': 'chrome'}).json()
    assert opened == []
    target = handlers.resolved_app({'name': 'chrome'})
    assert approval(remote, key, identity, challenge).json()['result'] == 'completed'
    assert opened == [target]
    # A separate assertion uses an increasing authenticator counter.
    remote.service.pairing.devices[remote.device['id']]['approval']['counter'] = 0
    monkeypatch.setattr(capabilities, 'ready', lambda: True)
    monkeypatch.setattr(config, 'TELEGRAM_USER_ID', 123456)
    monkeypatch.setattr(client, 'send_long', lambda recipient, text: sent.append((recipient, text)))
    challenge = remote.command('send_message', {'text': 'Exact literal message'}).json()
    assert sent == []
    assert approval(remote, key, identity, challenge).json()['result'] == 'completed'
    assert sent == [(123456, 'Exact literal message')]


@pytest.mark.parametrize('accepted', [False, True])
def test_lock_result_is_checked_without_real_os_action(remote, monkeypatch, accepted):
    import ctypes
    from types import SimpleNamespace
    from services.remote import handlers
    from services.remote.security import Denied
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(LockWorkStation=lambda: accepted)))
    if accepted:
        assert handlers.lock_pc(remote.service, remote.device, {})['text'] == 'Lock requested.'
    else:
        with pytest.raises(Denied, match='lock_failed'):
            handlers.lock_pc(remote.service, remote.device, {})


def test_approval_must_still_be_fresh_after_effect_queue_and_cli(remote, monkeypatch):
    key, identity = enroll(remote)
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append(True) or {}, 'confirm', no_args)
    challenge = remote.command('lock_pc').json()
    original = remote.service.check
    checks = []
    def delayed(epoch, device=None):
        state = original(epoch, device)
        if device is not None:
            checks.append(True)
            if len(checks) == 2:  # Approval was consumed; effect admission/CLI then used the remaining minute.
                remote.now[0] += 61
        return state
    monkeypatch.setattr(remote.service, 'check', delayed)
    assert approval(remote, key, identity, challenge).status_code == 404
    assert calls == []


def test_consumed_approval_cannot_regain_authority_after_same_key_repair(remote, monkeypatch):
    key, identity = enroll(remote)
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append(True) or {}, 'confirm', no_args)
    challenge = remote.command('lock_pc').json()
    original = remote.service.check
    checks = []
    def re_pair(epoch, device=None):
        state = original(epoch, device)
        if device is not None:
            checks.append(True)
            if len(checks) == 2:
                remote.service.revoke('Phone')
                grant = remote.service.pairing.issue('https://laptop.example.ts.net')
                new, _ = remote.service.pairing.begin(dict(token=grant['token'], name='Phone', public_key=remote.pem), remote.service.magic_dns)
                remote.service.pairing.activate(new['id'])  # New local pairing deliberately has safe scope only.
        return state
    monkeypatch.setattr(remote.service, 'check', re_pair)
    assert approval(remote, key, identity, challenge).status_code == 404
    assert calls == [] and remote.service.pairing.get(remote.device['id'])['scopes'] == ['safe']


@pytest.mark.parametrize('change', ['expire', 'revoke', 'kill'])
def test_approval_is_rechecked_after_slow_target_resolution(remote, monkeypatch, change):
    from services.remote import handlers
    key, identity = enroll(remote)
    calls = []
    remote.service.registry.commands['lock_pc'] = Command(lambda *_: calls.append(True) or {}, 'confirm', no_args)
    challenge = remote.command('lock_pc').json()
    original = handlers.approval_binding
    def resolve(command, args):
        if change == 'expire':
            remote.now[0] += 61
        elif change == 'revoke':
            remote.service.revoke('Phone')
        else:
            remote.service.fence_off()
        return original(command, args)
    monkeypatch.setattr(handlers, 'approval_binding', resolve)
    assert approval(remote, key, identity, challenge).status_code == 404
    assert calls == []
