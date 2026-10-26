"""Launcher-to-widget-to-editor checks without owner data or real actions."""
import os
import gc
import time
import tkinter as tk
from types import SimpleNamespace

import httpx
import pytest

from interfaces.settings import launcher
from interfaces.taskbar import panel as panel_module
from interfaces.tray import app as desktop, backend
from test_tray import friday, api, events

native = pytest.mark.skipif(os.environ.get('FRIDAY_PANEL_UI_TEST') != '1',
                            reason='Native GUI check requires an interactive desktop')


def test_normal_desktop_launch_requests_one_background_backend_start(monkeypatch):
    calls = []
    noop = lambda *args, **kwargs: None
    bar = SimpleNamespace(create=noop, request_show=noop, request_quit=noop,
                          request_ask=noop, request_ask_done=noop,
                          run_message_loop=lambda: calls.append('loop'))
    for name in ('reply', 'submit', 'voice_hotkey', 'wake_hotkey', 'conversation_hotkey', 'chat_done'):
        setattr(bar, 'set_' + name + '_listener', noop)
    tray = SimpleNamespace(icon=SimpleNamespace(stop=noop), _stopping=SimpleNamespace(set=noop),
                           notify=noop, bar_submitted=noop, toggle_listening=noop, toggle_wake=noop,
                           toggle_conversation=noop, typed_reply_done=noop, run=noop, status='offline')
    panel = SimpleNamespace(start=lambda: calls.append('panel'), stop=noop,
                            request_toggle=noop, request_show=noop,
                            _lifecycle=lambda action: calls.append('backend:' + action))
    host = SimpleNamespace(start=lambda: calls.append('host'), stop=noop)
    body = SimpleNamespace(_thread=SimpleNamespace(is_alive=lambda: False))
    monkeypatch.setattr(desktop, 'command_bar', bar)
    monkeypatch.setattr(desktop, 'FridayTray', lambda **kwargs: tray)
    monkeypatch.setattr(desktop, 'ControlPanel', lambda *args: panel)
    monkeypatch.setattr(desktop, 'TaskbarButton', lambda *args, **kwargs: host)
    monkeypatch.setattr(desktop, 'FridayBody', lambda *args: body)
    desktop._run_desktop(SimpleNamespace(busy=False))
    assert calls == ['panel', 'host', 'backend:start', 'loop']


@pytest.mark.parametrize('response, expected', [
    (httpx.Response(200, json={'service': 'F.R.I.D.A.Y'}), True),
    (httpx.Response(200, json={'service': 'another app'}), False),
    (httpx.Response(200, json=['F.R.I.D.A.Y']), False),
    (httpx.Response(200, json=None), False),
    (httpx.Response(200, text='<html>Other server</html>'), False),
    (httpx.Response(503, json={'service': 'F.R.I.D.A.Y'}), False),
])
def test_health_requires_friday_identity_and_bypasses_proxies(monkeypatch, response, expected):
    calls = []
    def get(*args, **kwargs):
        calls.append(kwargs)
        return response
    monkeypatch.setattr(backend.httpx, 'get', get)
    assert backend.is_online() is expected
    assert calls[0]['trust_env'] is False


def test_health_connection_failure_is_offline(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('disposable connection failure')
    monkeypatch.setattr(backend.httpx, 'get', unavailable)
    assert backend.is_online() is False


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    gc.collect()  # Dispose test window cycles on the Tcl-owning thread.
    root.destroy()


@pytest.fixture
def panel(friday, monkeypatch, tk_root):
    # Keep test windows in one Tcl interpreter. Production owns a dedicated Tk thread.
    monkeypatch.setattr(panel_module.tk, 'Tk', lambda: tk.Toplevel(tk_root))
    runtime = SimpleNamespace(owned=False, busy=False, message='Stopped')
    instance = panel_module.ControlPanel(friday, runtime, SimpleNamespace(
        request_show=lambda: None, request_quit=lambda: None))
    instance._build()
    monkeypatch.setattr(instance, '_outside', lambda: False)
    yield instance
    for timer in instance.root.tk.call('after', 'info'):
        instance.root.after_cancel(timer)
    instance.root.destroy()
    instance.buttons.clear()
    for key in ('_photo', '_menu_variables', '_menu', 'status', 'detail'):
        instance.__dict__.pop(key, None)
    instance.root = None


@native
@pytest.mark.parametrize('visible', [False, True])
@pytest.mark.parametrize('state', ['stopped', 'online', 'busy', 'owned'])
def test_repeated_launcher_show_starts_once_and_idle_ticks_preserve_stop(panel, monkeypatch, visible, state):
    starts = []
    panel.tray.online = state == 'online'
    panel.runtime.busy = state == 'busy'
    panel.runtime.owned = state == 'owned'
    panel._visible = visible
    def start(action):
        starts.append(action)
        panel.runtime.busy = True
    monkeypatch.setattr(panel, '_lifecycle', start)
    for _ in range(2):
        panel.request_show((1305, 1020, 1480, 1080))
        panel._tick()
        assert panel._visible
    assert starts == (['start'] if state == 'stopped' else [])
    if state == 'stopped':
        panel.runtime.busy = False
        panel.hide()
        for _ in range(3):
            panel._tick()
        assert starts == ['start']
        panel.request_show()
        panel._tick()
        assert starts == ['start', 'start']


@native
def test_actual_flyout_menu_opens_customization_while_offline(panel, monkeypatch):
    opened = []
    panel.tray.online = False
    monkeypatch.setattr(launcher, 'launch', lambda: opened.append(True))
    monkeypatch.setattr(tk.Menu, 'tk_popup', lambda *args: None)
    panel._more_controls()
    menu = panel._menu
    index = next(i for i in range(menu.index('end') + 1)
                 if menu.type(i) != 'separator' and menu.entrycget(i, 'label') == 'Customize FRIDAY…')
    menu.invoke(index)
    deadline = time.monotonic() + 3
    while not opened and time.monotonic() < deadline:
        panel.root.update()
        time.sleep(.01)
    assert opened == [True]
