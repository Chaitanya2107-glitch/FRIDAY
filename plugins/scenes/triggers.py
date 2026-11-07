"""Optional local clock/process/event rules: suggest unless explicitly automatic."""
from datetime import datetime
import hashlib
import json
import re

from services.event_bus import validate_topic

DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def validate_triggers(rules):
    if not isinstance(rules, list) or len(rules) > 32:
        raise ValueError('triggers must be a list of at most 32 rules.')
    for rule in rules:
        if not isinstance(rule, dict) or rule.get('type') not in {'time', 'process', 'event'}:
            raise ValueError('Trigger type must be time, process or event.')
        if set(rule) - {'type', 'auto', 'action', 'at', 'days', 'process', 'topic', 'match', 'within_minutes'}:
            raise ValueError('Unknown trigger fields.')
        if type(rule.get('auto', False)) is not bool or rule.get('action', 'start') not in {'start', 'end'}:
            raise ValueError('Triggers use auto true/false and action start/end.')
        if rule['type'] == 'time':
            if not isinstance(rule.get('at'), str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', rule['at']):
                raise ValueError('Time triggers need at in HH:MM format.')
            days = rule.get('days', 'daily')
            valid_days = (days in ['daily', 'weekdays', 'weekends'] if isinstance(days, str)
                          else isinstance(days, list) and bool(days) and all(d in DAYS for d in days))
            if not valid_days:
                raise ValueError('days must be daily, weekdays, weekends or a list of mon through sun.')
        elif rule['type'] == 'process':
            if not isinstance(rule.get('process'), str) or not re.fullmatch(r'[\w .+-]+\.exe', rule['process'], re.I):
                raise ValueError('Process triggers need one exact executable name, such as steam.exe.')
        else:
            validate_topic(rule.get('topic'), pattern=True)
            if not isinstance(rule.get('match', {}), dict):
                raise ValueError('Event match must be a JSON object.')
            if 'within_minutes' in rule and (type(rule['within_minutes']) not in {int, float} or not 0 < rule['within_minutes'] <= 1440):
                raise ValueError('within_minutes must be positive, at most 1440.')


def rule_id(scene, rule):
    return scene['key'] + ':' + hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:20]


class Triggers:
    def __init__(self, engine, processes):
        self.engine, self.processes = engine, processes
        self.previous = None

    def rules(self):
        disabled = self.engine.api.settings.get('disabled_triggers', [])
        return [(scene, rule, rule_id(scene, rule)) for scene in self.engine.catalog.scenes.values()
                for rule in scene['triggers'] if rule_id(scene, rule) not in disabled]

    def offer(self, scene, rule, identity, slot):
        engine = self.engine
        from services.automation.intent import is_awaiting_confirmation
        if is_awaiting_confirmation():
            return
        if engine.needs_recovery or engine.pending or (engine.active and engine.active['name'] == scene['name'] and rule.get('action', 'start') == 'start'):
            return
        if rule.get('action') == 'end' and (not engine.active or engine.active['name'] != scene['name']):
            return
        if not rule.get('auto', False):
            from services.quiet_mode import enabled
            if enabled():
                return  # Optional suggestions must not interrupt a quiet scene.
        last = engine.api.settings.get('trigger_slots', {})
        if last.get(identity) == slot:
            return
        last[identity] = slot
        engine.api.settings.set('trigger_slots', last)
        if rule.get('auto', False):
            if rule.get('action') == 'end':
                engine.end('trigger')
            else:
                engine.request(scene['key'])  # First-run and close confirmations still apply.
            return
        engine.ask_trigger(scene, identity, rule.get('action', 'start'))

    def tick(self):
        now = datetime.fromtimestamp(self.engine.now()).astimezone()
        rules = self.rules()
        process_rules = [r for r in rules if r[1]['type'] == 'process']
        current = self.processes() if process_rules else None
        new = current - self.previous if current is not None and self.previous is not None else set()
        self.previous = current
        for scene, rule, identity in rules:
            if rule['type'] == 'time':
                days = rule.get('days', 'daily')
                allowed = (days == 'daily' or days == 'weekdays' and now.weekday() < 5
                           or days == 'weekends' and now.weekday() >= 5
                           or isinstance(days, list) and DAYS[now.weekday()] in days)
                if allowed and now.strftime('%H:%M') == rule['at']:
                    self.offer(scene, rule, identity, now.strftime('%Y-%m-%d %H:%M'))
            elif rule['type'] == 'process' and any(row[2] == rule['process'].lower() for row in new):
                self.offer(scene, rule, identity, str(int(self.engine.now() // 60)))

    def event(self, event):
        from fnmatch import fnmatchcase
        if event.get('plugin_id') == 'scenes':
            return
        for scene, rule, identity in self.rules():
            if rule['type'] != 'event' or not fnmatchcase(event['topic'], rule['topic']):
                continue
            payload = event['payload']
            if any(payload.get(k) != v for k, v in rule.get('match', {}).items()):
                continue
            if event['topic'] == 'schedule.class_soon':
                try:
                    start = datetime.fromisoformat(payload['starts_at'])
                    delta = start.timestamp() - self.engine.now()
                    if not 0 <= delta <= rule.get('within_minutes', 5) * 60:
                        continue
                except (ValueError, KeyError, TypeError):
                    continue
            self.offer(scene, rule, identity, str(int(self.engine.now() // 60)))
