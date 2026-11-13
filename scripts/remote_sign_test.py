"""Pair a software test device and send signed requests, without an Android app.

Run from the repository: venv/Scripts/python.exe scripts/remote_sign_test.py --pair --local
The pairing JSON is read with hidden input. No token, private key, or request text is logged.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from services.remote.security import b64, key_id, public_key, signing_bytes, unb64
from services.settings_store import publish

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, url, key, owner_login=None):
        parsed = urlsplit(url)
        local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
        if (parsed.username or parsed.password or parsed.query or parsed.fragment
                or (local and (parsed.scheme != 'http' or parsed.path != '/remote'))
                or (not local and (parsed.scheme != 'https' or not parsed.hostname
                                   or not parsed.hostname.endswith('.ts.net') or parsed.path not in {'', '/'}
                                   or parsed.port not in {None, 443}))):
            raise ValueError('Use a Tailscale HTTPS URL, or http://localhost:<port>/remote with --local.')
        self.url, self.key = url.rstrip('/'), key
        self.pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode('ascii')
        self.identity, self.owner_login = key_id(self.pem), owner_login if local else None
        self.http = httpx.Client(timeout=45, trust_env=False, follow_redirects=False)

    def request(self, method, path, body=None):
        raw = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode() if body is not None else b''
        timestamp, nonce = str(int(time.time())), secrets.token_urlsafe(24)
        signature = self.key.sign(signing_bytes(method, '/remote' + path, raw, timestamp, nonce), ec.ECDSA(hashes.SHA256()))
        headers = {'X-Device-Id': self.identity, 'X-Timestamp': timestamp, 'X-Nonce': nonce,
                   'X-Signature': b64(signature), 'Content-Type': 'application/json'}
        if self.owner_login:
            headers['Tailscale-User-Login'] = self.owner_login
        response = self.http.request(method, self.url + path, content=raw, headers=headers)
        if response.status_code != 200:
            raise ValueError(f'Request refused (HTTP {response.status_code}). Check remote enable, identity, pairing and freshness.')
        return response.json(), nonce

    def verify_server(self, response, nonce, expected):
        proof = response['proof']
        key = public_key(proof['public_key'])
        der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if 'sha256:' + hashlib.sha256(der).hexdigest() != expected:
            raise ValueError('Server fingerprint differs from the laptop QR.')
        payload = proof['payload']
        if (payload['nonce'] != nonce or payload['device_id'] != self.identity
                or payload['state'] != response.get('state', 'registration')):
            raise ValueError('Server response does not match this request.')
        key.verify(unb64(proof['signature']), json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), ec.ECDSA(hashes.SHA256()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair', action='store_true')
    parser.add_argument('--pair-json', type=Path, help='Local file containing the laptop QR JSON; otherwise paste with hidden input.')
    parser.add_argument('--local', action='store_true', help='Test the loopback bridge, supplying its saved owner header locally.')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--url', help='https://<laptop>.<tailnet>.ts.net')
    parser.add_argument('--key', type=Path, default=ROOT / 'memory/remote/test-phone.pem')
    parser.add_argument('--name', default='Signed test phone')
    parser.add_argument('--command', default='status')
    parser.add_argument('--args-json', type=Path, help='JSON arguments file, e.g. {"minutes":25}.')
    options = parser.parse_args()
    qr = None
    if options.pair:
        qr = json.loads(options.pair_json.read_text(encoding='utf-8') if options.pair_json else getpass.getpass('Paste laptop pairing JSON (hidden): '))
        if time.time() >= qr['expires']:
            raise ValueError('Pairing token has expired. Say pair my phone at the laptop again.')
    setup_path = ROOT / 'memory/remote/setup.json'
    setup = json.loads(setup_path.read_text(encoding='utf-8')) if setup_path.exists() else {}
    url = f'http://localhost:{options.port}/remote' if options.local else options.url or (qr or {}).get('url') or 'https://' + setup.get('magic_dns', '')
    if options.key.exists():
        key = serialization.load_pem_private_key(options.key.read_bytes(), password=None)
    else:
        if not options.pair:
            raise ValueError('No test key. Pair first with --pair.')
        key = ec.generate_private_key(ec.SECP256R1())
        publish(options.key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    client = Client(url, key, setup.get('owner_login') if options.local else None)
    try:
        if qr:
            pin = getpass.getpass('Set a 6-digit approval PIN (hidden): ')
            if len(pin) != 6 or not pin.isascii() or not pin.isdigit():
                raise ValueError('PIN must have exactly six digits.')
            response, nonce = client.request('POST', '/v1/pair', {'token': qr['token'], 'name': options.name, 'public_key': client.pem, 'pin': pin})
            pin = None
            client.verify_server(response, nonce, qr['fingerprint'])
            print('Approve the pairing prompt on the laptop. Confirm-risk commands require the approval PIN.')
            deadline = min(time.time() + 120, qr['expires'])
            while time.time() < deadline:
                response, nonce = client.request('GET', '/v1/pair/status')
                client.verify_server(response, nonce, qr['fingerprint'])
                if response['state'] == 'paired':
                    print('Paired.')
                    break
                time.sleep(4)
            else:
                raise ValueError('Laptop pairing approval expired.')
        args = json.loads(options.args_json.read_text(encoding='utf-8')) if options.args_json else {}
        response, _ = client.request('GET', '/v1/status') if options.command == 'status' else client.request(
            'POST', '/v1/commands', dict(command=options.command, args=args))
        print(json.dumps(response, indent=2, ensure_ascii=False))
    finally:
        client.http.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, InvalidSignature, httpx.HTTPError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
