"""Focus tests use a fake clock/API and temporary files, never desktop actions."""
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import threading

import pytest

from plugins.focus import main
from plugins.focus.timer import Focus
from services import settings_store
from services.plugin_storage import Settings


class FakeClock:
    def __init__(self, value=None):
        self.value = value or datetime(2026, 11, 6, 10, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class FakeAPI:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.data_dir.mkdir(exist_ok=True)
        self.settings = Settings(data_dir / 'settings.json')
        self.log = logging.getLogger('focus-test')
        self.stop_event = threading.Event()
        self.events, self.notifications, self.moods, self.commands = [], [], [], []
        self.services, self.routes, self.timers = {}, {}, []

    def _active(self):
        if self.stop_event.is_set():
            raise RuntimeError('Unloaded')

    def publish(self, topic, payload):
        self.events.append((topic, payload))

    def notify(self, *args):
        self.notifications.append(args)

    def set_mood(self, *args, **kwargs):
        self.moods.append((args, kwargs))

    def on_command(self, *args, **kwargs):
        self.commands.append(args)

    def provide(self, name, obj):
        self.services[name] = obj

    def add_route(self, method, path, handler):
        self.routes[path] = handler

    def every(self, seconds, callback):
        self.timers.append((seconds, callback))


@pytest.fixture
def focus(tmp_path):
    api, clock = FakeAPI(tmp_path / 'focus'), FakeClock()
    value = Focus(api, clock)
    yield value
    value.close()


def events(focus, topic):
    return [payload for kind, payload in focus.api.events if kind == topic]


@pytest.mark.parametrize('text', ['focus', 'focus 25', 'start focus timer 25 minutes',
    'start focus timer 1 minute', 'pomodoro', 'pause focus', 'resume focus', 'stop focus',
    'how long is left', 'focus stats today', 'focus stats this week', 'hey friday, focus 25 please!'])
def test_whole_string_command_phrasings(focus, text):
    assert focus.matches(text)
    assert not focus.matches('something ' + text)
    assert not focus.matches(text + ' and open calculator')


def test_start_is_durable_and_publishes_existing_and_new_contracts(focus):
    reply = focus.handle_command('focus 25')
    assert reply['ok'] and reply['speech'] == reply['text']
    state = focus.status()
    assert state['state'] == 'running' and state['remaining_s'] == 1500
    saved = json.loads(focus.path.read_text())
    assert saved['active']['end_at'] == focus.clock.now().timestamp() + 1500
    assert focus.path.parent == focus.api.data_dir
    event = events(focus, 'focus.started')[0]
    assert event['minutes'] == 25 and event['label'] == 'Focus'
    assert event['duration_s'] == 1500 and event['session_id'] == state['session_id']


def test_timer_survives_restart_and_completes_once(focus):
    focus.start(25)
    deadline = focus.status()['end_at']
    focus.clock.advance(120)
    restored = Focus(focus.api, focus.clock)
    assert restored.status()['remaining_s'] == 1380
    assert restored.status()['end_at'] == deadline
    focus.clock.advance(1380)
    restored.tick()
    assert restored.status()['state'] == 'idle'
    assert restored.today_minutes() == 25
    assert len(restored.data['history']) == 1
    assert events(restored, 'focus.done')[0]['completed'] is True
    assert restored.api.notifications == [('Focus complete', 'Focus finished.', 'critical')]
    assert restored.api.moods == [(('celebrating', 6), {'priority': 3})]
    again = Focus(focus.api, focus.clock)
    again.tick()
    assert len(again.data['history']) == len(again.api.notifications) == 1


def test_pause_resume_survive_restart_and_exclude_paused_time(focus):
    focus.start(10)
    focus.clock.advance(120)
    assert focus.pause()['ok']
    assert events(focus, 'focus.paused')[-1]['remaining_s'] == 480
    focus.clock.advance(3600)
    restored = Focus(focus.api, focus.clock)
    assert restored.status()['state'] == 'paused'
    assert restored.status()['remaining_s'] == 480
    assert restored.today_minutes() == 2
    assert restored.resume()['ok']
    focus.clock.advance(480)
    restored.tick()
    assert restored.today_minutes() == 10
    assert len(restored.data['history'][0]['segments']) == 2


@pytest.mark.parametrize('spent', [0, 120])
def test_backward_clock_pause_restart_preserves_only_unspent_budget(focus, spent):
    focus.start(10)
    if spent:
        focus.clock.advance(spent)
        focus.pause()
        focus.resume()
    focus.clock.advance(-300)
    assert focus.pause()['ok']
    restored = Focus(focus.api, focus.clock)
    assert restored.status()['state'] == 'paused'
    assert restored.status()['remaining_s'] == 600 - spent
    assert sum(end-start for start, end in restored.data['active']['segments']) == spent
    restored.resume()
    focus.clock.advance(600 - spent)
    restored.tick()
    assert restored.today_minutes() == 10
    assert restored.data['history'][0]['minutes'] == 10
    assert len(restored.data['history']) == 1
    assert len(events(restored, 'focus.done')) == 1
    assert Focus(focus.api, focus.clock).today_minutes() == 10


def test_pause_at_completion_boundary_does_not_save_invalid_zero_remaining(focus, monkeypatch):
    focus.start(1)
    focus.clock.advance(59)
    original_now, calls = focus.clock.now, []
    def ticking_now():
        value = original_now()
        if not calls:
            focus.clock.advance(1)
        calls.append(True)
        return value
    monkeypatch.setattr(focus.clock, 'now', ticking_now)
    assert focus.pause()['ok']
    restored = Focus(focus.api, focus.clock)
    assert restored.status()['state'] == 'idle'
    assert restored.today_minutes() == 1
    assert len(events(restored, 'focus.done')) == 1


def test_stop_records_actual_partial_work_and_owner_guard_preserves_other_timer(focus):
    focus.start(25, owner='study-scene')
    session = focus.status()['session_id']
    focus.clock.advance(30)
    assert focus.stop(owner='old-scene')['ok']
    assert focus.status()['session_id'] == session
    assert not focus.data['history']
    focus.stop(owner='study-scene')
    assert focus.status()['state'] == 'idle'
    assert focus.today_minutes() == .5
    assert focus.stats()['stopped'] == 1
    assert focus.data['history'][0]['completed'] is False
    assert focus.data['history'][0]['minutes'] == .5
    assert not focus.api.notifications and not focus.api.moods
    focus.stop()
    assert len(focus.data['history']) == 1


def test_existing_active_or_paused_timer_is_not_replaced(focus):
    focus.start(25, owner='user')
    original = focus.status()['session_id']
    assert focus.start(50, owner='scene')['error'] == 'already_running'
    focus.pause()
    assert focus.start(50, owner='scene')['error'] == 'already_running'
    assert focus.status()['session_id'] == original
    assert focus.status()['owner'] == 'user'


def test_pomodoro_short_breaks_then_long_break_and_round_restart(focus):
    focus.api.settings.set('focus', dict(focus_minutes=1, short_break_minutes=.1, long_break_minutes=.2, rounds=4))
    assert focus.handle_command('pomodoro')['ok']
    for round in range(1, 5):
        assert focus.status()['phase'] == 'focus' and focus.status()['round'] == round
        focus.clock.advance(60)
        focus.tick()
        state = focus.status()
        assert state['phase'] == ('long_break' if round == 4 else 'short_break')
        assert state['remaining_s'] == (12 if round == 4 else 6)
        assert len(focus.data['history']) == round
        focus.clock.advance(state['remaining_s'])
        focus.tick()
    assert focus.status()['phase'] == 'focus' and focus.status()['round'] == 1
    assert focus.today_minutes() == 4
    assert focus.stats()['completed'] == 4
    assert all(row['minutes'] == 1 for row in focus.data['history'])


def test_overdue_pomodoro_does_not_invent_missed_rounds_on_restart(focus):
    focus.api.settings.set('focus', dict(focus_minutes=1, short_break_minutes=.1, long_break_minutes=.2, rounds=4))
    focus.start(pomodoro=True)
    focus.clock.advance(36000)
    restored = Focus(focus.api, focus.clock)
    assert restored.status()['phase'] == 'short_break'
    assert restored.status()['remaining_s'] == 6
    assert restored.today_minutes() == 1
    assert len(restored.data['history']) == 1
    assert len(events(restored, 'focus.done')) == 1


@pytest.mark.parametrize('start', [datetime(2026, 11, 6, 23, 50, tzinfo=timezone.utc),
                                  datetime(2026, 11, 8, 23, 50, tzinfo=timezone.utc)])
def test_stats_clip_active_and_completed_work_at_midnight_and_week_boundary(focus, start):
    focus.clock.value = start
    focus.start(20)
    focus.clock.advance(15 * 60)
    assert focus.today_minutes() == 5
    assert focus.stats('this week')['minutes'] == (5 if focus.clock.now().weekday() == 0 else 15)
    focus.clock.advance(5 * 60)
    focus.tick()
    assert focus.today_minutes() == 10
    assert focus.stats('this week')['minutes'] == (10 if focus.clock.now().weekday() == 0 else 20)
    assert focus.stats()['completed'] == 1


def test_late_completion_keeps_its_scheduled_date(focus):
    focus.clock.value = datetime(2026, 11, 8, 22, tzinfo=timezone.utc)
    focus.start(25)
    focus.clock.advance(10 * 3600)
    restored = Focus(focus.api, focus.clock)
    restored.tick()
    assert restored.data['history'][0]['date'] == '2026-11-08'
    assert restored.today_minutes() == restored.stats('this week')['minutes'] == 0
    assert restored.stats()['completed'] == 0


@pytest.mark.parametrize('minutes', [0, -1, True, float('nan'), float('inf'), 1441, '25'])
def test_invalid_duration_is_friendly_and_does_not_create_timer(focus, minutes):
    assert not focus.start(minutes)['ok']
    assert focus.status()['state'] == 'idle'
    assert not focus.path.exists()


@pytest.mark.parametrize('bad', [{'focus_minutes': 0}, {'focus_minutes': float('nan')},
    {'rounds': False}, {'rounds': 0}, {'rounds': 4.5}, 'bad'])
def test_invalid_settings_are_preserved_and_reported(tmp_path, bad):
    api = FakeAPI(tmp_path / 'focus')
    raw = json.dumps({'focus': bad})
    api.settings.path.write_text(raw)
    with pytest.raises(ValueError, match='Focus settings'):
        Focus(api, FakeClock())
    assert api.settings.path.read_text() == raw


@pytest.mark.parametrize('bad', [{'version': 2}, {'version': 1, 'active': {'broken': True}, 'history': []},
    {'version': 1, 'active': None, 'history': [{}]}, {'version': 1, 'history': 'bad'}, {'version': 1, 'history': []}])
def test_damaged_state_is_not_silently_overwritten(tmp_path, bad):
    api = FakeAPI(tmp_path / 'focus')
    path = api.data_dir / 'focus.json'
    raw = json.dumps(bad)
    path.write_text(raw)
    with pytest.raises(ValueError, match='state is damaged'):
        Focus(api, FakeClock())
    assert path.read_text() == raw


def test_tiny_fractional_timer_can_reload_its_own_completed_record(focus):
    focus.start(.01)
    focus.clock.advance(.6)
    focus.tick()
    restored = Focus(focus.api, focus.clock)
    assert restored.status()['state'] == 'idle'
    assert restored.data['history'][0]['minutes'] == pytest.approx(.01)


def test_completion_write_failure_does_not_mutate_memory_or_publish(focus, monkeypatch):
    focus.start(1)
    focus.clock.advance(60)
    original = settings_store.save
    monkeypatch.setattr(settings_store, 'save', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        focus.tick()
    assert not focus.data['history'] and focus.data['active']
    assert not events(focus, 'focus.done') and not focus.api.notifications
    monkeypatch.setattr(settings_store, 'save', original)
    focus.tick()
    assert len(focus.data['history']) == len(events(focus, 'focus.done')) == 1


def test_registered_service_routes_managed_tick_and_unload_keep_durable_timer(tmp_path):
    api, clock = FakeAPI(tmp_path / 'focus'), FakeClock()
    main.register(api)
    value = api.services['focus']
    value.clock = clock
    assert api.timers[0][0] == 1 and api.commands
    value.start(25, owner='scene')
    assert api.routes['status']({})['owner'] == 'scene'
    assert api.routes['stats']({'query': {'range': 'wrong'}})['error'] == 'invalid_range'
    api.stop_event.set()
    main.unload()
    clock.advance(10)
    api.timers[0][1]()
    replacement = Focus(FakeAPI(api.data_dir), clock)
    assert replacement.status()['remaining_s'] == 1490
