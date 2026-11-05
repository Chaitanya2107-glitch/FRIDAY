"""Real WebView2/native catalog check with an isolated config and local-only CDP.

Exercises pin/unpin, ID rejection, rescan and restart persistence. It launches
Windows Calculator once and closes only a newly created Calculator window.
The debug port exists only in this test child's environment, not product config.
"""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_native import ROOT, u, w, CALLBACK
from playwright.sync_api import sync_playwright, expect


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); return listener.getsockname()[1]


def calculators():
    result = set()
    def visit(hwnd, _):
        title = c.create_unicode_buffer(256); u.GetWindowTextW(hwnd, title, 256)
        if title.value == 'Calculator': result.add(hwnd)
        return True
    u.EnumWindows(CALLBACK(visit), 0)
    return result


def main():
    output = ROOT / 'tasks/island-apps-native'
    output.mkdir(exist_ok=True)
    config = output / 'config.json'
    config.write_text(json.dumps({'hotkeys': {'sneak': 'Ctrl+Shift+Alt+F23', 'expand': 'Ctrl+Shift+Alt+F24'},
                                  'connection': {'port': port()}}), encoding='utf-8')
    executable = ROOT / 'island/src-tauri/target/release/friday-island.exe'
    evidence = {'artifact_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
    before = calculators()
    sessions = []
    u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    with sync_playwright() as p:
        try:
            def start():
                debug_port = port()
                log = (output / f'app-{len(sessions)}.log').open('w', encoding='utf-8')
                env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config),
                           WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1')
                app = subprocess.Popen([str(executable)], cwd=ROOT / 'island', env=env, stdout=log, stderr=log)
                session = {'app': app, 'browser': None, 'log': log}; sessions.append(session)
                for _ in range(80):
                    try:
                        browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}', timeout=500)
                        session['browser'] = browser; break
                    except Exception:
                        assert app.poll() is None, 'Island exited before CDP became ready'
                        time.sleep(.15)
                assert session['browser'], 'Test-only WebView2 debug endpoint did not start'
                page = session['browser'].contexts[0].pages[0]
                page.wait_for_function('window.__TAURI_INTERNALS__?.invoke !== undefined')
                return session, page

            def invoke(page, command, args=None):
                return page.evaluate('([command,args])=>window.__TAURI_INTERNALS__.invoke(command,args)', [command, args or {}])

            def ready(page):
                for _ in range(80):
                    state = invoke(page, 'app_index_status')
                    if state['count'] and not state['scanning']: return state
                    page.wait_for_timeout(150)
                raise AssertionError('Native app index did not become ready')

            def key(page, codes):
                for code in codes: u.keybd_event(code, 0, 0, 0)
                try: page.wait_for_timeout(150)
                finally:
                    for code in reversed(codes): u.keybd_event(code, 0, 2, 0)
                page.wait_for_timeout(400)

            def stop(session):
                if session['app'].poll() is None: session['app'].terminate()
                session['app'].wait(timeout=10)
                if session['browser']:
                    try: session['browser'].close()
                    except Exception: pass
                session['log'].close()

            session, page = start()
            state = ready(page)
            evidence['indexed_apps'] = state['count']; evidence['scan_errors'] = state['errors']
            matches = invoke(page, 'search_apps', {'query': 'Calculator'})
            target = next((app for app in matches if app['source'] == 'Windows Store' and app['name'] == 'Calculator'), None)
            assert target, 'Installed Windows Calculator missing from native catalog'
            app_id = target['id']
            assert invoke(page, 'app_icon', {'id': app_id}).startswith('data:image/png;base64,')
            assert not invoke(page, 'get_config')['pins'], 'Fixture must start without favourites'
            rejected = page.evaluate('''async () => {try {
                await window.__TAURI_INTERNALS__.invoke('launch',{kind:'app',id:'C:/Windows/System32/cmd.exe'});
                return false;
            } catch { return true; }}''')
            assert rejected; evidence['non_indexed_target_rejected'] = True
            key(page, [0x11, 0x10, 0x12, 0x86])
            command = page.get_by_role('combobox', name='FRIDAY command')
            await_mode = page.locator('.surface')
            expect(await_mode).to_have_attribute('data-mode', 'sneak')
            command.fill('open Calculator')
            option = page.get_by_role('option').filter(has_text='Windows Store').filter(has_text='Calculator').first
            expect(option).to_be_visible()
            option.get_by_role('button', name='Pin Calculator', exact=True).click()
            assert any(pin.get('app_id') == app_id for pin in invoke(page, 'get_config')['pins'])
            option.get_by_role('button', name='Unpin Calculator', exact=True).click()
            assert not invoke(page, 'get_config')['pins']
            evidence['suggestion_pin_unpin'] = True
            option.locator('.suggestion-run').click()
            expect(await_mode).to_have_attribute('data-mode', 'rest')
            expect(page.locator('.feedback')).to_contain_text('Opened Calculator')
            for _ in range(40):
                if calculators(): break
                page.wait_for_timeout(150)
            assert calculators(), 'Calculator activation produced no window'
            evidence['unpin_does_not_prevent_launch'] = True
            assert any(recent['id'] == app_id and recent['count'] >= 1 for recent in invoke(page, 'get_config')['recent_apps'])
            evidence['successful_launch_recorded'] = True
            # Pin in actual Settings, then restart the app against the same config.
            key(page, [0x11, 0x10, 0x12, 0x87])
            page.get_by_role('button', name='Settings', exact=True).first.click()
            page.get_by_role('button', name='Pinned apps', exact=True).click()
            page.get_by_role('textbox', name='Find installed apps').fill('Calculator')
            row = page.locator('.installed-row').filter(has_text='Windows Store').filter(has_text='Calculator').first
            row.get_by_role('button', name='Pin Calculator', exact=True).click()
            assert any(pin.get('app_id') == app_id for pin in invoke(page, 'get_config')['pins'])
            stop(session)
            page.wait_for_timeout(300) if not page.is_closed() else None
            session, page = start(); ready(page)
            persisted = invoke(page, 'get_config')
            assert any(pin.get('app_id') == app_id for pin in persisted['pins'])
            assert any(recent['id'] == app_id for recent in persisted['recent_apps'])
            evidence['favourites_and_recents_survive_restart'] = True
            scan = invoke(page, 'rescan_apps')
            assert scan['count'] > 0 and not scan['scanning']; evidence['manual_rescan'] = True
            evidence['offline'] = page.locator('.surface').evaluate("node => node.classList.contains('offline')")
            assert evidence['offline']
            print(json.dumps(evidence, indent=2))
            print('PASS: real native offline app search/launch, ID rejection, icons, pin/unpin, rescan and restart persistence')
        finally:
            for session in sessions:
                if session['app'].poll() is None: session['app'].terminate()
                session['app'].wait(timeout=10)
                if session['browser']:
                    try: session['browser'].close()
                    except Exception: pass
                if not session['log'].closed: session['log'].close()
            for hwnd in calculators() - before: u.PostMessageW(hwnd, 0x10, 0, 0)
            (output / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
