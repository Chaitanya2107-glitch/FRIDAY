"""Isolated loopback bridge for the native HUD check; never imported by FRIDAY."""
import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import secrets
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import psutil

from services.event_bus import EventBus
from services.friday_island_server.config import load_config
from services.friday_island_server.http import create_router
from services.plugin_manager import PluginManager


def main():
    config = load_config(Path(sys.argv[1]))
    temporary = tempfile.TemporaryDirectory(prefix='friday-hud-probe-')
    manager = PluginManager(ROOT / 'plugins', Path(temporary.name), bus=EventBus())
    # Discover only HUD, without loading or modifying the owner's other plugins.
    discover = manager.discover
    manager.discover = lambda: {key: value for key, value in discover().items() if key == 'hud'}
    before = psutil.Process().memory_full_info()
    manager.scan()
    after = psutil.Process().memory_full_info()
    plugin_memory = dict(rss_mib=(after.rss-before.rss)/1048576, private_mib=(after.uss-before.uss)/1048576)
    manager.services['schedule'] = ('hud', SimpleNamespace(next_class=lambda: dict(
        subject='Quantum Mechanics', faculty='Dr. A. Raman', room='Science · 204',
        starts_at=(datetime.now() + timedelta(minutes=10)).isoformat())))
    manager.services['activity'] = ('hud', SimpleNamespace(
        summary=lambda day: {'categories': {'study': 8400, 'work': 3600, 'break': 1800}, 'top_apps': [{'app_name': 'NEVER SHOW THIS'}]},
        is_fullscreen=lambda: False))
    manager.bus.publish('scene.started', {'scene_id': 'study', 'name': 'study', 'since': 0})
    manager.bus.publish('focus.started', {'session_id': 'fixture', 'duration_s': 1500})
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['http://tauri.localhost', 'https://tauri.localhost', 'tauri://localhost'],
                       allow_methods=['GET', 'POST'], allow_headers=['X-Friday-Token', 'Content-Type'])
    app.include_router(create_router(lambda: manager, lambda: config))
    counts = {'stats': 0}
    original_route = manager.route
    def route(plugin, path, request):
        if plugin == 'hud' and path == 'stats': counts['stats'] += 1
        return original_route(plugin, path, request)
    manager.route = route
    def authorized(token):
        if token != config.connection.token: raise HTTPException(401)
    @app.get('/fixture/counts')
    def count(x_friday_token: str = Header(default='')):
        authorized(x_friday_token)
        return counts | {'plugin_memory': plugin_memory}
    @app.post('/fixture/event')
    def event(payload: dict, x_friday_token: str = Header(default='')):
        authorized(x_friday_token)
        manager.bus.publish(payload['topic'], payload['payload'])
        return {'ok': True}
    epoch = secrets.token_hex(12)
    @app.post('/fixture/start')
    def restart(x_friday_token: str = Header(default='')):
        nonlocal epoch
        authorized(x_friday_token)
        epoch = secrets.token_hex(12)
        return {'ok': True}
    @app.websocket('/')
    async def websocket(ws: WebSocket):
        await ws.accept()
        hello = await ws.receive_json()
        if hello.get('token') != config.connection.token: await ws.close(); return
        async def send(kind, **data): await ws.send_json(dict(v=1, type=kind, **data))
        await send('handshake', id=hello['id'], ok=True)
        await send('status', integrated=True, plugin_api_port=config.connection.api_port)
        await send('plugin_list', plugins=[])
        def state():
            return dict(backend=True, epoch=epoch, last=0, provider='local fixture', events=[],
                        body={'listening': False, 'thinking': False, 'speaking': False},
                        desktop={'connected': True, 'listening': False, 'wake': False, 'conversation': False,
                                 'speak': False, 'speak_typed': False, 'body': False, 'owned': False, 'message': ''},
                        system={'mode': {'name': None}, 'screen_watch': {}}, automation={'active': False})
        try:
            while True:
                await send('runtime_state', **state())
                try: request = await asyncio.wait_for(ws.receive_json(), 1)
                except TimeoutError: continue
                kind = request['type']
                if kind == 'command':
                    result = manager.command(request['text']) or {'ok': False, 'text': 'Fixture only supports HUD commands.'}
                    await send('command_result', id=request['id'], **result)
                elif kind == 'plugin_widget': await send('plugin_widget', id=request['id'], widget={'title': 'Fixture', 'text': ''})
                elif kind == 'history': await send('history', id=request['id'], items=[])
                else: await send(kind, id=request['id'], items=[], plugins=[])
        except Exception:
            pass
    try: uvicorn.run(app, host='127.0.0.1', port=config.connection.api_port, log_level='warning', access_log=False)
    finally: manager.close(); manager.bus.close(); temporary.cleanup()


if __name__ == '__main__': main()
