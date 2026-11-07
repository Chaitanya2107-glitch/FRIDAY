"""Mochi rules and lifecycle use a fake clock; no desktop, sleeps or notifications."""
from datetime import datetime
import json
import logging
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from plugins.mood.engine import MoodEngine
from plugins.focus.timer import Focus
from plugins.mood.rules import MOODS
from services.event_bus import EventBus
from services.plugin_manager import PluginManager
from tests.test_plugin_system import wait_for

SOURCE = Path(__file__).resolve().parents[1] / 'plugins/mood'


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 6, 12).timestamp()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def moods(tmp_path):
    clock, settings, events = Clock(), {}, []
    rules = tmp_path / 'mood_rules.json'
    shutil.copyfile(SOURCE / 'mood_rules.json', rules)
    api = SimpleNamespace(settings=settings, log=logging.getLogger('test.mood'),
                          publish=lambda topic, payload: events.append(dict(topic=topic, payload=payload)))
    engine = MoodEngine(api, rules, clock=clock, active=lambda: True)
    return SimpleNamespace(engine=engine, clock=clock, api=api, events=events, rules=rules)


def send(moods, topic, **payload):
    moods.engine.receive(dict(topic=topic, payload=payload, plugin_id='test', at=moods.clock()))
    return moods.engine.snapshot()


@pytest.mark.parametrize('topic,payload,mood,seconds,priority,text', [
    ('battery.low', {'percent': 18}, 'worried', 8, 3, 'Battery at 18%'),
    ('battery.critical', {}, 'alarmed', 15, 5, ''),
    ('battery.plugged', {}, 'happy', 4, 2, ''),
    ('schedule.class_soon', {'subject': 'DBMS', 'minutes': 5}, 'alert', 10, 4, 'DBMS in 5 min'),
    ('schedule.due_soon', {}, 'alert', 6, 3, ''),
    ('focus.done', {}, 'celebrating', 6, 3, ''),
    ('activity.nudge', {}, 'worried', 6, 2, 'Maybe a break?'),
    ('activity.idle_ended', {}, 'waving', 3, 1, ''),
    ('clipboard.action_available', {}, 'curious', 3, 2, ''),
    ('index.done', {}, 'happy', 3, 1, ''),
])
def test_default_mapping_and_payload(moods, topic, payload, mood, seconds, priority, text):
    result = send(moods, topic, **payload)
    assert result == dict(mood=mood, until=moods.clock() + seconds, sticky=False,
                          priority=priority, message=text, plugin_id='mood')
    emitted = moods.events[-1]['payload']
    assert emitted['previous'] == 'idle' and emitted['expires_at'] == result['until']
    json.dumps(emitted, allow_nan=False)


@pytest.mark.parametrize('scene,mood,priority', [('study', 'focused', 4), ('exam', 'focused', 4),
                                               ('game', 'happy', 2), ('sleep', 'sleepy', 2)])
def test_sticky_scenes(moods, scene, mood, priority):
    result = send(moods, 'scene.started', scene_id='scene1', name=scene)
    assert result['mood'] == mood and result['priority'] == priority
    assert result['sticky'] is True and result['until'] is None
    moods.clock.advance(86400)
    moods.engine.tick()
    assert moods.engine.current['mood'] == mood
    assert send(moods, 'scene.ended', scene_id='scene1')['mood'] == 'idle'


def test_priority_equal_replacement_and_sticky_return(moods):
    send(moods, 'focus.started', session_id='focus1')
    assert send(moods, 'battery.low', percent=12)['mood'] == 'focused'
    assert send(moods, 'battery.critical')['mood'] == 'alarmed'
    assert not moods.engine.request(dict(mood='happy', priority=4, duration_s=9))
    assert moods.engine.request(dict(mood='curious', priority=5, duration_s=2))
    moods.clock.advance(2)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'focused'  # interrupted alarm is discarded
    assert send(moods, 'focus.done', session_id='focus1')['mood'] == 'celebrating'
    moods.clock.advance(6)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'
    assert moods.events[-1]['payload']['until'] is None


