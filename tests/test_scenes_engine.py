import json
from types import SimpleNamespace

import pytest

from scenes_support import make_scenes, put_scene
from plugins.scenes.registry import Action, Skipped
from services import quiet_mode, settings_store


@pytest.fixture
def host(tmp_path):
    value = make_scenes(tmp_path)
    yield value
    value.engine.close(); value.api.stop(); value.manager.bus.close()


def test_actions_apply_in_order_and_restore_exact_settings_in_reverse(host):
    original = (dict(host.desktop.audio), dict(host.desktop.brightness), host.desktop.plan)
    put_scene(host, actions=[dict(type='set_volume', percent=30), dict(type='set_brightness', percent=20),
                             dict(type='set_power_plan', plan='high_performance')])
    assert host.engine.request('test')['ok']
    assert host.desktop.calls == ['volume', 'brightness', 'power:high_performance']
    journal = json.loads(host.engine.path.read_text())
    assert all(row['state'] == 'applied' for row in journal['active']['entries'])
    assert host.engine.end()['ok']
    assert host.desktop.calls[-3:] == ['power:' + original[2], 'undo-brightness', 'undo-audio']
    assert (host.desktop.audio, host.desktop.brightness, host.desktop.plan) == original
    assert [event['topic'] for event in host.manager.bus.recent('scene.*')] == ['scene.started', 'scene.ended']


def test_first_run_changed_files_and_stale_cards_require_fresh_confirmation(host):
    put_scene(host, confirm_first_run=True, actions=[dict(type='set_volume', percent=30)])
    assert host.engine.handle_command('test mode')['data']['awaiting_confirmation']
    assert host.desktop.calls == []
    old = host.engine.pending['nonce']
    put_scene(host, confirm_first_run=True, actions=[dict(type='set_volume', percent=20)])
    reply = host.engine.answer('yes', old)
    assert reply['ok'] and host.engine.pending['nonce'] != old and not host.desktop.calls
    assert not host.engine.answer('yes', old)['ok']
    assert host.engine.handle_command('yes')['ok']
    assert host.desktop.audio['scalar'] == .2
    host.engine.end()
    assert host.engine.request('test')['ok'] and not host.engine.awaiting()
    host.engine.end()
    put_scene(host, confirm_first_run=True, actions=[dict(type='set_volume', percent=10)])
    host.engine.request('test')
    assert host.engine.awaiting() and host.desktop.audio['scalar'] == .734


def test_close_always_confirms_unless_explicitly_disabled(host):
    put_scene(host, actions=[dict(type='close_app', name='Chrome')])
    host.engine.request('test')
    assert host.engine.awaiting() and not host.desktop.calls
    host.engine.answer('yes')
    host.engine.end()
    host.engine.request('test')
    assert host.engine.awaiting()
    host.engine.answer('no')
    put_scene(host, close_without_asking=True, actions=[dict(type='close_app', name='Chrome')])
    host.engine.request('test')
    assert not host.engine.awaiting() and host.desktop.calls.count('close:Chrome') == 2


def test_switching_scene_restores_previous_before_applying_next(host):
    put_scene(host, name='one', actions=[dict(type='set_volume', percent=20)])
    put_scene(host, name='two', actions=[dict(type='set_volume', percent=40)])
    host.engine.request('one'); host.engine.request('two')
    assert host.desktop.calls == ['volume', 'undo-audio', 'volume']
    assert host.engine.status()['active'] == 'two'
    host.engine.end()
    assert host.desktop.audio == dict(device='fake-speakers', scalar=.734, mute=True)


