import hashlib
import json
import sqlite3
import uuid
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.remote.phone_handoff import store
from services.remote.phone_files import CHUNK, MAX_FILE, PhoneFiles, filename
from services.remote.security import Denied, b64
from services.remote.transport_store import TransportStore
from services.settings_store import save


def send(remote, path, value):
    raw = json.dumps(value, separators=(',', ':')).encode()
    return remote.client.post('/remote/v1/' + path, content=raw,
                              headers=remote.signed('POST', '/remote/v1/' + path, raw))


def scoped(remote):
    remote.service.pairing.devices[remote.device['id']]['scopes'].append('phone_data')
    remote.service.pairing._save()
    save(remote.service.directory / 'companion.json', {'quarantine': str(remote.service.directory / 'received')})


def envelope(remote, command='add_note', args=None, identity=None):
    return dict(id=identity or uuid.uuid4().hex, command=command, args=args or {},
                created=remote.now[0], expires_at=remote.now[0] + 900)


def test_outbox_delivery_ack_scope_expiry(remote):
    data = store(remote.service)
    identity = data.put(remote.device['id'], 'text', dict(text='private handoff'))
    path = '/remote/v1/phone/inbox'
    assert remote.client.get(path, headers=remote.signed(path=path)).status_code == 404
    scoped(remote)
    response = remote.client.get(path, headers=remote.signed(path=path))
    assert response.json()['messages'][0]['id'] == identity
    assert data.inbox(remote.device['id'])[0]['id'] == identity  # No loss before persisted receipt.
    assert data.inbox('other-device') == []
    assert send(remote, 'phone/ack', {'ids': [identity]}).status_code == 200
    assert data.inbox(remote.device['id']) == []
    data.put(remote.device['id'], 'ring', dict(duration=30), ttl=1)
    remote.now[0] += 2
    assert data.inbox(remote.device['id']) == []
    with pytest.raises(Denied):
        data.put(remote.device['id'], 'ring', {}, ttl=86401)
    remote.service.registry.commands.pop('phone_inbox')
    assert remote.client.get(path, headers=remote.signed(path=path)).status_code == 404


def test_queue_at_most_once_and_conflict(remote):
    calls = []
    original = remote.service.registry.get('add_note')
    remote.service.registry.commands['add_note'] = replace(original, handler=lambda s, d, a: calls.append(a['text']) or {'ok': True})
    first = envelope(remote, args={'text': 'one'})
    assert send(remote, 'queue', first).json()['result'] == 'completed'
    assert send(remote, 'queue', first).json()['result'] == 'completed'
    assert calls == ['one']
    assert send(remote, 'queue', dict(first, args={'text': 'changed'})).status_code == 404
    second = envelope(remote, args={'text': 'two'})
    assert send(remote, 'queue', second).status_code == 200
    assert calls == ['one', 'two']
    # A restart after claim but before durable completion is never retried.
    uncertain = envelope(remote, args={'text': 'uncertain'})
    data = store(remote.service)
    assert data.claim(remote.device['id'], uncertain) is None
    assert send(remote, 'queue', uncertain).json()['result'] == 'uncertain'
    assert calls == ['one', 'two']


@pytest.mark.parametrize('command', ['lock_pc', 'sleep_pc', 'send_message', 'delete_note', 'phone_forget', 'ask', 'shell'])
def test_confirm_and_nonqueue_commands_never_queue(remote, command):
    assert send(remote, 'queue', envelope(remote, command)).status_code == 404
    data = store(remote.service)
    with data.db() as db:
        assert db.execute('SELECT count(*) FROM receipts').fetchone()[0] == 0


@pytest.mark.parametrize('mutation', ['expired', 'long', 'future', 'bool', 'changed_risk'])
def test_queue_expiry_and_current_risk(remote, mutation):
    row = envelope(remote, 'start_focus')
    if mutation == 'expired': row['expires_at'] = remote.now[0] - 1
    elif mutation == 'long': row['expires_at'] += 86400
    elif mutation == 'future': row['created'] += 1000
    elif mutation == 'bool': row['created'] = True
    elif mutation == 'changed_risk':
        remote.service.registry.commands['start_focus'] = replace(remote.service.registry.get('start_focus'), risk='confirm')
    assert send(remote, 'queue', row).status_code == 404


