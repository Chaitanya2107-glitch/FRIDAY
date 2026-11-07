"""Loopback mood bridge for isolated UI checks; never imported by FRIDAY."""
import asyncio
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from services.event_bus import EventBus
from services.friday_island_server.config import load_config
from services.friday_island_server.http import create_router
from services.plugin_manager import PluginManager


def main():
    config = load_config(Path(sys.argv[1]))
    temporary = tempfile.TemporaryDirectory(prefix='friday-mood-probe-')
    manager = PluginManager(ROOT / 'plugins', Path(temporary.name), bus=EventBus())
    discover = manager.discover
    manager.discover = lambda: {key: value for key, value in discover().items() if key in {'focus', 'mood'}}
    manager.scan()
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['http://tauri.localhost', 'https://tauri.localhost', 'tauri://localhost'],
                       allow_methods=['GET', 'POST'], allow_headers=['X-Friday-Token', 'Content-Type'])
    app.include_router(create_router(lambda: manager, lambda: config))

    @app.post('/fixture/command')
    def command(payload: dict, x_friday_token: str = Header(default='')):
        if x_friday_token != config.connection.token:
            raise HTTPException(401)
        return manager.command(payload.get('text', '')) or {'ok': False, 'text': 'Unknown test command'}

    @app.websocket('/')
    async def websocket(ws: WebSocket):
        await ws.accept()
        hello = await ws.receive_json()
        if hello.get('token') != config.connection.token:
            await ws.close()
            return
        async def send(kind, **data):
            await ws.send_json(dict(v=1, type=kind, **data))
        await send('handshake', id=hello['id'], ok=True)
        await send('status', integrated=False, plugin_api_port=config.connection.api_port)
        await send('plugin_list', plugins=[])
        try:
            while True:
                request = await ws.receive_json()
                kind = request['type']
                if kind == 'command':
                    result = await asyncio.to_thread(manager.command, request['text'])
                    await send('command_result', id=request['id'], **(result or {'ok': False, 'text': 'Mood fixture command unavailable.'}))
                elif kind == 'plugin_widget':
                    await send('plugin_widget', id=request['id'], widget={'title': 'Fixture', 'text': ''})
                else:
                    await send(kind, id=request['id'], items=[], plugins=[])
        except Exception:
            pass
    try:
        uvicorn.run(app, host='127.0.0.1', port=config.connection.api_port, log_level='error', access_log=False)
    finally:
        manager.close()
        manager.bus.close()
        temporary.cleanup()


if __name__ == '__main__':
    main()
