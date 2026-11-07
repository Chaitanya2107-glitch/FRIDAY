"""HUD hardware is injected; bridge authentication uses the real companion router."""
from collections import namedtuple
from pathlib import Path
import shutil
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from plugins.hud.main import DEFAULTS, HUD, validate
from plugins.hud.stats import Stats
from services.event_bus import EventBus
from services.friday_island_server.http import create_router
from services.plugin_manager import PluginManager
from services.plugin_storage import Settings

TOKEN = 'a' * 64
Times = namedtuple('Times', 'user system idle')


class Reader:
    calls = 0
    total = 100
    def cpu_times(self):
        self.calls += 1
        return Times(self.total / 4, self.total / 4, self.total / 2)
    def net_io_counters(self):
        return SimpleNamespace(bytes_sent=self.total * 10, bytes_recv=self.total * 20)
    def virtual_memory(self):
        return SimpleNamespace(percent=25, used=2048, total=8192)
    def sensors_battery(self):
        return SimpleNamespace(percent=29, power_plugged=False)


def test_sample_cache_zero_clock_boundaries_thread_independent_and_counter_reset():
    reader, now = Reader(), [0.0]
    sampler = Stats(reader=reader, clock=lambda: now[0], wall=lambda: 1700000000)
    first = sampler.snapshot()
    assert first == dict(sampled_at=1700000000, cpu_percent=None,
                         ram=dict(percent=25, used_bytes=2048, total_bytes=8192),
                         battery=dict(percent=29, plugged=False, charging=False), gpu=None, network=None)
    first['ram']['percent'] = 90
    now[0] = .999
    assert sampler.snapshot()['ram']['percent'] == 25
    assert reader.calls == 1
    now[0], reader.total = 1, 120
    second = sampler.snapshot()
    assert reader.calls == 2 and second['cpu_percent'] == 50
    assert second['network'] == dict(upload_bps=200, download_bps=400)
    now[0], reader.total = 2, 1
    assert sampler.snapshot()['network'] == dict(upload_bps=0, download_bps=0)


def test_unavailable_hardware_is_null():
    class Missing:
        def __getattr__(self, name):
            raise OSError('unavailable')
    assert Stats(reader=Missing()).snapshot() | {'sampled_at': 0} == dict(
        sampled_at=0, cpu_percent=None, ram=None, battery=None, gpu=None, network=None)


def test_route_token_schema_cache_and_no_stats_events(tmp_path, monkeypatch):
    folder = tmp_path / 'code' / 'hud'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'plugins' / 'hud', folder,
                    ignore=shutil.ignore_patterns('__pycache__'))
    # The unit test must never initialize a real hardware driver.
    (folder / 'gpu.py').write_text('class GPU:\n def read(self): return None\n def close(self): pass\n', encoding='utf-8')
    import psutil
    reader = Reader()
    for name in ('cpu_times', 'net_io_counters', 'virtual_memory', 'sensors_battery'):
        monkeypatch.setattr(psutil, name, getattr(reader, name))
    manager = PluginManager(tmp_path / 'code', tmp_path / 'data', bus=EventBus())
    manager.scan()
    app = FastAPI()
    app.include_router(create_router(lambda: manager, lambda: SimpleNamespace(connection=SimpleNamespace(token=TOKEN))))
    client = TestClient(app, base_url='http://127.0.0.1')
    try:
        path = '/api/plugins/hud/stats'
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'X-Friday-Token': 'wrong'}).status_code == 401
        headers = {'X-Friday-Token': TOKEN}
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert set(response.json()) == {'sampled_at', 'cpu_percent', 'ram', 'battery', 'gpu', 'network'}
        assert client.get(path, headers=headers).json() == response.json()
        assert reader.calls == 1
        assert all(event['topic'] == 'hud.available' for event in manager.bus.recent('hud.*'))
        assert client.post('/api/plugins/hud/actions/settings', json={'enabled': False}).status_code == 401
        assert client.post('/api/plugins/hud/actions/settings', headers=headers, json={'layer': 'bad'}).json()['ok'] is False
        assert client.post('/api/plugins/hud/actions/settings', headers=headers, json={'widgets': {'clock': False}}).json()['ok']
        assert client.get('/api/plugins/hud/state', headers=headers).json()['settings']['widgets']['network']
    finally:
        client.close(); manager.close(); manager.bus.close()


def api(tmp_path, services=None):
    events = []
    return SimpleNamespace(settings=Settings(tmp_path / 'settings.json'),
                           get_service=lambda name: (services or {}).get(name),
                           publish=lambda topic, payload: events.append((topic, payload)),
                           log=SimpleNamespace(debug=lambda *a, **kw: None)), events


def test_commands_optional_services_privacy_and_edit_session(tmp_path):
    services = {'activity': SimpleNamespace(summary=lambda day: {'categories': {'study': 120, 'private': 60},
                                                                  'top_apps': [{'app_name': 'SECRET APP'}]},
                                            is_fullscreen=lambda: False),
                'schedule': SimpleNamespace(next_class=lambda: {'subject': 'Physics', 'faculty': 'Ada', 'room': 'R2',
                                                               'starts_at': '2026-11-06T15:00:00'})}
    interface, events = api(tmp_path, services)
    hud = HUD(interface)
    assert hud.state()['activity'] == {'study': 120, 'private': 60}
    assert 'SECRET APP' not in str(hud.state())
    assert hud.state()['next_class']['faculty'] == 'Ada'
    assert hud.change({'editing': True})['ok']
    assert hud.state()['settings']['editing'] is True
    assert HUD(interface).state()['settings']['editing'] is False
    assert events[-1][0] == 'hud.changed'
    services.clear()
    assert hud.state()['next_class'] is None and hud.state()['activity'] is None
    import re
    for command in ('on', 'off', 'edit', 'done', 'layer desktop', 'layer top', 'saver on', 'saver off'):
        assert hud.command(re.fullmatch(r'hud (.*)', 'hud ' + command))['ok']


def test_focus_scene_events_and_invalid_settings(tmp_path):
    interface, _ = api(tmp_path)
    hud = HUD(interface)
    for topic, payload in [('scene.started', {'scene_id': 'one', 'name': 'game'}),
                           ('focus.started', {'session_id': 'f', 'duration_s': 1500})]:
        hud.event({'topic': topic, 'payload': payload, 'at': 100})
    assert hud.state()['game'] and hud.state()['focus']['ends_at'] == 1600
    hud.event({'topic': 'focus.paused', 'payload': {'session_id': 'f', 'remaining_s': 20}, 'at': 110})
    assert hud.state()['focus']['remaining_s'] == 20 and hud.state()['focus']['ends_at'] is None
    hud.event({'topic': 'focus.done', 'payload': {'session_id': 'other'}, 'at': 110})
    assert hud.state()['focus'] is not None
    hud.event({'topic': 'scene.ended', 'payload': {'scene_id': 'one'}, 'at': 110})
    assert not hud.state()['game']
    for changes in ({'layer': 'bad'}, {'width': float('nan')}, {'x': -1}, {'monitor': ''}, {'widgets': {'bad': True}},
                    {'saver': 1}, {'opacity': 2}, {'token': 'oops'}):
        with pytest.raises(ValueError): validate(changes)
    assert DEFAULTS['layer'] == 'desktop'
