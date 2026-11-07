"""Owned Windows/WebView2 smoke test and source-bound resource benchmark.

Temporarily closes Island (its full FRIDAY backend remains running), then restores
the current release. Test config, token, services and data are temporary.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import psutil
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tasks' / 'hud'))
from measure import measure
sys.path.insert(0, str(Path(__file__).parent))
from check_native import u, CALLBACK

u.GetWindow.argtypes = [w.HWND, w.UINT]; u.GetWindow.restype = w.HWND
u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u.IsWindowVisible.argtypes = [w.HWND]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]


def until(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result: return result
        except Exception:
            pass
        time.sleep(.1)
    raise AssertionError('Timed out waiting for native condition')


def windows():
    found = []
    def collect(hwnd, _):
        name = c.create_unicode_buffer(256); title = c.create_unicode_buffer(128)
        u.GetClassNameW(hwnd, name, 256); u.GetWindowTextW(hwnd, title, 128)
        pid = w.DWORD(); u.GetWindowThreadProcessId(hwnd, c.byref(pid))
        found.append((hwnd, name.value, title.value, pid.value, bool(u.IsWindowVisible(hwnd))))
        return True
    u.EnumWindows(CALLBACK(collect), 0)
    return found


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--seconds', type=int, default=35)
    parser.add_argument('--skip-baseline', action='store_true'); args = parser.parse_args()
    output = ROOT / 'tasks' / 'hud'; output.mkdir(exist_ok=True)
    executable = ROOT / 'island/src-tauri/target/release/friday-island.exe'
    receipt = {'os': __import__('platform').platform(), 'warmup_seconds': 12,
               'candidate_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(), 'checks': {}}
    checks = receipt['checks']
    fixture = app = browser = None
    owned = None
    log = (output / 'native.log').open('w', encoding='utf-8')
    # Full desktop FRIDAY processes intentionally survive Island restarts.
    original = [p for p in psutil.process_iter(['name']) if p.info['name'] == 'friday-island.exe']
    subprocess.run([str(executable), '--quit'], creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    for process in original:
        try: process.wait(timeout=10)
        except psutil.NoSuchProcess: pass
    with tempfile.TemporaryDirectory(prefix='friday-hud-native-') as temporary, sync_playwright() as playwright:
        config = Path(temporary) / 'config.json'
        api_port, token = port(), __import__('secrets').token_hex(32)
        config.write_text(json.dumps(dict(connection=dict(port=api_port, api_port=api_port, token=token),
            startup=dict(manage_bridge=False), user_name='Chaitanya',
            hotkeys=dict(sneak='Ctrl+Shift+Alt+F21', expand='Ctrl+Shift+Alt+F22', hud='Ctrl+Shift+Alt+F23'))), encoding='utf-8')
        fixture = subprocess.Popen([str(ROOT / 'venv/Scripts/python.exe'), '-B', str(Path(__file__).with_name('hud_fixture.py')), str(config)],
                                   cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        client = httpx.Client(base_url=f'http://127.0.0.1:{api_port}', headers={'X-Friday-Token': token}, trust_env=False, timeout=4)
        until(lambda: client.get('/api/plugins/hud/state').status_code == 200)
        assert client.post('/api/plugins/hud/actions/settings', json={'hide_fullscreen': False}).json()['ok']
        owned = u.CreateWindowExW(0, 'STATIC', 'FRIDAY HUD owned fixture', 0x10CF0000, 20, 100, 800, 600, None, None, None, None)
        assert owned
        u.SetForegroundWindow(owned)
        def launch(binary):
            nonlocal app, browser
            debug = port()
            env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config), FRIDAY_ISLAND_MANAGE_BRIDGE='0',
                       WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug} --remote-debugging-address=127.0.0.1')
            app = subprocess.Popen([str(binary), '--background'], cwd=ROOT / 'island', env=env,
                                   stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            browser = until(lambda: playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug}', timeout=500))
            main_page = until(lambda: next((p for p in browser.contexts[0].pages if 'hud.html' not in p.url), None))
            main_page.on('pageerror', lambda error: receipt.setdefault('page_errors', []).append(str(error)))
            main_page.on('console', lambda message: receipt.setdefault('console_errors', []).append(message.text) if message.type == 'error' else None)
            main_page.wait_for_selector('.surface'); return main_page
        def stop():
            nonlocal app, browser
            if browser: browser.close(); browser = None
            if app and app.poll() is None:
                app.terminate(); app.wait(timeout=10)
            app = None
            time.sleep(1)
        def backend():
            root = psutil.Process(fixture.pid)
            cpu, rss, private = 0, 0, 0
            for process in [root, *root.children(recursive=True)]:
                times = process.cpu_times(); memory = process.memory_full_info()
                cpu += times.user+times.system; rss += memory.rss; private += memory.uss
            return dict(at=time.perf_counter(), cpu=cpu, rss=rss/1048576, private=private/1048576)
        def resource():
            before = backend(); data = measure(app.pid, args.seconds); after = backend()
            data['backend_cpu'] = 100 * (after['cpu']-before['cpu'])/(after['at']-before['at'])
            data['backend_rss_mib'] = after['rss']; data['backend_private_mib'] = after['private']
            return data
        try:
            if not args.skip_baseline:
                launch(output / 'baseline.exe'); time.sleep(12)
                receipt['baseline'] = resource(); stop()
                print(json.dumps({'baseline_cpu_machine': receipt['baseline']['cpu_machine_mean'],
                                  'baseline_private_mib': receipt['baseline']['private_working_set_mib']}), flush=True)
            page = launch(executable)
            page.reload(); page.wait_for_selector('.surface')
            client.post('/fixture/start')
            try:
                page.wait_for_function("() => document.querySelector('.surface').classList.contains('booting')", timeout=6000)
            except Exception:
                receipt['boot_debug'] = {'text': page.locator('body').inner_text(),
                    'status': page.evaluate("() => window.__TAURI_INTERNALS__.invoke('runtime_status')"),
                    'classes': page.locator('.surface').get_attribute('class'),
                    'connection': page.evaluate("async () => {const c=await window.__TAURI_INTERNALS__.invoke('get_config');return {port:c.connection.port, api_port:c.connection.api_port};}"),
                    'marker_saved': bool(json.loads(config.read_text()).get('island', {}).get('last_boot_epoch'))}
                page.screenshot(path=str(output / 'boot-debug.png'))
                raise
            checks['boot_started'] = True
            checks['boot_sweep_and_eyes'] = page.evaluate("() => getComputedStyle(document.querySelector('.boot-ring rect')).animationName === 'boot-sweep' && (document.querySelector('.surface').classList.contains('boot-reduced') || getComputedStyle(document.querySelector('.character .eyes')).animationName === 'boot-eyes')")
            page.screenshot(path=str(output / 'boot.png'))
            page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'x',bubbles:true}))")
            page.wait_for_function("() => !document.querySelector('.surface').classList.contains('booting')")
            checks['boot_skip'] = True
            hud = until(lambda: next((p for p in browser.contexts[0].pages if 'hud.html' in p.url), None))
            hud.on('pageerror', lambda error: receipt.setdefault('hud_errors', []).append(str(error)))
            try:
                hud.wait_for_selector('#hud.shown', timeout=5000)
                hud.wait_for_function("() => /^\\d/.test(document.querySelector('.gauge-number').textContent)", timeout=8000)
            except Exception:
                receipt['hud_debug'] = {'text': hud.locator('body').inner_text(), 'counts': client.get('/fixture/counts').json(),
                                       'state_status': client.get('/api/plugins/hud/state').status_code,
                                       'stats_status': client.get('/api/plugins/hud/stats').status_code}
                receipt['hud_debug']['native'] = hud.evaluate("""async () => {
                  const api=window.__TAURI_INTERNALS__;
                  return await new Promise(async (resolve,reject)=> {
                    const handler=api.transformCallback(event=>resolve(event.payload),false);
                    await api.invoke('plugin:event|listen',{event:'hud-status',target:{kind:'Any'},handler});
                    await api.invoke('hud_ready');setTimeout(()=>reject('no native status'),2000);
                  });
                }""")
                hud.screenshot(path=str(output / 'hud-debug.png'))
                raise
            def invoke(command, args=None): return page.evaluate('([cmd,args]) => window.__TAURI_INTERNALS__.invoke(cmd,args)', [command, args or {}])
            def command(text):
                # This is the real plugin handler and protected action route; no model call.
                result = client.post('/api/plugins/hud/actions/settings', json={})
                assert result.json()['ok']
                return page.evaluate("async text => { const ws = new WebSocket('ws://127.0.0.1:'+ (await window.__TAURI_INTERNALS__.invoke('get_config')).connection.port); return await new Promise(async (resolve,reject)=> { ws.onopen=async()=>ws.send(JSON.stringify({v:1,type:'handshake',id:'hello',token:(await window.__TAURI_INTERNALS__.invoke('get_config')).connection.token})); ws.onmessage=e=>{const f=JSON.parse(e.data);if(f.type==='handshake')ws.send(JSON.stringify({v:1,type:'command',id:'cmd',text}));if(f.id==='cmd'){ws.close();resolve(f);}};ws.onerror=reject;}); }", text)
            hwnd = until(lambda: next((row[0] for row in windows() if row[2] == 'FRIDAY HUD' and row[3] == app.pid), None))
            main_hwnd = next(row[0] for row in windows() if row[2] == 'FRIDAY Island' and row[3] == app.pid)
            checks['dpi'] = u.GetDpiForWindow(hwnd)
            exstyle = u.GetWindowLongPtrW(hwnd, -20)
            receipt['hud_exstyle'] = hex(exstyle)
            checks['toolwindow_noactivate_clickthrough'] = bool(exstyle & 0x80 and exstyle & 0x08000000 and exstyle & 0x20)
            assert checks['toolwindow_noactivate_clickthrough']
            checks['all_available_widgets_rendered'] = hud.evaluate("[...document.querySelectorAll('#hud > section')].filter(n=>!n.hidden).length >= 5")
            checks['no_app_names'] = 'NEVER SHOW THIS' not in hud.locator('body').inner_text()
            checks['layout_fits'] = hud.evaluate("document.querySelector('#hud').scrollHeight <= innerHeight")
            hud.screenshot(path=str(output / 'hud.png'))
            ordered = windows(); index = next(i for i, row in enumerate(ordered) if row[0] == hwnd)
            shell = [(i, row[1]) for i, row in enumerate(ordered) if row[1] in ('Progman', 'WorkerW') and row[4]]
            checks['desktop_above_wallpaper'] = bool(shell) and all(index < i for i, _ in shell)
            receipt['desktop_probe'] = dict(hud_index=index, shell_indices=shell, method='Tauri persistent always_on_bottom / HWND_BOTTOM')
            print(json.dumps({'native_checks': checks}), flush=True)
            assert checks['layout_fits'], 'HUD content clips at the selected size'
            assert command('hud layer top')['ok']; time.sleep(1)
            u.SetForegroundWindow(owned)
            rect = w.RECT(); u.GetWindowRect(hwnd, c.byref(rect))
            point = w.POINT(rect.left+50, rect.top+50)
            hit = u.WindowFromPoint(point)
            checks['native_hit_passes_through'] = u.GetAncestor(hit, 2) != hwnd
            assert checks['native_hit_passes_through']
            assert command('hud edit')['ok']
            until(lambda: hud.locator('#hud').evaluate("n=>n.classList.contains('editing')"))
            checks['edit_accepts_clicks'] = not bool(u.GetWindowLongPtrW(hwnd, -20) & 0x20)
            old = invoke('hud_geometry')
            rect = w.RECT(); u.GetWindowRect(hwnd, c.byref(rect))
            u.SetWindowPos(hwnd, None, rect.left+15, rect.top+10, rect.right-rect.left+10, rect.bottom-rect.top, 0x14)
            assert command('hud done')['ok']
            until(lambda: bool(u.GetWindowLongPtrW(hwnd, -20) & 0x20))
            saved = client.get('/api/plugins/hud/state').json()['settings']
            checks['done_saved_geometry'] = saved['x'] != old['x'] and saved['width'] != old['width']
            # Native foreground covers its monitor: fullscreen hide then restore.
            u.SetWindowPos(owned, None, 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1), 0x14)
            u.SetForegroundWindow(owned)
            client.post('/api/plugins/hud/actions/settings', json={'hide_fullscreen': True})
            until(lambda: not u.IsWindowVisible(hwnd))
            checks['fullscreen_hides'] = True
            count = client.get('/fixture/counts').json()['stats']; time.sleep(3)
            checks['hidden_stops_stats'] = client.get('/fixture/counts').json()['stats'] == count
            u.SetWindowPos(owned, None, 20, 100, 800, 600, 0x14)
            client.post('/api/plugins/hud/actions/settings', json={'hide_fullscreen': False})
            until(lambda: u.IsWindowVisible(hwnd))
            client.post('/fixture/event', json={'topic': 'scene.started', 'payload': {'scene_id': 'game', 'name': 'game', 'since': time.time()}})
            until(lambda: not u.IsWindowVisible(hwnd)); checks['game_scene_hides'] = True
            client.post('/fixture/event', json={'topic': 'scene.ended', 'payload': {'scene_id': 'game', 'name': 'game'}})
            until(lambda: u.IsWindowVisible(hwnd)); checks['game_scene_restores'] = True
            assert command('hud saver on')['ok']; time.sleep(1)
            count = client.get('/fixture/counts').json()['stats']; time.sleep(6)
            checks['saver_five_second_polling'] = 1 <= client.get('/fixture/counts').json()['stats']-count <= 2
            assert hud.locator('#hud').evaluate("n=>n.classList.contains('saver')")
            assert command('hud saver off')['ok']
            assert command('hud off')['ok']; until(lambda: not u.IsWindowVisible(hwnd))
            assert command('hud on')['ok']; until(lambda: u.IsWindowVisible(hwnd))
            checks['on_off'] = True
            assert command('hud layer desktop')['ok']
            # Keep no foreground fullscreen fixture during idle measurement.
            time.sleep(12)
            receipt['candidate'] = resource()
            baseline = receipt.get('baseline')
            if baseline:
                candidate = receipt['candidate']
                receipt['increment_rss_mib'] = candidate['rss_mib']-baseline['rss_mib'] + candidate['backend_rss_mib']-baseline['backend_rss_mib']
                receipt['increment_private_mib'] = candidate['private_working_set_mib']-baseline['private_working_set_mib'] + candidate['backend_private_mib']-baseline['backend_private_mib']
                receipt['combined_cpu_percent'] = candidate['cpu_mean'] + max(0, candidate['backend_cpu']-baseline['backend_cpu'])
                receipt['combined_machine_cpu_percent'] = receipt['combined_cpu_percent'] / candidate['logical_cpus']
                receipt['plugin_initial_memory'] = client.get('/fixture/counts').json()['plugin_memory']
                receipt['increment_private_mib'] += receipt['plugin_initial_memory']['private_mib']
                receipt['increment_rss_mib'] += receipt['plugin_initial_memory']['rss_mib']
                checks['cpu_budget'] = receipt['combined_machine_cpu_percent'] < 2
                checks['memory_budget'] = receipt['increment_private_mib'] < 100
            checks['boot_does_not_repeat_on_show'] = not page.locator('.surface').evaluate("n=>n.classList.contains('booting')")
            page.reload(); page.wait_for_selector('.surface'); time.sleep(1)
            checks['boot_does_not_repeat_on_reload'] = not page.locator('.surface').evaluate("n=>n.classList.contains('booting')")
            checks['reduced_motion'] = 'manual OS preference check still required'
            checks['lock_screen'] = 'manual check; probe does not lock the owner session'
            checks['two_monitors'] = invoke('hud_monitors')
            if baseline:
                assert checks['cpu_budget'], 'Idle CPU exceeds 2% of the machine'
                assert checks['memory_budget'], 'HUD incremental private working set exceeds 100 MiB'
            assert all(value is True for key, value in checks.items() if key not in ('dpi', 'reduced_motion', 'lock_screen', 'two_monitors'))
        finally:
            if owned: u.DestroyWindow(owned)
            stop()
            client.close()
            if fixture and fixture.poll() is None: fixture.terminate(); fixture.wait(timeout=10)
            receipt['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for parent in ('plugins/hud', 'island/src', 'island/src-tauri/src')
                                       for p in (ROOT / parent).glob('*') if p.is_file()}
            (output / 'native-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            if original:
                subprocess.Popen([str(executable), '--background'], cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            log.close()
    print(json.dumps({key: value for key, value in receipt.items() if key not in ('source_sha256', 'baseline', 'candidate')}, indent=2))


if __name__ == '__main__': main()
