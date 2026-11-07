"""Mochi's managed event/rule engine and optional local development commands."""
import json
from pathlib import Path
import time

from services.event_bus import validate_topic
from .engine import MoodEngine


def recent_input(api):
    activity = api.get_service('activity')
    if activity is not None:
        return activity.current().get('state') in {'active', 'private'}
    try:
        from services.activity.log import idle_seconds
        return idle_seconds() < 120
    except (ImportError, AttributeError, OSError):
        return False


def idle_input(api):
    activity = api.get_service('activity')
    if activity is not None and activity.current().get('state') != 'idle':
        return None
    try:
        from services.activity.log import idle_seconds
        return idle_seconds()
    except (ImportError, AttributeError, OSError):
        return None


def register(api):
    from services.quiet_mode import enabled as quiet_mode
    engine = MoodEngine(api, Path(__file__).with_name('mood_rules.json'), active=lambda: recent_input(api),
                        quiet=quiet_mode, idle_seconds=lambda: idle_input(api))
    api.provide('mood', engine)
    api.subscribe('*', engine.receive)
    api.add_route('GET', 'state', lambda request: engine.snapshot())
    api.on_command(r'mochi test (?P<mood>[a-z_]+)', lambda m: engine.test(m['mood'].lower()),
                   help='Try a Mochi mood, or all eleven (three seconds each).', examples=['mochi test all'])

    def setting(match):
        key = 'mood.calm_mode' if match['kind'].lower() == 'calm' else 'mood.dev_commands'
        api.settings.set(key, match['value'].lower() == 'on')
        engine.tick()
        return dict(ok=True, text=f"Mochi {match['kind'].lower()} {match['value'].lower()}.", error=None)
    api.on_command(r'mochi (?P<kind>calm|dev) (?P<value>on|off)', setting, help='Set calm mode or developer commands.')

    def fake(match):
        if api.settings.get('mood.dev_commands', False) is not True:
            return dict(ok=False, text='Enable local test events with mochi dev on.', error='dev_commands_off')
        try:
            topic = match['topic']
            validate_topic(topic)
            payload = json.loads(match['payload']) if match['payload'] else {
                'percent': 18, 'plugged': False, 'subject': 'Study', 'minutes': 5,
                'scene_id': 'mochi-test', 'name': 'study', 'reason': 'completed',
                'session_id': 'mochi-test', 'since': time.time() - 600,
            }
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON object')
            api.publish(topic, payload)
            return dict(ok=True, text='Published test event ' + topic + '.', error=None)
        except (ValueError, TypeError):
            return dict(ok=False, text='Use fake event <topic> [JSON object].', error='invalid_event')
    api.on_command(r'fake event (?P<topic>\S+)(?: (?P<payload>\{.*\}))?', fake,
                   help='Publish a local test event when developer commands are on.')

    def worker(stop):
        while not stop.wait(engine.next_delay()):
            try:
                api._call(engine.tick)
            except Exception:
                pass  # The host logs/counts failures and fences auto-disabled jobs.
    api.run_background(worker)
