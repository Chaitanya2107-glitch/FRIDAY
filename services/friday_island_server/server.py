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


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    v: Literal[1]
    type: Literal["handshake", "command", "suggestions", "plugin_list", "plugin_widget", "plugin_action", "status"]
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=4000)
    token: str = Field(default="", max_length=128)
    plugin: str = Field(default="", max_length=64)
    action: str = Field(default='', max_length=32, pattern=r'^[a-z_]*$')
    item: str = Field(default='', max_length=64)
    value: str = Field(default='', max_length=160)
    revision: int | FiniteFloat | None = None


class Bridge:
    def __init__(self, path: Path | None = None, registry: Registry | None = None, engine: Engine | None = None):
        self.path = path.resolve() if path is not None else None
        self.registry = registry or Registry()
        self.engine = engine or Engine(self.registry)
        self.clients: set[ServerConnection] = set()

    @staticmethod
    async def send(ws: ServerConnection, kind: str, id: str | None = None, **data):
        await ws.send(json.dumps({"v": PROTOCOL_VERSION, "type": kind, "id": id, **data}, ensure_ascii=False))

    async def updates(self, ws: ServerConnection):
        while True:
            snippet = await asyncio.to_thread(self.registry.snippet)
            await self.send(ws, "pill_snippet_update", **snippet)
            await asyncio.sleep(60)

    async def handle(self, ws: ServerConnection):
        if ws.remote_address[0] != "127.0.0.1" or len(self.clients) >= 8:
            await ws.close(1008, "Loopback only or connection limit")
            return
        self.clients.add(ws)
        ticker = None
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
            await self.send(ws, "status", online=True)
            await self.send(ws, "plugin_list", plugins=self.registry.manifests())
            ticker = asyncio.create_task(self.updates(ws))
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
                    if request.type == "command":
                        result = await asyncio.wait_for(self.engine.execute(request.text, config), 60)
                        await self.send(ws, "command_result", request.id, **result)
                    elif request.type == 'plugin_action':
                        plugin = self.registry.plugins.get(request.plugin)
                        handler = getattr(plugin, 'action', None)
                        if handler is None:
                            raise ValueError('Unknown plugin action')
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
                        await self.send(ws, "status", request.id, online=True)
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
