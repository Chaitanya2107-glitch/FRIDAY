"""Read-only inspection, or --apply to refresh this desktop and verify the real VBS."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import psutil
import win32con
import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from core.config import config
from interfaces.settings import launcher
from interfaces.settings.client import Client
from interfaces.taskbar.host import HOST_CLASS, BUTTON_CLASS
from interfaces.taskbar.windows import LAUNCH_PATH, WINDOW_TITLE

BASE = f'http://{config.API_HOST}:{config.API_PORT}'
OUTPUT = ROOT / 'tasks/desktop-integration-live.json'


def phase(name, **values):
    print(json.dumps({'phase': name, **values}), flush=True)


def health():
    try:
        response = httpx.get(BASE + '/health', timeout=2, trust_env=False)
        data = response.json()
        return response.status_code == 200 and isinstance(data, dict) and data.get('service') == 'F.R.I.D.A.Y'
    except (httpx.HTTPError, ValueError):
        return False


def wait_for(label, check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.25)
    raise RuntimeError('Timed out waiting for ' + label)


def process_for(hwnd):
    return psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1])


def exact_script(process, path):
    try:
        return Path(process.cwd()).resolve() == ROOT and any(
            Path(arg).is_absolute() and Path(arg).resolve() == path for arg in process.cmdline()[1:])
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def close_this_desktop():
    hwnd = win32gui.FindWindow(HOST_CLASS, None)
    if not hwnd:
        return False
    desktop = process_for(hwnd)
    if not exact_script(desktop, LAUNCH_PATH):
        raise RuntimeError('Existing widget is not this checkout; nothing was stopped.')
    bar = win32gui.FindWindow('FridayQuickBarWindow', None)
    if not bar or process_for(bar).pid != desktop.pid:
        raise RuntimeError('Cannot verify command-bar ownership; nothing was stopped.')
    phase('closing_verified_project_desktop', pid=desktop.pid)
    win32gui.PostMessage(bar, win32con.WM_CLOSE, 0, 0)
    desktop.wait(timeout=65)
    wait_for('old desktop windows to close', lambda: not win32gui.FindWindow(HOST_CLASS, None))
    return True


def launch_vbs():
    result = subprocess.run(['cscript.exe', '//nologo', str(ROOT / 'launch_friday.vbs')],
                            cwd=ROOT / 'tasks', capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('The real VBS launcher returned an error: ' + result.stderr.strip())


def managed_backend_groups():
    processes = []
    for process in psutil.process_iter(['name']):
        try:
            if process.info['name'].lower() == 'python.exe' and exact_script(process, ROOT / 'main.py'):
                if '--desktop-managed' in process.cmdline():
                    processes.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    ids = {p.pid for p in processes}
    return sorted(p.pid for p in processes if p.ppid() not in ids)


def verify():
    report = {'started_utc': datetime.now(timezone.utc).isoformat(),
              'authorization': 'tasks/desktop-integration-policy.json',
              'owner_settings_mutated_by_probe': False}
    log_path = ROOT / 'logs/desktop.log'
    offset = log_path.stat().st_size if log_path.exists() else 0
    try:
        report['previous_desktop_closed_gracefully'] = close_this_desktop()
        report['existing_backend_before_launch'] = health()
        phase('launching_real_vbs_from_tasks_folder')
        launch_vbs()
        host = wait_for('resident widget', lambda: win32gui.FindWindow(HOST_CLASS, None))
        desktop = process_for(host)
        if not exact_script(desktop, LAUNCH_PATH):
            raise RuntimeError('The VBS did not activate this checkout.')
        report['desktop_pid'] = desktop.pid
        phase('waiting_for_automatic_backend_start', desktop_pid=desktop.pid)
        started = time.monotonic()
        wait_for('FRIDAY backend health without clicking the widget', health, timeout=310)
        report['health_wait_seconds'] = round(time.monotonic() - started, 3)
        report['backend_healthy_after_vbs'] = True
        groups = managed_backend_groups()
        report['managed_backend_groups'] = groups
        if not report['existing_backend_before_launch'] and len(groups) != 1:
            raise RuntimeError('Expected exactly one managed backend after the VBS launch.')
        report['automatic_background_start_verified'] = not report['existing_backend_before_launch'] and len(groups) == 1
        report['backend_reused'] = report['existing_backend_before_launch']

        panel = wait_for('flyout window', lambda: win32gui.FindWindow(None, WINDOW_TITLE))
        for attempt in range(2):
            launch_vbs()
            wait_for('repeat launch to show the flyout', lambda: win32gui.IsWindowVisible(panel))
            time.sleep(.5)
            if process_for(win32gui.FindWindow(HOST_CLASS, None)).pid != desktop.pid:
                raise RuntimeError('Repeat launch replaced the resident desktop.')
            if managed_backend_groups() != groups:
                raise RuntimeError('Repeat launch created or replaced a managed backend.')
        report['duplicate_launch_preserves_desktop_and_backend'] = True
        report['duplicate_launch_keeps_flyout_visible'] = bool(win32gui.IsWindowVisible(panel))

        button = win32gui.FindWindowEx(win32gui.FindWindow('Shell_TrayWnd', None), 0, BUTTON_CLASS, None)
        report['taskbar_button_present'] = bool(button)
        report['flyout_toolwindow'] = bool(win32gui.GetWindowLong(panel, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW)
        report['flyout_has_separate_app_button'] = bool(win32gui.GetWindowLong(panel, win32con.GWL_EXSTYLE) & win32con.WS_EX_APPWINDOW)
        if not button:
            raise RuntimeError('The taskbar button has no visible native child; inspect available taskbar space.')
        if not report['flyout_toolwindow'] or report['flyout_has_separate_app_button']:
            raise RuntimeError('The flyout has incorrect native window styles.')
        client = Client()
        catalogs = {}
        for section in ('contacts', 'routines', 'projects', 'modes'):
            data = client.load(section)
            catalogs[section] = {'loaded': True, 'entries': len(data['items'])}
        report['live_frontend_catalogs'] = catalogs

        existing = win32gui.FindWindow(None, launcher.TITLE)
        if not existing:
            launcher.launch()
        editor = wait_for('real customization window', lambda: win32gui.FindWindow(None, launcher.TITLE))
        editor_process = process_for(editor)
        if ('interfaces.settings' not in editor_process.cmdline()
                or Path(editor_process.cwd()).resolve() != ROOT):
            raise RuntimeError('Customization window belongs to an unexpected process.')
        report['customization_window_open'] = True
        report['customization_window_reused'] = bool(existing)
        report['customization_pid'] = editor_process.pid
        report['left_running'] = health()
        if not report['left_running']:
            raise RuntimeError('FRIDAY stopped responding during the live check.')
        if log_path.exists():
            with log_path.open('rb') as stream:
                stream.seek(offset)
                fresh_log = stream.read().decode('utf-8', errors='replace')
            report['new_desktop_tracebacks'] = fresh_log.count('Traceback (most recent call last)')
            if report['new_desktop_tracebacks']:
                raise RuntimeError('Fresh desktop errors were logged during the live check.')
        report['source_sha256'] = {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
                                  for path in ('launch_friday.vbs', 'interfaces/tray/app.py',
                                               'interfaces/tray/backend.py', 'interfaces/taskbar/panel.py',
                                               'interfaces/taskbar/host.py', 'interfaces/settings/app.py')}
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        OUTPUT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        phase('verification_receipt', path=str(OUTPUT), status=report['status'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Refresh this checkout desktop and leave FRIDAY running')
    args = parser.parse_args()
    if args.apply:
        verify()
    else:
        print(json.dumps({'online': health(), 'managed_backend_groups': managed_backend_groups()}))
