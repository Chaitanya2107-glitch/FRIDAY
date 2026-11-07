import ctypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from scenes_support import make_scenes, put_scene
from plugins.scenes.actions import safe_path
from plugins.scenes.desktop import Desktop, Windows
from plugins.scenes.registry import Action, Skipped


@pytest.fixture
def host(tmp_path):
    value = make_scenes(tmp_path)
    yield value
    value.engine.close(); value.api.stop(); value.manager.bus.close()


@pytest.mark.parametrize('action', [
    {'type': 'shell', 'text': 'anything'}, {'type': 'shutdown'}, {'type': 'restart'},
    {'type': 'sleep'}, {'type': 'hibernate'}, {'type': 'sign_out'}, {'type': 'delete_file'},
    {'type': 'unrecognised_action'}, {'type': 'close_app', 'name': '*'},
    {'type': 'open_app', 'name': 'cmd /c shutdown /s'}, {'type': 'open_url', 'url': 'javascript:alert(1)'},
    {'type': 'open_url', 'url': 'file:///C:/Windows/System32/cmd.exe'},
    {'type': 'run_command', 'text': 'shutdown the laptop'},
    {'type': 'run_command', 'text': 'open calculator and delete file C:/secret.txt'},
    {'type': 'run_command', 'text': 'powershell -Command hi'},
    {'type': 'run_command', 'text': 'routines launch'},
])
def test_unknown_and_forbidden_scenes_are_refused_before_any_actions(host, action):
    put_scene(host, actions=[dict(type='set_volume', percent=30), action])
    reply = host.engine.request('test')
    assert not reply['ok'] and not host.desktop.calls and host.engine.active is None
    assert any(word in reply['text'].lower() for word in ['forbidden', 'unknown', 'unsupported', 'cannot', 'use'])


def test_path_validation_checks_resolved_target_and_rejects_executables(tmp_path, monkeypatch):
    target = tmp_path / 'danger.cmd'; target.write_text('synthetic test text')
    apparent = tmp_path / 'innocent.txt'; apparent.write_text('synthetic test text')
    resolve = Path.resolve
    monkeypatch.setattr(Path, 'resolve', lambda p, *a, **kw: target if p == apparent else resolve(p, *a, **kw))
    with pytest.raises(ValueError, match='scripts, executables'):
        safe_path(str(apparent))
    with pytest.raises(ValueError):
        safe_path(str(target))


def test_run_command_uses_validated_providers_not_general_intent(host, monkeypatch):
    from services.automation import intent
    monkeypatch.setattr(intent, 'try_system_action', lambda *a: pytest.fail('General/AI routing was called'))
    put_scene(host, actions=[dict(type='run_command', text='volume 20 and mute')])
    assert host.engine.request('test')['ok']
    assert host.desktop.audio['scalar'] == .2 and host.desktop.audio['mute']
    host.engine.end()
    assert host.desktop.audio == dict(device='fake-speakers', scalar=.734, mute=True)


def test_close_hidden_in_run_command_still_requires_confirmation(host):
    put_scene(host, actions=[dict(type='run_command', text='close chrome')])
    host.engine.request('test')
    assert host.engine.awaiting() and not host.desktop.calls
    host.engine.answer('yes')
    assert host.desktop.calls == ['close:chrome']


def test_close_sends_only_wm_close_and_reports_refused_window(host, monkeypatch):
    messages = []
    user = SimpleNamespace()
    for name in ['PostMessageW', 'IsWindow', 'GetWindowThreadProcessId', 'GetWindowPlacement', 'SetWindowPlacement']:
        setattr(user, name, lambda *args: 1)
    user.PostMessageW = lambda *args: messages.append(args) or 1
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: user)
    native = Windows()
    assert native.post_close(123)
    assert messages == [(123, 0x0010, 0, 0)]
    fake = SimpleNamespace(identity=lambda h: {'pid': 1}, alive=lambda h, i: True,
                           post_close=lambda h: native.post_close(h))
    desktop = Desktop(host.api, windows=fake)
    monkeypatch.setattr(desktop, 'app_windows', lambda name: [123])
    host.api.stop_event.set()  # Avoid a real wait; fake window deliberately refuses.
    with pytest.raises(Skipped, match='still open'):
        desktop.close_app('chrome')
    assert all(message[1] == 0x0010 for message in messages)


def test_unidentified_windows_are_neither_silently_closed_nor_minimized(host, monkeypatch):
    fake = SimpleNamespace(identity=lambda h: None, alive=lambda h, i: False)
    desktop = Desktop(host.api, windows=fake)
    monkeypatch.setattr(desktop, 'app_windows', lambda name: [123])
    with pytest.raises(Skipped, match='still open'):
        desktop.close_app('unknown')
    with pytest.raises(Skipped, match='safely identified'):
        desktop.window_snapshot('unknown')


def test_extension_registry_unloads_by_identity_and_old_generation_cannot_remove_new(host):
    first = Action(lambda p: None, lambda t: None, lambda p: 'Test', lambda p: None)
    host.registry.register('custom', first)
    with pytest.raises(ValueError):
        host.registry.register('custom', first)
    host.registry.unregister('custom', first)
    second = Action(lambda p: None, lambda t: None, lambda p: 'Test', lambda p: None)
    host.registry.register('custom', second)
    host.registry.unregister('custom', first)
    assert host.registry.get('custom') is second
    with pytest.raises(ValueError, match='Forbidden'):
        host.registry.register('run_shell', second)


def test_corrupt_journal_is_preserved_and_oversized_preview_is_refused(host, tmp_path):
    put_scene(host, actions=[dict(type='say', text='x' * 2000), dict(type='say', text='y' * 2000)])
    assert 'preview' in host.engine.request('test')['text'].lower()
    host.engine.path.write_text('{broken')
    from plugins.scenes.engine import Scenes
    with pytest.raises(ValueError):
        Scenes(host.api, host.registry, host.desktop, Path(__file__).resolve().parents[1] / 'plugins/scenes/defaults')
    assert host.engine.path.read_text() == '{broken'


def test_saved_focus_token_cannot_stop_a_different_owner(host):
    calls = []
    host.manager.services['focus'] = SimpleNamespace(stop=lambda **kw: calls.append(kw))
    with host.registry.owned('scenes:' + 'a' * 32):
        with pytest.raises(ValueError, match='owner'):
            host.registry.get('start_focus').undo({'owner': 'user'})
    assert not calls


def test_close_matcher_cannot_include_a_different_app_in_same_install_folder(host, monkeypatch, tmp_path):
    from services.automation import app_finder
    from services.automation.system_control import system, APP_REGISTRY
    monkeypatch.setitem(APP_REGISTRY, 'test suite', str(tmp_path / 'suite/good.exe'))
    monkeypatch.setattr(system, '_process_matcher', lambda *a: lambda process: True)
    processes = [SimpleNamespace(name=lambda: 'good.exe'), SimpleNamespace(name=lambda: 'other.exe')]
    monkeypatch.setattr(app_finder, 'app_windows', lambda matches: [i for i, process in enumerate(processes) if matches(process)])
    assert Desktop(host.api).app_windows('test suite') == [0]
