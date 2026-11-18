"""Island migration checks never touch the owner's clipboard, files or windows."""
import asyncio
from types import SimpleNamespace
import time

import pytest

from services.desktop_visibility import suppressed as foreground_suppressed
from services.friday_island_server.tools import DesktopTools
from tests.test_island_runtime import run_async


@pytest.mark.parametrize('state, maximized, covers_monitor, app, expected', [
    (2, False, False, 'WindowsTerminal.exe', False),
    (5, True, True, 'WindowsTerminal.exe', False),
    (2, False, True, 'WindowsTerminal.exe', True),
    (3, True, True, 'WindowsTerminal.exe', True),
    (5, True, True, 'VALORANT.exe', True),
])
def test_desktop_visibility_checks_the_current_foreground(monkeypatch, state, maximized, covers_monitor, app, expected):
    import ctypes
    import psutil
    import win32api
    import win32con
    import win32gui
    import win32process
    def notification_state(output):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_int))[0] = state
        return 0

    bounds = (0, 0, 1920, 1080)
    monkeypatch.setattr(ctypes.windll.shell32, 'SHQueryUserNotificationState', notification_state)
    monkeypatch.setattr(win32gui, 'GetForegroundWindow', lambda: 1)
    monkeypatch.setattr(win32gui, 'IsIconic', lambda hwnd: False)
    monkeypatch.setattr(win32gui, 'GetClassName', lambda hwnd: 'AppWindow')
    monkeypatch.setattr(win32gui, 'GetWindowText', lambda hwnd: '')
    monkeypatch.setattr(win32gui, 'GetWindowLong', lambda hwnd, field: win32con.WS_MAXIMIZE if maximized else 0)
    monkeypatch.setattr(win32gui, 'GetWindowRect', lambda hwnd: bounds if covers_monitor else (0, 0, 800, 600))
    monkeypatch.setattr(win32api, 'MonitorFromWindow', lambda hwnd, flags: 1)
    monkeypatch.setattr(win32api, 'GetMonitorInfo', lambda monitor: {'Monitor': bounds})
    monkeypatch.setattr(win32process, 'GetWindowThreadProcessId', lambda hwnd: (1, -1))
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(name=lambda: app))
    assert foreground_suppressed() is expected


@run_async
async def test_private_clipboard_handles_are_connection_bound_and_revoked(monkeypatch):
    from interfaces.api.routes import clipboard, files
    from services.automation import routines, system_stats, clipboard as native
    async def history(): return SimpleNamespace(items=['private fixture'])
    async def status(): return {'enabled': True, 'files': 2}
    monkeypatch.setattr(clipboard, 'get_clipboard_history', history)
    monkeypatch.setattr(files, 'file_search_status', status)
    monkeypatch.setattr(routines, 'load', lambda: {'start work': ['open notepad']})
    monkeypatch.setattr(system_stats, 'menu_lines', lambda: ['CPU 1%'])
    copied = []
    monkeypatch.setattr(native, 'set_text', copied.append)
    tools = DesktopTools()
    data = await tools.request('owner', 'read')
    key = data['clipboard'][0]['id']
    assert data['stats'] == ['CPU 1%'] and data['routines'] == ['start work']
    with pytest.raises(ValueError): await tools.request('other', 'clipboard_copy', key)
    assert (await tools.request('owner', 'clipboard_copy', key))['ok']
    assert copied == ['private fixture']
    await tools.request('owner', 'close')
    with pytest.raises(ValueError): await tools.request('owner', 'clipboard_copy', key)
    with pytest.raises(ValueError): await tools.request('owner', 'powershell', value='arbitrary')


@run_async
async def test_predictions_are_server_owned_consumed_once_and_private_safe(monkeypatch):
    from interfaces.api.routes import system
    calls = []
    async def suggestions(): return {'suggestions': ['list reminders']}
    async def outcome(body): calls.append(body.model_dump())
    monkeypatch.setattr(system, 'bar_suggestions', suggestions)
    monkeypatch.setattr(system, 'bar_outcome', outcome)
    tools = DesktopTools()
    assert (await tools.suggestions('owner'))[0]['fill']
    await tools.outcome('other', 'list reminders')
    assert not calls
    await tools.outcome('owner', 'list reminders')
    await tools.outcome('owner', 'list reminders')
    assert calls == [{'offered': ['list reminders'], 'sent': 'list reminders'}]
    await tools.suggestions('owner')
    tools.private_pending.add('owner')
    await tools.outcome('owner', 'private approval')
    assert calls[-1]['sent'] is None
    tools.disconnect('owner')
    assert not tools.predictions and not tools.private_pending


