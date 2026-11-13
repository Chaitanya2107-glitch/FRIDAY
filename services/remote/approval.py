"""WebAuthn ES256 approvals: verified biometric/PIN, exact origin and one command."""
import json
import secrets
import threading
import time

from fido2.server import Fido2Server
from fido2.webauthn import (AttestedCredentialData, AuthenticationResponse,
                            PublicKeyCredentialParameters, RegistrationResponse)

from .security import Denied, b64, unb64


def server(dns):
    value = Fido2Server({'id': dns, 'name': 'FRIDAY Remote'},
                        verify_origin=lambda origin: origin == 'https://' + dns)
    value.allowed_algorithms = [PublicKeyCredentialParameters(type='public-key', alg=-7)]
    value.timeout = 60000
    return value


def no_cross_origin(client_data):
    if json.loads(client_data).get('crossOrigin', False) is not False:
        raise Denied('cross_origin_approval')


def registration_begin(dns, device):
    options, state = server(dns).register_begin(
        {'id': bytes.fromhex(device['id']), 'name': device['id'], 'displayName': device['name']},
        user_verification='required', authenticator_attachment='platform')
    return dict(options), state


def registration_complete(dns, state, response):
    try:
        value = RegistrationResponse.from_dict(response)
        no_cross_origin(value.response.client_data)
        data = server(dns).register_complete(state, value)
        if data.credential_data.public_key.get(3) != -7:
            raise Denied('approval_algorithm')
        return dict(credential=b64(bytes(data.credential_data)), counter=data.counter)
    except (ValueError, TypeError, KeyError, AssertionError):
        raise Denied('invalid_registration') from None


class Approvals:
    def __init__(self, clock=time.time):
        self.clock, self.pending = clock, {}
        self.lock = threading.RLock()

    def clear(self):
        with self.lock:
            self.pending.clear()

    def create(self, dns, device, command, args, epoch, binding=None):
        credential = device.get('approval', {}).get('credential')
        if not credential and not device.get('pin'):
            raise Denied('user_verification_unavailable')
        options, state = ({}, None)
        if credential:
            options, state = server(dns).authenticate_begin(
                [AttestedCredentialData(unb64(credential))], user_verification='required')
        with self.lock:
            self.pending = {key: row for key, row in self.pending.items()
                            if row['expires'] > self.clock() and row['device'] != device['id']}
            identity = secrets.token_urlsafe(24)
            self.pending[identity] = dict(device=device['id'], command=command,
                args=json.loads(json.dumps(args, allow_nan=False)), epoch=epoch, state=state,
                dns=dns, expires=self.clock() + 60, binding=binding or {})
        return dict(challenge=identity, expires_in=60, command=command, args=args,
                    pin_required=bool(device.get('pin')), **dict(options))

    def consume(self, identity, device, response, epoch, pairing=None):
        with self.lock:
            row = self.pending.pop(identity, None)
        if not row or row['device'] != device['id'] or row['epoch'] != epoch or self.clock() >= row['expires']:
            raise Denied('approval_expired')
        if device.get('pin'):
            from .commands import fields
            from .pin import verify_pin
            fields(response, ('pin',))
            verify_pin(pairing, device['id'], response['pin'])
            return row, None
        try:
            value = AuthenticationResponse.from_dict(response)
            no_cross_origin(value.response.client_data)
            credential = AttestedCredentialData(unb64(device['approval']['credential']))
            server(row['dns']).authenticate_complete(row['state'], [credential], value)
            counter = value.response.authenticator_data.counter
            old = device['approval'].get('counter', 0)
            if (old or counter) and counter <= old:
                raise Denied('approval_counter')
        except (ValueError, TypeError, KeyError):
            raise Denied('invalid_approval') from None
        return row, counter
