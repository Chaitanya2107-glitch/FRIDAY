"""P-256 request proofs, bounded replay windows and device throttling."""
from __future__ import annotations

import base64
from collections import defaultdict, deque
import hashlib
import re
import threading
import time

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


class Denied(ValueError):
    """Internal audit reason; never returned to an unauthorised caller."""


def public_key(pem: str):
    if not isinstance(pem, str) or len(pem) > 2048:
        raise Denied('invalid_key')
    try:
        key = serialization.load_pem_public_key(pem.encode('ascii'))
    except (ValueError, UnicodeError, TypeError, UnsupportedAlgorithm):
        raise Denied('invalid_key') from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise Denied('invalid_key')
    return key


def key_id(pem: str) -> str:
    der = public_key(pem).public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:32]


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def unb64(value: str, limit=8192) -> bytes:
    if not isinstance(value, str) or len(value) > limit:
        raise Denied('invalid_encoding')
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, UnicodeError):
        raise Denied('invalid_encoding') from None


def signing_bytes(method: str, path: str, body: bytes, timestamp: str, nonce: str) -> bytes:
    return '\n'.join((method.upper(), path, hashlib.sha256(body).hexdigest(), timestamp, nonce)).encode('utf-8')


class RequestProofs:
    def __init__(self, notify=lambda message: None, clock=time.time):
        self.clock, self.notify = clock, notify
        self.lock = threading.RLock()
        self.nonces = {}
        self.requests = defaultdict(deque)
        self.failures, self.locked_until = {}, {}

    def verify(self, device: dict, method: str, path: str, body: bytes, headers) -> None:
        now, device_id = self.clock(), device['id']
        with self.lock:
            self.nonces = {k: expiry for k, expiry in self.nonces.items() if expiry > now}
            if self.locked_until.get(device_id, 0) > now:
                raise Denied('device_locked')
            recent = self.requests[device_id]
            while recent and recent[0] <= now - 60:
                recent.popleft()
            if len(recent) >= 30:
                raise Denied('rate_limited')
            recent.append(now)
            timestamp, nonce = headers.get('x-timestamp', ''), headers.get('x-nonce', '')
            if not re.fullmatch(r'[0-9]{1,12}', timestamp) or abs(now - int(timestamp)) > 60:
                raise Denied('timestamp_skew')
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', nonce):
                raise Denied('invalid_nonce')
            if (device_id, nonce) in self.nonces:
                raise Denied('replay')
            try:
                signature = unb64(headers.get('x-signature', ''), 256)
                if len(signature) == 64:  # WebCrypto uses IEEE P1363; Android also supports DER.
                    signature = encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big'))
                public_key(device['public_key']).verify(signature, signing_bytes(method, path, body, timestamp, nonce), ec.ECDSA(hashes.SHA256()))
            except (ValueError, InvalidSignature):
                failures = self.failures.get(device_id, 0) + 1
                self.failures[device_id] = failures
                if failures >= 5:
                    self.locked_until[device_id] = now + 600
                    self.failures[device_id] = 0
                    self.notify('Remote device locked for 10 minutes after five bad signatures.')
                raise Denied('bad_signature') from None
            self.nonces[device_id, nonce] = now + 300

    def forget(self, device_id):
        with self.lock:
            self.requests.pop(device_id, None)
            self.failures.pop(device_id, None)
            self.locked_until.pop(device_id, None)
            self.nonces = {k: v for k, v in self.nonces.items() if k[0] != device_id}
