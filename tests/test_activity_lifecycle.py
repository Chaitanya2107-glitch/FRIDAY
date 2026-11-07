import json
from pathlib import Path
import shutil

from services.event_bus import EventBus
from services.plugin_api import PluginAPI
from services.plugin_manager import PluginManager
from plugins.activity.policy import Policy
from activity_support import FakeProvider, FakeClock


MANIFEST = dict(id='activity', name='Local Activity', version='1.0.0', api_version=1,
                description='Private local Windows activity', author='FRIDAY', permissions=['events', 'files', 'ui', 'system_control'],
                requires=['psutil'], enabled_by_default=True)


def test_real_manager_reloads_maps_without_native_calls_and_keeps_last_valid(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'plugins/activity'
    folder = tmp_path / 'plugins/activity'
    shutil.copytree(source, folder)
    (folder / 'plugin.json').write_text(json.dumps(MANIFEST), encoding='utf-8')
    jobs = []
    monkeypatch.setattr(PluginAPI, 'run_background', lambda self, fn: jobs.append(fn))
    bus = EventBus()
    manager = PluginManager(tmp_path / 'plugins', tmp_path / 'user', bus=bus)
    try:
        manager.scan()
        activity = manager.get_service('activity')
        assert activity and activity.policy.sanitize('code.exe', '').category == 'coding'
        assert [s.pattern for s in activity.api.subscriptions] == ['scene.*']
        assert jobs  # Background polling was registered, never run on a desktop.
        (folder / 'categories.json').write_text('{half-written', encoding='utf-8')
        manager.scan()
        activity = manager.get_service('activity')
        assert activity and activity.policy.sanitize('code.exe', '').category == 'coding'
        assert manager.list_plugins()[0]['status'] == 'loaded'
        assert manager.route('activity', 'summary', {'query': {'range': 'bad'}})['error'] == 'invalid_range'
    finally:
        manager.close(); bus.close()
