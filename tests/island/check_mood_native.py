"""Exercise commands -> authenticated SSE -> packaged SVG, using owned fixtures."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time

import httpx
import psutil
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
MOODS = ['idle', 'happy', 'curious', 'worried', 'alarmed', 'sleepy', 'dozing', 'focused', 'alert', 'celebrating', 'waving']


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    output = ROOT / 'tasks/mochi-mood/native-check'
    output.mkdir(parents=True, exist_ok=True)
    build = ROOT / 'tasks/mochi-mood/builds/candidate'
    binding = json.loads((build / 'source.json').read_text())
    executable = build / binding.get('executable', 'friday-island.exe')
    token, api_port, cdp = secrets.token_hex(32), port(), port()
    config = output / 'config.json'
    config.write_text(json.dumps({'startup': {'manage_bridge': False}, 'island': {'boot_animation': False},
        'appearance': {'idle_mode': 'always'}, 'connection': {'port': api_port, 'api_port': api_port, 'token': token},
        'hotkeys': {'sneak': 'Ctrl+Shift+Alt+F22', 'expand': 'Ctrl+Shift+Alt+F23', 'hud': 'Ctrl+Shift+Alt+F24'}}), encoding='utf-8')
    env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config), FRIDAY_ISLAND_MANAGE_BRIDGE='0',
        WEBVIEW2_USER_DATA_FOLDER=str(output / 'webview-profile'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={cdp} --remote-debugging-address=127.0.0.1')
    receipt = {'binary_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(), 'checks': {}, 'moods': []}
    with (output / 'app.log').open('w', encoding='utf-8') as log:
        fixture = subprocess.Popen([sys.executable, '-B', 'tests/island/mood_fixture.py', str(config)], cwd=ROOT,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(150):
            try:
                if httpx.get(f'http://127.0.0.1:{api_port}/api/plugins/mood/state', headers={'X-Friday-Token': token}).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        child = subprocess.Popen([str(executable), '--background'], cwd=ROOT, env=env,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        process = psutil.Process(child.pid)
        try:
            with sync_playwright() as playwright, httpx.Client(base_url=f'http://127.0.0.1:{api_port}',
                    headers={'X-Friday-Token': token}, timeout=10) as client:
                browser = None
                for _ in range(120):
                    assert child.poll() is None, 'Owned Island exited'
                    try:
                        browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp}', timeout=500)
                        break
                    except Exception:
                        time.sleep(.15)
                assert browser
                page = None
                for _ in range(100):
                    page = next((p for p in browser.contexts[0].pages if p.locator('.character').count()), None)
                    if page:
                        break
                    time.sleep(.1)
                assert page, [p.url for p in browser.contexts[0].pages]
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: print('WebView error: ' + message.text[:180], flush=True) if message.type == 'error' else None)
                detail = page.evaluate("""async token => { const c=await window.__TAURI_INTERNALS__.invoke('get_config');
                    return {port:c.connection.port,api_port:c.connection.api_port,token_matches:c.connection.token===token}; }""", token)
                print(json.dumps({'native_config': detail, 'expected_port': api_port}), flush=True)
                surface, orb = page.locator('.surface'), page.locator('.character')
                expect(orb).to_be_visible()
                try:
                    expect(surface).to_have_attribute('data-mood', re.compile('idle|dozing|sleepy'), timeout=30000)
                except Exception:
                    print(json.dumps({'page_errors': errors}), flush=True)
                    raise
                expect(surface).to_have_css('width', '288px')
                expect(page.locator('.island-row')).to_have_css('height', '32px')
                status = page.evaluate("() => window.__TAURI_INTERNALS__.invoke('runtime_status')")
                receipt['environment'] = {key: status.get(key) for key in ['fullscreen_front', 'desktop_locked', 'reduce_motion']}
                if status.get('fullscreen_front'):
                    expect(surface).to_have_attribute('data-motion-paused', 'true')
                    receipt['checks']['native_fullscreen_suspends'] = True
                def command(text):
                    response = client.post('/fixture/command', json={'text': text})
                    response.raise_for_status()
                    result = response.json()
                    assert result['ok'], result
                command('mochi test all')
                for mood in MOODS:
                    expect(surface).to_have_attribute('data-mood', mood, timeout=4500)
                    page.wait_for_timeout(150)
                    orb.screenshot(path=str(output / f'{mood}.png'))
                    receipt['moods'].append(mood)
                print('All eleven moods rendered through authenticated SSE.', flush=True)
                page.wait_for_timeout(3100)
                command('mochi dev on')
                command('fake event battery.low')
                expect(surface).to_have_attribute('data-mood', 'worried')
                expect(orb.locator('.mochi-sweat')).to_be_visible()
                expect(page.locator('.mood-bubble')).to_have_text('Battery at 18%')
                # A fullscreen foreground app correctly suppresses automatic peek.
                # An explicit hover still reveals passive peek without taking focus.
                page.locator('.rest-clock').hover()
                expect(page.locator('.mood-bubble')).to_be_visible()
                expect(surface).to_have_css('width', '288px')
                page.screenshot(path=str(output / 'battery-bubble.png'))
                page.wait_for_timeout(4100)
                expect(page.locator('.mood-bubble')).to_be_hidden()
                receipt['checks']['battery_rule_and_four_second_peek'] = True
                command('focus 25')
                expect(surface).to_have_attribute('data-mood', 'focused')
                command('pause focus')
                expect(surface).to_have_attribute('data-mood', re.compile('idle|dozing|sleepy'))
                command('resume focus')
                expect(surface).to_have_attribute('data-mood', 'focused')
                command('stop focus')
                expect(surface).to_have_attribute('data-mood', 'celebrating')
                receipt['checks']['focus_start_pause_resume_end'] = True
                command('mochi test alarmed')
                expect(surface).to_have_attribute('data-mood', 'alarmed')
                page.wait_for_timeout(100)
                page.evaluate("""() => { window.__mochiFrames=[]; window.__mochiObserver=new MutationObserver(() => window.__mochiFrames.push(performance.now()));
                    window.__mochiObserver.observe(document.querySelector('.character'), {attributes:true,attributeFilter:['style']}); }""")
                page.wait_for_timeout(1100)
                times = page.evaluate('() => window.__mochiFrames')
                assert len(times) <= 33, times
                receipt['checks']['animation_samples_per_second'] = len(times) / 1.1
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_timeout(150)
                before = orb.get_attribute('style')
                page.wait_for_timeout(400)
                assert orb.get_attribute('style') == before
                assert page.evaluate("() => document.documentElement.classList.contains('reduce-motion')")
                receipt['checks']['prefers_reduced_motion_static'] = True
                page.emulate_media(reduced_motion='no-preference')
                page.locator('.rest-clock').click()
                page.get_by_role('button', name='Settings', exact=True).first.click()
                page.get_by_role('button', name='Look', exact=True).click()
                page.get_by_label('Reduced motion', exact=True).check()
                expect(page.locator('html')).to_have_class('reduce-motion')
                saved = json.loads(config.read_text(encoding='utf-8'))
                assert saved['island']['reduced_motion'] is True
                receipt['checks']['reduced_motion_setting_persists'] = True
                page.get_by_label('Reduced motion', exact=True).uncheck()
                page.keyboard.press('Escape')
                page.mouse.move(0, 200)
                expect(surface).to_have_attribute('data-mode', 'rest')
                command('mochi test alarmed')
                page.evaluate("() => { document.querySelector('.surface').dataset.mode='hidden'; document.dispatchEvent(new Event('visibilitychange')); }")
                expect(surface).to_have_attribute('data-motion-paused', 'true')
                before = orb.get_attribute('style')
                page.wait_for_timeout(400)
                assert orb.get_attribute('style') == before
                receipt['checks']['hidden_animation_suspended'] = True
                assert not errors, errors
                receipt['checks']['console_errors'] = errors
                # Check the actual authenticated HTTP request, never store its secret.
                assert client.get('/api/plugins/mood/state').status_code == 200
                assert httpx.get(f'http://127.0.0.1:{api_port}/api/plugins/mood/state').status_code == 401
                receipt['checks']['token_required'] = True
                browser.close()
        finally:
            children = process.children(recursive=True) if process.is_running() else []
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            for owned in children:
                try:
                    owned.terminate()
                except psutil.NoSuchProcess:
                    pass
            if fixture.poll() is None:
                fixture.terminate()
                fixture.wait(timeout=5)
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