def test_owner_lifecycles_and_pause_resume(moods):
    send(moods, 'scene.started', scene_id='one', name='study')
    send(moods, 'scene.started', scene_id='two', name='exam')
    send(moods, 'scene.ended', scene_id='one')
    assert moods.engine.current['mood'] == 'focused'
    send(moods, 'focus.started', session_id='session')
    send(moods, 'focus.paused', session_id='different')
    assert 'focus:session' in moods.engine.stickies
    send(moods, 'focus.paused', session_id='session')
    send(moods, 'focus.started', session_id='session')
    assert 'focus:session' in moods.engine.stickies


def test_cooldown_and_ignored_low_priority_do_not_consume_it(moods):
    send(moods, 'battery.critical')
    send(moods, 'battery.low', percent=18)
    moods.clock.advance(15)
    assert send(moods, 'battery.low', percent=17)['mood'] == 'worried'
    moods.clock.advance(8)
    moods.engine.tick()
    assert send(moods, 'battery.low', percent=16)['mood'] == 'idle'
    moods.clock.advance(52)
    assert send(moods, 'battery.low', percent=15)['mood'] == 'worried'


def test_calm_and_quiet_scenes_only_allow_priority_four_and_up(moods):
    send(moods, 'battery.low', percent=18)
    moods.api.settings['mood.calm_mode'] = True
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'
    assert send(moods, 'activity.nudge')['mood'] == 'idle'
    assert send(moods, 'schedule.class_soon', subject='OS', minutes=4)['mood'] == 'alert'
    moods.clock.advance(10)
    moods.api.settings['mood.calm_mode'] = False
    send(moods, 'scene.started', scene_id='quiet', name='game', quiet_mode=True)
    assert send(moods, 'battery.plugged')['mood'] == 'idle'
    assert send(moods, 'battery.critical')['mood'] == 'alarmed'
    moods.clock.advance(15)
    assert send(moods, 'scene.ended', scene_id='quiet')['mood'] == 'idle'


def test_idle_waits_ten_minutes_since_actual_last_input_then_waves(moods):
    assert send(moods, 'activity.idle_started', since=moods.clock() - 120)['mood'] == 'idle'
    moods.clock.advance(479)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'
    moods.clock.advance(1)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'dozing'
    assert moods.engine.current['sticky']
    assert send(moods, 'activity.idle_ended')['mood'] == 'waving'
    moods.clock.advance(3)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'


def test_startup_already_idle_and_shared_scene_quiet_state(moods):
    moods.engine.idle_seconds = lambda: 601
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'dozing'
    moods.engine.idle_seconds = lambda: None
    send(moods, 'activity.idle_ended')
    moods.engine.quiet = lambda: True
    send(moods, 'scene.started', name='game', scene_id='custom')
    assert moods.engine.current['mood'] == 'idle'
    assert send(moods, 'battery.critical')['mood'] == 'alarmed'


def test_late_night_requires_activity_and_thirty_minute_cooldown(moods):
    moods.clock.now = datetime(2026, 11, 7, 0, 59).timestamp()
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'
    moods.clock.advance(60)
    moods.engine.active = lambda: False
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'
    moods.engine.active = lambda: True
    moods.engine.tick()
    assert moods.engine.current['message'] == "It's late."
    moods.clock.advance(1799)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'
    moods.clock.advance(1)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'sleepy'
    moods.clock.now = datetime(2026, 11, 7, 6).timestamp()
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'idle'


