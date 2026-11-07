from datetime import datetime

import pytest

from scenes_support import make_scenes, put_scene
from services import quiet_mode


@pytest.fixture
def host(tmp_path):
    value = make_scenes(tmp_path)
    yield value
    value.engine.close(); value.api.stop(); value.manager.bus.close()


def test_time_trigger_suggests_by_default_and_dont_suggest_again_persists(host):
    now = datetime.fromtimestamp(host.clock.value).astimezone()
    put_scene(host, actions=[dict(type='set_volume', percent=20)], triggers=[dict(type='time', at=now.strftime('%H:%M'))])
    host.engine.tick()
    assert not host.desktop.calls and host.engine.pending['kind'] == 'trigger'
    card = host.manager.bus.recent('ui.card')[-1]['payload']
    assert [a['label'] for a in card['actions']] == ['Yes', 'Not now', "Don't suggest again"]
    assert card['urgency'] == 'normal'
    host.engine.answer('disable')
    host.clock.value += 7 * 86400
    host.engine.tick()
    assert not host.engine.pending and host.api.settings.get('disabled_triggers')


def test_auto_trigger_requires_opt_in_and_still_obeys_first_run_confirmation(host):
    now = datetime.fromtimestamp(host.clock.value).astimezone()
    put_scene(host, actions=[dict(type='set_volume', percent=20)], triggers=[dict(type='time', at=now.strftime('%H:%M'), auto=True)])
    host.engine.tick()
    assert host.desktop.audio['scalar'] == .2 and host.engine.active
    host.engine.end()
    put_scene(host, confirm_first_run=True, actions=[dict(type='set_volume', percent=20)],
              triggers=[dict(type='time', at=now.strftime('%H:%M'), auto=True, days='daily')])
    host.engine.tick()
    assert host.engine.awaiting() and host.desktop.audio['scalar'] == .734


def test_process_start_and_near_class_event_are_local_suggestions(host):
    put_scene(host, triggers=[dict(type='process', process='steam.exe'),
                             dict(type='event', topic='schedule.class_soon', within_minutes=5)])
    host.engine.tick()  # Establish baseline, do not suggest for existing processes.
    assert not host.engine.pending
    host.desktop.running.add((7, 1000., 'steam.exe'))
    host.engine.tick()
    assert host.engine.pending['kind'] == 'trigger'
    host.engine.answer('no')
    far = datetime.fromtimestamp(host.clock.value + 600).astimezone().isoformat()
    host.engine.event(dict(topic='schedule.class_soon', plugin_id='schedule', payload={'starts_at': far}))
    assert not host.engine.pending
    soon = datetime.fromtimestamp(host.clock.value + 240).astimezone().isoformat()
    host.engine.event(dict(topic='schedule.class_soon', plugin_id='schedule', payload={'starts_at': soon}))
    assert host.engine.pending['kind'] == 'trigger'


def test_quiet_mode_does_not_allow_optional_trigger_to_steal_confirmation(host):
    now = datetime.fromtimestamp(host.clock.value).astimezone()
    put_scene(host, triggers=[dict(type='time', at=now.strftime('%H:%M'))])
    quiet_mode.set_owner('test', True)
    host.engine.tick()
    assert not host.engine.pending and not host.manager.bus.recent('ui.card')
    host.engine.request('study')  # Explicit request/recovery can still show a critical confirmation.
    assert host.engine.awaiting() and host.manager.bus.recent('ui.card')[-1]['payload']['urgency'] == 'critical'
