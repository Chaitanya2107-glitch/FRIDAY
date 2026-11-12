import json
import secrets
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.remote.routes import BridgeSecurity, create_router, local_router
from services.remote.security import b64, signing_bytes
from services.remote.service import RemoteService
from services.remote.tailscale import Tailscale


class CLI:
    def __init__(self):
        self.funnel, self.serving, self.error = False, True, False
        self.calls = []

    def run(self, args, **kwargs):
        self.calls.append(args[1:])
        if self.error:
            raise OSError('Mock unavailable')
        command = args[1:]
        if command == ['status', '--json']:
            result = {'BackendState': 'Running', 'Self': {'UserID': 1, 'DNSName': 'laptop.example.ts.net.'},
                      'User': {'1': {'LoginName': 'owner@example.test'}}, 'CurrentTailnet': {'Name': 'example.test'}}
        elif command[:2] in (['serve', 'status'], ['funnel', 'status']):
            result = {'Web': {'laptop.example.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8000/remote'}}}},
                      'AllowFunnel': {'laptop.example.ts.net:443': self.funnel}} if self.serving else {}
        elif command == ['serve', '--help']:
            return SimpleNamespace(returncode=0, stdout='--bg --https --set-path')
        elif command == ['serve', 'reset']:
            self.serving = self.funnel = False
            result = {}
        else:
            assert command == ['serve', '--bg', '--https=443', '--set-path=/', 'http://127.0.0.1:8000/remote']
            self.serving = True
            result = {}
        return SimpleNamespace(returncode=0, stdout=json.dumps(result))


@pytest.fixture
def remote(tmp_path, monkeypatch):
    now = [1800000000.0]
    cli, notices = CLI(), []
    service = RemoteService(tmp_path / 'remote', 8000, tailscale=Tailscale('tailscale-mock', cli.run),
                            clock=lambda: now[0], confirm=lambda question: True, notify=notices.append,
                            bound_addresses=lambda: ['127.0.0.1'])
    service.register('127.0.0.1')
    service.enable(confirmed=True)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    grant = service.pairing.issue('https://laptop.example.ts.net')
    device, _ = service.pairing.begin({'token': grant['token'], 'name': 'Phone', 'public_key': pem}, service.magic_dns)
    device = service.pairing.activate(device['id'])
    app = FastAPI()
    app.include_router(create_router(service))
    app.include_router(local_router(service))

    @app.post('/api/v1/chat')
    def local_chat():
        return {'local': True}

    app.add_middleware(BridgeSecurity, service=service, allowed_hosts=['localhost', '127.0.0.1'])
    import services.remote
    monkeypatch.setattr(services.remote, '_service', service)
    with TestClient(app, base_url='http://localhost:8000', client=('127.0.0.1', 50000)) as client:
        fixture = SimpleNamespace(service=service, key=key, device=device, now=now, cli=cli, notices=notices,
                                  app=app, client=client, pem=pem)

        def signed(method='GET', path='/remote/v1/status', body=b'', *, key=key, device=device, nonce=None, timestamp=None):
            timestamp = str(int(now[0])) if timestamp is None else str(timestamp)
            nonce = nonce or secrets.token_urlsafe(24)
            signature = key.sign(signing_bytes(method, path, body, timestamp, nonce), ec.ECDSA(hashes.SHA256()))
            return {'Tailscale-User-Login': 'owner@example.test', 'X-Device-Id': device['id'],
                    'X-Timestamp': timestamp, 'X-Nonce': nonce, 'X-Signature': b64(signature), 'Content-Type': 'application/json'}

        def command(identity, args=None):
            raw = json.dumps(dict(command=identity, args=args or {}), separators=(',', ':')).encode()
            return client.post('/remote/v1/commands', content=raw, headers=signed('POST', '/remote/v1/commands', raw))
        fixture.signed, fixture.command = signed, command
        yield fixture
