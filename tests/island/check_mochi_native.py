"""Isolated WebView2 and native regions; guarded OS clicks when Windows is unlocked."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import psutil
import win32gui
import win32process
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def check(executable: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    config = output / 'config.json'
    config.write_text(json.dumps({'startup': {'manage_bridge': False},
        'connection': {'port': free_port()},
        'hotkeys': {'sneak': 'Ctrl+Shift+Alt+F23', 'expand': 'Ctrl+Shift+Alt+F24'}}), encoding='utf-8')
    port = free_port()
    env = dict(os.environ, FRIDAY_ISLAND_CONFIG=str(config), FRIDAY_ISLAND_MANAGE_BRIDGE='0',
        WEBVIEW2_USER_DATA_FOLDER=str(output / 'webview-profile'),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port} --remote-debugging-address=127.0.0.1')
    user = ctypes.windll.user32
    gdi = ctypes.windll.gdi32
    gdi.CreateRectRgn.restype = ctypes.c_void_p
    user.GetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.PtInRegion.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    cursor = win32gui.GetCursorPos()
    foreground = win32gui.GetForegroundWindow()
    def lock_overlay(root):
        return bool(root and win32gui.GetWindowText(root) == 'Windows Default Lock Screen'
            and psutil.Process(win32process.GetWindowThreadProcessId(root)[1]).name() == 'LockApp.exe')
    desktop_locked = lock_overlay(win32gui.GetAncestor(win32gui.WindowFromPoint((user.GetSystemMetrics(0) // 2, 15)), 2))
    real_clicks, cdp_clicks, region_checks = 0, 0, 0
    if not desktop_locked:
        user.SetCursorPos(user.GetSystemMetrics(0) // 2, max(cursor[1], 300))
    hwnd = None
    with (output / 'app.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen([str(executable), '--background'], cwd=ROOT, env=env,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with sync_playwright() as playwright:
                browser = None
                for _ in range(100):
                    assert child.poll() is None, 'Isolated candidate exited'
                    try:
                        browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=500)
                        break
                    except Exception:
                        time.sleep(.15)
                assert browser, 'Isolated WebView2 endpoint did not start'
                page = browser.contexts[0].pages[0]
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.evaluate("window.__nativeClicks=[]; addEventListener('click', event => window.__nativeClicks.push({target:event.target.closest('.character,.rest-clock,.island-row,button')?.className,x:event.clientX,y:event.clientY}),true)")
                surface, mochi = page.locator('.surface'), page.locator('.character')
                expect(surface).to_have_attribute('data-mode', 'rest')
                expect(surface).to_have_css('width', '288px')
                expect(page.locator('.island-row')).to_have_css('height', '32px')
                expect(page.locator('.clock-time')).to_be_visible()
                expect(page.locator('.clock-date')).to_be_visible()
                windows = []
                win32gui.EnumWindows(lambda handle, _: windows.append(handle)
                    if win32process.GetWindowThreadProcessId(handle)[1] == child.pid
                    and win32gui.GetWindowText(handle) == 'FRIDAY Island' else None, None)
                assert len(windows) == 1
                hwnd = windows[0]

                def point(locator, edge=False):
                    assert child.poll() is None and win32gui.IsWindow(hwnd)
                    assert win32process.GetWindowThreadProcessId(hwnd)[1] == child.pid
                    bounds = surface.bounding_box()
                    assert bounds and bounds['width'] >= 79 and bounds['height'] >= 23, 'Never click a hidden one-pixel window'
                    box = locator.bounding_box()
                    assert box and box['width'] > 0 and box['height'] > 0
                    origin = win32gui.ClientToScreen(hwnd, (0, 0))
                    scale = page.evaluate('devicePixelRatio')
                    return (round(origin[0] + (box['x'] + (4 if edge else box['width'] / 2)) * scale),
                            round(origin[1] + (box['y'] + (4 if edge else box['height'] / 2)) * scale))

                def move(locator, edge=False):
                    if desktop_locked:
                        locator.hover(position={'x': 4, 'y': 4} if edge else None)
                        return
                    position = point(locator, edge)
                    user.SetCursorPos(*position)
                    page.wait_for_timeout(80)

                def region_contains(position):
                    region = gdi.CreateRectRgn(0, 0, 0, 0)
                    try:
                        if not user.GetWindowRgn(hwnd, region):
                            return False
                        bounds = win32gui.GetWindowRect(hwnd)
                        return bool(gdi.PtInRegion(region, position[0] - bounds[0], position[1] - bounds[1]))
                    finally:
                        gdi.DeleteObject(region)

                def click(locator):
                    nonlocal real_clicks, cdp_clicks, region_checks
                    for _ in range(30):
                        position = point(locator)
                        if not desktop_locked:
                            user.SetCursorPos(*position)
                        page.wait_for_timeout(100)
                        target = win32gui.GetAncestor(win32gui.WindowFromPoint(position), 2)
                        owned, locked = target == hwnd, lock_overlay(target)
                        valid = region_contains(position) and position == point(locator)
                        if valid and (owned or locked):
                            break
                    # A window resize or another foreground application cannot redirect a test click.
                    if not valid or not (owned or locked):
                        hit = win32gui.WindowFromPoint(position)
                        root = win32gui.GetAncestor(hit, 2)
                        raise AssertionError({'point': position, 'window': win32gui.GetWindowRect(hwnd),
                            'visible': bool(win32gui.IsWindowVisible(hwnd)), 'enabled': bool(win32gui.IsWindowEnabled(hwnd)),
                            'extended_style': hex(win32gui.GetWindowLong(hwnd, -20)),
                            'hit_title': win32gui.GetWindowText(root), 'hit_class': win32gui.GetClassName(root),
                            'hit_pid': win32process.GetWindowThreadProcessId(root)[1], 'mochi': locator.bounding_box()})
                    region_checks += 1
                    if locked:
                        locator.click()  # Scoped WebView input; never send mouse events to LockApp.
                        cdp_clicks += 1
                    else:
                        user.SetCursorPos(*position)
                        assert win32gui.GetAncestor(win32gui.WindowFromPoint(position), 2) == hwnd
                        assert win32gui.GetCursorPos() == position and point(locator) == position
                        user.mouse_event(0x0002, 0, 0, 0, 0)
                        user.mouse_event(0x0004, 0, 0, 0, 0)
                        real_clicks += 1
                    page.wait_for_timeout(80)
                    (output / 'clicks.json').write_text(json.dumps(page.evaluate('window.__nativeClicks'), indent=2), encoding='utf-8')

                assert mochi.locator('svg .orb-body').count() == 1
                assert page.locator('canvas,.mochi-overview').count() == 0
                expect(surface).to_have_css('background-color', 'rgb(0, 0, 0)')
                expect(mochi).to_have_attribute('role', 'img')
                assert abs(point(mochi)[0] - point(surface)[0]) <= 1, 'Mochi is not centered in the capsule'
                anchor = point(mochi)
                for _ in range(3):
                    click(mochi)
                expect(page.locator('.mochi-popover')).to_have_count(0)
                assert mochi.get_attribute('data-reaction') is None
                expect(mochi.locator('.orb-body')).to_have_css('animation-name', 'none')
                expect(surface).to_have_attribute('data-mode', 'rest')
                expect(surface).to_have_css('width', '288px')
                assert all(abs(a - b) <= 1 for a, b in zip(anchor, point(mochi))), 'Clicking Mochi moved the capsule'
                bounds = win32gui.GetWindowRect(hwnd)
                assert not region_contains((bounds[0] + 2, bounds[1] + 16))
                if foreground != hwnd:
                    assert win32gui.GetForegroundWindow() != hwnd, 'Poking stole keyboard focus'
                page.screenshot(path=str(output / 'default-capsule.png'))
                if desktop_locked:
                    page.mouse.move(0, 300)
                else:
                    user.SetCursorPos(user.GetSystemMetrics(0) // 2, 300)
                move(surface, edge=True)
                expect(surface).to_have_attribute('data-mode', 'peek')
                expect(surface).to_have_attribute('data-active', 'false')
                expect(surface).to_have_css('width', '288px')
                expect(page.locator('.island-row')).to_have_css('height', '32px')
                media_height = 38 if page.locator('.capsule-media').is_visible() else 0
                expect(surface).to_have_css('height', f'{32 + media_height}px')
                page.screenshot(path=str(output / 'compact.png'))
                click(page.locator('.rest-clock'))
                expect(surface).to_have_attribute('data-active', 'true')
                expect(surface).to_have_css('width', '640px')
                command = page.get_by_role('combobox', name='FRIDAY command')
                command.fill('Isolated Mochi draft')
                for _ in range(3):
                    click(mochi)
                expect(page.locator('.mochi-popover')).to_have_count(0)
                assert mochi.get_attribute('data-reaction') is None
                expect(mochi.locator('.orb-body')).to_have_css('animation-name', 'none')
                expect(command).to_have_value('Isolated Mochi draft')
                assert command.evaluate('node => document.activeElement === node')
                expect(surface).to_have_attribute('data-mode', 'peek')
                page.screenshot(path=str(output / 'old-command-controls.png'))
                command.fill('')
                page.keyboard.press('Escape')
                expect(surface).to_have_attribute('data-mode', 'rest')
                expect(surface).to_have_css('width', '288px')
                expect(page.locator('.clock-time')).to_be_visible()
                assert not errors, errors
                result = {'passed': True, 'real_windows_clicks': real_clicks > 0 and cdp_clicks == 0,
                    'windows_clicks': real_clicks, 'scoped_cdp_clicks': cdp_clicks, 'desktop_locked': desktop_locked,
                    'native_region_checks': region_checks, 'transparent_margins_verified': True, 'isolated_profile': True,
                    'default_black_capsule': True, 'mochi_centered': True, 'amber_svg': True, 'no_click_reaction': True,
                    'passive_clicks': True, 'draft_and_focus_preserved': True, 'old_command_controls': True,
                    'browser_errors': errors, 'binary_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                    'screenshots': output.relative_to(ROOT).as_posix()}
                (output / 'native.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                return result
        finally:
            if not desktop_locked or real_clicks:
                user.SetCursorPos(*cursor)
            if child.poll() is None:
                if hwnd and win32gui.IsWindow(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == child.pid:
                    win32gui.PostMessage(hwnd, 0x0010, 0, 0)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.terminate()  # Only this isolated, freshly created test process.
                    child.wait(timeout=10)


if __name__ == '__main__':
    print(json.dumps(check(ROOT / 'tasks/capsule-default/friday-island.exe',
                          ROOT / 'tasks/capsule-default' / f'native-{time.time_ns()}')))
