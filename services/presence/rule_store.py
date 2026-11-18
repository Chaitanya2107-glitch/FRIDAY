"""Atomic owner-confirmed rule definitions, per-rule trust and bounded receipts."""
import json
from pathlib import Path
import threading
import uuid

from services import settings_store
from .rules import digest, validate
from .trust import accepted, declined


class RuleStore:
    def __init__(self, path):
        self.path, self.lock = Path(path), threading.RLock()

    def load(self):
        with self.lock:
            try:
                if self.path.stat().st_size > 1024 * 1024:
                    raise ValueError('Presence rule file exceeds its bounded size.')
                value = json.loads(self.path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                return dict(version=1, rules=[], runs=[])
            if (not isinstance(value, dict) or value.get('version') != 1 or set(value) != {'version', 'rules', 'runs'}
                    or not isinstance(value['rules'], list) or len(value['rules']) > 100 or not isinstance(value['runs'], list)
                    or len(value['runs']) > 200):
                raise ValueError('Presence rule file is damaged; it was preserved.')
            for row in value['rules']:
                validate(row['definition'])
                if row.get('level') not in {'ask', 'do_and_tell'} or type(row.get('streak')) is not int:
                    raise ValueError('Presence rule trust state is damaged.')
                if row.get('confirmed') != digest(row['definition']):
                    row.update(confirmed=None, level='ask', streak=0, promotion_offered=False)
            return value

    def update(self, edit):
        with self.lock:
            data = self.load()
            answer = edit(data)
            settings_store.save(self.path, data)
            return answer

    def add(self, definition, binding, *, identity=None, confirmed=True):
        validate(definition)
        def edit(data):
            if len(data['rules']) >= 100:
                raise ValueError('At most 100 presence rules may be saved.')
            identity_value = identity or uuid.uuid4().hex
            old = next((r for r in data['rules'] if r['id'] == identity_value), None)
            if identity is None:
                old = next((r for r in data['rules'] if digest(r['definition']) == digest(definition)
                            and r.get('binding') == binding), old)
            if old:
                return old
            row = dict(id=identity_value, definition=definition, binding=binding,
                       confirmed=digest(definition) if confirmed else None,
                       level='ask', streak=0, promotion_offered=False, last_slot=None, enabled=True)
            data['rules'].append(row)
            return row
        return self.update(edit)

    def get(self, identity):
        return next((r for r in self.load()['rules'] if r['id'] == identity), None)

    def patch(self, identity, **changes):
        def edit(data):
            row = next((r for r in data['rules'] if r['id'] == identity), None)
            if not row:
                raise ValueError('That presence rule was removed.')
            row.update(changes)
            return row
        return self.update(edit)

    def decline(self, identity):
        return self.patch(identity, **declined({}))

    def record(self, identity, at, tokens, *, status='completed'):
        def edit(data):
            row = next(r for r in data['rules'] if r['id'] == identity)
            if status == 'completed':
                row.update(accepted(row))
            receipt = dict(id=uuid.uuid4().hex, rule=identity, at=at, status=status, tokens=tokens, undone=False)
            data['runs'] = (data['runs'] + [receipt])[-200:]
            return receipt
        return self.update(edit)

    def begin(self, identity, at, owner):
        def edit(data):
            receipt = dict(id=uuid.uuid4().hex, rule=identity, at=at, status='running', tokens=[], owner=owner, undone=False)
            data['runs'] = (data['runs'] + [receipt])[-200:]
            return receipt
        return self.update(edit)

    def checkpoint(self, identity, tokens, status='running'):
        def edit(data):
            run = next(r for r in data['runs'] if r['id'] == identity)
            if status == 'completed' and run['status'] != 'completed':
                row = next(r for r in data['rules'] if r['id'] == run['rule'])
                row.update(accepted(row))
            run.update(tokens=tokens, status=status)
            return run
        return self.update(edit)

    def last_run(self):
        return next((r for r in reversed(self.load()['runs']) if not r['undone']), None)

    def undone(self, identity):
        def edit(data):
            run = next(r for r in data['runs'] if r['id'] == identity)
            run['undone'] = True
            rule = next((r for r in data['rules'] if r['id'] == run['rule']), None)
            if rule:
                rule.update(level='ask', streak=0)
        self.update(edit)
