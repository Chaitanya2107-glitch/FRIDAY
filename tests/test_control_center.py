"""Real native widgets and isolated transports; no owner actions or model calls."""
import copy
import json
import threading
import time
import tkinter as tk

import pytest

from interfaces.control_center import app as ui, catalog, focus, launcher
from interfaces.control_center.client import Client, Error
from interfaces.tray import backend
from test_tray import api, events, friday, find, click


class FakeClient:
    def __init__(self):
        self.calls, self.threads = [], []
        self.reply = {'response': 'Done.', 'awaiting_reply': False}
        self.failure = None
        self.gate = None
        self.data = {
            'online': True, 'health': {'service': 'F.R.I.D.A.Y'},
            'providers': {'active': 'ollama', 'available': ['ollama', 'openrouter']},
            'system': {'mode': {'name': 'study'}, 'spotify': {'connected': False},
                       'screen_watch': {'state': 'paused'}},
            'desktop': {'connected': True, 'listening': False, 'wake': True, 'conversation': False},
            'stats': {'lines': ['CPU 5%', 'RAM 30%']}, 'files': {'files': 12},
            'automation': {'active': False, 'state': 'idle'}, 'errors': {},
        }

    def snapshot(self):
        self.calls.append(('snapshot',))
        self.threads.append(threading.get_ident())
        return copy.deepcopy(self.data)

    def chat(self, message, provider, speak):
        self.calls.append(('chat', message, provider, speak))
        self.threads.append(threading.get_ident())
        if self.gate:
            self.gate.wait(5)
        if self.failure:
            raise self.failure
        return copy.deepcopy(self.reply)

    def control(self, action):
        self.calls.append(('control', action))
        return {'ok': True, 'text': 'Requested.'}

    def history(self):
        return [{'role': 'user', 'content': 'Earlier question'}, {'role': 'assistant', 'content': 'Earlier answer'}]

    def clear_history(self):
        self.calls.append(('clear',))
        return {'message': 'Cleared.'}


