"""Real release WebView2 + authenticated bridge + isolated shared tracker database.

Close the ordinary Island first. No owner records, providers or launch actions.
  venv/Scripts/python.exe -B tests/island/check_plugins_native.py
"""
import asyncio
import ctypes as c
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_native import ROOT, u, w
from check_apps_native import port
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
from websockets.asyncio.server import serve
from services.friday_island_server.config import load_config
from services.friday_island_server.plugins import CollegePlugin, Registry
from services.friday_island_server.productivity import TrackerPlugin
from services.friday_island_server.server import Bridge, ORIGINS
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.productivity.store import Tracker


def main():
    output = ROOT / 'tasks/island-plugins-native'; output.mkdir(exist_ok=True)
    original_cursor = w.POINT(); u.GetCursorPos(c.byref(original_cursor))
    executable = ROOT / 'island/src-tauri/target/release/friday-island.exe'
    evidence = {'artifact_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(dir=output) as temp:
        path = Path(temp) / 'config.json'; config = load_config(path)
        config.hotkeys.sneak, config.hotkeys.expand = 'Ctrl+Shift+Alt+F23', 'Ctrl+Shift+Alt+F24'
        store = Tracker(Workspace(Cognition(Path(temp) / 'tracker.db')))
        start = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
        college = CollegePlugin(lambda: {'subject': 'Island test class', 'date': start.date().isoformat(), 'start': start.strftime('%H:%M')})
        bridge = Bridge(path, Registry([college, TrackerPlugin('todo', store), TrackerPlugin('habit', store)]))
        stop, ready = threading.Event(), threading.Event(); errors = []; loop = None
        def worker():
            async def serve_fixture():
                nonlocal loop
                loop = asyncio.get_running_loop()
                try:
                    async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server:
                        config.connection.port = server.sockets[0].getsockname()[1]
                        path.write_text(config.model_dump_json(indent=2), encoding='utf-8'); ready.set()
                        while not stop.is_set(): await asyncio.sleep(.05)
                except Exception as error: errors.append(type(error).__name__); ready.set()
            asyncio.run(serve_fixture())
        thread = threading.Thread(target=worker, daemon=True); thread.start()
        assert ready.wait(5) and not errors, errors
        app = browser = None
        log = (output / 'app.log').open('w', encoding='utf-8')
        try:
            with sync_playwright() as playwright:
                debug_port = port()
                env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(path),
                           WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1')
                u.SetCursorPos(u.GetSystemMetrics(0)//2, 450)
                app = subprocess.Popen([str(executable)], cwd=ROOT / 'island', env=env, stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}', timeout=400); break
                    except Exception:
                        assert app.poll() is None, 'Island exited'
                        time.sleep(.15)
                assert browser, 'WebView2 did not start'
                page = browser.contexts[0].pages[0]
                expect(page.locator('.capsule-reminder')).to_contain_text('Island test class')
                expect(page.locator('.clock-date')).to_be_hidden()
                evidence['authenticated_timed_reminder'] = True
                page.locator('.island-row').hover()
                page.get_by_role('button', name='Projects', exact=True).click()
                page.get_by_role('button', name='Plugins', exact=True).click()
                todos, habits = page.locator('[data-plugin="todo"]'), page.locator('[data-plugin="habit_tracker"]')
                todo = page.get_by_role('textbox', name='New todo', exact=True)
                todo.click(); todo.fill('Native fixture task'); todo.press('Enter')
                expect(todos).to_contain_text('Native fixture task')
                todos.get_by_role('button', name='Done Native fixture task', exact=True).click()
                expect(todos).to_contain_text('All clear')
                habit = page.get_by_role('textbox', name='New habit', exact=True)
                habit.click(); habit.fill('Native daily habit'); habit.press('Enter')
                habits.get_by_role('button', name='Check in Native daily habit', exact=True).click()
                expect(habits).to_contain_text('1 day streak')
                page.screenshot(path=str(output / 'widgets.png'))
                restarted = Tracker(Workspace(Cognition(Path(temp) / 'tracker.db'))).snapshot()
                assert restarted['tasks'][0]['status'] == 'completed'
                assert restarted['habits'][0]['streak'] == 1
                evidence['release_widgets_and_shared_persistence'] = True
                async def clear_reminder():
                    college.now = lambda: start
                    for ws in tuple(bridge.clients): await bridge.send(ws, 'pill_snippet_update', **bridge.registry.snippet())
                asyncio.run_coroutine_threadsafe(clear_reminder(), loop).result(timeout=3)
                page.keyboard.press('Escape')
                expect(page.locator('.surface')).to_have_attribute('data-mode', 'rest')
                expect(page.locator('.clock-date')).to_be_visible()
                evidence['expired_class_restores_date'] = True
                evidence['dpi_scale'] = page.evaluate('devicePixelRatio')
                browser.close(); browser = None
        finally:
            if app and app.poll() is None: app.terminate(); app.wait(timeout=10)
            stop.set(); thread.join(timeout=5); log.close()
            u.SetCursorPos(original_cursor.x, original_cursor.y)
        paths = [*sorted((ROOT/'island/src').glob('*')), *sorted((ROOT/'services/friday_island_server').glob('*.py')),
                 *sorted((ROOT/'services/productivity').glob('*.py')),
                 ROOT/'services/mind/workspace.py', ROOT/'services/mind/cognition.py', ROOT/'services/proactive/timetable.py']
        manifest = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
        evidence['integration_source_sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        (output/'source.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (output/'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence, indent=2))
        print('PASS: native release tracker widgets, authenticated bridge, shared persistence and expiring class date swap')


if __name__ == '__main__': main()
