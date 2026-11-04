"""Versioned WebSocket bridge. Authentication precedes all data and actions."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from . import PROTOCOL_VERSION
from .config import load_config
from .engine import Engine
from .plugins import Registry

logger = logging.getLogger(__name__)
ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost", "http://127.0.0.1:1420"]
transport_state = {'ready': False, 'port': None, 'error': ''}


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    hwnd: int = Field(ge=1, le=2**64 - 1)
    pid: int = Field(ge=1, le=2**32 - 1)
    captured_at: FiniteFloat = Field(gt=0)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    v: Literal[1]
    type: Literal["handshake", "command", "suggestions", "plugin_list", "plugin_widget", "plugin_action", "status", "runtime_action", "history", "keyboard_apply", "projects"]
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=4000)
    token: str = Field(default="", max_length=128)
    plugin: str = Field(default="", max_length=64)
    action: str = Field(default='', max_length=32, pattern=r'^[a-z_]*$')
    item: str = Field(default='', max_length=64)
    value: str = Field(default='', max_length=160)
    revision: int | FiniteFloat | None = None
    target: Target | None = None


class Bridge:
    def __init__(self, path: Path | None = None, registry: Registry | None = None, engine: Engine | None = None, runtime=None):
        self.path = path.resolve() if path is not None else None
        self.registry = registry or Registry()
        self.engine = engine or Engine(self.registry)
        self.clients: set[ServerConnection] = set()
        self.runtime = runtime

    @staticmethod
    async def send(ws: ServerConnection, kind: str, id: str | None = None, **data):
        await ws.send(json.dumps({"v": PROTOCOL_VERSION, "type": kind, "id": id, **data}, ensure_ascii=False))

    async def updates(self, ws: ServerConnection, token):
        try:
            await self._updates(ws, token)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning('Island live state unavailable (%s)', type(error).__name__)
            await ws.close(1011, 'FRIDAY state unavailable; reconnect')
        finally:
            if self.runtime:
                from .events import listen
                listen(ws, False)

    async def _updates(self, ws: ServerConnection, token):
        cursor, epoch = None, None
        next_schedule, previous_schedule = 0, None
        while True:
            config = await asyncio.to_thread(load_config, self.path)
            if not hmac.compare_digest(token, config.connection.token):
                await ws.close(1008, 'Token changed; reconnect')
                return
            if time.monotonic() >= next_schedule:
                snippet = await asyncio.to_thread(self.registry.snippet)
                if snippet != previous_schedule:
                    await self.send(ws, "pill_snippet_update", **snippet)
                    previous_schedule = snippet
                next_schedule = time.monotonic() + 5
            if self.runtime:
                state = await self.runtime.snapshot(cursor)
                cursor, epoch = state['last'], state['epoch']
                await self.send(ws, 'runtime_state', **state)
            await asyncio.sleep(1 if self.runtime else 5)

    async def command(self, ws, request, config):
        try:
            head = request.text.strip().split(maxsplit=1)
            if self.runtime and (not head or head[0].casefold() not in self.registry.commands
                                 or (head[0].casefold() == 'next' and len(head) > 1)
                                 or getattr(self.runtime, 'pending', lambda: False)()):
                result = await asyncio.wait_for(self.runtime.command(request.text, ws,
                    request.target.model_dump() if request.target else None), 120)
            else:
                if self.runtime:
                    from .runtime import local_turn
                    from services.mind.cognition import cognition
                    with local_turn(), cognition.operation('feature_request', 'island', 'Local tracker command') as operation:
                        result = await asyncio.wait_for(self.engine.execute(request.text, config), 60)
                        operation.finish('completed' if result.get('ok') else 'failed')
                else:
                    result = await asyncio.wait_for(self.engine.execute(request.text, config), 60)
            await self.send(ws, 'command_result', request.id, **result)
        except ConnectionClosed:
            pass
        except Exception as error:
            logger.warning('Island command failed (%s)', type(error).__name__)
            await self.send(ws, 'error', request.id, code='handler_failed', text='FRIDAY could not complete that command. It was not retried.')

    async def handle(self, ws: ServerConnection):
        if ws.remote_address[0] != "127.0.0.1" or len(self.clients) >= 8:
            await ws.close(1008, "Loopback only or connection limit")
            return
        self.clients.add(ws)
        ticker = None
        work = None
        seen_ids = deque(maxlen=128)
        try:
            config = await asyncio.to_thread(load_config, self.path)
            try:
                first = Request.model_validate_json(await asyncio.wait_for(ws.recv(), 5))
                valid = first.type == "handshake" and hmac.compare_digest(first.token, config.connection.token)
            except (TimeoutError, ValidationError, TypeError):
                valid = False
            if not valid:
                await ws.close(1008, "Invalid handshake")
                return
            token = config.connection.token
            await self.send(ws, "handshake", first.id, ok=True)
            if self.runtime:
                from .events import listen
                listen(ws, True)
            await self.send(ws, "status", online=True, integrated=self.runtime is not None)
            await self.send(ws, "plugin_list", plugins=self.registry.manifests())
            ticker = asyncio.create_task(self.updates(ws, token))
            arrivals: deque[float] = deque()
            async for raw in ws:
                now = time.monotonic()
                while arrivals and arrivals[0] < now - 5:
                    arrivals.popleft()
                if len(arrivals) >= 40:
                    await ws.close(1008, "Rate limit")
                    break
                arrivals.append(now)
                request = None
                try:
                    request = Request.model_validate_json(raw)
                    config = await asyncio.to_thread(load_config, self.path)
                    if not hmac.compare_digest(config.connection.token, token):
                        await ws.close(1008, "Token changed; reconnect")
                        break
                    if request.id in seen_ids:
                        raise ValueError('Duplicate request ID')
                    seen_ids.append(request.id)
                    if request.type == "command":
                        if work and not work.done():
                            raise ValueError('A command is already running')
                        work = asyncio.create_task(self.command(ws, request, config))
                    elif request.type in {'runtime_action', 'history', 'keyboard_apply', 'projects'}:
                        if self.runtime is None:
                            raise ValueError('Full FRIDAY runtime required')
                        if request.type == 'runtime_action':
                            result = await self.runtime.action(request.action, request.value)
                        elif request.type == 'history':
                            result = await self.runtime.history()
                        elif request.type == 'projects':
                            from .projects import catalog, import_profiles
                            result = await asyncio.to_thread(import_profiles if request.action == 'import' else catalog, config)
                        else:
                            result = await self.runtime.apply_keyboard(request.item, ws)
                        await self.send(ws, request.type, request.id, **result)
                    elif request.type == 'plugin_action':
                        plugin = self.registry.plugins.get(request.plugin)
                        handler = getattr(plugin, 'action', None)
                        if handler is None:
                            raise ValueError('Unknown plugin action')
                        if self.runtime:
                            from .runtime import local_turn
                            from services.mind.cognition import cognition
                            with local_turn(), cognition.operation('feature_request', 'island', 'Local tracker operation') as operation:
                                result = await asyncio.wait_for(handler(request.action, request.item, request.value, request.revision), 60)
                                operation.finish('completed' if result.get('ok') else 'failed')
                        else:
                            result = await asyncio.wait_for(handler(request.action, request.item, request.value, request.revision), 60)
                        await self.send(ws, 'command_result', request.id, **result)
                    elif request.type == "suggestions":
                        await self.send(ws, "suggestions", request.id,
                                        items=await asyncio.to_thread(self.engine.suggestions, request.text, config))
                    elif request.type == "plugin_list":
                        await self.send(ws, "plugin_list", request.id, plugins=self.registry.manifests())
                    elif request.type == "plugin_widget":
                        plugin = self.registry.plugins.get(request.plugin)
                        if not plugin:
                            raise ValueError("Unknown plugin")
                        widget = await asyncio.to_thread(plugin.widget) if plugin.manifest.widget else {
                            "title": plugin.manifest.name, "text": ""}
                        await self.send(ws, "plugin_widget", request.id, plugin=request.plugin, widget=widget)
                    elif request.type == "status":
                        await self.send(ws, "status", request.id, online=True, integrated=self.runtime is not None)
                    else:
                        raise ValueError("Already authenticated")
                except (ValidationError, ValueError):
                    await self.send(ws, "error", request.id if request else None,
                                    code="invalid_request", text="Invalid protocol message.")
                except Exception as error:
                    # Never log the token, command text or owner data.
                    logger.warning("Island request failed (%s)", type(error).__name__)
                    await self.send(ws, "error", request.id if request else None,
                                    code="handler_failed", text="FRIDAY could not complete that command.")
        except ConnectionClosed:
            pass
        finally:
            if self.runtime:
                from .events import listen
                listen(ws, False)
            if work:
                # Disconnect never replays actions; let an already submitted action finish.
                await asyncio.gather(work, return_exceptions=True)
            if self.runtime:
                self.runtime.disconnect(ws)
            if ticker:
                ticker.cancel()
                await asyncio.gather(ticker, return_exceptions=True)
            self.clients.discard(ws)

    async def run(self):
        config = await asyncio.to_thread(load_config, self.path)
        async with serve(self.handle, "127.0.0.1", config.connection.port, origins=ORIGINS,
                         max_size=16384, max_queue=16, compression=None):
            logger.info("Island bridge listening on 127.0.0.1:%d", config.connection.port)
            await asyncio.Future()


async def run_integrated_bridge():
    from .runtime import FridayRuntime
    bridge = Bridge(runtime=FridayRuntime())
    migrated = False
    while True:
        try:
            config = await asyncio.to_thread(load_config)
            async with serve(bridge.handle, '127.0.0.1', config.connection.port, origins=ORIGINS,
                             max_size=16384, max_queue=16, compression=None):
                if not migrated and config.projects:
                    from .projects import import_profiles
                    try:
                        await asyncio.to_thread(import_profiles, config)
                    except (ValueError, OSError) as error:
                        logger.warning('Project folders need review (%s)', type(error).__name__)
                    migrated = True
                transport_state.update(ready=True, port=config.connection.port, error='')
                while True:
                    await asyncio.sleep(1)
                    current = await asyncio.to_thread(load_config)
                    if current.connection.port != config.connection.port:
                        break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            kind = type(error).__name__
            if transport_state['error'] != kind:
                logger.error('FRIDAY Island transport unavailable (%s)', kind)
            transport_state.update(error=kind)
            await asyncio.sleep(2)
        finally:
            transport_state.update(ready=False)
