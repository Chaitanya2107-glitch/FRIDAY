"""Per-device scrypt PINs. Attempts and lockouts survive a laptop restart."""
import hashlib
import hmac
import re
import secrets

from .security import Denied


def pin_record(pin):
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{6}', pin):
        raise Denied('invalid_pin')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode('ascii'), salt=salt, n=16384, r=8, p=1)
    return dict(salt=salt.hex(), digest=digest.hex(), failures=0, locked_until=0)


def verify_pin(pairing, identity, pin):
    with pairing.lock:
        device = pairing.get(identity)
        row = device.get('pin')
        if not row:
            raise Denied('pin_unavailable')
        now = pairing.clock()
        if row['locked_until'] > now:
            raise Denied('pin_locked')
        valid = isinstance(pin, str) and re.fullmatch(r'[0-9]{6}', pin)
        digest = hashlib.scrypt((pin if valid else 'invalid').encode('ascii'),
                                salt=bytes.fromhex(row['salt']), n=16384, r=8, p=1)
        accepted = bool(valid and hmac.compare_digest(digest.hex(), row['digest']))
        row['failures'] = 0 if accepted else row['failures'] + 1
        if row['failures'] >= 3:
            row.update(failures=0, locked_until=now + 600)
        pairing.devices[identity]['pin'] = row
        pairing._save()  # A failed persistence write must never authorize an effect.
        if not accepted:
            raise Denied('pin_incorrect')
