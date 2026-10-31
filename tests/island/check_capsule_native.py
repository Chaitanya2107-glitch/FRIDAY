"""Release WebView2 + real Windows battery/SMTC, using an owned local audio fixture.

Close the normal Island first. No provider/network or owner player is controlled.
  venv/Scripts/python.exe -B tests/island/check_capsule_native.py
"""
import base64
import ctypes as c
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_native import ROOT, u, w, CALLBACK
from playwright.sync_api import sync_playwright, expect


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    output = ROOT / 'tasks/island-capsule-native'
    output.mkdir(exist_ok=True)
    config = output / 'config.json'
    config.write_text(json.dumps({'hotkeys': {'sneak': 'Ctrl+Shift+Alt+F23', 'expand': 'Ctrl+Shift+Alt+F24'},
                                 'connection': {'port': free_port()}}), encoding='utf-8')
    executable = ROOT / 'island/src-tauri/target/release/friday-island.exe'
    evidence = {'artifact_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
    original_cursor = w.POINT(); u.GetCursorPos(c.byref(original_cursor))
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 8000 * 30)
    data = 'data:audio/wav;base64,' + base64.b64encode(audio.getvalue()).decode()
    app = browser = None
    log = (output / 'app.log').open('w', encoding='utf-8')
    with sync_playwright() as playwright:
        fixture = playwright.chromium.launch(headless=False, args=['--autoplay-policy=no-user-gesture-required'])
        try:
            player = fixture.new_page()
            player.set_content('<title>Island owned media fixture</title><audio loop></audio><button>Start fixture</button>')
            player.evaluate('''data => {
                window.calls = {play:0,pause:0,nexttrack:0,previoustrack:0};
                const audio = document.querySelector('audio'); audio.src = data;
                window.track = n => navigator.mediaSession.metadata = new MediaMetadata({title:'FRIDAY fixture '+n,artist:'Local test player'});
                track('one');
                navigator.mediaSession.setActionHandler('play', () => { calls.play++; audio.play(); });
                navigator.mediaSession.setActionHandler('pause', () => { calls.pause++; audio.pause(); });
                navigator.mediaSession.setActionHandler('nexttrack', () => { calls.nexttrack++; track('two'); });
                navigator.mediaSession.setActionHandler('previoustrack', () => { calls.previoustrack++; track('one'); });
                audio.onplay = () => navigator.mediaSession.playbackState = 'playing';
                audio.onpause = () => navigator.mediaSession.playbackState = 'paused';
                document.querySelector('button').onclick = () => audio.play();
            }''', data)
            player.get_by_role('button').click()
            player.wait_for_function("navigator.mediaSession.playbackState === 'playing'")
            debug_port = free_port()
            env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config),
                       WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1')
            u.SetCursorPos(u.GetSystemMetrics(0) // 2, 450)
            foreground = u.GetForegroundWindow()
            app = subprocess.Popen([str(executable)], cwd=ROOT / 'island', env=env, stdout=log, stderr=log)
            for _ in range(100):
                try:
                    browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}', timeout=400)
                    break
                except Exception:
                    assert app.poll() is None, 'Island exited'
                    time.sleep(.15)
            assert browser, 'Test-only WebView2 endpoint did not start'
            page = browser.contexts[0].pages[0]
            page.wait_for_function('window.__TAURI_INTERNALS__?.invoke !== undefined')

            def invoke(command, args=None):
                return page.evaluate('([command,args])=>window.__TAURI_INTERNALS__.invoke(command,args)', [command, args or {}])

            def rejected(command, args):
                try:
                    invoke(command, args)
                except Exception:
                    return True
                return False

            for _ in range(40):
                status = invoke('desktop_status')
                if status['media'] and status['media']['title'] == 'FRIDAY fixture one': break
                page.wait_for_timeout(250)
            assert status['media'] and status['media']['title'] == 'FRIDAY fixture one', 'Owned player was not exposed by Windows SMTC'
            evidence['windows_media_metadata'] = True
            source = status['media']['source']
            assert rejected('media_control', {'action': 'next', 'source': 'not-the-visible-player'})
            assert rejected('media_control', {'action': 'open spotify', 'source': source})
            assert rejected('media_control', {'action': 'toggle', 'source': ''})
            assert player.evaluate('calls') == {'play': 0, 'pause': 0, 'nexttrack': 0, 'previoustrack': 0}
            evidence['unknown_action_and_stale_player_rejected'] = True

            class Power(c.Structure):
                _fields_ = [('ac', c.c_ubyte), ('flags', c.c_ubyte), ('percent', c.c_ubyte),
                            ('saver', c.c_ubyte), ('remaining', w.DWORD), ('full', w.DWORD)]
            power = Power()
            assert c.windll.kernel32.GetSystemPowerStatus(c.byref(power))
            if power.flags != 255 and power.flags & 128:
                assert status['battery'] is None
            else:
                assert status['battery']['percent'] == (power.percent if power.percent <= 100 else None)
            evidence['battery_matches_windows'] = True
            media_title = page.locator('.media-title')
            expect(media_title).to_have_text('FRIDAY fixture one')
            expect(page.locator('.clock-period')).to_have_text(re.compile('AM|PM'))
            surface = page.locator('.surface')
            expect(surface).to_have_attribute('data-mode', 'rest')
            bounds, orb = surface.bounding_box(), page.locator('.character').bounding_box()
            assert abs(bounds['x'] + bounds['width']/2 - orb['x'] - orb['width']/2) < .5
            assert u.GetForegroundWindow() == foreground, 'Background clock/media read stole focus'
            evidence['centered_and_startup_passive'] = True
            page.screenshot(path=str(output / 'rest.png'))

            hwnd = None
            def find(candidate, _):
                nonlocal hwnd
                pid = w.DWORD(); u.GetWindowThreadProcessId(candidate, c.byref(pid))
                title = c.create_unicode_buffer(128); u.GetWindowTextW(candidate, title, 128)
                if pid.value == app.pid and title.value == 'FRIDAY Island': hwnd = candidate
                return True
            u.EnumWindows(CALLBACK(find), 0)
            assert hwnd
            scale = u.GetDpiForWindow(hwnd) / 96
            evidence['dpi'] = u.GetDpiForWindow(hwnd)
            u.SetCursorPos(u.GetSystemMetrics(0)//2, 10)
            expect(surface).to_have_attribute('data-mode', 'peek')
            page.wait_for_timeout(350)

            def click_control(label):
                box = page.get_by_role('button', name=label, exact=True).bounding_box()
                rect = w.RECT(); u.GetWindowRect(hwnd, c.byref(rect))
                u.SetCursorPos(int(rect.left + (box['x'] + box['width']/2)*scale), int(rect.top + (box['y'] + box['height']/2)*scale))
                u.mouse_event(2, 0, 0, 0, 0); u.mouse_event(4, 0, 0, 0, 0)

            click_control('Pause')
            player.wait_for_function('calls.pause === 1')
            expect(page.get_by_role('button', name='Play', exact=True)).to_be_enabled()
            click_control('Play')
            player.wait_for_function('calls.play === 1')
            expect(page.get_by_role('button', name='Pause', exact=True)).to_be_enabled()
            click_control('Next track')
            player.wait_for_function('calls.nexttrack === 1')
            expect(media_title).to_have_text('FRIDAY fixture two')
            click_control('Previous track')
            player.wait_for_function('calls.previoustrack === 1')
            expect(media_title).to_have_text('FRIDAY fixture one')
            assert u.GetForegroundWindow() == foreground, 'Media click stole focus'
            evidence['real_mouse_media_controls_without_activation'] = player.evaluate('calls')
            (output / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            print(json.dumps(evidence, indent=2))
            print('PASS: real Windows battery/media metadata, fixed actions, centered capsule, OS media clicks without focus theft')
        finally:
            if browser: browser.close()
            if app and app.poll() is None:
                app.terminate(); app.wait(timeout=10)
            fixture.close(); log.close()
            u.SetCursorPos(original_cursor.x, original_cursor.y)


if __name__ == '__main__':
    main()
