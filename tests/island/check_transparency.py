"""Actual compositor pixels and Win32 input over an owned Chromium fixture."""
import ctypes as c
import json
import hashlib
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
    u.SetCursorPos(u.GetSystemMetrics(0) // 2, 450)
    evidence = {}
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(output / 'browser-profile'), headless=False,
                    no_viewport=True, ignore_default_args=['--no-startup-window'], args=['--start-maximized'])
        browser = context.browser
        page = context.pages[0] if context.pages else context.new_page()
        page.set_content('''<title>Island transparency fixture</title><style>
          body { margin:0; background:#137e91; height:100vh; color:white; font:20px sans-serif }
          input { position:absolute; top:200px; left:calc(50% - 180px); width:360px; height:50px; }
        </style><input aria-label="Underlying browser input" placeholder="Owned input fixture">''')
        session = page.context.new_cdp_session(page)
        window_id = session.send('Browser.getWindowForTarget')['windowId']
        session.send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'windowState': 'fullscreen'}})
        page.wait_for_timeout(500)
        browser_session = browser.new_browser_cdp_session()
        browser_pid = next(info['id'] for info in browser_session.send('SystemInfo.getProcessInfo')['processInfo'] if info['type'] == 'browser')
        ratio = page.evaluate('window.devicePixelRatio')
        x = u.GetSystemMetrics(0) // 2
        browser_hwnd = None
        def find_browser(candidate, _):
            nonlocal browser_hwnd
            title = c.create_unicode_buffer(256); u.GetWindowTextW(candidate, title, 256)
            pid = w.DWORD(); u.GetWindowThreadProcessId(candidate, c.byref(pid))
            if pid.value == browser_pid and title.value.startswith('Island transparency fixture') and u.IsWindowVisible(candidate):
                browser_hwnd = candidate
                return False
            return True
        u.EnumWindows(CALLBACK(find_browser), 0)
        assert browser_hwnd, 'Owned browser window not found'
        evidence['fixture_was_minimized'] = bool(u.IsIconic(browser_hwnd))
        u.ShowWindow(browser_hwnd, 9)  # restore a launch-hidden/minimized fixture
        session.send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'windowState': 'fullscreen'}})
        page.wait_for_timeout(200)
        # Keep the owned fixture above unrelated desktop overlays, then create
        # the Island later in the same topmost band so its real hit test still wins.
        u.SetWindowPos(browser_hwnd, w.HWND(-1), 0, 0, 0, 0, 0x13)
        u.SetForegroundWindow(browser_hwnd)
        page.wait_for_timeout(200)
        browser_bounds = w.RECT(); u.GetWindowRect(browser_hwnd, c.byref(browser_bounds))
        input_box = page.get_by_role('textbox').bounding_box()
        content = page.evaluate('({width:innerWidth,height:innerHeight})')
        click_x = int(browser_bounds.left + ((browser_bounds.right - browser_bounds.left) - content['width'] * ratio) / 2 + (input_box['x'] + input_box['width'] / 2) * ratio)
        y = int(browser_bounds.bottom - content['height'] * ratio + (input_box['y'] + input_box['height'] / 2) * ratio)
        sample = (x + int(250 * ratio), int(180 * ratio))
        def sample_pixels(): return ImageGrab.grab(bbox=(sample[0], sample[1], sample[0] + 4, sample[1] + 4))
        # Wait for the owned page to be composed on the physical desktop, rather
        # than comparing an early screenshot of the previously foreground app.
        for _ in range(40):
            page.bring_to_front()
            u.SetWindowPos(browser_hwnd, w.HWND(-1), 0, 0, 0, 0, 0x13)
            pixel = sample_pixels().getpixel((0, 0))[:3]
            if all(abs(a - b) < 8 for a, b in zip(pixel, (19, 126, 145))): break
            page.wait_for_timeout(250)
        assert all(abs(a - b) < 8 for a, b in zip(pixel, (19, 126, 145))), 'Owned browser fixture is not visible on the physical desktop'
        baseline = sample_pixels().tobytes()
        evidence['baseline_pixel'] = pixel
        executable = ROOT / 'island/src-tauri/target' / ('release' if '--release' in sys.argv else 'debug') / 'friday-island.exe'
        evidence['artifact_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
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
            assert evidence['rest'][2] < 400 * ratio and evidence['rest'][3] < 120 * ratio, evidence
            # Re-establish the controlled stack after startup: this owned browser
            # under the Island, both above unrelated Chrome windows/overlays.
            page.bring_to_front()
            # Windows may deny activation from this separate test process. Join
            # the foreground input queue only for the deliberate fixture focus.
            message = w.MSG(); u.PeekMessageW(c.byref(message), None, 0, 0, 0)
            current_thread = c.windll.kernel32.GetCurrentThreadId()
            foreground_thread = u.GetWindowThreadProcessId(u.GetForegroundWindow(), None)
            u.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
            attached = u.AttachThreadInput(current_thread, foreground_thread, True) if current_thread != foreground_thread else False
            try:
                u.SetWindowPos(browser_hwnd, w.HWND(-1), 0, 0, 0, 0, 0x13)
                u.SetForegroundWindow(browser_hwnd)
            finally:
                if attached: u.AttachThreadInput(current_thread, foreground_thread, False)
            u.SetWindowPos(browser_hwnd, w.HWND(-1), 0, 0, 0, 0, 0x13)
            u.SetForegroundWindow(browser_hwnd)
            u.SetWindowPos(hwnd, w.HWND(-1), 0, 0, 0, 0, 0x13)
            page.wait_for_timeout(150)
            current_image = sample_pixels(); current = current_image.tobytes(); evidence['current_pixel'] = current_image.getpixel((0, 0))[:3]
            assert current == baseline, 'Pixels under the former large window changed (opaque rectangle)'
            evidence['desktop_pixels_unchanged'] = True
            # These are OS mouse/keyboard events, not CDP page.click/type.
            u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
            target = u.GetAncestor(u.WindowFromPoint(w.POINT(click_x, y)), 2)
            evidence['underlying_browser_is_hit_target'] = target == browser_hwnd
            evidence['input_screen_point'] = [click_x, y]
            if target != browser_hwnd:
                import psutil
                pid = w.DWORD(); u.GetWindowThreadProcessId(target, c.byref(pid))
                evidence['interfering_process'] = psutil.Process(pid.value).name()
                browser_pid = w.DWORD(); u.GetWindowThreadProcessId(browser_hwnd, c.byref(browser_pid))
                evidence['same_browser_process'] = pid.value == browser_pid.value
                evidence['target_is_browser_child_process'] = browser_pid.value in [p.pid for p in psutil.Process(pid.value).parents()]
                u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
                classes = []
                for handle in [target, browser_hwnd]:
                    name = c.create_unicode_buffer(256); u.GetClassNameW(handle, name, 256); classes.append(name.value)
                evidence['target_and_browser_classes'] = classes
                evidence['target_owner_matches_browser'] = u.GetAncestor(target, 3) == u.GetAncestor(browser_hwnd, 3)
                caption = c.create_unicode_buffer(256); u.GetWindowTextW(target, caption, 256)
                evidence['target_is_old_fixture'] = caption.value.startswith('Island transparency fixture')
                evidence['target_is_playwright_browser'] = any('playwright_chromiumdev_profile' in arg for arg in psutil.Process(pid.value).cmdline())
                rect = w.RECT(); u.GetWindowRect(target, c.byref(rect)); evidence['target_rect'] = [rect.left, rect.top, rect.right, rect.bottom]
                evidence['fixture_rect'] = [browser_bounds.left, browser_bounds.top, browser_bounds.right, browser_bounds.bottom]
            assert target == browser_hwnd, f'Browser input point hits another window: {evidence}, island={hwnd}, bounds={bounds()}'
            u.SetCursorPos(click_x, y); u.mouse_event(2, 0, 0, 0, 0); u.mouse_event(4, 0, 0, 0, 0)
            page.wait_for_timeout(100)
            for letter in 'BROWSER': keys([ord(letter)])
            evidence['received_text'] = page.get_by_role('textbox').input_value()
            assert evidence['received_text'].lower() == 'browser', f'Browser input failed: {evidence}, foreground={u.GetForegroundWindow()}, active={page.evaluate("document.activeElement.tagName")}'
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