@pytest.mark.parametrize('name', ['../x.txt', '/tmp/x.txt', 'C:\\x.txt', 'a/b.txt', 'a\\b.txt', 'x:stream.txt',
                                'a.exe', 'a.EXE.txt', 'a.ps1', 'a.jar', 'a.js', 'a.sh', 'a.py', 'a.url', 'CON.txt', 'a.txt.'])
def test_unsafe_filename(name):
    with pytest.raises(Denied):
        filename(name)


def file_begin(remote, name='notes.txt', content=b'received private file'):
    args = dict(name=name, size=len(content), sha256=hashlib.sha256(content).hexdigest())
    response = send(remote, 'phone/file/begin', args)
    return response, content


def test_file_chunks_quarantine_hash_audit_and_no_search(remote):
    scoped(remote)
    response, content = file_begin(remote)
    identity = response.json()['id']
    assert file_begin(remote)[0].json()['id'] == identity  # Lost begin reply resumes the same upload.
    assert (remote.service.directory / 'received/.nosearch').exists()
    value = dict(id=identity, offset=0, data=b64(content))
    assert send(remote, 'phone/file/chunk', value).json()['offset'] == len(content)
    assert send(remote, 'phone/file/chunk', value).json()['offset'] == len(content)
    final = send(remote, 'phone/file/finish', dict(id=identity)).json()
    assert final['sha256'] == hashlib.sha256(content).hexdigest()
    assert send(remote, 'phone/file/finish', dict(id=identity)).json() == final
    destination = remote.service.directory / 'received' / (identity + '-notes.txt')
    assert destination.read_bytes() == content
    from plugins.semantic_search.documents import blocked_folder
    assert blocked_folder(destination.parent)
    assert any(row['result'] == final['sha256'] for row in remote.service.audit.recent())
    assert 'received private file' not in remote.service.audit.path.read_text()
    phone_files = PhoneFiles(remote.service, store(remote.service))
    phone_files.forget(remote.device['id'])
    assert not destination.exists()


def test_file_invalid_caps_offsets_digest_and_scope(remote):
    assert file_begin(remote)[0].status_code == 404
    scoped(remote)
    for size in (MAX_FILE + 1, -1, True):
        assert send(remote, 'phone/file/begin', dict(name='a.txt', size=size, sha256='a' * 64)).status_code == 404
    response, content = file_begin(remote)
    identity = response.json()['id']
    assert send(remote, 'phone/file/chunk', dict(id=identity, offset=1, data=b64(content))).status_code == 404
    assert send(remote, 'phone/file/finish', dict(id=identity)).status_code == 404
    assert send(remote, 'phone/file/chunk', dict(id=identity, offset=0, data=b64(b'x' * (CHUNK + 1)))).status_code == 404
    assert send(remote, 'phone/file/chunk', dict(id=identity, offset=0, data=b64(b'x' * len(content)))).status_code == 200
    assert send(remote, 'phone/file/finish', dict(id=identity)).status_code == 404


@pytest.mark.parametrize('text', ['https://example.com/path', 'http://example.com', 'file:///C:/secret.txt', 'javascript:alert(1)', 'a note'])
def test_handoff_is_inert_and_history_source(remote, monkeypatch, text):
    import webbrowser
    monkeypatch.setattr(webbrowser, 'open', lambda *a: pytest.fail('Received data must never auto-open'))
    from services.automation.clipboard_history import clipboard_history
    clipboard_history.clear()
    scoped(remote)
    assert send(remote, 'phone/handoff', dict(text=text)).status_code == 200
    assert clipboard_history.entries()[0] == dict(text=text, source='phone')
    link = getattr(remote.service, '_phone_link', None)
    assert bool(link) == text.startswith(('http://', 'https://'))
    clipboard_history.forget_phone()


def test_approval_accept_deny_timeout_replay_and_binding(remote):
    from services.remote import phone_approvals as approvals
    scoped(remote)
    data, device = store(remote.service), remote.device['id']
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    with data.db() as db:
        db.execute('INSERT INTO approval_keys VALUES (?,?)', (device, public))
    data.inbox(device)
    for accepted in (True, False):
        identity = approvals.create(remote.service, 'delete_files', 'Delete reviewed files', {'file': 'one'})
        with data.db() as db:
            row = db.execute('SELECT canonical FROM phone_approvals WHERE id=?', (identity,)).fetchone()
        proof = b64(key.sign((row['canonical'] + '\naccept').encode(), ec.ECDSA(hashes.SHA256()))) if accepted else ''
        body = dict(challenge=identity, accepted=accepted, signature=proof)
        assert send(remote, 'phone/approval/result', body).status_code == 200
        assert send(remote, 'phone/approval/result', body).status_code == 404
        assert approvals.take(remote.service, identity) is accepted
        with pytest.raises(Denied): approvals.take(remote.service, identity)
    identity = approvals.create(remote.service, 'send_message', 'Send reviewed message', {'recipient': 'one'})
    assert send(remote, 'phone/approval/result', dict(challenge=identity, accepted=True, signature=proof)).status_code == 404
    remote.now[0] += 61
    assert approvals.take(remote.service, identity) is None
    assert send(remote, 'phone/approval/result', dict(challenge=identity, accepted=False, signature='')).status_code == 404
    with pytest.raises(Denied): approvals.create(remote.service, 'unlock_windows', 'Unlock', {})


