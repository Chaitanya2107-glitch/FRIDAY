"""Actual compositor pixels and Win32 input over an owned Chromium fixture."""
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_native import ROOT, u, w, CALLBACK
from PIL import ImageGrab
from playwright.sync_api import sync_playwright


def main():
    output = ROOT / 'tasks/island-transparency'
    output.mkdir(exist_ok=True)
    config = output / 'config.json'
    # Test keys avoid FRIDAY's existing default binding.
    config.write_text(json.dumps({'hotkeys': {'sneak': 'Ctrl+Shift+Alt+F23', 'expand': 'Ctrl+Shift+Alt+F24'}}), encoding='utf-8')
    original_cursor = w.POINT(); u.GetCursorPos(c.byref(original_cursor))
    evidence = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(no_viewport=True)
        page.set_content('''<title>Island transparency fixture</title><style>
          body { margin:0; background:#137e91; height:100vh; color:white; font:20px sans-serif }
          input { position:absolute; top:200px; left:calc(50% - 180px); width:360px; height:50px; }
        </style><input aria-label="Underlying browser input" placeholder="Owned input fixture">''')
        session = page.context.new_cdp_session(page)
        window_id = session.send('Browser.getWindowForTarget')['windowId']
        session.send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'windowState': 'fullscreen'}})
        page.wait_for_timeout(500)
        ratio = page.evaluate('window.devicePixelRatio')
        x = u.GetSystemMetrics(0) // 2
        y = int(225 * ratio)
        sample = (x + int(250 * ratio), int(180 * ratio))
        baseline = ImageGrab.grab(bbox=(sample[0], sample[1], sample[0] + 4, sample[1] + 4)).tobytes()
        executable = ROOT / 'island/src-tauri/target' / ('release' if '--release' in sys.argv else 'debug') / 'friday-island.exe'
        log = (output / 'app.log').open('w', encoding='utf-8')
        app = subprocess.Popen([str(executable)], cwd=ROOT / 'island', env=dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config)), stdout=log, stderr=log)
        hwnd = None
        try:
            def find(candidate, _):
                nonlocal hwnd
                pid = w.DWORD(); u.GetWindowThreadProcessId(candidate, c.byref(pid))
                title = c.create_unicode_buffer(128); u.GetWindowTextW(candidate, title, 128)
                if pid.value == app.pid and title.value == 'FRIDAY Island': hwnd = candidate
                return True

            for _ in range(100):
                u.EnumWindows(CALLBACK(find), 0)
                if hwnd: break
                page.wait_for_timeout(100)
            assert hwnd, 'Island did not start'
            page.wait_for_timeout(1800)

            def bounds():
                rect = w.RECT(); u.GetWindowRect(hwnd, c.byref(rect))
                return [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]

            def keys(codes):
                for code in codes: u.keybd_event(code, 0, 0, 0)
                try: page.wait_for_timeout(140)
                finally:
                    for code in reversed(codes): u.keybd_event(code, 0, 2, 0)
                page.wait_for_timeout(500)

            evidence['dpi'] = u.GetDpiForWindow(hwnd)
            evidence['rest'] = bounds()
            assert evidence['rest'][2] < 400 * ratio and evidence['rest'][3] < 90 * ratio, evidence
            current = ImageGrab.grab(bbox=(sample[0], sample[1], sample[0] + 4, sample[1] + 4)).tobytes()
            assert current == baseline, 'Pixels under the former large window changed (opaque rectangle)'
            evidence['desktop_pixels_unchanged'] = True
            # These are OS mouse/keyboard events, not CDP page.click/type.
            u.SetCursorPos(x, y); u.mouse_event(2, 0, 0, 0, 0); u.mouse_event(4, 0, 0, 0, 0)
            page.wait_for_timeout(100)
            for letter in 'BROWSER': keys([ord(letter)])
            assert page.get_by_role('textbox').input_value().lower() == 'browser', 'Island blocked real browser input'
            evidence['real_browser_click_and_typing'] = True
            keys([0x11, 0x10, 0x12, 0x87]); evidence['peek'] = bounds()
            assert evidence['peek'][2] > evidence['rest'][2] + 100 and evidence['peek'][3] < 120 * ratio
            keys([0x11, 0x10, 0x12, 0x87]); evidence['expanded'] = bounds()
            assert evidence['expanded'][3] > evidence['peek'][3] + 100
            keys([0x1B]); keys([0x11, 0x10, 0x12, 0x86]); evidence['sneak'] = bounds()
            assert evidence['sneak'][3] < 120 * ratio
            assert abs(evidence['sneak'][1] + evidence['sneak'][3] / 2 - u.GetSystemMetrics(1) / 2) < 3
            keys([0x1B])
            # No full canvas survives after shrinking back to Rest.
            assert bounds()[3] < 90 * ratio
            ImageGrab.grab(bbox=(max(0, x - 470), 0, x + 470, min(u.GetSystemMetrics(1), 380))).save(output / 'rest-over-browser.png')
            print(json.dumps(evidence, indent=2))
            print('PASS: actual browser input, unchanged desktop pixels, four native sizes, high DPI')
        finally:
            app.terminate(); app.wait(timeout=10); log.close(); browser.close()
            u.SetCursorPos(original_cursor.x, original_cursor.y)
            (output / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
