"""Real shared persistence behind the Island, always using a temporary database."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from services.friday_island_server.config import load_config
from services.friday_island_server.engine import Engine
from services.friday_island_server.plugins import CollegePlugin, Registry
from services.friday_island_server.productivity import TrackerPlugin
from services.friday_island_server.server import Bridge, ORIGINS, Request
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.productivity.store import Tracker


class TrackerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'cognition.db'
        self.store = Tracker(Workspace(Cognition(self.db)))
        self.todo, self.habits = TrackerPlugin('todo', self.store), TrackerPlugin('habit', self.store)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_commands_persist_and_use_real_streaks(self):
        self.assertTrue((await self.todo.command('todo buy charger'))['ok'])
        self.assertTrue((await self.habits.command('habit add Read 20 pages'))['ok'])
        self.assertTrue((await self.habits.command('habit check Read 20 pages'))['ok'])
        restarted = Tracker(Workspace(Cognition(self.db)))
        data = restarted.snapshot()
        self.assertEqual(data['tasks'][0]['title'], 'buy charger')
        self.assertEqual(data['habits'][0]['checks'], [date.today().isoformat()])
        self.assertEqual(data['habits'][0]['streak'], 1)
        self.assertIn('1 day streak', (await self.habits.command('habit'))['text'])
        self.assertTrue((await self.todo.command('todo done buy charger'))['ok'])
        self.assertEqual(restarted.snapshot()['tasks'][0]['status'], 'completed')
        self.assertTrue((await self.habits.command('habit undo Read 20 pages'))['ok'])
        self.assertEqual(restarted.snapshot()['habits'][0]['checks'], [])

    async def test_widget_revisions_unknown_actions_and_midnight_are_safe(self):
        await self.habits.command('habit add Walk')
        button = self.habits.widget()['items'][0]['action']
        args = {k: button[k] for k in ['action', 'item', 'revision', 'value']}
        self.assertTrue((await self.habits.action(**args))['ok'])
        # Repeating a stale click neither loses a check-in nor appends another one.
        self.assertFalse((await self.habits.action(**args))['ok'])
        current = self.habits.widget()['items'][0]['action']
        self.assertFalse((await self.habits.action('uncheck', current['item'], '1999-01-01', current['revision']))['ok'])
        self.assertFalse((await self.habits.action('uncheck', current['item'], current['value']))['ok'])
        self.assertFalse((await self.habits.action('launch', 'cmd.exe'))['ok'])
        self.assertEqual(len(self.store.snapshot()['habits'][0]['checks']), 1)

    async def test_task_conflicts_plans_and_limits_are_preserved(self):
        ident = self.store.save_task('A task')
        old = self.todo.widget()['items'][0]['action']
        self.store.save_task('Renamed elsewhere', ident=ident, revision=old['revision'])
        self.assertFalse((await self.todo.action('complete', str(ident), revision=old['revision']))['ok'])
        planned = self.store.work.start_task('A planned task')
        self.store.work.plan(planned, ['Review', 'Ship'])
        self.assertFalse((await self.todo.command(f'todo done #{planned}'))['ok'])
        self.assertFalse((await self.todo.command('todo add ' + 'x' * 161))['ok'])
        self.assertTrue(all(t['status'] == 'active' for t in self.store.snapshot()['tasks']))
        self.assertTrue(any(s['text'] == f'todo done #{ident}' for s in self.todo.suggestions('todo done Renamed')))

    async def test_widget_actions_authenticate_and_update_real_database(self):
        config_path = Path(self.temp.name) / 'config.json'
        config = load_config(config_path)
        registry = Registry([self.todo, self.habits])
        bridge = Bridge(config_path, registry, Engine(registry))
        async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server:
            url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async with connect(url, origin=ORIGINS[0]) as ws:
                await ws.send(json.dumps({'v': 1, 'type': 'handshake', 'id': 'hi', 'token': config.connection.token}))
                while json.loads(await ws.recv())['type'] != 'handshake': pass
                for request, response in [
                    ({'type': 'plugin_action', 'plugin': 'todo', 'action': 'add', 'value': 'Saved through socket'}, 'command_result'),
                    ({'type': 'plugin_widget', 'plugin': 'todo'}, 'plugin_widget'),
                    ({'type': 'plugin_action', 'plugin': 'missing', 'action': 'add', 'value': 'Must not save'}, 'error'),
                ]:
                    await ws.send(json.dumps({'v': 1, 'id': response, **request}))
                    while True:
                        result = json.loads(await ws.recv())
                        if result.get('id') == response: break
                    self.assertEqual(result['type'], response)
                    if response == 'plugin_widget':
                        self.assertEqual(result['widget']['items'][0]['label'], 'Saved through socket')
        self.assertEqual(len(self.store.snapshot()['tasks']), 1)
        for revision in [True, '123', float('nan')]:
            with self.assertRaises(ValidationError):
                Request.model_validate({'v': 1, 'type': 'plugin_action', 'id': 'bad', 'revision': revision})

    async def test_reminder_has_exact_local_expiry_and_no_all_day_snippet(self):
        now = datetime(2026, 10, 31, 10, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        plugin = CollegePlugin(lambda: {'subject': 'DBMS', 'date': '2026-10-31', 'start': '10:30'}, now=lambda: now)
        frame = Registry([plugin]).snippet()
        self.assertEqual(frame['expires_at'], int(now.replace(minute=30).timestamp() * 1000))
        self.assertEqual(frame['show_from'], frame['expires_at'] - 15 * 60 * 1000)
        plugin.now = lambda: now.replace(minute=30)
        self.assertEqual(Registry([plugin]).snippet(), {'plugin': None, 'text': ''})
        self.assertEqual(self.todo.snippet(), '')
        self.assertEqual(self.habits.snippet(), '')

    async def test_grammar_whitespace_never_creates_accidental_tasks_and_lists_more_than_six(self):
        for i in range(7):
            self.store.save_task(f'Item {i}')
        registry = Registry([self.todo])
        engine = Engine(registry)
        config = load_config(Path(self.temp.name) / 'config.json')
        result = await engine.execute('todo  list', config)
        self.assertIn('Item 0', result['text'])
        self.assertEqual(len(self.store.snapshot()['tasks']), 7)
        self.assertTrue((await engine.execute('todo\t done   #1', config))['ok'])
        self.assertEqual(len(self.store.snapshot()['tasks']), 7)
        self.assertEqual(next(t for t in self.store.snapshot()['tasks'] if t['id'] == 1)['status'], 'completed')
