"""Restore the normal FRIDAY launcher after local Mochi build checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.config import config

EXE = ROOT / 'island/src-tauri/target/release/friday-island.exe'
OUTPUT = ROOT / ('tasks/capsule-default' if '--capsule' in sys.argv else 'tasks/mochi-rollback' if '--rollback' in sys.argv else 'tasks/mochi-validation')


def islands():
    return [process for process in psutil.process_iter(['name', 'exe'])
            if process.info['name'] == 'friday-island.exe' and process.info['exe']
            and Path(process.info['exe']).resolve() == EXE.resolve()]


def building():
    for process in psutil.process_iter(['name']):
        if process.info['name'] not in {'cargo.exe', 'rustc.exe'}:
            continue
        try:
            if Path(process.cwd()).resolve().is_relative_to(ROOT):
                return True
        except (psutil.Error, OSError):
            continue
    return False


def status():
    import ctypes
    import win32gui
    import win32process
    current = islands()
    assert len(current) == 1
    hwnd = win32gui.FindWindow(None, 'FRIDAY Island')
    assert hwnd and win32process.GetWindowThreadProcessId(hwnd)[1] == current[0].pid
    bounds = win32gui.GetWindowRect(hwnd)
    dpi = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    env = current[0].environ()
    result = {'pid': current[0].pid, 'normal_profile': not bool(env.get('FRIDAY_ISLAND_CONFIG')),
        'debug_endpoint': bool(env.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS')),
        'logical_width': round((bounds[2] - bounds[0]) * 96 / dpi),
        'logical_height': round((bounds[3] - bounds[1]) * 96 / dpi),
        'binary_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest()}
    (OUTPUT / 'running.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


def show():
    import ctypes
    from ctypes import wintypes
    import win32gui
    import win32process
    user = ctypes.windll.user32
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    current = islands()
    assert len(current) == 1
    owner = current[0]
    hwnd = win32gui.FindWindow(None, 'FRIDAY Island')
    assert hwnd and win32process.GetWindowThreadProcessId(hwnd)[1] == owner.pid
    bounds = win32gui.GetWindowRect(hwnd)
    dpi = user.GetDpiForWindow(hwnd) or 96
    # Reveal through the same top-edge pointer path the owner uses.
    if bounds[2] - bounds[0] < 5:
        user.SetCursorPos(user.GetSystemMetrics(0) // 2, 300)
        time.sleep(.12)
        user.SetCursorPos(user.GetSystemMetrics(0) // 2, 0)
        time.sleep(.3)
        bounds = win32gui.GetWindowRect(hwnd)
    if bounds[2] - bounds[0] < 5:
        # windows.rs consumes WM_HOTKEY id=1 only on its owned hotkey thread.
        # Send it directly inside this process, never as a global keyboard shortcut.
        user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        for thread in owner.threads():
            if not user.PostThreadMessageW(thread.id, 0x0312, 1, 0):
                continue
            time.sleep(.3)
            user.SetCursorPos(user.GetSystemMetrics(0) // 2, 300)
            time.sleep(.12)
            user.SetCursorPos(user.GetSystemMetrics(0) // 2, 0)
            time.sleep(.3)
            assert win32process.GetWindowThreadProcessId(hwnd)[1] == owner.pid
            bounds = win32gui.GetWindowRect(hwnd)
            if bounds[2] - bounds[0] >= 80:
                break
        assert bounds[2] - bounds[0] >= 80, 'Island did not leave Sneak mode'
    width = (bounds[2] - bounds[0]) * 96 / dpi
    if '--capsule' in sys.argv:
        status()
        return
    if 80 <= width <= 330:
        time.sleep(.8)
        bounds = win32gui.GetWindowRect(hwnd)
        origin = win32gui.ClientToScreen(hwnd, (0, 0))
        point = ((bounds[0] + bounds[2]) // 2, origin[1] + round(10 * dpi / 96))
        user.SetCursorPos(*point)
        time.sleep(.1)
        assert win32process.GetWindowThreadProcessId(hwnd)[1] == owner.pid
        assert win32gui.GetAncestor(win32gui.WindowFromPoint(point), 2) == hwnd
        user.mouse_event(0x0002, 0, 0, 0, 0)
        user.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(1.2)
    status()


def activate():
    import ctypes
    import win32gui
    import win32process
    from build_coucou_candidate import inputs
    sys.path.insert(0, str(ROOT / 'tests/island'))
    from check_mochi_native import check
    from check_plugins_native import check as check_reminders

    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    output = OUTPUT
    staged = json.loads((output / 'candidate.json').read_text(encoding='utf-8'))
    candidate = ROOT / staged['candidate']
    assert candidate.resolve().is_relative_to(output.resolve())
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == staged['binary_sha256']
    assert inputs() == staged['source'], 'Source changed after the staged build'
    assert not building(), 'Another local build is active'
    current = islands()
    assert len(current) <= 1
    host = win32gui.FindWindow('FridayTaskbarHost', None)
    controller = psutil.Process(win32process.GetWindowThreadProcessId(host)[1]) if host else None
    if controller:
        assert any(Path(arg).is_absolute() and Path(arg).resolve() == ROOT / 'interfaces/taskbar/launch.py'
                   for arg in controller.cmdline()[1:]), 'Controller belongs to another checkout'
    if current:
        owner = current[0]
        assert not owner.environ().get('FRIDAY_ISLAND_CONFIG'), 'Leave other isolated tests alone'
        hwnd = win32gui.FindWindow(None, 'FRIDAY Island')
        assert hwnd and win32process.GetWindowThreadProcessId(hwnd)[1] == owner.pid
        bounds = win32gui.GetWindowRect(hwnd)
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
        assert (bounds[2] - bounds[0]) * 96 / dpi < 440, 'Close the expanded Island first to preserve any draft'
    backup = output / f'previous-{time.time_ns()}.exe'
    shutil.copy2(EXE, backup)
    receipt = {'authorization': 'Owner requested reminders through the same reply UI as FRIDAY, with Mochi on the side and centered again when idle',
        'decision': 'Validate the staged candidate before replacing the normal executable',
        'prior_binary_sha256': hashlib.sha256(backup.read_bytes()).hexdigest(),
        'candidate_sha256': staged['binary_sha256'], 'applied': False}
    path = output / 'activation.json'
    path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    try:
        if current:
            print('Closing only this checkout’s compact Island for isolated validation.', flush=True)
            win32gui.PostMessage(hwnd, 0x0010, 0, 0)
            owner.wait(timeout=20)
        if controller and controller.is_running():
            controller.wait(timeout=45)
        print('Checking the staged Mochi WebView and native click regions.', flush=True)
        native = check(candidate, output / f'native-{time.time_ns()}')
        assert native['passed'] and native['binary_sha256'] == staged['binary_sha256']
        reminders = check_reminders(candidate, output / f'reminders-native-{time.time_ns()}')
        assert reminders['artifact_sha256'] == staged['binary_sha256'] and reminders['same_reply_view_and_idle_recentering']
        assert not islands() and not building(), 'Another desktop update started; candidate was left staged'
        assert inputs() == staged['source']
        replacement = EXE.with_name('friday-island.next.exe')
        shutil.copy2(candidate, replacement)
        assert hashlib.sha256(replacement.read_bytes()).hexdigest() == staged['binary_sha256']
        os.replace(replacement, EXE)
        receipt.update(applied=True, native=native, reminders=reminders)
        print('Verified candidate installed; restoring the normal FRIDAY desktop.', flush=True)
    finally:
        path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        subprocess.run([str(ROOT / 'venv/Scripts/python.exe'), '-B', str(Path(__file__).resolve()), '--restore',
                        *(['--capsule'] if '--capsule' in sys.argv else ['--rollback'] if '--rollback' in sys.argv else [])],
            cwd=ROOT, timeout=330, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        restored = json.loads((OUTPUT / 'restored.json').read_text(encoding='utf-8'))
        receipt['restored'] = restored
        if receipt['applied']:
            assert restored['binary_sha256'] == staged['binary_sha256']
        path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'applied': receipt['applied'], 'native_passed': receipt['native']['passed'],
                      'pid': restored['pid'], 'backend_ready': restored['backend_ready']}), flush=True)


def main():
    assert '--restore' in sys.argv, 'Use --restore to start the normal local desktop'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Let any concurrent local release build finish before locking its executable.
    deadline = time.monotonic() + 900
    while building():
        assert time.monotonic() < deadline, 'A separate build is still running'
        time.sleep(1)
    if not islands():
        print('Restoring FRIDAY through its normal launcher.', flush=True)
        with (ROOT / 'logs/island-desktop.log').open('ab') as output:
            subprocess.Popen([str(ROOT / 'venv/Scripts/pythonw.exe'), '-B',
                str(ROOT / 'interfaces/taskbar/launch.py')], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 300
    with httpx.Client(trust_env=False, timeout=3) as client:
        while time.monotonic() < deadline:
            current = islands()
            try:
                health = client.get(f'http://127.0.0.1:{config.API_PORT}/health').json()
                if len(current) == 1 and health.get('service') == 'F.R.I.D.A.Y' and health.get('island', {}).get('ready'):
                    result = {'restored': True, 'pid': current[0].pid,
                        'created': current[0].create_time(), 'backend_ready': True, 'island_ready': True,
                        'binary_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest()}
                    (OUTPUT / 'restored.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                    print(json.dumps(result), flush=True)
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
    raise RuntimeError('The normal desktop did not finish starting; inspect logs/island-desktop.log')


if __name__ == '__main__':
    show() if '--show' in sys.argv else status() if '--status' in sys.argv else activate() if '--activate' in sys.argv else main()