def spin(window, condition, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.root.update()
        if condition():
            return
        time.sleep(.01)
    pytest.fail('Native control-center request did not finish')


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def window(monkeypatch, tk_root):
    monkeypatch.setattr(ui.messagebox, 'askyesno', lambda *a, **kw: True)
    root = tk.Toplevel(tk_root)
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    window = ui.ControlCenter(root, FakeClient())
    spin(window, lambda: not window.running)
    yield window
    if not window.closed:
        window.close()
    assert not errors


def test_catalog_covers_every_production_family_and_loads_all_guides():
    by_key = {item.key: item for item in catalog.CAPABILITIES}
    assert len(by_key) == len(catalog.CAPABILITIES) == 64
    for family, commands in catalog.PHRASE_GROUPS.items():
        item = by_key[family]
        assert item.description and item.how and item.requires and item.guide in catalog.GUIDES
        assert set(commands) <= set(item.examples)
        assert all(alias in item.examples for aliases in commands.values() for alias in aliases)
    for key in catalog.GUIDES:
        assert catalog.read_guide(key).strip()
    with pytest.raises(ValueError):
        catalog.read_guide('../.env')


def test_search_includes_aliases_requirements_and_multiple_terms():
    assert any(item.key == 'device' for item in catalog.search('recent copies'))
    assert any(item.key == 'phone' for item in catalog.search('KDE paired'))
    assert all(item.category == 'Music' for item in catalog.search('', 'Music'))
    assert not catalog.search('no-such-friday-feature')


def test_client_uses_shared_api_with_explicit_per_request_preferences(monkeypatch):
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {'response': 'Answer', 'private': True, 'keyboard': [{'text': 'hello'}]}
    monkeypatch.setattr(backend, '_request', request)
    result = Client().chat('list reminders', 'ollama', True)
    method, path, options = calls[0]
    assert (method, path) == ('POST', '/api/v1/chat')
    assert options['json'] == {'message': 'list reminders', 'provider': 'ollama', 'speak': True}
    assert options['timeout'] >= 60 and options['trust_env'] is False
    assert result['private'] and result['keyboard']
    for message in ('', ' ' * 5, 'x' * 4001, 'bad\x00value'):
        with pytest.raises(Error):
            Client().chat(message)
    assert len(calls) == 1


def test_offline_status_and_partial_failure_do_not_reuse_stale_state(monkeypatch):
    client = Client()
    monkeypatch.setattr(client, 'request', lambda *a, **kw: (_ for _ in ()).throw(Error('offline')))
    assert client.snapshot() == {'online': False, 'error': 'offline'}
    def request(method, path, **kw):
        if path == '/health':
            return {'service': 'F.R.I.D.A.Y'}
        raise Error('Unavailable route', 404)
    monkeypatch.setattr(client, 'request', request)
    monkeypatch.setattr(client, 'desktop_state', lambda: (_ for _ in ()).throw(Error('no desktop')))
    status = client.snapshot()
    assert status['online'] and len(status['errors']) == 6
    assert 'system' not in status and 'desktop' not in status


def test_conversation_command_delegates_existing_desktop_not_a_second_mic(monkeypatch):
    client, calls = Client(), []
    monkeypatch.setattr(client, 'desktop_state', lambda: {'connected': True, 'conversation': False})
    monkeypatch.setattr(client, 'control', lambda action: calls.append(action))
    assert 'Conversation mode requested' in client.chat('conversation mode')['response']
    assert calls == ['conversation']
    calls.clear()
    monkeypatch.setattr(client, 'desktop_state', lambda: {'connected': True, 'conversation': True})
    client.chat('conversation mode')
    assert not calls


def test_typed_requests_do_not_race_active_voice_input(monkeypatch):
    client = Client()
    monkeypatch.setattr(client, 'desktop_state', lambda: {'connected': True, 'conversation': True})
    monkeypatch.setattr(client, 'request', lambda *a, **kw: pytest.fail('Typed chat must not overlap voice'))
    with pytest.raises(Error, match='Voice input is active'):
        client.chat('yes')


def test_desktop_bridge_authenticates_and_matches_response_id(monkeypatch):
    from types import SimpleNamespace
    from websockets.sync import client as ws_client
    sent = []
    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def send(self, text):
            sent.append(json.loads(text))
        def recv(self, **kwargs):
            if len(sent) == 1:
                return json.dumps({'v': 1, 'type': 'handshake', 'ok': True})
            return json.dumps({'v': 1, 'type': 'runtime_action', 'id': sent[-1]['id'], 'ok': True, 'text': 'Requested.'})
    options = {}
    def connect(url, **kwargs):
        options.update(kwargs)
        assert url == 'ws://127.0.0.1:17321'
        return Socket()
    monkeypatch.setattr(ws_client, 'connect', connect)
    monkeypatch.setattr(Client, '_connection', staticmethod(lambda: SimpleNamespace(port=17321, token='test-token')))
    assert Client().control('wake')['ok']
    assert sent[0]['token'] == 'test-token'
    assert sent[1]['action'] == 'wake' and sent[1]['type'] == 'runtime_action'
    assert options['proxy'] is None
    with pytest.raises(Error):
        Client().control('arbitrary_shell')


@pytest.mark.parametrize('message', ['look at my screen', 'describe my current display',
    'what am I looking at', 'read the selection', 'read it out loud', 'read aloud',
    '\\c yes', '\\v explain this', 'desktop task type Hello', 'add this to my reading list'])
def test_target_guard_reuses_actual_screen_and_read_aloud_routing(message):
    assert focus.requires_target(message)


@pytest.mark.parametrize('message', ['list reminders', 'set volume to 30', 'screen awareness status',
                                    'research graph algorithms', 'phone status', 'desktop stop', '\\c status'])
def test_ordinary_commands_do_not_require_target(message):
    assert not focus.requires_target(message)


def test_six_pages_offline_library_and_examples_never_execute(window):
    assert set(window.pages) == {'home', 'library', 'chat', 'guides', 'tools', 'status'}
    assert all(call == ('snapshot',) for call in window.client.calls)
    window.client.data = {'online': False, 'error': 'not running'}
    window.refresh()
    spin(window, lambda: not window.running)
    assert 'offline' in window.connection.get()
    library = window.pages['library']
    library.query.set('recent copies')
    assert 'device' in library.list.get_children()
    library.list.selection_set('device')
    library.select()
    command = library.example()
    library.use()
    assert window.view == 'chat'
    assert window.pages['chat'].input.get('1.0', 'end-1c') == command
    assert not any(call[0] == 'chat' for call in window.client.calls)
    library.query.set('no-such-feature')
    assert not library.list.get_children()
    assert 'No matches' in library.detail.text.get('1.0', 'end')


def test_guides_render_search_and_missing_file_without_crashing(window, monkeypatch):
    window.open_guide('BROWSER_AUTOMATION.md')
    guides = window.pages['guides']
    guides.query.set('browser')
    assert 'matches' in guides.matches.cget('text')
    assert guides.document.text.tag_ranges('match')
    monkeypatch.setattr(catalog, 'read_guide', lambda key: (_ for _ in ()).throw(OSError('missing')))
    guides.open('FEATURES.md')
    assert 'Guide unavailable' in guides.document.text.get('1.0', 'end')


def test_chat_failure_retains_draft_and_success_sends_once_with_preferences(window):
    chat = window.pages['chat']
    chat.draft('list reminders')
    window.client.failure = Error('backend unavailable')
    chat.send()
    spin(window, lambda: not chat.busy)
    assert chat.input.get('1.0', 'end-1c') == 'list reminders'
    assert 'backend unavailable' in chat.transcript.get('1.0', 'end')
    window.client.failure = None
    chat.provider.set('ollama')
    chat.speak.set(True)
    chat.send()
    chat.send()  # A second click during work must not submit again.
    spin(window, lambda: not chat.busy)
    assert chat.input.get('1.0', 'end-1c') == ''
    calls = [call for call in window.client.calls if call[0] == 'chat']
    assert len(calls) == 2 and calls[-1] == ('chat', 'list reminders', 'ollama', True)


def test_confirmation_and_browser_approval_keep_correct_scopes(window):
    chat = window.pages['chat']
    window.client.reply = {'response': 'Are you sure?', 'awaiting_reply': True}
    chat.draft('organise downloads')
    chat.send()
    spin(window, lambda: not chat.busy)
    assert chat.awaiting and chat.confirm_yes == 'yes'
    chat.yes_button.invoke()
    spin(window, lambda: not chat.busy)
    assert any(call[:2] == ('chat', 'yes') for call in window.client.calls)
    window.client.reply = {'response': 'Review this browser step', 'awaiting_reply': True, 'automation_job': 'job-1'}
    chat.draft('browser task find tkinter')
    chat.send()
    spin(window, lambda: not chat.busy)
    assert chat.confirm_yes == 'browser yes' and chat.confirm_no == 'browser stop'
    chat.no_button.invoke()
    spin(window, lambda: not chat.busy)
    assert any(call[:2] == ('chat', 'browser stop') for call in window.client.calls)


def test_keyboard_response_is_prepared_and_target_required_before_input(window, monkeypatch):
    chat = window.pages['chat']
    window.client.reply = {'response': 'Prepared.', 'keyboard': [{'text': 'Hello'}], 'private': True}
    chat.draft('type Hello')
    chat.send()
    spin(window, lambda: not chat.busy)
    assert chat.steps == [{'text': 'Hello'}]
    assert 'PREPARED INPUT' in chat.transcript.get('1.0', 'end')
    calls = []
    monkeypatch.setattr(chat, 'countdown', lambda callback: callback(('window', 42, 1.0)))
    monkeypatch.setattr(focus, 'apply', lambda target, steps: calls.append((target, steps)) or 'Submitted.')
    chat.apply_button.invoke()
    spin(window, lambda: not chat.busy)
    assert calls == [(('window', 42, 1.0), [{'text': 'Hello'}])]
    chat.type_steps()
    assert len(calls) == 1


def test_screen_request_without_target_does_not_capture_center(window):
    chat = window.pages['chat']
    chat.draft('look at my screen')
    chat.send()
    assert not chat.busy
    assert not any(call[0] == 'chat' for call in window.client.calls)
    assert 'Target app' in window.message.get()


def test_focus_change_cancels_input_and_reports_partial_submission(monkeypatch):
    from services.automation import keyboard
    captured = [(100, 20, 1.0), (101, 20, 1.0)]
    calls = []
    monkeypatch.setattr(focus, 'capture', lambda: captured.pop(0))
    monkeypatch.setattr(keyboard, 'run_steps', lambda steps: calls.extend(steps))
    with pytest.raises(Error, match='after 1 submitted steps'):
        focus.apply((100, 20, 1.0), [{'text': 'first'}, {'text': 'second'}])
    assert calls == [{'text': 'first'}]


def test_loading_history_clears_hidden_keyboard_and_confirmation_state(window):
    chat = window.pages['chat']
    chat.steps = [{'text': 'Unseen old input'}]
    chat.set_awaiting(True)
    chat.history()
    spin(window, lambda: not chat.busy)
    assert not chat.steps and not chat.awaiting
    assert str(chat.apply_button.cget('state')) == 'disabled'
    assert 'Earlier answer' in chat.transcript.get('1.0', 'end')


def test_task_progress_is_bound_to_started_job(window):
    chat = window.pages['chat']
    chat.active_job = 'started-job'
    chat.progress({'job_id': 'other-job', 'response': 'Wrong job', 'active': True})
    assert 'Wrong job' not in chat.transcript.get('1.0', 'end')
    progress = {'job_id': 'started-job', 'response': 'Review next step', 'active': True, 'awaiting_reply': True}
    chat.progress(progress)
    chat.progress(progress)
    assert chat.transcript.get('1.0', 'end').count('Review next step') == 1
    assert chat.awaiting and chat.confirm_yes == 'browser yes'


def test_desktop_approvals_keep_target_handoff_through_progress(window, monkeypatch):
    chat = window.pages['chat']
    window.client.reply = {'response': 'Review the step', 'automation_job': 'desktop-job', 'awaiting_reply': True}
    monkeypatch.setattr(focus, 'verify', lambda target: None)
    target = (100, 20, 1.0)
    monkeypatch.setattr(chat, 'countdown', lambda callback: callback(target))
    chat.draft('desktop task type Hello')
    chat.target_send()
    spin(window, lambda: not chat.busy)
    assert chat.job_desktop and chat.confirm_yes == 'desktop yes'
    chat.progress({'job_id': 'desktop-job', 'response': 'Approve typing', 'active': True, 'awaiting_reply': True})
    assert chat.confirm_yes == 'desktop yes'
    chat.yes_button.invoke()
    spin(window, lambda: not chat.busy)
    assert any(call[:2] == ('chat', 'desktop yes') for call in window.client.calls)
    assert chat.job_desktop


def test_background_io_does_not_block_tk_and_close_cancels_callbacks(window):
    chat = window.pages['chat']
    gate = threading.Event()
    window.client.gate = gate
    chat.draft('list reminders')
    chat.send()
    ticks = []
    window.root.after(20, lambda: ticks.append('alive'))
    spin(window, lambda: bool(ticks))
    assert chat.busy
    assert all(worker != threading.get_ident() for worker in window.client.threads)
    window.close()
    gate.set()
    assert window.closed and not window.timers


def test_native_editor_and_start_launch_fixed_existing_modules(window, monkeypatch):
    calls = []
    monkeypatch.setattr(ui, 'open_editor', lambda key: calls.append(('editor', key)) or 'Opened.')
    monkeypatch.setattr(ui, 'start_desktop', lambda: calls.append(('start',)) or 'Starting.')
    window.editor('college')
    spin(window, lambda: not window.running)
    window.start()
    spin(window, lambda: not window.running)
    assert calls == [('editor', 'college'), ('start',)]
    spawned = []
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda args, **kw: spawned.append((args, kw)))
    launcher.launch()
    launcher.start_desktop()
    assert spawned[0][0][-2:] == ['-m', 'interfaces.control_center']
    assert spawned[1][0][-1].endswith('interfaces\\taskbar\\launch.py') or spawned[1][0][-1].endswith('interfaces/taskbar/launch.py')
    assert all(row[1]['cwd'] == catalog.ROOT for row in spawned)


def test_small_window_keeps_example_list_visible_and_tools_scrollable(window):
    window.root.deiconify()
    window.root.geometry('1080x720')
    window.show('library')
    window.root.update()
    library = window.pages['library']
    assert library.examples.winfo_height() >= 100
    assert library.examples.winfo_rooty() + library.examples.winfo_height() < window.root.winfo_rooty() + window.root.winfo_height()
    window.show('tools')
    window.root.update()
    page = window.pages['tools']
    assert page.canvas.winfo_height() > 100
    page.canvas.yview_moveto(1)
    window.root.update()
    assert page.canvas.yview()[1] == 1.0


def test_tray_entry_opens_center_without_starting_backend(friday, monkeypatch):
    from interfaces.tray import tray as tray_module
    calls = []
    monkeypatch.setattr(launcher, 'launch', lambda: calls.append('opened'))
    monkeypatch.setattr(tray_module, '_in_background', lambda fn, *args: fn(*args))
    click(friday, find(friday.icon.menu, 'Control Center & Guide'))
    assert calls == ['opened']
