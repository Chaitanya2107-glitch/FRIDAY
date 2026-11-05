"""Island surface over the existing desktop controller and backend lifecycle."""
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time

import httpx
import psutil

from core.logger import logger
from interfaces.tray import backend
from services.friday_island_server.config import load_config

ROOT = Path(__file__).resolve().parents[2]
EXECUTABLE = ROOT / 'island/src-tauri/target/release/friday-island.exe'


class IslandDesktop:
    def __init__(self, tray, panel, runtime, bar):
        self.tray, self.panel, self.runtime, self.bar = tray, panel, runtime, bar
        self.enabled = EXECUTABLE.is_file() and os.environ.get('FRIDAY_LEGACY_DESKTOP') != '1'
        self.process = None
        self.owner = secrets.token_hex(24)
        self.closing = threading.Event()
        self._start_requested = threading.Event()
        self._notify = tray.notify
        self._attached_pid = next((int(arg.split('=', 1)[1]) for arg in __import__('sys').argv
                                   if arg.startswith('--island-owner=')), None)
        self.executable = EXECUTABLE
        self.created = None
        if not self._attached_pid:
            self.enabled = self.enabled and load_config().startup.start_with_friday
        if self._attached_pid:
            try:
                process = psutil.Process(self._attached_pid)
                candidate = Path(process.exe()).resolve()
                if candidate.name.lower() != 'friday-island.exe':
                    raise ValueError('Invalid Island owner')
                self.executable, self.created = candidate, process.create_time()
                self.enabled = os.environ.get('FRIDAY_LEGACY_DESKTOP') != '1'
            except (psutil.Error, OSError, ValueError):
                self.enabled = False

    def summon(self, anchor=None):
        if not self.enabled:
            self.panel.request_show(anchor)
            return
        self._start_requested.set()
        self._launch(background=False)

    def _ensure_started(self):
        if not self._start_requested.is_set() or self.runtime.busy:
            return
        self._start_requested.clear()
        if not backend.is_online():
            self.panel._lifecycle('start')

    def _launch(self, background=True):
        env = {**os.environ, 'FRIDAY_ISLAND_MANAGE_BRIDGE': '0'}
        with (ROOT / 'logs/island-desktop.log').open('ab') as output:
            child = subprocess.Popen([str(self.executable), *(['--background'] if background else [])],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW)
        if self.process is None and child.poll() is None:
            self.process = child

    def start(self):
        if not self.enabled:
            return
        if not self._attached_pid:
            self._launch()
        self.tray.notify = self.notify
        self.tray._ask_in_bar = self.question
        self.tray._ask_done = lambda: None
        self.tray.voice_state = self.reply_state
        threading.Thread(target=self._run, name='friday-island-desktop', daemon=True).start()

    def _post(self, path, data):
        token = load_config().connection.token
        with httpx.Client(trust_env=False, timeout=2) as client:
            reply = client.post(backend.BASE_URL + '/api/v1/island/' + path,
                                headers={'X-Friday-Island': token}, json=data)
            reply.raise_for_status()
            return reply.json()

    def notify(self, text, transient=False, *, private=False):
        if not private:
            try:
                if self._post('event', {'kind': 'response', 'text': text, 'transient': transient})['accepted']:
                    return
            except (httpx.HTTPError, OSError, ValueError):
                pass
        self._notify(text, transient, private=private)

    def question(self, text):
        try:
            if self._post('event', {'kind': 'question', 'text': text})['accepted']:
                return
        except (httpx.HTTPError, OSError, ValueError):
            pass
        self.bar.request_ask(text)

    def reply_state(self, awaiting):
        try:
            self._post('event', {'kind': 'reply_state', 'text': '', 'awaiting_reply': awaiting})
        except (httpx.HTTPError, OSError, ValueError):
            pass

    def state(self):
        tray = self.tray
        return dict(listening=tray.listening, wake=tray.wake_on, conversation=tray.in_conversation,
                    speak=backend.settings.speak_replies, speak_typed=backend.settings.speak_typed,
                    provider=backend.settings.provider, body=bool(tray.body and tray.body.visible),
                    busy=self.runtime.busy, owned=self.runtime.owned, message=self.runtime.message)

    def dispatch(self, command):
        if time.monotonic() >= command.get('expires', float('inf')):
            return False
        action, value = command['action'], command.get('value', '')
        actions = {'listen': self.tray.toggle_listening, 'wake': self.tray.toggle_wake,
                   'conversation': self.tray.toggle_conversation, 'speech': self.tray.toggle_speak_replies,
                   'speak_typed': self.tray.toggle_speak_typed, 'body': self.tray.toggle_body,
                   'controls': self.panel.request_show, 'customization': self.tray.open_customization,
                   'college': self.tray.open_college_schedules, 'productivity': self.tray.open_productivity,
                   'quit': self.bar.request_quit, 'typed_done': self.tray.typed_reply_done}
        if action in {'start', 'stop', 'restart'}:
            if action == 'start':
                self._start_requested.set()
            else:
                self._start_requested.clear()
                self.panel._lifecycle(action)
        elif action == 'typed':
            self.tray.bar_submitted(value)
        elif action == 'provider':
            backend.settings.provider = value or None
        elif action in actions:
            actions[action]()
        else:
            return False
        return True

    def _alive(self):
        if self._attached_pid:
            try:
                process = psutil.Process(self._attached_pid)
                return Path(process.exe()).resolve() == self.executable.resolve() and process.create_time() == self.created
            except (psutil.Error, OSError):
                return False
        if self.process is not None and self.process.poll() is None:
            return True
        for process in psutil.process_iter(['pid', 'exe', 'create_time']):
            try:
                if process.info['exe'] and Path(process.info['exe']).resolve() == self.executable.resolve():
                    self._attached_pid, self.created = process.pid, process.info['create_time']
                    return True
            except (psutil.Error, OSError):
                continue
        return False

    def _run(self):
        completed = []
        while not self.closing.is_set():
            if not self._alive():
                self.bar.request_quit()
                return
            self._ensure_started()
            try:
                response = self._post('desktop', {'owner': self.owner, 'state': self.state(), 'completed': completed})
                completed = []
                for command in response['commands']:
                    if self.dispatch(command):
                        completed.append(command['id'])
            except (httpx.HTTPError, OSError, ValueError, KeyError):
                pass  # A stopped backend stays stopped until an explicit launch/start.
            self.closing.wait(.5)

    def close(self):
        self.closing.set()
        if self.enabled and self._alive():
            try:
                subprocess.run([str(self.executable), '--quit', '--background'], cwd=ROOT,
                    env={**os.environ, 'FRIDAY_ISLAND_MANAGE_BRIDGE': '0'}, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                logger.warning('Island did not acknowledge desktop shutdown')
