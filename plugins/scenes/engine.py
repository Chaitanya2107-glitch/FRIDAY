"""Durable scene transitions, previews and reverse undo with explicit recovery."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from uuid import uuid4

from services import settings_store
from services.remote.context import origin_scope, remote_origin as transport_origin

from .catalog import Catalog
from .registry import Skipped
from .triggers import Triggers


def result(text, *, ok=True, error=None, data=None):
    value = dict(ok=ok, text=text, speech=text, error=error)
    if data is not None:
        value['data'] = data
    return value


class Scenes:
    def __init__(self, api, registry, desktop, defaults, now=time.time):
        self.api, self.registry, self.desktop, self.now = api, registry, desktop, now
        self.lock = threading.RLock()
        self.path = api.data_dir / 'scene-state.json'
        self.catalog = Catalog(api, registry, defaults)
        self.epoch = sys.__dict__.setdefault('_friday_scenes_epoch', uuid4().hex)
        self.active, self.pending = None, None
        self.remote_events = False
        self.closed = False
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(state, dict) or state.get('version') != 1:
                raise ValueError('Scene recovery file is damaged; it was preserved.')
            self.active = state.get('active')
            if self.active is not None:
                self._validate_journal(self.active)
            self.remote_events = state.get('remote_origin', False)
            if type(self.remote_events) is not bool:
                raise ValueError('Scene origin metadata is damaged; the file was preserved.')
        self.needs_recovery = bool(self.active and (self.active.get('epoch') != self.epoch or self.active['phase'] != 'active'))
        self.triggers = Triggers(self, desktop.processes)
        self._last_mood = 0

    @staticmethod
    def _validate_journal(active):
        if (not isinstance(active, dict) or not isinstance(active.get('id'), str)
                or not re.fullmatch(r'scenes:[a-f0-9]{32}', active['id'])
                or not isinstance(active.get('name'), str) or active.get('phase') not in {'applying', 'active', 'undoing'}
                or type(active.get('restore')) is not bool or not isinstance(active.get('entries'), list)
                or len(active['entries']) > 96):
            raise ValueError('Scene recovery file is damaged; no undo was attempted.')
        for entry in active['entries']:
            if (not isinstance(entry, dict) or not isinstance(entry.get('type'), str)
                    or entry.get('state') not in {'prepared', 'applied', 'undone', 'undo_failed'}):
                raise ValueError('Invalid saved action; no undo was attempted.')

    def _save(self):
        state = dict(version=1, active=self.active)
        if self.remote_events:
            state['remote_origin'] = True
        settings_store.save(self.path, state)

    def ensure_active(self):
        self.api._active()
        if self.closed:
            raise RuntimeError('This scene generation was unloaded.')

    def status(self):
        with self.lock:
            return dict(active=self.active['name'] if self.active else None,
                        scene_id=self.active['id'] if self.active else None,
                        phase=self.active['phase'] if self.active else 'idle',
                        recovery=self.needs_recovery, awaiting_confirmation=self.awaiting(),
                        card=self.pending.get('card') if self.awaiting() else None,
                        ends_at=self.active.get('ends_at') if self.active else None)

    def awaiting(self):
        return bool(self.pending and self.pending['expires'] >= self.now())

    def dismiss_pending(self):
        with self.lock:
            self.pending = None
            self.sync_commands()

    def sync_commands(self):
        if command := getattr(self, 'alias_command', None):
            aliases = list(self.catalog.aliases)
            if self.awaiting():
                aliases += ['yes', 'yes please', 'no', 'no thanks', 'cancel']
            command.patterns = [re.compile(re.escape(alias), re.I) for alias in aliases] or [re.compile(r'(?!)')]

    def preview(self, scene):
        return self.catalog.preview(scene)

    def _card(self, title, body, kind, **details):
        self.ensure_active()
        from services.automation.intent import cancel_pending_confirmation
        cancel_pending_confirmation()  # A scene's Yes must never approve an older system action.
        nonce = uuid4().hex
        self.pending = dict(kind=kind, nonce=nonce, expires=self.now() + 120, **details)
        choices = [('yes', 'Yes'), ('no', 'No')]
        if kind == 'trigger':
            choices = [('yes', 'Yes'), ('no', 'Not now'), ('disable', "Don't suggest again")]
        card = dict(title=title, body=body, urgency='normal' if kind == 'trigger' else 'critical', ttl_s=120,
                    actions=[dict(id='answer', label=label, payload=dict(nonce=nonce, choice=value)) for value, label in choices])
        self.pending['card'] = card  # Authenticated status also delivers questions missed during startup/reconnect.
        self.sync_commands()
        with origin_scope(self.remote_events):
            self.api.publish('ui.card', card)
        return result(body + '\nAnswer yes or no.', data={'awaiting_confirmation': True})

    def offer_recovery(self):
        with self.lock:
            if self.needs_recovery:
                return self._card('Restore previous scene?', 'Restore your settings from the previous scene?', 'recover')
            return result('No previous scene needs restoration.')

    def _closes(self, scene):
        for action in self.catalog.actions(scene):
            provider, params = self.registry.validate(action)
            if action['type'] == 'close_app' or (getattr(provider, 'closes', None) and provider.closes(params)):
                return True
        return False

    def request(self, name):
        with self.lock:
            self.ensure_active()
            if self.needs_recovery:
                return self.offer_recovery()
            try:
                scene = self.catalog.get(name)
                approved = self.api.settings.get('approved_scenes', {}).get(scene['key']) == scene['hash']
                if (scene['confirm_first_run'] and not approved) or (self._closes(scene) and not scene['close_without_asking']):
                    return self._card('Preview ' + scene['name'] + ' mode', self.preview(scene), 'start',
                                      name=scene['key'], hash=scene['hash'])
                return self._start(scene)
            except (ValueError, OSError) as error:
                return result(str(error), ok=False, error='invalid_scene')

    def ask_trigger(self, scene, identity, action):
        verb = 'End' if action == 'end' else 'Start'
        return self._card(verb + ' ' + scene['name'] + ' mode?', verb + ' ' + scene['name'] + ' mode?',
                          'trigger', name=scene['key'], trigger=identity, action=action)

    def answer(self, choice, nonce=None):
        with self.lock:
            self.ensure_active()
            pending = self.pending
            if not self.awaiting() or nonce is not None and nonce != pending['nonce']:
                return result('That scene confirmation expired. Ask for the scene again.', ok=False, error='expired_confirmation')
            if choice not in {'yes', 'no', 'disable'}:
                return result('Answer yes or no.', ok=False, error='invalid_answer')
            self.pending = None
            self.sync_commands()
            if choice == 'disable' and pending['kind'] == 'trigger':
                disabled = self.api.settings.get('disabled_triggers', [])
                self.api.settings.set('disabled_triggers', sorted(set(disabled + [pending['trigger']])))
                return result('That scene suggestion is disabled.')
            if pending['kind'] == 'recover':
                self.needs_recovery = False
                return self.end('recovery', restore=choice == 'yes')
            if choice != 'yes':
                return result('Scene unchanged.')
            if pending['kind'] == 'trigger':
                return self.end('trigger') if pending['action'] == 'end' else self.request(pending['name'])
            try:
                scene = self.catalog.get(pending['name'])
                if scene['hash'] != pending['hash']:
                    return self._card('Scene changed', self.preview(scene), 'start', name=scene['key'], hash=scene['hash'])
                approved = self.api.settings.get('approved_scenes', {})
                approved[scene['key']] = scene['hash']
                self.api.settings.set('approved_scenes', approved)
                return self._start(scene)
            except (ValueError, OSError) as error:
                return result(str(error), ok=False, error='invalid_scene')

    def answer_action(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get('nonce'), str) or not re.fullmatch(r'[a-f0-9]{32}', payload['nonce']):
            return result('This button needs its original confirmation token. Ask for the scene again.', ok=False, error='invalid_confirmation')
        return self.answer(payload.get('choice'), payload['nonce'])

    def _start(self, scene):
        self.ensure_active()
        incoming_remote = transport_origin.get()
        actions = self.catalog.actions(scene)
        for action in actions:
            self.registry.validate(action)  # Validate all actions before ending a previous scene.
        if self.active:
            ended = self.end('replaced')
            if not ended['ok']:
                return ended
        now = self.now()
        self.pending = None
        self.remote_events = incoming_remote
        self.active = dict(id='scenes:' + uuid4().hex, name=scene['name'], key=scene['key'], hash=scene['hash'], epoch=self.epoch,
                           since=now, ends_at=now + scene['duration_minutes'] * 60 if 'duration_minutes' in scene else None,
                           restore=scene['restore'], phase='applying', entries=[])
        if incoming_remote:
            self.active['remote_origin'] = True
        self._save()
        self.api.publish('scene.started', dict(name=scene['name'], scene_id=self.active['id'], since=now))
        warnings = []
        try:
            with self.registry.owned(self.active['id']):
                for action in actions:
                    self.api._active()
                    provider, params = self.registry.validate(action)
                    prepare = getattr(provider, 'prepare', None)
                    try:
                        token = prepare(params) if prepare else None
                    except Skipped as error:
                        warnings.append(str(error))
                        continue
                    entry = dict(type=action['type'], token=token, state='prepared', cleanup=bool(getattr(provider, 'cleanup', False)))
                    json.dumps(token, allow_nan=False)
                    self.active['entries'].append(entry)
                    self._save()  # Built-ins checkpoint previous settings BEFORE touching hardware.
                    try:
                        entry['token'] = provider.do(params)
                    except Skipped as error:
                        warnings.append(str(error))
                    entry['state'] = 'applied'
                    json.dumps(entry['token'], allow_nan=False)
                    self._save()  # Each action's returned token is durable before the next action.
            self.active['phase'] = 'active'
            self._save()
        except Exception as error:
            self.api.log.warning('Scene action failed (%s); restoring completed actions', type(error).__name__)
            ended = self.end('action_failed', restore=True)
            return result('Scene could not finish: ' + str(error) + '. ' + ended['text'], ok=False, error='action_failed')
        text = 'Started ' + scene['name'] + ' mode.'
        if warnings:
            text += '\n' + '\n'.join(warnings)
        return result(text, data=self.status())

    def end(self, reason='command', restore=None):
        with self.lock, origin_scope(self.remote_events):
            self.ensure_active()
            self.pending = None
            self.sync_commands()
            if not self.active:
                return result('No scene is active.')
            active = self.active
            active['phase'] = 'undoing'
            self._save()
            failures = []
            should_restore = active['restore'] if restore is None else restore
            with self.registry.owned(active['id']):
                for entry in reversed(active['entries']):
                    if entry['state'] == 'undone':
                        continue
                    try:
                        provider = self.registry.get(entry['type']) if entry['token'] is not None else None
                        if provider and (should_restore or bool(getattr(provider, 'cleanup', False))):
                            provider.undo(entry['token'])
                        entry['state'] = 'undone'
                    except Exception as error:
                        entry['state'] = 'undo_failed'
                        failures.append(entry['type'] + ': ' + str(error))
                    self._save()
            if failures:
                return result('Some settings still need restoration. Say end scene to retry.\n' + '\n'.join(failures),
                              ok=False, error='restore_pending', data=self.status())
            # Always release the scene's policy, including a crash before its action checkpoint.
            from services import quiet_mode
            quiet_mode.set_owner(active['id'], False)
            if activity := self.api.get_service('activity'):
                activity.clear_overrides(active['id'])
            self.active = None
            self.needs_recovery = False
            self._save()
            self.api.publish('scene.ended', dict(name=active['name'], scene_id=active['id'], reason=reason))
            return result('Ended ' + active['name'] + ' mode.' + (' Reversible settings restored.' if should_restore else ' Settings kept.'), data=self.status())

    def tick(self):
        with self.lock:
            if self.closed or self.api.stop_event.is_set():
                return
            self.publish_state()
            self.catalog.reload()
            self.sync_commands()
            if self.pending and not self.awaiting():
                self.pending = None
            if self.needs_recovery:
                if not self.pending:
                    from services.automation.intent import is_awaiting_confirmation
                    if not is_awaiting_confirmation():
                        self.offer_recovery()
                return
            if self.active and self.active.get('ends_at') and self.now() >= self.active['ends_at']:
                self.end('timer')
            if self.active and self.active['phase'] == 'active' and self.now() - self._last_mood >= 5:
                for entry in reversed(self.active['entries']):
                    if entry['type'] == 'set_mood' and entry['state'] == 'applied':
                        scene = self.catalog.scenes.get(self.active['key'])
                        if scene and scene['hash'] == self.active['hash']:
                            for action in reversed(scene['actions']):
                                if action['type'] == 'set_mood':
                                    self.api.set_mood(action['mood'], 120, priority=4)
                                    break
                        break
                self._last_mood = self.now()
            self.triggers.tick()

    def publish_state(self):
        active = self.active or {}
        with origin_scope(self.remote_events):
            self.api.publish('scene.state', dict(name=active.get('name'), scene_id=active.get('id'),
                                                since=active.get('since'), phase=active.get('phase', 'idle')))

    def event(self, event):
        with self.lock:
            if not self.closed and not self.needs_recovery:
                self.triggers.event(event)

    def close(self):
        with self.lock:
            self.closed = True  # Journal/quiet policy survive reload/shutdown; startup asks to restore.

    def matches(self, text):
        return self.commands.matches(text)

    def handle_command(self, text):
        return self.commands.handle(text)
