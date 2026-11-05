"""Desktop lifecycle regression checks; no real windows or processes are launched."""
from pathlib import Path
from types import SimpleNamespace
import threading

from interfaces.taskbar import island


def test_duplicate_launcher_attaches_to_real_island(monkeypatch, tmp_path):
    executable = tmp_path / 'friday-island.exe'
    instance = object.__new__(island.IslandDesktop)
    instance._attached_pid = None
    instance.created = None
    instance.executable = executable
    instance.process = SimpleNamespace(poll=lambda: 0)
    process = SimpleNamespace(pid=42, info={'exe': str(executable), 'create_time': 100})
    monkeypatch.setattr(island.psutil, 'process_iter', lambda fields: [process])
    assert instance._alive()
    assert instance._attached_pid == 42 and instance.created == 100


def test_attached_identity_rejects_pid_reuse(monkeypatch, tmp_path):
    instance = object.__new__(island.IslandDesktop)
    instance._attached_pid, instance.created = 42, 100
    instance.executable = tmp_path / 'friday-island.exe'
    monkeypatch.setattr(island.psutil, 'Process', lambda pid: SimpleNamespace(
        exe=lambda: str(instance.executable), create_time=lambda: 101))
    assert not instance._alive()


def test_offline_summon_requests_start_once_through_existing_owner(monkeypatch):
    instance = object.__new__(island.IslandDesktop)
    starts, summons = [], []
    instance.enabled = True
    instance._start_requested = threading.Event()
    instance.runtime = SimpleNamespace(busy=False)
    def lifecycle(action):
        starts.append(action); instance.runtime.busy = True
    instance.panel = SimpleNamespace(_lifecycle=lifecycle)
    instance._launch = lambda background: summons.append(background)
    monkeypatch.setattr(island.backend, 'is_online', lambda: False)
    instance.summon(); instance.summon()
    instance._ensure_started(); instance._ensure_started()
    assert starts == ['start'] and summons == [False, False]


def test_start_requested_during_stop_is_retained_until_lifecycle_is_free(monkeypatch):
    instance = object.__new__(island.IslandDesktop)
    instance.enabled = True
    instance._start_requested = threading.Event()
    instance.runtime = SimpleNamespace(busy=True)
    starts = []
    instance.panel = SimpleNamespace(_lifecycle=lambda action: starts.append(action))
    instance._launch = lambda background: None
    monkeypatch.setattr(island.backend, 'is_online', lambda: False)
    instance.summon()
    instance._ensure_started()
    assert starts == [] and instance._start_requested.is_set()
    instance.runtime.busy = False
    instance._ensure_started(); instance._ensure_started()
    assert starts == ['start'] and not instance._start_requested.is_set()


def test_voice_controls_use_existing_state_machines(monkeypatch):
    instance = object.__new__(island.IslandDesktop)
    calls = []
    noop = lambda *args: None
    instance.tray = SimpleNamespace(toggle_listening=lambda: calls.append('listen'), toggle_wake=lambda: calls.append('wake'),
        toggle_conversation=lambda: calls.append('conversation'), toggle_speak_replies=noop, toggle_speak_typed=noop,
        toggle_body=noop, open_customization=noop, open_college_schedules=noop, open_productivity=noop,
        typed_reply_done=noop, bar_submitted=noop)
    instance.panel = SimpleNamespace(request_show=noop, _lifecycle=noop)
    instance.bar = SimpleNamespace(request_quit=noop)
    for action in ['listen', 'wake', 'conversation']:
        instance.dispatch({'action': action})
    assert calls == ['listen', 'wake', 'conversation']
    assert instance.dispatch({'action': 'conversation', 'expires': 0}) is False
    assert calls == ['listen', 'wake', 'conversation']


def test_short_voice_replies_reach_capsule_but_private_replies_stay_private():
    instance = object.__new__(island.IslandDesktop)
    calls, published = [], []
    instance._post = lambda path, data: published.append((path, data)) or {'accepted': True}
    instance._notify = lambda text, transient, private: calls.append((transient, private))
    instance.notify('Opened', transient=True)
    instance.notify('Private reply', private=True)
    assert calls == [(False, True)]
    assert published == [('event', {'kind': 'response', 'text': 'Opened', 'transient': True})]
    instance._post = lambda *args: {'accepted': False}
    instance.notify('Opened offline', transient=True)
    assert calls[-1] == (True, False)
