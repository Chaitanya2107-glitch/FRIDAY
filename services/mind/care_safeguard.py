"""Reviewable first-person phrases and a local, text-free pause for automatic nudges."""
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from core.config import config
from services import settings_store

PATTERNS = (
    'i want to die', 'i wish i were dead', 'i wish i was dead',
    'i do not want to live anymore', 'i want to end my life',
    'i want to kill myself', 'i am going to kill myself',
    'i am thinking about suicide', 'i am thinking of suicide', 'i am suicidal',
    'i have been thinking about killing myself', 'i feel like ending my life',
    'i want to hurt myself', 'i might hurt myself', 'i am going to hurt myself',
    'i feel like hurting myself', 'i am thinking about hurting myself',
    'i cannot keep myself safe', 'i do not feel safe with myself',
    'i cannot cope anymore', 'i feel completely hopeless', 'i cannot go on anymore',
    'i do not want to be alive', 'i do not want to live', 'i am in serious distress',
    'i am thinking of hurting myself', 'i am about to hurt myself',
)
RESPONSE = ("I'm glad you told me. I'll pause nudges and coaching for 24 hours. "
            "Please reach out to someone you trust or a local crisis helpline. "
            "If you might act on this now, contact local emergency services or go somewhere you can be with another person.")
DAY = 24 * 60 * 60
AUTOMATIC_NOTICE_KINDS = {'presence', 'care', 'goal'}
_phrases = tuple(re.compile(r'(?<!\w)' + re.escape(value) + r'(?!\w)') for value in PATTERNS)
_task = re.compile(r'^(?:(?:hey |hi )?friday[, :]*|please )*(?:write|implement|add|test|debug|translate|quote|review|detect|match|build|create|list)\b')
_reported = re.compile(r'\b(?:he|she|they|someone|my (?:friend|partner|brother|sister|mother|father|girlfriend|boyfriend)|the (?:user|owner|patient|character))\b.{0,60}\b(?:said|says|wrote|writes|told|reports|asks)\b')
_disavowed = re.compile(r'\b(?:it is not true that|i am not saying|i never said|i do not think|i no longer feel|if i (?:say|said|write|type))\b')
_failed_pause = (None, 0.)


def matches(text: str) -> bool:
    if not isinstance(text, str):
        return False
    value = text[:16000].lower().replace('\u2019', "'").replace('\u2018', "'")
    # Literal examples in code, quotations and programming requests are not owner disclosures.
    value = re.sub(r'```[\s\S]*?```|`[^`\n]*`|"[^"\n]*"|(?<!\w)\x27[^\x27\n]*\x27(?!\w)', ' ', value)
    for old, new in (("i'm", 'i am'), ("i've", 'i have'), ("don't", 'do not'), ("can't", 'cannot'), ("isn't", 'is not')):
        value = value.replace(old, new)
    value = re.sub(r'\b(?:really|honestly|seriously)\s+', '', value)
    value = re.sub(r'\s+', ' ', value).strip()
    if _task.match(value):
        return False
    for phrase in _phrases:
        for found in phrase.finditer(value):
            before = re.split(r'[.!?;]|\bbut\b', value[:found.start()])[-1][-120:]
            if not _reported.search(before) and not _disavowed.search(before):
                return True
    return False


def path() -> Path:
    return Path(config.MEMORY_DIR) / 'mind' / 'care-pause.json'


def _stamp(now=None) -> float:
    return now.timestamp() if isinstance(now, datetime) else time.time() if now is None else float(now)


def _read() -> float:
    try:
        value = json.loads(path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return 0.
    if (not isinstance(value, dict) or set(value) != {'paused_until'}
            or type(value['paused_until']) not in {int, float}
            or not math.isfinite(value['paused_until']) or value['paused_until'] < 0):
        raise ValueError('Invalid automatic-nudge pause state')
    return float(value['paused_until'])


def active(now=None) -> bool:
    stamp = _stamp(now)
    if _failed_pause[0] == path().absolute() and stamp < _failed_pause[1]:
        return True
    try:
        return stamp < _read()
    except (OSError, ValueError, TypeError):
        return True


def _discard_pending():
    from services.proactive import watcher
    from services.mind import talk
    watcher._held.clear()
    state = talk.load()
    pending = state.get('pending') or {}
    if pending and not pending.get('explicit'):
        talk.retire_question()  # Withhold; do not train distress as rejection or poor engagement.
    if not pending.get('explicit'):
        while not talk.asks().empty():
            talk.asks().get_nowait()


def _discard_phone_notices():
    files = {Path(config.MEMORY_DIR) / 'phone' / 'transport.db'}
    from services.remote import _service
    if _service is not None and getattr(_service, 'directory', None):
        files.add(_service.directory.parent / 'phone' / 'transport.db')
    for file in files:
        file = file.absolute()
        if not file.is_file():
            continue
        with sqlite3.connect(file.as_uri() + '?mode=rw', uri=True, timeout=10) as db:
            db.execute('PRAGMA secure_delete=ON')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='outbox'").fetchone():
                continue
            rows = db.execute("SELECT id,payload FROM outbox WHERE delivered IS NULL AND type IN ('notice','text')").fetchall()
            for identity, raw in rows:
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if (isinstance(payload, dict) and isinstance(payload.get('kind'), str)
                        and payload['kind'] in AUTOMATIC_NOTICE_KINDS):
                    db.execute('DELETE FROM outbox WHERE id=? AND delivered IS NULL', (identity,))


def activate(now=None) -> float:
    """Persist only the deadline; the disclosure never reaches this function."""
    global _failed_pause
    until = _stamp(now) + DAY
    with settings_store.lock:
        try:
            until = max(until, _read())
        except (OSError, ValueError, TypeError):
            pass
        try:
            settings_store.save(path(), {'paused_until': until})
            _failed_pause = (None, 0.)
        except OSError:
            _failed_pause = (path().absolute(), until)
    # Cleanup failures cannot cancel the already-established pause.
    for cleanup in (_discard_pending, _discard_phone_notices):
        try:
            cleanup()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            pass
    return until