def test_new_endpoints_identity_and_kill_gate(remote):
    scoped(remote)
    path = '/remote/v1/phone/info'
    assert remote.client.get(path).status_code == 404
    assert remote.client.get(path, headers=remote.signed(path=path)).status_code == 200
    remote.service.trip()
    assert send(remote, 'queue', envelope(remote, 'ring_laptop')).status_code == 404
    assert remote.client.get(path, headers=remote.signed(path=path)).status_code == 404


def test_transport_forget_erases_payloads_keeps_dedupe_tombstone(remote):
    data, device = store(remote.service), remote.device['id']
    data.put(device, 'text', {'text': 'private'})
    data.claim(device, envelope(remote, args={'text': 'private'}))
    data.forget(device)
    assert data.inbox(device) == []
    with data.db() as db:
        assert db.execute('SELECT count(*) FROM outbox').fetchone()[0] == 0
        assert db.execute('SELECT state,result FROM receipts').fetchone()['result'] is None


def test_expired_transfer_cannot_read_but_later_forget_still_finds_quarantine(remote):
    scoped(remote)
    response, content = file_begin(remote)
    identity = response.json()['id']
    send(remote, 'phone/file/chunk', dict(id=identity, offset=0, data=b64(content)))
    send(remote, 'phone/file/finish', dict(id=identity))
    remote.now[0] += 86401
    files = PhoneFiles(remote.service, store(remote.service))
    destination = remote.service.directory / 'received' / (identity + '-notes.txt')
    assert destination.exists()
    files.forget(remote.device['id'])
    assert not destination.exists()


def test_waiting_inbox_receives_new_message_and_revalidates_kill_switch(remote):
    from concurrent.futures import ThreadPoolExecutor
    import time
    scoped(remote)
    path = '/remote/v1/phone/inbox'
    headers = remote.signed(path=path)
    data = store(remote.service)
    with ThreadPoolExecutor(1) as executor:
        waiting = executor.submit(remote.client.get, path, headers=headers)
        until = time.monotonic() + 5
        while not data.reachable(remote.device['id']):
            assert time.monotonic() < until
            time.sleep(.01)
        identity = data.put(remote.device['id'], 'text', {'text': 'new note'})
        assert waiting.result(5).json()['messages'][0]['id'] == identity
        data.ack(remote.device['id'], [identity])
        waiting = executor.submit(remote.client.get, path, headers=remote.signed(path=path))
        time.sleep(.1)
        remote.service.trip()
        assert waiting.result(5).status_code == 404


def test_approval_enrollment_requires_laptop_consent_and_invalidates_old_challenges(remote):
    import time
    scoped(remote)
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    data = store(remote.service)
    data.inbox(remote.device['id'])
    with data.db() as db:
        db.execute('INSERT INTO approval_keys VALUES (?,?)', (remote.device['id'], remote.pem))
    from services.remote.phone_approvals import create, take
    pending = create(remote.service, 'send_message', 'Send', {})
    remote.service.confirm = lambda question: False
    assert send(remote, 'phone/approval/enroll', {'public_key': public}).json()['state'] == 'awaiting_laptop'
    time.sleep(.1)
    with data.db() as db:
        assert db.execute('SELECT public_key FROM approval_keys').fetchone()[0] == remote.pem
    remote.service.confirm = lambda question: True
    send(remote, 'phone/approval/enroll', {'public_key': public})
    until = time.monotonic() + 5
    while True:
        with data.db() as db:
            updated = db.execute('SELECT public_key FROM approval_keys').fetchone()[0]
        if updated == public:
            break
        assert time.monotonic() < until
        time.sleep(.01)
    with pytest.raises(Denied):
        take(remote.service, pending)
