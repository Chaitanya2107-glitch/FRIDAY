import json
from pathlib import Path
import shutil
import threading

import pytest

from services.event_bus import EventBus
from services.plugin_manager import PluginManager
from test_plugin_system import make_plugin


def test_scene_aliases_and_pending_answers_do_not_capture_unrelated_commands(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'plugins/scenes'
    target = tmp_path / 'code/scenes'
    shutil.copytree(source, target)
    entry = target / 'main.py'
    entry.write_text(entry.read_text().replace('desktop = desktop or Desktop(api)',
        'from scenes_support import Hardware\n    desktop = desktop or Hardware()'))
    (target / 'plugin.json').write_text(json.dumps(dict(id='scenes', name='Scenes', version='1', api_version=1,
        description='Test', author='Tests', permissions=['events', 'files', 'ui'], enabled_by_default=True)))
    bus = EventBus()
    manager = PluginManager(target.parent, tmp_path / 'user', bus=bus)
    try:
        manager.scan()
        engine = manager.get_service('scenes')
        assert engine and manager.command('a normal chat sentence') is None
        reply = manager.command('study mode')
        assert reply['ok'] and engine.awaiting()
        assert not manager.action('scenes', 'answer', {'choice': 'yes'})['ok']
        assert engine.desktop.calls == []
        assert manager.command('no')['ok']
        assert manager.command('yes') is None
        file = engine.catalog.folder / 'study.json'
        value = json.loads(file.read_text()); value['aliases'].append('library time')
        file.write_text(json.dumps(value))
        engine.tick()
        assert manager.command('library time')['ok'] and engine.awaiting()
        manager.command('no')
        old = engine.api
        manager.set_enabled('scenes', False)
        with pytest.raises(RuntimeError):
            old.publish('scene.late', {})
        assert manager.get_service('scene_actions') is None
    finally:
        manager.close(); bus.close()


@pytest.mark.parametrize('operation', ['lookup', 'crashing_plugin'])
def test_plugin_queries_and_failure_reporting_do_not_deadlock_unload(tmp_path, operation):
    bus = EventBus()
    manager = PluginManager(tmp_path / 'code', tmp_path / 'user', bus=bus)
    make_plugin(manager.plugins_dir, 'dependency', code="def register(api):\n    api.provide('dependency', [])\n")
    make_plugin(manager.plugins_dir, 'scene_test', code='''
import threading
engine_lock = threading.RLock()
entered = threading.Event()
blocked = False
def register(api):
    pass
def unload():
    global blocked
    entered.set()
    if not engine_lock.acquire(timeout=1):
        blocked = True
    else:
        engine_lock.release()
''')
    manager.scan()
    module = manager.states['scene_test'].module
    dependency = manager.states['dependency'].api
    ready, lookup = threading.Event(), threading.Event()
    values = []
    def command():
        with module.engine_lock:
            ready.set()
            assert lookup.wait(3)
            if operation == 'lookup':
                values.append(manager.get_service('dependency'))
            else:
                values.append(manager.invoke(dependency, lambda: 1 / 0, command=True))
    worker = threading.Thread(target=command, daemon=True)
    disable = threading.Thread(target=lambda: manager.set_enabled('scene_test', False), daemon=True)
    try:
        worker.start(); assert ready.wait(2)
        disable.start(); assert module.entered.wait(2)
        lookup.set()
        worker.join(3); disable.join(3)
        assert not worker.is_alive() and not disable.is_alive() and not module.blocked
        assert values and (values[0] == [] if operation == 'lookup' else values[0]['ok'] is False)
    finally:
        lookup.set(); worker.join(3); disable.join(3)
        manager.close(); bus.close()


def test_service_is_not_exposed_until_registration_finishes(tmp_path):
    bus = EventBus()
    manager = PluginManager(tmp_path / 'code', tmp_path / 'user', bus=bus)
    make_plugin(manager.plugins_dir, 'partial', code='''
import threading
provided = threading.Event()
finish = threading.Event()
def register(api):
    api.provide('partial', 'complete object')
    provided.set()
    finish.wait(3)
''')
    worker = threading.Thread(target=manager.scan, daemon=True)
    try:
        worker.start()
        # The module is installed before its register function is called.
        import time
        deadline = time.monotonic() + 2
        while 'partial' not in manager.states or not hasattr(manager.states['partial'].module, 'provided'):
            assert time.monotonic() < deadline
            time.sleep(.01)
        module = manager.states['partial'].module
        assert module.provided.wait(2)
        assert manager.get_service('partial') is None
        module.finish.set(); worker.join(3)
        assert manager.get_service('partial') == 'complete object'
    finally:
        if 'partial' in manager.states and hasattr(manager.states['partial'].module, 'finish'):
            manager.states['partial'].module.finish.set()
        worker.join(3); manager.close(); bus.close()
