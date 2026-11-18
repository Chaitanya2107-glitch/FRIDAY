"""Owner-confirmed presence rules. Timers only stage; shared delivery releases effects."""
from datetime import datetime
from uuid import uuid4

from services.presence.rules import digest, eligible, matches, validate
from services.presence.rule_store import RuleStore
from services.presence.trust import can_offer
from services.remote.context import origin_scope

from .engine import result
from .presence_actions import RuleActions


class PresenceRules:
    def __init__(self, engine):
        self.engine = engine
        self.store = RuleStore(engine.api.data_dir / 'presence-rules.json')
        self.actions = RuleActions(engine)
        self.previous = None
        self.latest = None
        self.initial_edge = None
        self.proposal = None
        self.scene_waiting = None
        self.applying_owner = None
        self.read_current = None

    def draft(self, definition):
        validate(definition)
        body = self.actions.preview(definition)
        binding = self.actions.binding(definition)
        return self.engine._card('Save presence rule?', body, 'presence_save', definition=definition, binding=binding)

    def catalog_rules(self):
        from .triggers import rule_id
        for scene in self.engine.catalog.scenes.values():
            for trigger in scene['triggers']:
                if trigger['type'] != 'presence':
                    continue
                definition = dict(trigger={k: v for k, v in trigger.items() if k in {'type', 'event', 'place', 'state'}},
                                  conditions=trigger.get('conditions', {}), actions=[dict(type='start_scene', name=scene['key'])])
                identity = 'scene:' + rule_id(scene, trigger)
                if not self.store.get(identity):
                    self.store.add(definition, self.actions.binding(definition), identity=identity, confirmed=False)

    def tick(self, now=None, presence=None):
        """No effects and no UI here; the async owner watcher must drain proposals."""
        with self.engine.lock:
            self.engine.ensure_active()
            now = now or datetime.fromtimestamp(self.engine.now())
            if not isinstance(now, datetime):
                now = datetime.fromtimestamp(now)
            if presence is None:
                try:
                    from services.presence.engine import current
                    presence = current(now)
                except ImportError:
                    return
            if not isinstance(presence, dict):
                return
            self.latest = dict(presence)
            self.catalog_rules()
            previous = self.previous
            if previous is None:
                self.initial_edge = str((presence.get('transition') or {}).get('id') or '')
            if presence.get('data_available') and presence.get('confidence', 0) >= .6:
                self.previous = dict(presence)
            if self.proposal or self.engine.awaiting() or self.scene_waiting:
                return
            for row in self.store.load()['rules']:
                if not row.get('enabled', True):
                    continue
                if can_offer(row, self.actions.risky(row['definition'])):
                    slot = 'promotion:' + now.date().isoformat()
                    if row.get('promotion_attempt') != slot:
                        self.proposal = dict(rule=row['id'], slot=slot, definition=digest(row['definition']),
                                             binding=row['binding'], kind='promote', expires=now.timestamp() + 120)
                        return
                definition = row['definition']
                slot = matches(definition, now, presence, previous)
                if not slot or row.get('last_slot') == slot or slot == self.initial_edge:
                    continue
                starts = next((a for a in definition['actions'] if a['type'] == 'start_scene'), None)
                if starts and self.engine.active and self.engine.active['key'] == self.engine.catalog.get(starts['name'])['key']:
                    self.store.patch(row['id'], last_slot=slot)
                    continue
                binding = self.actions.binding(definition)
                if row.get('binding') != binding:
                    row = self.store.patch(row['id'], binding=binding, confirmed=None, level='ask', streak=0,
                                           promotion_offered=False)
                risky = self.actions.risky(definition)
                if risky and row['level'] != 'ask':
                    row = self.store.decline(row['id'])
                self.proposal = dict(rule=row['id'], slot=slot, definition=digest(definition), binding=binding,
                                     kind='review' if not row.get('confirmed') else 'ask' if row['level'] == 'ask' else 'run',
                                     expires=now.timestamp() + 120)
                return

    def _available(self):
        from services.automation.intent import is_awaiting_confirmation
        return not (self.engine.closed or self.engine.needs_recovery or self.engine.awaiting() or is_awaiting_confirmation())

    def still_matches(self, row, now):
        if self.read_current is not None:
            self.latest = self.read_current(datetime.fromtimestamp(self.engine.now()))
        current = self.latest or {}
        if not eligible(row['definition'], now, current):
            return False
        tr = row['definition']['trigger']
        if tr['type'] == 'time':
            return matches(row['definition'], now, current, current) is not None
        if not current.get('data_available') or current.get('confidence', 0) < .6:
            return False
        if tr['event'] == 'enter_state':
            return current.get('state') == tr['state']
        if tr['event'] == 'leave_state':
            return current.get('state') != tr['state']
        if tr['event'] == 'arrive':
            return str(current.get('place') or '').casefold() == tr['place'].casefold()
        edge = current.get('transition') or {}
        return edge.get('event') == 'leave' and edge.get('place', '').casefold() == tr['place'].casefold()

    def _proceed(self, proposal, now):
        with self.engine.lock:
            self.engine.ensure_active()
            if not self._available() or self.engine.now() >= proposal['expires']:
                return False
            row = self.store.get(proposal['rule'])
            if not row or digest(row['definition']) != proposal['definition'] or self.actions.binding(row['definition']) != proposal['binding']:
                return False
            if proposal['kind'] != 'promote' and not self.still_matches(row, now):
                return False
            if proposal['kind'] != 'promote':
                self.store.patch(row['id'], last_slot=proposal['slot'])
            if proposal['kind'] == 'promote':
                self.store.patch(row['id'], promotion_offered=True)
                self.engine._card('Do this and tell you next time?', self.actions.preview(row['definition']) +
                                  '\nYou accepted three times in a row. Switch this rule to Do and tell?',
                                  'presence_promote', rule=row['id'], definition=proposal['definition'], binding=proposal['binding'])
            elif proposal['kind'] == 'review':
                self.engine._card('Confirm presence rule?', self.actions.preview(row['definition']), 'presence_review',
                                  rule=row['id'], definition=proposal['definition'], binding=proposal['binding'])
            elif proposal['kind'] == 'ask':
                self.engine._card('Presence rule — run now?', self.actions.preview(row['definition']), 'presence_run',
                                  rule=row['id'], definition=proposal['definition'], binding=proposal['binding'])
            else:
                if not row.get('confirmed') or self.actions.risky(row['definition']):
                    return False
                self.run(row, now)
            return True

    async def drain(self, now=None, *, submit=None):
        now = now or datetime.fromtimestamp(self.engine.now())
        if not isinstance(now, datetime):
            now = datetime.fromtimestamp(now)
        with self.engine.lock:
            self.engine.ensure_active()
            proposal, self.proposal = self.proposal, None
            if proposal is None:
                return False
            row = self.store.get(proposal['rule'])
            if not row:
                return False
            text = self.actions.preview(row['definition'])
            if proposal['kind'] == 'promote':
                self.store.patch(row['id'], promotion_attempt=proposal['slot'])
        if submit is None:
            from services.presence.delivery import submit
        return await submit(text, kind='presence_rule' if proposal['kind'] == 'run' else 'presence_question', now=now,
                            key='presence-rule:' + proposal['rule'] + ':' + proposal['slot'],
                            on_send=lambda: self._proceed(proposal, now))

    def answer(self, pending, choice):
        if pending['kind'] == 'presence_save':
            if choice != 'yes':
                return result('Presence rule not saved.')
            if self.actions.binding(pending['definition']) != pending['binding']:
                return self.draft(pending['definition'])
            row = self.store.add(pending['definition'], pending['binding'])
            return result('Presence rule saved at Ask. Each matching occurrence asks before acting.', data={'rule': row['id']})
        row = self.store.get(pending['rule'])
        if not row or digest(row['definition']) != pending['definition'] or self.actions.binding(row['definition']) != pending['binding']:
            return result('That rule changed. Review it again before running.', ok=False, error='rule_changed')
        if choice != 'yes':
            self.store.decline(row['id'])
            return result('No action taken. This rule is at Ask.')
        if pending['kind'] == 'presence_review':
            self.store.patch(row['id'], confirmed=digest(row['definition']), binding=pending['binding'], level='ask', streak=0)
            return result('Rule confirmed at Ask. It will ask at its next occurrence.')
        if pending['kind'] == 'presence_promote':
            if self.actions.risky(row['definition']):
                self.store.decline(row['id'])
                return result('This rule includes a confirm-risk effect and must stay at Ask.')
            self.store.patch(row['id'], level='do_and_tell')
            return result('This rule will do and tell you next time. Undo or No returns it to Ask.')
        if not self.still_matches(row, datetime.fromtimestamp(self.engine.now())):
            return result('That presence condition no longer matches. No action was taken.', ok=False, error='rule_stale')
        return self.run(row, datetime.fromtimestamp(self.engine.now()))

    def run(self, row, now, *, skip_scene=False, tokens=None, owner=None, receipt_id=None):
        if row.get('confirmed') != digest(row['definition']):
            return result('This rule has not been confirmed.', ok=False, error='rule_unconfirmed')
        owner, tokens = owner or 'presence:' + uuid4().hex, list(tokens or [])
        receipt_id = receipt_id or self.store.begin(row['id'], now.timestamp(), owner)['id']
        actions = row['definition']['actions']
        try:
            for index, action in enumerate(actions):
                if skip_scene and action['type'] == 'start_scene':
                    continue
                planned = (dict(type='scene_owner', owner=owner) if action['type'] == 'start_scene' else
                           dict(type=action['type'], owner=owner) if action['type'] in {'phone_notice', 'phone_mode'} else
                           dict(type='spoken' if action['type'] == 'read_due_today' else 'card'))
                self.store.checkpoint(receipt_id, tokens + [planned])
                token = self.actions.effect(action, owner, now)
                if token['type'] == 'scene_pending':
                    self.scene_waiting = dict(rule=row['id'], hash=self.actions.binding(row['definition']), owner=owner,
                                              tokens=tokens, at=now.timestamp(), receipt=receipt_id)
                    self.store.checkpoint(receipt_id, tokens + [planned], status='awaiting_confirmation')
                    return result('Review the scene preview before it runs.', data={'awaiting_confirmation': True})
                tokens.append(token)
                self.store.checkpoint(receipt_id, tokens)
            receipt = self.store.checkpoint(receipt_id, tokens, status='completed')
            self._promotion(row['id'], now)
            with origin_scope(True):
                self.engine.api.publish('presence.rule_ran', dict(rule=row['id'], run=receipt['id'], at=now.timestamp()))
                if row['level'] == 'do_and_tell':
                    self.engine.api.show_card('Presence rule ran', self.actions.preview(row['definition']),
                                             actions=[dict(id='presence_undo', label='Undo', payload=dict(run=receipt['id']))], ttl_s=30)
            return result('Presence rule completed. Say undo that to restore reversible changes.', data={'run': receipt['id']})
        except (ValueError, OSError, RuntimeError) as error:
            existing = self.store.last_run()
            receipt = self.store.checkpoint(receipt_id, existing['tokens'] if existing and existing['id'] == receipt_id else tokens, status='failed')
            with origin_scope(True):
                self.engine.api.show_card('Presence rule stopped', 'The rule could not complete. Reversible changes can be undone.',
                                         actions=[dict(id='presence_undo', label='Undo', payload=dict(run=receipt['id']))], ttl_s=30)
            return result('Presence rule could not complete; reversible changes can be undone.', ok=False, error='rule_failed')

    def _promotion(self, identity, now):
        row = self.store.get(identity)
        if can_offer(row, self.actions.risky(row['definition'])):
            self.proposal = dict(rule=identity, slot='promotion:' + now.date().isoformat(), definition=digest(row['definition']), binding=row['binding'],
                                 kind='promote', expires=now.timestamp() + 120)

    def permit_scene_answer(self):
        if self.scene_waiting is None:
            return True
        row = self.store.get(self.scene_waiting['rule'])
        allowed = bool(row and self.actions.binding(row['definition']) == self.scene_waiting['hash']
                       and self.still_matches(row, datetime.fromtimestamp(self.engine.now())))
        if not allowed:
            self.scene_declined()
        return allowed

    def scene_completed(self, scene, value):
        waiting = self.scene_waiting
        if waiting is None:
            return
        self.scene_waiting = None
        row = self.store.get(waiting['rule'])
        if not row or self.actions.binding(row['definition']) != waiting['hash'] or not value['ok'] or not self.engine.active:
            return
        tokens = waiting['tokens'] + [dict(type='scene', scene_id=self.engine.active['id'])]
        self.run(row, datetime.fromtimestamp(waiting['at']), skip_scene=True, tokens=tokens, owner=waiting['owner'], receipt_id=waiting['receipt'])

    def scene_declined(self):
        if self.scene_waiting:
            self.store.decline(self.scene_waiting['rule'])
            run = self.store.last_run()
            if run and run['id'] == self.scene_waiting['receipt']:
                self.store.checkpoint(run['id'], run['tokens'], status='cancelled')
            self.scene_waiting = None

    def can_undo(self):
        run = self.store.last_run()
        if not run or not run.get('tokens') or self.engine.now() - run['at'] > 900:
            return False
        scenes = [t for t in run['tokens'] if t['type'] in {'scene', 'scene_owner'}]
        return not scenes or bool(self.engine.active and (self.engine.active['id'] == scenes[-1].get('scene_id')
                                  or scenes[-1].get('owner') and self.engine.active.get('presence_owner') == scenes[-1]['owner']))

    def can_decline_auto(self):
        run = self.store.last_run()
        row = self.store.get(run['rule']) if run else None
        return bool(self.can_undo() and row and row['level'] == 'do_and_tell' and self.engine.now() - run['at'] <= 120)

    def release_scene(self, active):
        """Scene exit also releases phone modes owned by that reviewed rule run."""
        for run in self.store.load()['runs']:
            owns = any(t['type'] == 'scene' and t.get('scene_id') == active['id'] or
                       t['type'] == 'scene_owner' and t.get('owner') == active.get('presence_owner')
                       for t in run.get('tokens', []))
            if owns and any(t['type'] == 'phone_mode' for t in run.get('tokens', [])):
                self.store.update(lambda data: next(r for r in data['runs'] if r['id'] == run['id']).update(restore_phone_pending=True))
        self.retry_phone_restores()

    def retry_phone_restores(self):
        from services.presence import phone
        for run in self.store.load()['runs']:
            if not run.get('restore_phone_pending'):
                continue
            try:
                for token in run['tokens']:
                    if token['type'] != 'phone_mode':
                        continue
                    if not token.get('id') or not phone.cancel(token['id']):
                        phone.send('mode', dict(restore_owner=token['owner']), ttl=900)
                def saved(data):
                    row = next(r for r in data['runs'] if r['id'] == run['id'])
                    row['restore_phone_pending'] = False
                    row['tokens'] = [dict(type='phone_restored') if t['type'] == 'phone_mode' else t for t in row['tokens']]
                self.store.update(saved)
            except (ValueError, OSError, RuntimeError):
                pass  # Keep the receipt; native ownership leases independently restore on expiry.

    def forget(self, device=None):
        """Discard phone-derived learning/receipts, retaining explicit owner definitions."""
        with self.engine.lock:
            def clear(data):
                identities = {row['id'] for row in data['rules'] if row['definition']['trigger']['type'] == 'presence'}
                for row in data['rules']:
                    if row['id'] in identities:
                        row.update(level='ask', streak=0, promotion_offered=False, last_slot=None)
                        row.pop('promotion_attempt', None)
                data['runs'] = [run for run in data['runs'] if run['rule'] not in identities]
                return identities
            identities = self.store.update(clear)
            self.previous = self.latest = None
            self.initial_edge = None
            if self.proposal and self.proposal['rule'] in identities:
                self.proposal = None
            if self.scene_waiting and self.scene_waiting['rule'] in identities:
                self.scene_waiting = None
                self.engine.pending = None
            if self.engine.pending and self.engine.pending.get('rule') in identities:
                self.engine.pending = None
            self.engine.sync_commands()

    def undo(self, payload=None):
        with self.engine.lock:
            self.engine.ensure_active()
            if payload is not None and (not isinstance(payload, dict) or set(payload) != {'run'} or not isinstance(payload['run'], str)):
                return result('Use the original presence Undo button.', ok=False, error='undo_unavailable')
            run = self.store.last_run()
            if not run or (payload is None and not self.can_undo()) or payload is not None and payload.get('run') != run['id']:
                return result('No current presence action can be undone.', ok=False, error='undo_unavailable')
            try:
                note = self.actions.undo(run['tokens'])
                self.store.undone(run['id'])
                self.proposal = None
                return result('Presence action undone. The rule is back at Ask. ' + note)
            except (ValueError, OSError, RuntimeError):
                return result('Restoration needs another try. The receipt was kept.', ok=False, error='undo_failed')
