"""Offline plugin lifecycle tests: all state and plugins belong to this test."""
import asyncio
import json
from pathlib import Path
import threading
import time

import pytest

from services.event_bus import EventBus
from services.plugin_manager import PluginManager


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'Timed out waiting for plugin worker'


def make_plugin(root, plugin_id='demo', code=None, **manifest):
    folder = root / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    value = dict(id=plugin_id, name=plugin_id, version='1.0.0', api_version=1,
                 description='Test', author='Tests', permissions=['events'], enabled_by_default=True)
    value.update(manifest)
    (folder / 'plugin.json').write_text(json.dumps(value), encoding='utf-8')
    (folder / 'main.py').write_text(code or "def register(api):\n    api.on_command('demo', lambda m: {'ok': True, 'text': 'old', 'error': None})\n", encoding='utf-8')
    return folder


@pytest.fixture
def host(tmp_path, monkeypatch):
    from services.plugin_api import PluginAPI
    every, background = PluginAPI.every, PluginAPI.run_background
    # Bundled-plugin lifecycle tests never read the real clipboard/register keys.
    monkeypatch.setattr(PluginAPI, 'every', lambda api, *args: None if api.plugin_id == 'smart_clipboard' else every(api, *args))
    monkeypatch.setattr(PluginAPI, 'run_background', lambda api, *args: None if api.plugin_id == 'smart_clipboard' else background(api, *args))
    bus = EventBus()
    manager = PluginManager(tmp_path / 'code', tmp_path / 'data', bus=bus, poll_seconds=.05)
    yield manager
    manager.close()
    bus.close()


def test_manifest_discovery_skips_bad_manifest_and_template(host, caplog):
    make_plugin(host.plugins_dir)
    make_plugin(host.plugins_dir, 'bad', api_version=2)
    make_plugin(host.plugins_dir, '_template')
    make_plugin(host.plugins_dir, 'bad_path', entry='../escape.py')
    host.scan()
    assert [row['id'] for row in host.list_plugins()] == ['demo']
    assert 'Skipping bad plugin manifest bad' in caplog.text
    assert host.command('demo')['text'] == 'old'


def test_handler_crash_is_a_friendly_failed_result(host, caplog):
    make_plugin(host.plugins_dir, code="def register(api):\n    def crash(m):\n        raise RuntimeError('broken')\n    api.on_command('crash', crash)\n")
    host.scan()
    value = host.command('crash')
    assert value['ok'] is False and value['error'] == 'plugin_error'
    assert 'demo' in caplog.text
    assert host.states['demo'].enabled


def test_five_failures_auto_disable_publish_notify_and_persist(host):
    notifications = []
    host.notify = lambda *args: notifications.append(args)
    make_plugin(host.plugins_dir, code="def register(api):\n    api.on_command('crash', lambda m: 1 / 0)\n")
    host.scan()
    for _ in range(5):
        assert host.command('crash')['ok'] is False
    wait_for(lambda: bool(notifications))
    assert not host.states['demo'].enabled
    assert host.settings.get('demo') is False
    assert host.bus.recent('plugin.disabled')[-1]['payload']['plugin_id'] == 'demo'
    host.scan(force=True)
    assert host.command('crash') is None
    assert host.set_enabled('demo', True)['ok']
    assert host.states['demo'].enabled


def test_old_failures_expire_outside_sixty_second_window(host):
    make_plugin(host.plugins_dir)
    host.scan()
    state = host.states['demo']
    state.failures.extend([time.monotonic() - 61] * 4)
    host.failed('demo')
    assert state.enabled and len(state.failures) == 1


def test_registration_failure_retries_then_disables(host):
    make_plugin(host.plugins_dir, code="def register(api):\n    raise RuntimeError('bad registration')\n")
    for _ in range(5):
        host.scan()
    assert not host.states['demo'].enabled
    assert '5 failures' in host.states['demo'].error


def test_hot_reload_uses_fresh_same_size_source_and_discovers_new_folder(host):
    folder = make_plugin(host.plugins_dir)
    host.start()
    old = host.states['demo'].module.__name__
    path = folder / 'main.py'
    path.write_text(path.read_text().replace("'old'", "'new'"), encoding='utf-8')
    wait_for(lambda: host.command('demo')['text'] == 'new')
    assert host.states['demo'].module.__name__ != old
    make_plugin(host.plugins_dir, 'extra', code="def register(api):\n    api.on_command('extra', lambda m: {'ok': True, 'text': 'new folder'})\n")
    wait_for(lambda: host.command('extra') is not None)


