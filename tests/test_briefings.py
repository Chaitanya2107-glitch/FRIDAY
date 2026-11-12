"""Offline delivery/content contracts with fake civil time and optional services."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from briefing_fakes import Clock, make_brief
from plugins.briefings import weather
from services.schedule_adapter import ScheduleItem


def rich_sources(clock):
    today = clock.now().date()
    def classes(day):
        start = datetime.combine(day, datetime.min.time()).replace(hour=10)
        return [ScheduleItem('class', 'Physics lab', 'Physics lab', 'Prof. Ray', 'B-4', start, start+timedelta(hours=1))]
    due = [ScheduleItem(str(n), title, subject='Physics', due_at=datetime.combine(today+timedelta(days=n), datetime.min.time()).replace(hour=17), kind=kind)
           for n, title, kind in [(0, 'Lab report', 'assignment'), (1, 'Homework', 'homework'), (5, 'Physics exam', 'exam')]]
    schedule = SimpleNamespace(classes_on=classes, due_items=lambda n: due[:2], upcoming_exams=lambda n: due[2:],
                               pending_homework=lambda: due[1:2])
    return dict(schedule=schedule, focus=SimpleNamespace(stats=lambda period: dict(minutes=45)),
                activity=SimpleNamespace(summary=lambda period: dict(categories={'study': 1200, 'private': 3000})),
                todo=SimpleNamespace(snapshot=lambda: dict(items=[{'done': False}, {'done': True, 'done_at': clock.now().isoformat()}])))


def test_first_activity_inside_window_and_once_per_day_across_restart(tmp_path):
    brief, clock, api = make_brief(tmp_path)
    clock.value = clock.now().replace(hour=4, minute=59)
    event = dict(topic='activity.idle_ended', payload={})
    brief.event(event)
    assert not api.events
    clock.advance(minutes=1)
    brief.event(event)
    brief.event(event)
    assert len(api.payloads('briefing.ready')) == 1
    restored, _, restored_api = make_brief(tmp_path, clock=clock)
    restored.event(event)
    restored.tick()
    assert not restored_api.events
    clock.advance(days=1)
    restored.event(event)
    assert len(restored_api.payloads('briefing.ready')) == 1


@pytest.mark.parametrize('hour,minute,expected', [(7, 29, 0), (7, 30, 1), (8, 0, 1), (11, 0, 0), (4, 59, 0)])
def test_0730_fallback_catches_up_within_morning_window(tmp_path, hour, minute, expected):
    brief, clock, api = make_brief(tmp_path, services={'activity': object()})
    clock.value = clock.now().replace(hour=hour, minute=minute)
    brief.tick()
    brief.tick()
    assert len(api.payloads('briefing.ready')) == expected


def test_input_fallback_without_activity_and_custom_window(tmp_path):
    brief, clock, api = make_brief(tmp_path, desktop=lambda: dict(fullscreen=False, active=True))
    api.settings.update({'briefings.morning_start': '06:30', 'briefings.morning_end': '09:00'})
    brief.tick()
    assert not api.events
    clock.advance(minutes=30)
    brief.tick()
    assert len(api.payloads('briefing.ready')) == 1


@pytest.mark.parametrize('name', ['game', 'class'])
def test_scene_defers_ten_minutes_including_manual_and_restart(tmp_path, name):
    current = {'active': name, 'phase': 'active'}
    services = {'scenes': SimpleNamespace(status=lambda: current)}
    brief, clock, api = make_brief(tmp_path, services=services)
    assert 'deferred' in brief.request('morning')['text']
    assert not api.payloads('briefing.ready') and not brief.state['delivered']
    restored, _, new_api = make_brief(tmp_path, clock=clock, services=services)
    current.update(active=None, phase='idle')
    clock.advance(minutes=9, seconds=59)
    restored.tick()
    assert not new_api.payloads('briefing.ready')
    clock.advance(seconds=1)
    restored.tick()
    assert len(new_api.payloads('briefing.ready')) == 1


@pytest.mark.parametrize('fullscreen', [True, None])
def test_fullscreen_or_unknown_foreground_defers(tmp_path, fullscreen):
    brief, _, api = make_brief(tmp_path, desktop=lambda: dict(fullscreen=fullscreen))
    brief.request('night')
    assert not api.events
    assert 'night' in brief.state['pending']


def test_auto_morning_deferral_does_not_escape_window(tmp_path):
    context = {'fullscreen': True}
    brief, clock, api = make_brief(tmp_path, desktop=lambda: context)
    clock.value = clock.now().replace(hour=10, minute=55)
    brief.tick()
    context['fullscreen'] = False
    clock.advance(minutes=10)
    brief.tick()
    assert not api.events and not brief.state['pending']


def test_rich_brief_six_lines_and_battery_thresholds(tmp_path):
    clock = Clock()
    brief, _, api = make_brief(tmp_path, clock=clock, services=rich_sources(clock),
                              battery={'percent': 39, 'plugged': False, 'charging': False})
    api.settings.update(user_name='Sam', honorific='Captain')
    morning = brief.build('morning')
    assert len(morning.splitlines()) == 6
    for part in ['Good morning, Captain Sam', 'Physics lab at 10:00 with Prof. Ray in B-4',
                 '1 class today', 'Due today: Lab report', 'Due tomorrow: Homework', 'Physics in 5 days',
                 '1 homework', '1 open todos', 'Yesterday: 45 focus minutes', 'Top category: study', 'Battery 39%']:
        assert part in morning
    night = brief.build('night')
    assert len(night.splitlines()) == 6
    assert all(s in night for s in ['Today: 45 focus minutes', '1 todos completed today', 'Tomorrow starts', 'Battery 39%', 'Rest well'])
    assert 'private' not in morning
    brief.builder.battery = lambda: dict(percent=82, plugged=True, charging=True)
    assert 'Battery' not in brief.build('morning')
    assert 'charge' not in brief.build('night')


@pytest.mark.parametrize('source,excluded', [('schedule', 'Physics'), ('focus', 'focus minutes'),
                                         ('activity', 'Top category'), ('todo', 'open todos')])
def test_missing_services_leave_out_their_sections(tmp_path, source, excluded):
    clock = Clock()
    services = rich_sources(clock)
    del services[source]
    brief, _, _ = make_brief(tmp_path, clock=clock, services=services)
    assert excluded not in brief.build('morning')
    assert len(brief.build('morning').splitlines()) <= 6


def test_no_schedule_or_any_services_still_delivers_quiet_short_brief(tmp_path):
    brief, _, api = make_brief(tmp_path)
    reply = brief.handle_command('brief me')
    assert reply['ok'] and len(reply['text'].splitlines()) == 1
    assert api.payloads('briefing.ready') == [{'kind': 'morning', 'text': reply['text']}]
    assert not api.spoken  # Only managed, cancellable jobs were queued.


def test_failing_optional_services_are_silent(tmp_path, caplog):
    def fail(*args):
        raise OSError('Missing database')
    broken = SimpleNamespace(classes_on=fail, due_items=fail, upcoming_exams=fail, pending_homework=fail,
                             stats=fail, summary=fail, snapshot=fail)
    brief, _, _ = make_brief(tmp_path, services=dict.fromkeys(['schedule', 'focus', 'activity', 'todo'], broken))
    assert len(brief.build('morning').splitlines()) == 1
    assert not caplog.records


def test_opener_does_not_repeat_on_next_day_or_after_restart(tmp_path):
    brief, clock, api = make_brief(tmp_path)
    brief.request('morning')
    before = api.payloads('briefing.ready')[-1]['text'].splitlines()[0]
    clock.advance(days=1)
    restored, _, api2 = make_brief(tmp_path, clock=clock)
    restored.request('morning', reason='activity')
    assert before != api2.payloads('briefing.ready')[-1]['text'].splitlines()[0]


def test_snooze_replays_once_and_skip_stops_it(tmp_path):
    brief, clock, api = make_brief(tmp_path)
    brief.request('morning')
    first_id = brief.state['offer']['id']
    assert brief.handle_command('snooze 30')['ok']
    assert not brief.matches('skip')
    assert not brief.respond('skip', {'card_id': first_id})['ok']
    clock.advance(minutes=29, seconds=59)
    brief.tick()
    assert len(api.payloads('briefing.ready')) == 1
    restored, _, api2 = make_brief(tmp_path, clock=clock)
    clock.advance(seconds=1)
    restored.tick()
    assert len(api2.payloads('briefing.ready')) == 1
    assert not restored.respond('skip', {'card_id': first_id})['ok']
    assert not restored.respond('skip', {})['ok']
    assert restored.handle_command('skip')['ok']
    assert not restored.state['pending'] and not restored.matches('skip')
    restored.tick()
    assert len(api2.payloads('briefing.ready')) == 1


def test_old_offer_expires_and_manual_can_repeat_outside_window(tmp_path):
    brief, clock, api = make_brief(tmp_path)
    brief.request('morning')
    clock.advance(minutes=11)
    assert not brief.matches('skip')
    clock.value = clock.now().replace(hour=14)
    brief.handle_command('morning brief')
    assert len(api.payloads('briefing.ready')) == 2
    assert 'Good afternoon' in api.payloads('briefing.ready')[-1]['text']


def test_night_clock_sleep_trigger_and_public_sleep_offer(tmp_path):
    brief, clock, api = make_brief(tmp_path)
    requested = []
    def request(name):
        assert not brief.lock._is_owned()
        requested.append((name, brief.tomorrow_summary()))
        return dict(ok=True, text='Preview sleep mode', speech='')
    api.services['scenes'] = SimpleNamespace(status=lambda: dict(active=None, phase='idle'), request=request)
    clock.value = clock.now().replace(hour=22, minute=29)
    brief.tick()
    assert not api.events
    clock.advance(minutes=1)
    brief.tick()
    card = api.payloads('ui.card')[-1]
    assert card['body'].endswith('Start sleep mode?')
    assert {a['label'] for a in card['actions']} >= {'Yes', 'Not now'}
    assert len(card['body'].splitlines()) <= 6
    assert brief.respond('sleep', {'card_id': card['card_id']})['ok']
    assert requested[0][0] == 'sleep'
    brief.event(dict(topic='scene.started', payload={'name': 'sleep'}))
    assert len(api.payloads('briefing.ready')) == 1


def test_sleep_trigger_delivers_under_quiet_but_game_still_defers(tmp_path):
    brief, _, api = make_brief(tmp_path, quiet=lambda: True)
    brief.event(dict(topic='scene.started', payload={'name': 'sleep'}))
    assert api.payloads('briefing.ready')[0]['kind'] == 'night'
    assert api.payloads('ui.card')[0]['urgency'] == 'critical'
    brief.event(dict(topic='scene.started', payload={'name': 'game'}))
    brief.request('morning')
    assert len(api.payloads('briefing.ready')) == 1


def test_moods_and_voice_defaults_are_local_and_cancellable(tmp_path):
    brief, _, api = make_brief(tmp_path)
    brief.request('morning')
    assert api.moods[0][0] == ('waving',)
    api.jobs[0](api.stop_event)
    assert api.spoken == [api.payloads('briefing.ready')[0]['text']]
    api.jobs[1](SimpleNamespace(wait=lambda seconds: False))
    assert api.moods[-1][0] == ('happy',)
    before = len(api.jobs)
    brief.request('night')
    assert len(api.jobs) == before and api.moods[-1][0] == ('sleepy',)
    api.settings['briefings.speak'] = False
    brief.request('morning')
    assert len(api.jobs) == before+1  # Smile only; no speech.


def test_weather_off_by_default_and_invalid_coordinates_never_connect(monkeypatch):
    monkeypatch.setattr(httpx, 'Client', lambda **kw: pytest.fail('Unexpected network use'))
    assert weather.fetch({}) == ''
    assert weather.fetch({'briefings.weather': True}) == ''
    assert weather.fetch({'briefings.weather': True, 'briefings.latitude': 100, 'briefings.longitude': 0}) == ''


def test_weather_failure_silent_three_second_timeout(tmp_path, monkeypatch, caplog):
    calls = []
    def failed(**kwargs):
        calls.append(kwargs)
        raise httpx.ConnectError('Offline')
    monkeypatch.setattr(httpx, 'Client', failed)
    brief, _, api = make_brief(tmp_path)
    api.settings.update({'briefings.weather': True, 'briefings.latitude': 12.9, 'briefings.longitude': 77.6})
    assert brief.request('morning')['ok']
    assert calls == [dict(timeout=3, trust_env=False, follow_redirects=False)]
    assert not caplog.records


def test_weather_success_uses_only_fixed_endpoint(monkeypatch):
    requests = []
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, *, params):
            requests.append((url, params))
            return httpx.Response(200, json={'current': {'temperature_2m': 24.7}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'Client', Client)
    assert weather.fetch({'briefings.weather': True, 'briefings.latitude': 12.9, 'briefings.longitude': 77.6}) == 'Outside: 25°C.'
    assert [url for url, _ in requests] == ['https://api.open-meteo.com/v1/forecast']


def test_sleep_transition_delivers_on_active_state_without_redundant_offer(tmp_path):
    current = dict(active='sleep', phase='applying')
    brief, _, api = make_brief(tmp_path, services={'scenes': SimpleNamespace(status=lambda: current)})
    brief.event(dict(topic='scene.started', plugin_id='scenes', payload=dict(name='sleep', scene_id='s1')))
    assert not api.payloads('briefing.ready')
    current['phase'] = 'active'
    brief.event(dict(topic='scene.state', plugin_id='scenes', payload=dict(name='sleep', scene_id='s1', phase='active')))
    assert len(api.payloads('briefing.ready')) == 1
    assert 'Start sleep mode?' not in api.payloads('ui.card')[0]['body']


def test_sleep_state_snapshots_do_not_restart_fullscreen_deferral(tmp_path):
    current = dict(active='sleep', phase='applying')
    context = {'fullscreen': True}
    brief, clock, api = make_brief(tmp_path, services={'scenes': SimpleNamespace(status=lambda: current)},
                                  desktop=lambda: context)
    brief.event(dict(topic='scene.started', plugin_id='scenes', payload=dict(name='sleep', scene_id='s1')))
    current['phase'] = 'active'
    event = dict(topic='scene.state', plugin_id='scenes', payload=dict(name='sleep', scene_id='s1', phase='active'))
    brief.event(event)
    retry_at = brief.state['pending']['night']['at']
    clock.advance(minutes=1)
    brief.event(event)
    assert brief.state['pending']['night']['at'] == retry_at
    context['fullscreen'] = False
    brief.event(event)
    assert not api.payloads('briefing.ready')
    clock.advance(minutes=9)
    brief.tick()
    assert len(api.payloads('briefing.ready')) == 1


def test_rechecks_eligibility_after_build_and_before_queued_speech(tmp_path):
    context = {'fullscreen': False}
    brief, _, api = make_brief(tmp_path, desktop=lambda: context)
    original = brief.builder.render
    def build_then_fullscreen(*args):
        value = original(*args)
        context['fullscreen'] = True
        return value
    brief.builder.render = build_then_fullscreen
    brief.request('morning')
    assert not api.events
    context['fullscreen'] = False
    brief.builder.render = original
    brief.request('morning')
    context['fullscreen'] = True
    api.jobs[0](api.stop_event)
    assert not api.spoken


def test_night_deferral_across_midnight_does_not_consume_next_night(tmp_path):
    context = {'fullscreen': True}
    brief, clock, api = make_brief(tmp_path, desktop=lambda: context)
    clock.value = clock.now().replace(hour=23, minute=55)
    brief.tick()
    first_day = clock.now().date().isoformat()
    clock.advance(minutes=10)
    context['fullscreen'] = False
    brief.tick()
    assert brief.state['delivered']['night'] == first_day
    clock.value = clock.now().replace(hour=22, minute=30)
    brief.tick()
    assert len(api.payloads('briefing.ready')) == 2
