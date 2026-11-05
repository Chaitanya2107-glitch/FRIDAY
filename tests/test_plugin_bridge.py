"""Bridge requests run through in-process ASGI, without sockets or desktop actions."""
import asyncio
import json
import logging
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from services.event_bus import EventBus
from services.friday_island_server.http import create_router
from services.friday_island_server.security import PathOnlyAccess
from services.plugin_manager import PluginManager
from tests.test_plugin_system import make_plugin

TOKEN = 'a' * 64


def test_bridge_auth_host_origin_and_plugin_routes(tmp_path):
    manager = PluginManager(tmp_path / 'plugins', tmp_path / 'data', bus=EventBus())
    make_plugin(manager.plugins_dir, code="""
def register(api):
    api.add_route('GET', 'state', lambda request: {'hello': 'world'})
    api.on_action('choose', lambda payload: {'ok': True, 'text': payload['value']})
""")
    manager.scan()
    app = FastAPI()
    app.include_router(create_router(lambda: manager, lambda: SimpleNamespace(connection=SimpleNamespace(token=TOKEN))))
    client = TestClient(app, base_url='http://127.0.0.1')
    headers = {'X-Friday-Token': TOKEN}
    try:
        for method, path in [('get', '/api/plugins'), ('post', '/api/plugins/demo/enable'),
                             ('post', '/api/plugins/reload'), ('get', '/api/events'), ('get', '/api/plugins/demo/state')]:
            assert getattr(client, method)(path).status_code == 401
        assert client.get('/api/plugins', headers={'X-Friday-Token': 'wrong'}).status_code == 401
        assert client.get('/api/plugins', headers={**headers, 'Host': 'evil.example'}).status_code == 400
        assert client.get('/api/plugins', headers={**headers, 'Host': 'localhost.evil'}).status_code == 400
        assert client.get('/api/plugins', headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/plugins', headers={**headers, 'Origin': 'http://tauri.localhost'}).status_code == 200
        assert client.get('/api/plugins/demo/state', headers=headers).json() == {'hello': 'world'}
        assert client.post('/api/plugins/demo/actions/choose', headers=headers, json={'value': 'chosen'}).json()['text'] == 'chosen'
        assert client.post('/api/plugins/demo/disable', headers=headers).json()['ok']
        assert client.get('/api/plugins/demo/state', headers=headers).status_code == 404
        assert client.post('/api/plugins/demo/enable', headers=headers).json()['ok']
        assert client.post('/api/plugins/reload', headers=headers).json()['ok']
        assert client.post('/api/plugins/missing/enable', headers=headers).status_code == 404
        assert client.get('/api/events?topic=bad..topic', headers=headers).status_code == 422
    finally:
        client.close()
        manager.close()
        manager.bus.close()


def test_sse_filters_delivers_and_unsubscribes_on_disconnect(tmp_path):
    manager = PluginManager(tmp_path / 'plugins', tmp_path / 'data', bus=EventBus())
    router = create_router(lambda: manager, lambda: SimpleNamespace(connection=SimpleNamespace(token=TOKEN)))
    endpoint = next(route.endpoint for route in router.routes if route.path == '/api/events')
    async def receive():
        await asyncio.Future()
    async def run():
        request = Request({'type': 'http', 'method': 'GET', 'path': '/api/events',
                           'query_string': b'topic=todo.*', 'headers': [(b'host', b'127.0.0.1'), (b'x-friday-token', TOKEN.encode())],
                           'scheme': 'http', 'client': ('127.0.0.1', 1), 'server': ('127.0.0.1', 8000)}, receive)
        response = await endpoint(request)
        stream = response.body_iterator
        assert 'FRIDAY events' in await anext(stream)
        assert len(manager.bus._subscriptions) == 1
        manager.bus.publish('battery.low', {'percent': 20})
        manager.bus.publish('todo.changed', {'items': []})
        chunk = await asyncio.wait_for(anext(stream), 2)
        assert 'event: todo.changed' in chunk and 'battery.low' not in chunk
        event = json.loads(next(line[6:] for line in chunk.splitlines() if line.startswith('data: ')))
        assert event['payload'] == {'items': []}
        await stream.aclose()
        assert len(manager.bus._subscriptions) == 0
    try:
        asyncio.run(run())
    finally:
        manager.close()
        manager.bus.close()


def test_access_log_never_includes_query_token():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s - "%s %s HTTP/%s" %d',
                               ('client', 'GET', '/api/events?token=secret', '1.1', 200), None)
    PathOnlyAccess().filter(record)
    assert 'secret' not in record.getMessage() and '?' not in record.getMessage()


def test_existing_app_mounts_companion_with_island_cors(tmp_path, monkeypatch):
    from interfaces.api.app import create_app
    from services import plugin_runtime
    from services.friday_island_server.config import load_config
    monkeypatch.setenv('FRIDAY_ISLAND_CONFIG', str(tmp_path / 'island.json'))
    config = load_config()
    manager = PluginManager(tmp_path / 'code', tmp_path / 'data', bus=EventBus())
    monkeypatch.setattr(plugin_runtime, '_manager', manager)
    client = TestClient(create_app(), base_url='http://127.0.0.1')
    headers = {'Origin': 'http://tauri.localhost', 'X-Friday-Token': config.connection.token}
    try:
        assert client.get('/api/plugins').status_code == 401
        response = client.get('/api/plugins', headers=headers)
        assert response.status_code == 200
        assert response.headers['Access-Control-Allow-Origin'] == headers['Origin']
        assert client.options('/api/plugins', headers={'Origin': headers['Origin'],
                              'Access-Control-Request-Headers': 'x-friday-token'}).status_code == 200
        assert client.get('/api/plugins', headers={**headers, 'Host': 'evil.test'}).status_code == 400
    finally:
        client.close()
        manager.close()
        manager.bus.close()
