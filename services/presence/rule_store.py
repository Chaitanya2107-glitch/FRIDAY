"""Atomic owner-confirmed rule definitions, per-rule trust and bounded receipts."""
from pathlib import Path
import uuid

from services import settings_store
from services.automation import autonomy
from .rules import digest, validate


class RuleStore:
    def __init__(self, path, legacy=None):
        self.path = Path(path)
        self.legacy = Path(legacy) if legacy is not None else None

    @staticmethod
    def _validate(rules):
        for row in rules:
            validate(row['definition'])
            if row.get('level') not in autonomy.LEVELS or type(row.get('streak')) is not int:
                raise ValueError('Presence rule trust state is damaged.')
            if row.get('confirmed') != digest(row['definition']):
                row.update(confirmed=None, level='ask', streak=0, promotion_offered=False, silence_offered=False)

    def load(self):
        with settings_store.lock:
            value = autonomy.load(self.path)
            if self.legacy and not value.get('presence_imported') and self.legacy.exists():
                if self.legacy.stat().st_size > 1024 * 1024:
                    raise ValueError('Presence rule file exceeds its bounded size.')
                legacy = autonomy.load(self.legacy)
                self._validate(legacy['rules'])
                existing = {row['id'] for row in value['rules']}
                added = [row for row in legacy['rules'] if row['id'] not in existing]
                if len(added) + len(value['rules']) > 100:
                    raise ValueError('Presence migration would exceed the saved-rule limit.')
                value['rules'].extend(added)
                imported = {row['id'] for row in added}
                value['runs'].extend(row for row in legacy['runs'] if row.get('rule') in imported)
                value['runs'].sort(key=lambda row: row['at'])
                value['runs'] = value['runs'][-autonomy.MAX_RUNS:]
                value['presence_imported'] = True
                settings_store.save(self.path, value)
            self._validate(value['rules'])
            return value

    def update(self, edit):
        with settings_store.lock:
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
        def edit(data):
            row = next(r for r in data['rules'] if r['id'] == identity)
            row.update(autonomy.declined(row))
            return row
        return self.update(edit)

    def begin(self, identity, at, owner, *, accepted=True):
        def edit(data):
            receipt = dict(id=uuid.uuid4().hex, rule=identity, at=at, status='running',
                           tokens=[], owner=owner, undone=False, accepted=accepted)
            autonomy.append_run(data, receipt)
            return receipt
        return self.update(edit)

    def checkpoint(self, identity, tokens, status='running'):
        def edit(data):
            run = next(r for r in data['runs'] if r['id'] == identity)
            if status == 'completed' and run['status'] != 'completed' and run.get('accepted', True):
                row = next(r for r in data['rules'] if r['id'] == run['rule'])
                row.update(autonomy.accepted(row))
            if status == 'failed':
                row = next(r for r in data['rules'] if r['id'] == run['rule'])
                row['streak'] = 0
            run.update(tokens=tokens, status=status)
            return run
        return self.update(edit)

    def last_run(self):
        return next((r for r in reversed(self.load()['runs'])
                     if 'rule' in r and not r['undone'] and r['status'] != 'cancelled'), None)

    def accept_run(self, identity):
        def edit(data):
            run = next((r for r in data['runs'] if r['id'] == identity and 'rule' in r), None)
            if not run or run['status'] != 'completed' or run.get('accepted', True) or run['undone'] or run.get('demoted'):
                return None
            rule = next(r for r in data['rules'] if r['id'] == run['rule'])
            run['accepted'] = True
            if rule['level'] == autonomy.TELL and 'silence_offered' not in rule:
                rule.update(streak=0, silence_offered=False)
            rule.update(autonomy.accepted(rule))
            return rule
        return self.update(edit)

    def undone(self, identity):
        self.update(lambda data: next(r for r in data['runs'] if r['id'] == identity).update(undone=True))