def test_unload_stops_timers_threads_subscriptions_services_and_routes(host):
    make_plugin(host.plugins_dir, code="""
def register(api):
    api.provide('test', [])
    api.subscribe('test.*', lambda event: api.settings.set('event', True))
    api.every(.02, lambda: api.settings.set('tick', True))
    api.run_background(lambda stop: stop.wait())
    api.add_route('GET', 'state', lambda request: {'ok': True})
    api.on_action('do', lambda payload: {'ok': True, 'text': 'done'})
def unload():
    pass
""")
    host.scan()
    api = host.states['demo'].api
    wait_for(lambda: api.settings.get('tick'))
    assert host.get_service('test') == []
    host.set_enabled('demo', False)
    assert all(not thread.is_alive() for thread in api.threads)
    assert all(not subscription.thread.is_alive() for subscription in api.subscriptions)
    assert host.get_service('test') is None
    assert host.route('demo', 'state', {}) is None
    assert not host.action('demo', 'do', {})['ok']
    host.bus.publish('test.happened', {})
    assert api.settings.get('event') is None
    with pytest.raises(RuntimeError):
        api.publish('test.late', {})


def test_reload_refreshes_relative_helpers_even_with_identical_stat(host):
    import os
    folder = make_plugin(host.plugins_dir, code="from .helper import text\ndef register(api):\n    api.on_command('demo', lambda m: {'ok': True, 'text': text})\n")
    helper = folder / 'helper.py'
    helper.write_text("text = 'old'\n", encoding='utf-8')
    host.scan()
    stat = helper.stat()
    assert host.command('demo')['text'] == 'old'
    helper.write_text("text = 'new'\n", encoding='utf-8')
    os.utime(helper, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    host.scan()
    assert host.command('demo')['text'] == 'new'


def test_normalization_fullmatch_and_builtin_precedence(host):
    make_plugin(host.plugins_dir, code="""
def register(api):
    api.on_command(['demo', 'volume up'], lambda match: {'ok': True, 'text': 'plugin'}, examples=['volume up'])
""")
    host.builtin_matcher = lambda text: text.lower() == 'volume up'
    host.scan()
    assert host.command('hey friday, demo please!')['text'] == 'plugin'
    assert host.command('something demo') is None
    assert host.command('volume up') is None
    assert any('Built-in wins' in value for value in host.list_plugins()[0]['warnings'])


def test_actual_router_runs_builtins_then_plugins_before_fallback(host, monkeypatch):
    from services import plugin_runtime
    from services.automation import intent
    from core.config import config
    make_plugin(host.plugins_dir, code="""
def register(api):
    api.on_command(['what time is it', 'hello friday', 'demo bread and butter'], lambda m: {'ok': True, 'text': 'plugin ran'})
""")
    host.builtin_matcher = plugin_runtime.builtin_matches
    host.scan()
    monkeypatch.setattr(plugin_runtime, '_manager', host)
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_LANGUAGE_ENABLED', True)
    async def no_fallback(*args, **kwargs):
        pytest.fail('Plugin command reached language fallback')
    monkeypatch.setattr(intent, '_understand_command', no_fallback)
    async def run():
        assert (await intent._try_system_action('what time is it', 'ollama')).message != 'plugin ran'
        assert (await intent._try_system_action('hello friday', 'ollama')).message == 'plugin ran'
        assert (await intent._try_system_action('demo bread and butter', 'ollama')).message == 'plugin ran'
    asyncio.run(run())


def test_bundled_plugins_and_json_todo_persistence(host):
    host.plugins_dir = Path(__file__).resolve().parents[1] / 'plugins'
    host.scan()
    expected = {p.parent.name for p in host.plugins_dir.glob('*/plugin.json') if not p.parent.name.startswith('_')}
    assert {row['id'] for row in host.list_plugins()} == expected
    assert all(row['status'] == 'loaded' for row in host.list_plugins())
    assert host.command('hello friday')['ok']
    assert host.command('todo add Buy bread and butter')['ok']
    assert 'Buy bread and butter' in host.command('plugin todos')['text']
    host.scan(force=True)
    assert host.command('todo done 1')['ok']
    assert host.command('todo add Keep this')['ok']
    assert host.command('todo clear done')['ok']
    assert len(host.get_service('todo').snapshot()['items']) == 1
    assert host.command('todo remove 2')['ok']
    assert host.get_service('todo').snapshot()['items'] == []
    assert host.bus.recent('todo.changed')


def test_battery_reuses_readings_and_hysteresis(host):
    host.plugins_dir = Path(__file__).resolve().parents[1] / 'plugins'
    host.scan()
    for percent, plugged in [(50, True), (20, False), (10, False), (8, True), (24, True), (10, False), (26, True), (10, False)]:
        host.bus.publish('system.battery_reading', {'percent': percent, 'plugged': plugged})
    wait_for(lambda: len(host.bus.recent('battery.critical')) == 2)
    assert len(host.bus.recent('battery.low')) == 2
    assert len(host.bus.recent('battery.unplugged')) == 3
    assert len(host.bus.recent('battery.plugged')) == 2


def test_non_json_plugin_results_are_isolated(host):
    make_plugin(host.plugins_dir, code="""
def register(api):
    api.on_command('demo', lambda m: {'ok': True, 'text': 'bad', 'data': {'bad': object()}})
    api.add_route('GET', 'state', lambda request: {'bad': float('nan')})
""")
    host.scan()
    assert host.command('demo')['error'] == 'plugin_error'
    assert host.route('demo', 'state', {})['error'] == 'plugin_error'


def test_actual_builtin_collision_without_examples_is_reported(host, monkeypatch):
    from services import plugin_runtime
    from services.automation import intent
    make_plugin(host.plugins_dir, code="def register(api):\n    api.on_command('what day is it', lambda m: {'ok': True, 'text': 'wrong'})\n")
    host.scan()
    monkeypatch.setattr(plugin_runtime, '_manager', host)
    value = asyncio.run(intent.try_system_action('what day is it', 'ollama'))
    assert value and value.message != 'wrong'
    assert any('what day is it' in warning for warning in host.list_plugins()[0]['warnings'])


def test_mood_priority_and_expiry_are_shared_bus_events():
    from services.plugin_mood import MoodController
    bus = EventBus()
    moods = MoodController(bus)
    try:
        bus.publish('mood.set', {'mood': 'happy', 'priority': 10, 'duration_s': .2}, plugin_id='hello')
        wait_for(lambda: bool(bus.recent('mood.changed')))
        bus.publish('mood.set', {'mood': 'sleepy', 'priority': 0, 'duration_s': 1}, plugin_id='todo')
        wait_for(lambda: bus.recent('mood.changed')[-1]['payload']['mood'] == 'idle')
        assert [row['payload']['mood'] for row in bus.recent('mood.changed')] == ['happy', 'idle']
    finally:
        moods.close()
        bus.close()


def test_todo_widget_preserves_workspace_tasks_and_updates_plugin_items(host, monkeypatch):
    from services import plugin_runtime
    from services.friday_island_server.todo import TodoPlugin
    from types import SimpleNamespace
    host.plugins_dir = Path(__file__).resolve().parents[1] / 'plugins'
    host.scan()
    monkeypatch.setattr(plugin_runtime, '_manager', host)
    legacy = SimpleNamespace(snapshot=lambda: {'tasks': [{'id': 90, 'title': 'Workspace task', 'status': 'active',
                             'steps': [], 'cursor': 0, 'due': None, 'updated': 1}]})
    plugin = TodoPlugin(legacy)
    assert asyncio.run(plugin.action('add', value='JSON todo'))['ok']
    widget = plugin.widget()
    assert [row['label'] for row in widget['items']] == ['JSON todo', 'Workspace task']
    assert not asyncio.run(plugin.action('remove', 'plugin-1'))['ok']
    assert not host.get_service('todo').snapshot()['items'][0]['done']
    assert asyncio.run(plugin.action('complete', 'plugin-1'))['ok']
    assert host.get_service('todo').snapshot()['items'][0]['done']
