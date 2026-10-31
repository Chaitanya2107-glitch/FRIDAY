"""Isolated tests: python -m unittest discover -s tests/island -v."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

from services.friday_island_server.config import IslandConfig, Pin, Project, load_config
from services.friday_island_server.engine import Engine
from services.friday_island_server.plugins import CollegePlugin, Manifest, Registry
from services.friday_island_server.server import Bridge, ORIGINS


class ConfigTests(unittest.TestCase):
    def test_indexed_favourites_and_recents_roundtrip(self):
        ref = "app-" + "a" * 32
        config = IslandConfig.model_validate({"pins": [{"id": ref, "name": "Calculator", "app_id": ref}],
                                              "recent_apps": [{"id": ref, "last_used": 12345, "count": 3}]})
        self.assertEqual(config.pins[0].path, "")
        self.assertEqual(IslandConfig.model_validate_json(config.model_dump_json()).recent_apps[0].count, 3)
        for invalid in [{"pins": [{"id": "x", "name": "X", "app_id": ref, "path": "C:/app.exe"}]},
                        {"pins": [{"id": "x", "name": "X", "app_id": "C:/app.exe"}]}]:
            with self.assertRaises(ValidationError): IslandConfig.model_validate(invalid)

    def test_missing_token_is_materialized_without_losing_hand_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for partial in [{"appearance": {"glow": "#FF9900"}}, {"connection": {"port": 18001}}]:
                path.write_text(json.dumps(partial), encoding="utf-8")
                first = load_config(path)
                self.assertEqual(first.connection.token, load_config(path).connection.token)
                saved = json.loads(path.read_text())
                self.assertEqual(first.connection.token, saved["connection"]["token"])
                self.assertEqual(first.appearance.glow, partial.get("appearance", {}).get("glow", "#FFB347"))

    def test_first_run_roundtrip_and_corruption_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            first = load_config(path)
            self.assertEqual(first.connection.token, load_config(path).connection.token)
            self.assertEqual(len(first.connection.token), 64)
            path.write_text("{broken hand edit", encoding="utf-8")
            self.assertEqual(load_config(path).version, 1)
            self.assertEqual(next(path.parent.glob("config.corrupt-*.json")).read_text(), "{broken hand edit")

    def test_validation_rejects_unsafe_config(self):
        for change in [
            {"connection": {"port": 80}}, {"appearance": {"glow": "red"}}, {"version": 2},
            {"pins": [{"id": "x", "name": "x", "path": "cmd.bat"}]},
            {"pins": [{"id": "x", "name": "x", "path": "C:/a/../b.exe"}]},
            {"projects": [{"id": "x", "name": "x", "path": "C:/x", "actions": [{"kind": "url", "url": "javascript:alert(1)"}]}]},
            {"projects": [{"id": "x", "name": "x", "path": "C:/x", "actions": [{"kind": "editor", "executable": "cmd"}]}]},
        ]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                IslandConfig.model_validate(change)

    def test_concurrent_initialization_has_one_token(self):
        import concurrent.futures
        with tempfile.TemporaryDirectory() as directory, concurrent.futures.ThreadPoolExecutor(4) as pool:
            path = Path(directory) / "config.json"
            tokens = list(pool.map(lambda _: load_config(path).connection.token, range(8)))
            self.assertEqual(len(set(tokens)), 1)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []

        async def assistant(text):
            self.seen.append(text)
            return "Tool-free answer"

        self.engine = Engine(Registry([CollegePlugin(lambda: {"subject": "DBMS", "start": "10:30"})]), assistant)
        self.config = IslandConfig(pins=[Pin(id="editor", name="Editor", path="C:/editor.exe")],
                                   projects=[Project(id="friday", name="FRIDAY", path="C:/FRIDAY")])

    async def test_fuzzy_match_returns_only_configured_id(self):
        result = await self.engine.execute("proj fri", self.config)
        self.assertEqual(result["action"], {"kind": "project", "id": "friday"})
        result = await self.engine.execute("open edit", self.config)
        self.assertEqual(result["action"], {"kind": "app_search", "query": "edit"})
        # Python never resolves an executable or launches it; native catalog enforces this.
        self.assertEqual((await self.engine.execute("open powershell; rm", self.config))["action"]["kind"], "app_search")
        self.assertEqual(self.seen, [])

    async def test_ambiguous_and_hidden_pins_are_not_launched(self):
        self.config.pins[0].visible = False
        self.assertEqual((await self.engine.execute("open editor", self.config))["action"]["kind"], "app_search")
        self.config.projects.append(Project(id="other", name="FRIDAY Test", path="C:/test"))
        self.assertFalse((await self.engine.execute("proj fri", self.config))["ok"])
        self.assertEqual((await self.engine.execute("proj FRIDAY", self.config))["action"]["id"], "friday")

    async def test_plugins_suggestions_and_conversation(self):
        self.assertIn("DBMS", (await self.engine.execute("next", self.config))["text"])
        self.assertEqual(self.engine.suggestions("proj fri", self.config)[0]["text"], "proj FRIDAY")
        self.assertEqual((await self.engine.execute("hello FRIDAY", self.config))["text"], "Tool-free answer")
        self.assertEqual(self.seen, ["hello FRIDAY"])
        self.assertEqual(len(Registry().manifests()), 3)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "config.json"
        self.config = load_config(self.path)
        registry = Registry([CollegePlugin(lambda: {"subject": "DBMS", "start": "10:30"})])
        self.bridge = Bridge(self.path, registry, Engine(registry, self.answer))
        self.server = await serve(self.bridge.handle, "127.0.0.1", 0, origins=ORIGINS, max_size=16384)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def answer(self, text):
        if text == "fail":
            raise RuntimeError("Private exception")
        return "Hello"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.directory.cleanup()

    async def handshake(self, ws, **overrides):
        await ws.send(json.dumps({"v": 1, "type": "handshake", "id": "hello",
                                  "token": self.config.connection.token, **overrides}))

    async def response(self, ws, kind, id=None):
        for _ in range(10):
            result = json.loads(await asyncio.wait_for(ws.recv(), 2))
            if result["type"] == kind and (id is None or result["id"] == id):
                return result
        self.fail("Missing response")

    async def test_origin_token_and_version_rejected_before_data(self):
        with self.assertRaises(InvalidStatus):
            async with connect(self.url, origin="https://evil.example"):
                pass
        for fields in [{"token": "wrong"}, {"v": 2}, {"type": "command", "text": "next"}]:
            async with connect(self.url, origin=ORIGINS[0]) as ws:
                await self.handshake(ws, **fields)
                with self.assertRaises(ConnectionClosed):
                    await ws.recv()
                self.assertEqual(ws.close_code, 1008)

    async def test_authenticated_messages_errors_and_recovery(self):
        class CommandOnly:
            manifest = Manifest("command_only", "Commands only", ("helpme",), widget=False)
            def snippet(self): return ""
            async def command(self, text): return {"ok": True, "text": "Hello"}

        self.bridge.registry.register(CommandOnly())
        async with connect(self.url, origin=ORIGINS[0]) as ws:
            await self.handshake(ws)
            self.assertTrue((await self.response(ws, "handshake"))["ok"])
            self.assertEqual((await self.response(ws, "pill_snippet_update"))["text"], "Next: DBMS · 10:30")
            for kind, data in [("command", {"text": "next"}), ("suggestions", {"text": "ne"}),
                               ("plugin_widget", {"plugin": "college_schedule"})]:
                await ws.send(json.dumps({"v": 1, "type": kind, "id": kind, **data}))
                expected = "command_result" if kind == "command" else kind
                self.assertEqual((await self.response(ws, expected))["id"], kind)
            await ws.send(json.dumps({"v": 1, "type": "plugin_widget", "id": "optional", "plugin": "command_only"}))
            self.assertEqual((await self.response(ws, "plugin_widget", "optional"))["widget"], {"title": "Commands only", "text": ""})
            await ws.send("{bad json")
            self.assertEqual((await self.response(ws, "error"))["code"], "invalid_request")
            await ws.send(json.dumps({"v": 1, "type": "command", "id": "err", "text": "fail"}))
            self.assertNotIn("Private", (await self.response(ws, "error", "err"))["text"])
            await ws.send(json.dumps({"v": 1, "type": "command", "id": "ok", "text": "hi"}))
            self.assertEqual((await self.response(ws, "command_result", "ok"))["text"], "Hello")
