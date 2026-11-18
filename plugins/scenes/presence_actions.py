"""Finite presence-rule effects using existing scene transitions and owner tokens."""
from datetime import datetime

from services.presence.rules import label
from services.remote.context import origin_scope

SAFE_SCENE_ACTIONS = {'quiet_mode', 'set_mood', 'start_focus', 'set_activity_threshold',
                      'set_volume', 'mute', 'set_brightness', 'set_power_plan', 'minimize_app', 'say'}


class RuleActions:
    def __init__(self, engine):
        self.engine = engine

    def binding(self, definition):
        return {row['name']: self.engine.catalog.get(row['name'])['hash']
                for row in definition['actions'] if row['type'] == 'start_scene'}

    def preview(self, definition):
        from services.presence.rules import preview
        text = preview(definition)
        for row in definition['actions']:
            if row['type'] == 'start_scene':
                text += '\n\n' + self.engine.preview(self.engine.catalog.get(row['name']))
        if len(text) > 3800:
            raise ValueError('The full rule preview is too long. Split it into smaller rules.')
        return text

    def risky(self, definition):
        for row in definition['actions']:
            if row['type'] == 'phone_mode':
                return True  # Phone interruption policy always requires a fresh owner Yes.
            if row['type'] == 'start_scene':
                scene = self.engine.catalog.get(row['name'])
                # Unknown/custom/plugin effects and P0 confirm effects never gain automatic authority.
                if any(action['type'] not in SAFE_SCENE_ACTIONS for action in self.engine.catalog.actions(scene)):
                    return True
        return False

    def effect(self, action, owner, now):
        kind = action['type']
        if kind == 'start_scene':
            previous = self.engine.active['id'] if self.engine.active else None
            self.engine.presence.applying_owner = owner
            try:
                with origin_scope(True):
                    value = self.engine.request(action['name'])
            finally:
                self.engine.presence.applying_owner = None
            if not value['ok']:
                raise ValueError(value['text'])
            if value.get('data', {}).get('awaiting_confirmation'):
                return dict(type='scene_pending', name=action['name'])
            active = self.engine.active
            return dict(type='scene', scene_id=active['id'], previous=previous)
        if kind in {'phone_notice', 'phone_mode'}:
            from services.presence import phone
            payload = ({'title': action.get('title', 'FRIDAY'), 'text': action['text'], 'owner': owner}
                       if kind == 'phone_notice' else {**{k: v for k, v in action.items() if k != 'type'}, 'owner': owner})
            identity = phone.send('notice' if kind == 'phone_notice' else 'mode', payload, ttl=900)
            return dict(type=kind, id=identity, owner=owner)
        if kind == 'read_due_today':
            from services.college import overview
            when = now if isinstance(now, datetime) else datetime.fromtimestamp(now)
            rows = [r for r in overview.overview(when).get('due_soon', []) if str(r.get('due', ''))[:10] == when.date().isoformat()]
            names = [str(r.get('what') or r.get('subject') or 'an assignment')[:160] for r in rows[:10]]
            text = 'Due today: ' + '; '.join(names) + '.' if names else 'Nothing is recorded as due today.'
            self.engine.api.speak(text)
            return dict(type='spoken')
        label(action['text'], 2000)
        with origin_scope(True):
            self.engine.api.show_card(action.get('title', 'FRIDAY'), action['text'], ttl_s=30)
        return dict(type='card')

    def undo(self, tokens):
        notes = []
        for token in reversed(tokens):
            kind = token['type']
            if kind in {'scene', 'scene_owner'}:
                active = self.engine.active
                owned = bool(active and (active['id'] == token.get('scene_id') or token.get('owner')
                                         and active.get('presence_owner') == token['owner']))
                if not owned:
                    notes.append('The scene changed later; it was left alone.')
                    continue
                if any(entry['type'] == 'say' for entry in active['entries']):
                    notes.append('Already spoken words cannot be recalled.')
                value = self.engine.end('presence_undo', restore=True)
                if not value['ok']:
                    raise ValueError(value['text'])
            elif kind in {'phone_notice', 'phone_mode'}:
                from services.presence import phone
                cancelled = phone.cancel(token['id']) if token.get('id') else False
                if kind == 'phone_mode' and not cancelled:
                    phone.send('mode', dict(restore_owner=token['owner']), ttl=900)
                elif kind == 'phone_notice' and not cancelled:
                    notes.append('The phone notice was already delivered and cannot be unsent.')
            elif kind == 'spoken':
                notes.append('Already spoken words cannot be recalled.')
            elif kind == 'card':
                with origin_scope(True):
                    self.engine.api.show_card('Presence rule undone', 'Previous presence card withdrawn.', ttl_s=1)
        return ' '.join(notes)
