"""Lazy local Windows adapters. Tests replace this object; no shell commands."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import re
import time

from .registry import Skipped

PLAN_GUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
PLANS = {'balanced': 'SCHEME_BALANCED', 'high_performance': 'SCHEME_MIN', 'power_saver': 'SCHEME_MAX'}


class Placement(ctypes.Structure):
    _fields_ = [('length', W.UINT), ('flags', W.UINT), ('showCmd', W.UINT),
                ('ptMinPosition', W.POINT), ('ptMaxPosition', W.POINT), ('rcNormalPosition', W.RECT)]


class Windows:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        for name, args, result in [
            ('PostMessageW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            ('IsWindow', [W.HWND], W.BOOL),
            ('GetWindowThreadProcessId', [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            ('GetWindowPlacement', [W.HWND, ctypes.POINTER(Placement)], W.BOOL),
            ('SetWindowPlacement', [W.HWND, ctypes.POINTER(Placement)], W.BOOL),
        ]:
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result

    def identity(self, hwnd):
        import psutil
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            return dict(pid=pid.value, created=psutil.Process(pid.value).create_time()) if pid.value else None
        except psutil.Error:
            return None

    def alive(self, hwnd, identity):
        return bool(self.user.IsWindow(hwnd) and identity and self.identity(hwnd) == identity)

    def post_close(self, hwnd):
        return bool(self.user.PostMessageW(hwnd, 0x0010, 0, 0))  # WM_CLOSE only; unsaved-work prompts stay visible.

    def placement(self, hwnd):
        p = Placement()
        p.length = ctypes.sizeof(p)
        if not self.user.GetWindowPlacement(hwnd, ctypes.byref(p)):
            raise OSError('Could not read window placement.')
        return [p.flags, p.showCmd, p.ptMinPosition.x, p.ptMinPosition.y,
                p.ptMaxPosition.x, p.ptMaxPosition.y, p.rcNormalPosition.left, p.rcNormalPosition.top,
                p.rcNormalPosition.right, p.rcNormalPosition.bottom]

    def restore(self, hwnd, values):
        if not isinstance(values, list) or len(values) != 10 or any(type(v) is not int for v in values):
            raise ValueError('Invalid saved window placement.')
        p = Placement(ctypes.sizeof(Placement), values[0], values[1], W.POINT(*values[2:4]),
                      W.POINT(*values[4:6]), W.RECT(*values[6:10]))
        if not self.user.SetWindowPlacement(hwnd, ctypes.byref(p)):
            raise OSError('Windows did not restore the window placement.')


class Desktop:
    def __init__(self, api, windows=None):
        self.api, self._windows = api, windows

    @property
    def windows(self):
        if self._windows is None:
            self._windows = Windows()
        return self._windows

    @staticmethod
    def app_name(name):
        from services.automation.command_words import clean_target, resolve_app
        from services.automation.system_control import system
        target = clean_target(name.lower())
        return resolve_app(target, system.list_apps()) or target

    def app_windows(self, name):
        from services.automation.system_control import system, UNCLOSABLE_APPS, APP_REGISTRY, PROCESS_NAMES
        from services.automation import app_finder
        app = self.app_name(name)
        if app in UNCLOSABLE_APPS:
            raise ValueError('The desktop/taskbar cannot be closed or minimized by a scene.')
        names = {n.lower() for n in PROCESS_NAMES.get(app, [])}
        if not names:
            found = APP_REGISTRY.get(app) or app_finder.find_app(app)
            program = app_finder.shortcut_target(found) if found and found.lower().endswith('.lnk') else found
            if not program or not program.lower().endswith('.exe'):
                raise Skipped(f'No exact process identity is registered for {name}.')
            names = {Path(program).name.lower()}
        matcher = system._process_matcher(app, name)
        # The general helper also matches an installation folder. A scene may
        # close/minimize only explicitly identified processes, not their neighbours.
        return app_finder.app_windows(lambda process: process.name().lower() in names and matcher(process))

    def open_app(self, name):
        if name.casefold() in {'college schedules', 'college schedule'}:
            try:
                from interfaces.college.launcher import launch
                launch()
                return
            except ImportError as error:
                raise Skipped('College Schedules UI is not installed.') from error
        from services.automation.system_control import system
        system.open_app(self.app_name(name))

    def close_app(self, name):
        snapshots = [(hwnd, self.windows.identity(hwnd)) for hwnd in self.app_windows(name)]
        refused = [hwnd for hwnd, identity in snapshots if not identity or (self.windows.alive(hwnd, identity)
                   and not self.windows.post_close(hwnd))]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and any(self.windows.alive(h, i) for h, i in snapshots):
            if self.api.stop_event.wait(.1):
                break
        if refused or any(self.windows.alive(h, i) for h, i in snapshots):
            raise Skipped(f'{name} is still open (it may be waiting for you to save work).')

    def window_snapshot(self, name):
        rows = []
        for hwnd in self.app_windows(name):
            identity = self.windows.identity(hwnd)
            if identity is None:
                raise Skipped(f'{name} cannot be safely identified; no windows were minimized.')
            rows.append(dict(hwnd=int(hwnd), identity=identity, placement=self.windows.placement(hwnd)))
        return rows

    def minimize(self, name):
        from services.automation.app_finder import minimize_windows
        previous = self.window_snapshot(name)
        minimize_windows([row['hwnd'] for row in previous])
        return previous

    def restore_windows(self, previous):
        for row in previous:
            if self.windows.alive(row['hwnd'], row['identity']):
                self.windows.restore(row['hwnd'], row['placement'])

    @contextmanager
    def audio(self, device_id=None):
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
        except ImportError as error:
            raise Skipped('Core Audio control is unavailable; install pycaw offline to enable it.') from error
        comtypes.CoInitialize()
        try:
            device = (AudioUtilities.CreateDevice(AudioUtilities.GetDeviceEnumerator().GetDevice(device_id))
                      if device_id else AudioUtilities.GetSpeakers())
            yield device.id, device.EndpointVolume
        except Exception as error:
            raise Skipped('No usable Core Audio output device.') from error
        finally:
            comtypes.CoUninitialize()

    def audio_snapshot(self):
        with self.audio() as (device, volume):
            return dict(device=device, scalar=float(volume.GetMasterVolumeLevelScalar()), mute=bool(volume.GetMute()))

    def set_volume(self, percent):
        with self.audio() as (_, volume):
            volume.SetMasterVolumeLevelScalar(percent / 100, None)
            if percent:
                volume.SetMute(0, None)

    def mute(self, on):
        with self.audio() as (_, volume):
            volume.SetMute(int(on), None)

    def restore_audio(self, token):
        if (not isinstance(token, dict) or type(token.get('scalar')) not in {int, float}
                or not 0 <= token['scalar'] <= 1 or type(token.get('mute')) is not bool
                or not isinstance(token.get('device'), str)):
            raise ValueError('Invalid saved audio state.')
        with self.audio(token['device']) as (_, volume):
            volume.SetMasterVolumeLevelScalar(token['scalar'], None)
            volume.SetMute(int(token['mute']), None)
            if abs(float(volume.GetMasterVolumeLevelScalar()) - token['scalar']) > 1e-7 or bool(volume.GetMute()) != token['mute']:
                raise Skipped('Audio readback differs; restoration is still pending.')

    @contextmanager
    def wmi(self):
        try:
            import pythoncom
            import win32com.client
        except ImportError as error:
            raise Skipped('Built-in-display WMI control is unavailable.') from error
        pythoncom.CoInitialize()
        try:
            yield win32com.client.Dispatch('WbemScripting.SWbemLocator').ConnectServer('.', r'root\WMI')
        finally:
            pythoncom.CoUninitialize()

    def brightness_snapshot(self):
        try:
            with self.wmi() as service:
                rows = {str(row.InstanceName): int(row.CurrentBrightness)
                        for row in service.ExecQuery('SELECT * FROM WmiMonitorBrightness') if row.Active}
        except Exception as error:
            raise Skipped('Built-in-display brightness is unsupported on this computer.') from error
        if not rows:
            raise Skipped('No supported built-in display was found.')
        return rows

    def set_brightness(self, percent):
        previous = self.brightness_snapshot()
        self.restore_brightness({name: percent for name in previous})

    def restore_brightness(self, previous):
        if (not isinstance(previous, dict) or not previous
                or any(not isinstance(k, str) or type(v) is not int or not 0 <= v <= 100 for k, v in previous.items())):
            raise ValueError('Invalid saved brightness state.')
        with self.wmi() as service:
            methods = {str(row.InstanceName): row for row in service.ExecQuery('SELECT * FROM WmiMonitorBrightnessMethods')}
            if set(previous) - set(methods):
                raise Skipped('A previous display is unavailable; brightness restoration is still pending.')
            for name, value in previous.items():
                methods[name].WmiSetBrightness(0, value)
        for _ in range(5):
            actual = self.brightness_snapshot()
            if all(actual.get(name) == value for name, value in previous.items()):
                return
            if self.api.stop_event.wait(.1):
                break
        raise Skipped('Brightness readback differs; restoration is still pending.')

    @staticmethod
    def power_plan():
        from services.automation.system_control import _run_hidden
        response = _run_hidden(['powercfg.exe', '/getactivescheme'])
        found = PLAN_GUID.search(response.stdout)
        if response.returncode or not found:
            raise Skipped('Windows did not report its active power plan.')
        return found.group().lower()

    @staticmethod
    def set_power_plan(plan):
        from services.automation.system_control import _run_hidden
        target = PLANS.get(plan, plan)
        if target not in PLANS.values() and not PLAN_GUID.fullmatch(target):
            raise ValueError('Invalid power-plan identifier.')
        response = _run_hidden(['powercfg.exe', '/setactive', target])
        if response.returncode:
            raise Skipped('Windows could not activate that power plan.')
        if PLAN_GUID.fullmatch(target) and Desktop.power_plan().casefold() != target.casefold():
            raise Skipped('Power-plan readback differs; restoration is still pending.')

    @staticmethod
    def open_url(url):
        from services.automation.system_control import system
        system.open_url(url)

    @staticmethod
    def open_path(path):
        os.startfile(str(Path(path)))

    def play_music(self, value):
        from services.automation import media_control
        if value in {'music', 'resume'}:
            return media_control.play_music(lambda: self.open_app('spotify'))
        return media_control.search_spotify(value)

    @staticmethod
    def processes():
        import psutil
        found = set()
        for process in psutil.process_iter(['pid', 'name', 'create_time']):
            try:
                found.add((process.info['pid'], process.info['create_time'], (process.info['name'] or '').lower()))
            except psutil.Error:
                pass
        return found