def test_sensitive_requests_check_foreground_and_process_identity(monkeypatch):
    import win32gui
    import win32process
    import psutil
    from services.friday_island_server.focus import check_target, requires_target
    assert requires_target('\\c click save')
    assert requires_target('\\c yes')
    assert requires_target("what's on my screen?")
    for command in ['hello', '\\c status', '\\c stop', '\\c no']:
        assert not requires_target(command)
    monkeypatch.setattr(win32gui, 'GetForegroundWindow', lambda: 12)
    monkeypatch.setattr(win32process, 'GetWindowThreadProcessId', lambda hwnd: (1, 99))
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(create_time=lambda: 1))
    check_target({'hwnd': 12, 'pid': 99, 'captured_at': 2})
    for target in [None, {'hwnd': 13, 'pid': 99, 'captured_at': 2},
                   {'hwnd': 12, 'pid': 100, 'captured_at': 2},
                   {'hwnd': 12, 'pid': 99, 'captured_at': .5},
                   {'hwnd': 12, 'pid': 99, 'captured_at': time.time() + 100}]:
        with pytest.raises(ValueError): check_target(target)


@run_async
async def test_failed_focus_never_reaches_the_canonical_chat(monkeypatch):
    from interfaces.api.routes import chat
    from services.friday_island_server import focus
    from services.friday_island_server.runtime import FridayRuntime
    from services.friday_island_server import desktop_link
    monkeypatch.setattr(desktop_link.desktop, 'snapshot', lambda: {})
    def fail(target): raise ValueError('foreground changed')
    monkeypatch.setattr(focus, 'check_target', fail)
    async def chat_must_not_run(request): pytest.fail('unsafe computer command reached chat')
    monkeypatch.setattr(chat, 'chat', chat_must_not_run)
    with pytest.raises(ValueError, match='foreground changed'):
        await FridayRuntime().command('\\c yes', object(), {'hwnd': 12, 'pid': 99, 'captured_at': 2})


def test_gaming_withdraws_badge_and_revokes_capture_before_hiding(monkeypatch):
    from interfaces.taskbar.screen_badge import ScreenBadge
    from services import desktop_visibility
    monkeypatch.setattr(desktop_visibility, 'suppressed', lambda: True)
    badge = object.__new__(ScreenBadge)
    badge.tray = SimpleNamespace(online=True, screen_indicator=123,
        runtime_status={'screen_watch': {'enabled': True, 'paused': False}})
    badge._pending_pause = False
    hidden = []
    badge.window = SimpleNamespace(withdraw=lambda: hidden.append(badge.tray.screen_indicator))
    badge.update()
    assert hidden == [0] and badge.tray.screen_indicator == 0


def test_gaming_defers_toasts_and_island_delivery_avoids_windows_popup(monkeypatch):
    from services import desktop_visibility
    from services.reminders import service
    from services.friday_island_server import events
    monkeypatch.setattr(service, '_show_toast', lambda *a, **kw: pytest.fail('Windows popup bypassed Island'))
    monkeypatch.setattr(desktop_visibility, 'suppressed', lambda: True)
    assert not service.show_toast('FRIDAY', 'Due reminder', mirror_telegram=False)
    monkeypatch.setattr(desktop_visibility, 'suppressed', lambda: False)
    monkeypatch.setattr(events, 'connected', lambda: True)
    delivered = []
    monkeypatch.setattr(events, 'publish', lambda *a, **kw: delivered.append((a, kw)))
    assert service.show_toast('FRIDAY', 'Due reminder', mirror_telegram=False)
    assert delivered[0][0] == ('notification', 'Due reminder')
    assert service.show_toast('FRIDAY', 'Opened', transient=True, mirror_telegram=False)
    assert delivered[-1][1]['transient'] is True


def test_private_voice_events_are_ephemeral_and_never_public_history():
    from services.friday_island_server import events
    owner = object()
    events.listen(owner, True)
    try:
        before = events.snapshot(0)
        events.publish_private('secret fixture')
        assert events.snapshot(0) == before
        assert events.take_private(owner)[0]['text'] == 'secret fixture'
        assert events.take_private(owner) == []
        events.publish_private('discard on disconnect')
    finally:
        events.listen(owner, False)
    assert events.take_private(owner) == []