def test_partial_failure_restores_prior_actions_and_failed_undo_can_be_retried(host):
    host.registry.register('broken', Action(lambda p: (_ for _ in ()).throw(RuntimeError('synthetic failure')),
        lambda t: None, lambda p: 'Fail in test.', lambda p: None))
    put_scene(host, actions=[dict(type='set_volume', percent=20), dict(type='broken')])
    assert not host.engine.request('test')['ok']
    assert host.engine.active is None and host.desktop.audio['scalar'] == .734
    put_scene(host, actions=[dict(type='set_volume', percent=20)])
    host.engine.request('test')
    previous = host.desktop.restore_audio
    host.registry.get('set_volume').undo = lambda token: (_ for _ in ()).throw(OSError('offline device'))
    assert host.engine.end()['error'] == 'restore_pending'
    assert host.engine.active['entries'][0]['state'] == 'undo_failed'
    host.registry.get('set_volume').undo = previous
    assert host.engine.end()['ok'] and host.desktop.audio['scalar'] == .734


def test_crash_after_effect_before_return_has_write_ahead_undo_and_recovery_card(tmp_path):
    class ProcessDied(BaseException): pass
    first = make_scenes(tmp_path)
    before = first.desktop.audio_snapshot()
    def die(params):
        first.desktop.set_volume(15)
        raise ProcessDied()
    provider = first.registry.get('set_volume')
    provider.do = die
    put_scene(first, actions=[dict(type='set_volume', percent=15)])
    with pytest.raises(ProcessDied):
        first.engine.request('test')
    assert first.desktop.audio['scalar'] == .15
    saved = json.loads(first.engine.path.read_text())['active']
    assert saved['entries'][0]['state'] == 'prepared' and saved['entries'][0]['token'] == before
    first.api.stop(); first.engine.close(); first.manager.bus.close()
    second = make_scenes(tmp_path, hardware=first.desktop)
    try:
        assert second.engine.needs_recovery
        second.engine.offer_recovery()
        card = second.manager.bus.recent('ui.card')[-1]['payload']
        assert card['body'] == 'Restore your settings from the previous scene?'
        assert [a['label'] for a in card['actions']] == ['Yes', 'No']
        assert second.engine.status()['card'] == card  # Reconnect can recover the question.
        assert second.engine.answer('yes')['ok']
        assert second.desktop.audio == before and second.engine.active is None
    finally:
        second.api.stop(); second.engine.close(); second.manager.bus.close()


def test_restart_recovery_no_keeps_settings_but_releases_quiet(host, tmp_path):
    put_scene(host, actions=[dict(type='quiet_mode', on=True), dict(type='set_volume', percent=10)])
    host.engine.request('test')
    assert quiet_mode.enabled()
    state = json.loads(host.engine.path.read_text()); state['active']['epoch'] = 'previous-process'
    settings_store.save(host.engine.path, state)
    host.api.stop(); host.engine.close()
    second = make_scenes(tmp_path, hardware=host.desktop)
    try:
        second.engine.offer_recovery(); second.engine.answer('no')
        assert second.desktop.audio['scalar'] == .1 and not quiet_mode.enabled()
        assert second.engine.active is None
    finally:
        second.api.stop(); second.engine.close(); second.manager.bus.close()


def test_optional_focus_and_activity_skip_cleanly_and_timer_end_restores(host):
    put_scene(host, actions=[dict(type='start_focus', minutes=25),
                             dict(type='set_activity_threshold', category='games', minutes=10)], duration_minutes=.1)
    assert host.engine.request('test')['ok']
    host.clock.value += 7
    host.engine.tick()
    assert host.engine.active is None


def test_preview_distractions_alias_edit_and_create_never_touch_desktop_settings(host):
    assert host.engine.handle_command('preview study mode')['ok']
    assert not host.desktop.calls
    host.engine.handle_command('add Chrome to study distractions')
    assert 'Chrome' in host.engine.catalog.get('study')['distractions']
    host.engine.handle_command('remove Chrome from study distractions')
    assert host.engine.catalog.get('study')['distractions'] == []
    assert host.engine.handle_command('create scene reading')['ok']
    assert host.engine.catalog.get('reading')['name'] == 'reading'
    assert host.desktop.calls[0].startswith('path:') and len(host.desktop.calls) == 1