def test_user_edits_reload_atomically_without_losing_sticky(moods):
    send(moods, 'focus.started', session_id='s')
    data = json.loads(moods.rules.read_text())
    data['rules'][0].update(mood='curious', priority=6, cooldown_s=0, message='Charge {percent}%')
    moods.rules.write_text(json.dumps(data))
    moods.engine.tick()
    assert send(moods, 'battery.low', percent=11)['mood'] == 'curious'
    moods.rules.write_text('{partial')
    moods.clock.advance(8)
    moods.engine.tick()
    assert moods.engine.current['mood'] == 'focused'
    assert send(moods, 'battery.low', percent=10)['message'] == 'Charge 10%'
    data['rules'][0]['message'] = '{percent.__class__}'
    moods.rules.write_text(json.dumps(data))
    moods.engine.tick()
    assert send(moods, 'battery.low', percent=9)['message'] == 'Charge 9%'


@pytest.mark.parametrize('value', [{'mood': 'unknown'}, {'mood': 'happy', 'duration_s': float('nan')},
                                 {'mood': 'happy', 'priority': True}, {'mood': 'happy', 'sticky': 'yes'},
                                 {'mood': 'happy', 'duration_s': 0}, {'mood': 'happy', 'message': {}}])
def test_invalid_raw_requests_are_ignored(moods, value):
    assert not moods.engine.request(value)
    assert not moods.events


def test_test_all_cycles_every_three_seconds_and_returns_to_context(moods):
    send(moods, 'focus.started', session_id='s')
    assert moods.engine.test('all')['ok']
    for mood in MOODS:
        assert moods.engine.current['mood'] == mood
        moods.clock.advance(3)
        moods.engine.tick()
    assert moods.engine.current['mood'] == 'focused'


def test_focus_timer_pause_resume_and_completion_with_fake_clock(moods, tmp_path):
    from tests.test_focus_plugin import FakeAPI, FakeClock
    api, clock = FakeAPI(tmp_path / 'focus'), FakeClock()
    focus = Focus(api, clock)
    command = focus.handle_command
    assert command('focus 25')['ok']
    send(moods, 'focus.started', **api.events[-1][1])
    assert moods.engine.current['mood'] == 'focused'
    moods.clock.advance(60)
    clock.advance(60)
    assert command('pause focus')['ok']
    send(moods, 'focus.paused', **api.events[-1][1])
    clock.advance(1000)
    focus.tick()
    assert focus.status()['state'] == 'paused'
    assert command('resume focus')['ok']
    send(moods, 'focus.started', **api.events[-1][1])
    clock.advance(1440)
    focus.tick()
    assert focus.status()['state'] == 'idle'
    assert api.events[-1][0] == 'focus.done'
    assert send(moods, 'focus.done', **api.events[-1][1])['mood'] == 'celebrating'
    assert not command('focus 0')['ok']


def test_host_commands_dev_gate_and_rule_edit_preserves_engine(tmp_path, monkeypatch):
    from services.plugin_api import PluginAPI
    monkeypatch.setattr(PluginAPI, 'every', lambda *args: None)
    folder = tmp_path / 'code/mood'
    shutil.copytree(SOURCE, folder, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(SOURCE.parent / 'focus', tmp_path / 'code/focus', ignore=shutil.ignore_patterns('__pycache__'))
    bus = EventBus()
    host = PluginManager(tmp_path / 'code', tmp_path / 'data', bus=bus)
    try:
        host.scan()
        assert host.command('fake event battery.low')['error'] == 'dev_commands_off'
        assert host.command('mochi dev on')['ok']
        assert host.command('fake event battery.low')['ok']
        wait_for(lambda: host.get_service('mood').current['mood'] == 'worried')
        assert host.route('mood', 'state', {})['message'] == 'Battery at 18%'
        assert host.command('focus 25')['ok']
        wait_for(lambda: host.get_service('mood').current['mood'] == 'focused')
        engine = host.get_service('mood')
        (folder / 'mood_rules.json').write_text('{partial')
        host.scan()
        assert host.get_service('mood') is engine
        assert host.command('stop focus')['ok']
        wait_for(lambda: engine.current['mood'] == 'celebrating')
        assert host.command('mochi test all')['ok']
        assert host.command('mochi test unknown')['error'] == 'invalid_mood'
        assert not host.command('fake event ../invalid')['ok']
    finally:
        host.close()
        bus.close()
