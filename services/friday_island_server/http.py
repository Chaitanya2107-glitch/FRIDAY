"""Token-protected HTTP/SSE companion to the existing Island WebSocket bridge."""
from __future__ import annotations

import asyncio
import hmac
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from services.event_bus import validate_topic
from services.friday_island_server.config import load_config
from services.friday_island_server.server import ORIGINS
from services.plugin_runtime import current_manager


def is_plugin_path(path: str) -> bool:
    return path == '/api/events' or path == '/api/plugins' or path.startswith('/api/plugins/')


def allowed_host(host: str) -> bool:
    return bool(re.fullmatch(r'(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?', host, re.I))


def create_router(manager_provider=current_manager, config_provider=load_config) -> APIRouter:
    router = APIRouter()

    async def authorized(request: Request):
        if not allowed_host(request.headers.get('host', '')):
            raise HTTPException(400, 'Invalid localhost Host header')
        if request.client and request.client.host not in {'127.0.0.1', 'testclient'}:
            raise HTTPException(403, 'IPv4 loopback only')
        origin = request.headers.get('origin')
        if origin is not None and origin not in ORIGINS:
            raise HTTPException(403, 'Origin is not FRIDAY Island')
        token = request.headers.get('x-friday-token', '')
        if request.url.path == '/api/events' and not token:
            token = request.query_params.get('token', '')
        config = await asyncio.to_thread(config_provider)
        if not token.isascii() or not hmac.compare_digest(token, config.connection.token):
            raise HTTPException(401, 'FRIDAY token required')
        manager = manager_provider()
        if manager is None:
            raise HTTPException(503, 'FRIDAY plugin host is starting')
        return manager, token

    @router.get('/api/plugins')
    async def plugins(request: Request):
        manager, _ = await authorized(request)
        return {'plugins': await asyncio.to_thread(manager.list_plugins)}

    @router.post('/api/plugins/reload')
    async def reload(request: Request):
        manager, _ = await authorized(request)
        await asyncio.to_thread(manager.scan, force=True)
        return {'ok': True, 'plugins': manager.list_plugins()}

    @router.post('/api/plugins/{plugin_id}/{operation}')
    async def toggle(plugin_id: str, operation: str, request: Request):
        manager, _ = await authorized(request)
        if operation not in {'enable', 'disable'}:
            raise HTTPException(404, 'Unknown plugin operation')
        value = await asyncio.to_thread(manager.set_enabled, plugin_id, operation == 'enable')
        return JSONResponse(value, status_code=404 if value['error'] == 'not_found' else 200)

    @router.post('/api/plugins/{plugin_id}/actions/{action_id}')
    async def action(plugin_id: str, action_id: str, request: Request):
        manager, _ = await authorized(request)
        raw = await request.body()
        if len(raw) > 16384:
            raise HTTPException(413, 'Action payload too large')
        try:
            payload = json.loads(raw or b'{}')
            if not isinstance(payload, dict):
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Action payload must be a JSON object') from None
        return await asyncio.to_thread(manager.action, plugin_id, action_id, payload)

    @router.get('/api/plugins/{plugin_id}/{path:path}')
    async def plugin_route(plugin_id: str, path: str, request: Request):
        manager, _ = await authorized(request)
        value = await asyncio.to_thread(manager.route, plugin_id, path, dict(query=dict(request.query_params)))
        if value is None:
            raise HTTPException(404, 'Plugin route unavailable')
        return value

    @router.get('/api/events')
    async def events(request: Request):
        manager, token = await authorized(request)
        pattern = request.query_params.get('topic', '*')
        try:
            validate_topic(pattern, pattern=True)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        loop = asyncio.get_running_loop()
        pending: asyncio.Queue = asyncio.Queue(maxsize=200)

        def enqueue(event):
            if pending.full():
                pending.get_nowait()
            pending.put_nowait(event)

        def receive(event):
            try:
                loop.call_soon_threadsafe(enqueue, event)
            except RuntimeError:
                pass  # The ASGI connection's loop was already closed.

        async def stream():
            subscription = manager.bus.subscribe(pattern, receive, plugin_id='island-sse')
            try:
                yield ': FRIDAY events\n\n'
                while not await request.is_disconnected():
                    current = await asyncio.to_thread(config_provider)
                    if not hmac.compare_digest(token, current.connection.token):
                        break
                    try:
                        event = await asyncio.wait_for(pending.get(), 1)
                    except TimeoutError:
                        yield ': keepalive\n\n'
                        continue
                    if event['topic'] == 'ui.card':
                        from services.quiet_mode import suppresses
                        if suppresses(event['payload'].get('urgency', 'normal')):
                            continue
                    yield f"id: {event['id']}\nevent: {event['topic']}\ndata: {json.dumps(event, ensure_ascii=False, allow_nan=False)}\n\n"
            finally:
                await asyncio.to_thread(manager.bus.unsubscribe, subscription)

        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    return router


def companion_app(manager, config_path=None):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from .security import protect_access_logs
    protect_access_logs()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(create_router(lambda: manager, lambda: load_config(config_path)))
    app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=['GET', 'POST'],
                       allow_headers=['X-Friday-Token', 'Content-Type'])
    return app
