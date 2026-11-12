"""One-time local pairing grants and atomically published public device keys."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import socket
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from services.settings_store import publish, save
from .approval import registration_begin
from .security import Denied, b64, key_id, public_key


def device_input(body):
    name, pem = body.get('name'), body.get('public_key')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(not c.isprintable() for c in name):
        raise Denied('invalid_device')
    key = public_key(pem)
    pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode('ascii')
    return dict(id=key_id(pem), name=name.strip(), public_key=pem)


class Pairing:
    def __init__(self, directory: Path, clock=time.time):
        self.directory = Path(directory).absolute()
        self.path = self.directory / 'devices.json'
        self.clock, self.lock = clock, threading.RLock()
        self.devices, self.pending, self.grant = {}, {}, None
        self.error = False
        try:
            if self.path.exists():
                if self.path.stat().st_size > 512 * 1024:
                    raise ValueError()
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if value.get('version') != 1 or not isinstance(value.get('devices'), list) or len(value['devices']) > 64:
                    raise ValueError()
                for row in value['devices']:
                    checked = device_input(row)
                    if (row.get('id') != checked['id'] or row['id'] in self.devices
                            or not isinstance(row.get('created'), (int, float))
                            or not isinstance(row.get('last_seen'), (int, float))
                            or not isinstance(row.get('scopes'), list)
                            or any(scope not in {'safe', 'confirm'} for scope in row['scopes'])):
                        raise ValueError()
                    self.devices[row['id']] = row
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.devices, self.error = {}, True  # Preserve unreadable records; never repair by overwriting.

    def _save(self):
        if self.error:
            raise Denied('devices_unavailable')
        save(self.path, dict(version=1, devices=list(self.devices.values())))

    def fingerprint(self):
        with self.lock:
            path = self.directory / 'server-key.pem'
            if path.exists():
                key = serialization.load_pem_private_key(path.read_bytes(), password=None)
                if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                    raise Denied('server_key_invalid')
            else:
                key = ec.generate_private_key(ec.SECP256R1())
                publish(path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            return 'sha256:' + hashlib.sha256(der).hexdigest()

    def issue(self, url):
        with self.lock:
            if self.error:
                raise Denied('devices_unavailable')
            token = secrets.token_urlsafe(32)
            self.grant = dict(digest=hashlib.sha256(token.encode()).digest(), expires=self.clock() + 120)
            return dict(url=url, token=token, laptop=socket.gethostname(), fingerprint=self.fingerprint(),
                        expires=self.grant['expires'], signing_prefix='/remote')

    def proof(self, identity, phase, nonce):
        with self.lock:
            self.fingerprint()
            key = serialization.load_pem_private_key((self.directory / 'server-key.pem').read_bytes(), password=None)
            payload = dict(device_id=identity, state=phase, nonce=nonce)
            encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
            return dict(payload=payload, public_key=key.public_key().public_bytes(serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo).decode('ascii'),
                        signature=b64(key.sign(encoded, ec.ECDSA(hashes.SHA256()))))

    def check_token(self, token):
        if not isinstance(token, str) or len(token) > 128:
            raise Denied('pairing_token')
        with self.lock:
            if not self.grant or self.clock() >= self.grant['expires'] or not hmac.compare_digest(
                    self.grant['digest'], hashlib.sha256(token.encode()).digest()):
                raise Denied('pairing_token')

    def begin(self, body, dns, *, passkey=False):
        candidate = device_input(body)
        with self.lock:
            self.check_token(body.get('token'))
            self.pending = {key: row for key, row in self.pending.items() if row['expires'] > self.clock()}
            if len(self.pending) >= 8 or len(self.devices) >= 64 or candidate['id'] in self.devices:
                raise Denied('pairing_limit')
            self.grant = None  # Consume before any prompt; a rejected pairing also burns the token.
            row = dict(**candidate, created=self.clock(), last_seen=0, scopes=['safe', 'confirm'],
                       expires=self.clock() + 120, phase='ready', pairing_id=secrets.token_hex(16))
            options, state = registration_begin(dns, row) if passkey else ({}, None)
            row['registration_state'] = state
            self.pending[row['id']] = row
            return copy.deepcopy(row), options

    def pending_device(self, identity):
        with self.lock:
            row = self.pending.get(identity)
            if not row or self.clock() >= row['expires']:
                raise Denied('pairing_expired')
            return copy.deepcopy(row)

    def get(self, identity):
        with self.lock:
            if self.error or identity not in self.devices:
                raise Denied('device_unknown')
            return copy.deepcopy(self.devices[identity])

    def activate(self, identity, approval=None, *, expected_pairing=None):
        with self.lock:
            row = self.pending_device(identity)
            if expected_pairing is not None and row['pairing_id'] != expected_pairing:
                raise Denied('pairing_replaced')
            device = {key: row[key] for key in ('id', 'name', 'public_key', 'created', 'last_seen', 'scopes')}
            if approval:
                device['approval'] = approval
            else:
                device['scopes'] = ['safe']
            previous = dict(self.devices)
            self.devices[identity] = device
            try:
                self._save()
            except OSError:
                self.devices = previous
                raise
            self.pending.pop(identity, None)
            return copy.deepcopy(device)

    def discard_pending(self, identity, expected_pairing):
        with self.lock:
            row = self.pending.get(identity)
            if row and row['pairing_id'] == expected_pairing:
                self.pending.pop(identity, None)

    def seen(self, identity, counter=None):
        with self.lock:
            self.get(identity)
            self.devices[identity]['last_seen'] = self.clock()
            if counter is not None:
                self.devices[identity]['approval']['counter'] = counter
            self._save()

    def revoke(self, name):
        with self.lock:
            matches = [row for row in self.devices.values() if row['name'].casefold() == name.casefold() or row['id'] == name]
            if len(matches) != 1:
                raise Denied('device_name_ambiguous')
            identity = matches[0]['id']
            self.devices.pop(identity)  # Runtime revocation wins even if publication fails.
            self.pending.pop(identity, None)
            self._save()
            return identity

    def cancel(self):
        with self.lock:
            self.grant = None
            self.pending.clear()

    def list(self):
        with self.lock:
            if self.error:
                raise Denied('devices_unavailable')
            return copy.deepcopy(list(self.devices.values()))
