import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from services import customization
from services.screen_watch import capture, companion, service
from services.screen_watch.app_rules import app_name, rules
from test_passive_assistant import aware
from test_screen_watch_service import screen, observe


def save(name, allowed, original=None, revision=None):
    return customization.change('screen_apps', name=name, original=original, value={'allowed': allowed},
                                revision=revision or customization.snapshot('screen_apps')['revision'])


def test_rules_persist_and_canonical_names_prevent_duplicate_permissions():
    assert rules.allowed('chrome') and not rules.path.exists()
    first = save('Chrome.EXE', False)
    assert first['items'][0]['name'] == 'chrome' and 'Blocked' in first['items'][0]['label']
    assert not rules.allowed('CHROME.exe') and capture.blocked({'app': 'chrome', 'title': 'Notes'})
    with pytest.raises(customization.Conflict):
        save('chrome', True)
    save('chrome.exe', True, original='chrome')
    assert rules.allowed('chrome') and not capture.blocked({'app': 'chrome', 'title': 'Notes'})
    save('Windows Terminal', False)
    assert not rules.allowed('windowsterminal')
    assert json.loads(rules.path.read_text())['chrome'] == {'allowed': True}
    save('notepad++.exe', False)
    assert not rules.allowed('notepad++')


def test_allow_never_overrides_existing_privacy_and_own_window_guards():
    save('powershell', True)
    assert capture.blocked({'app': 'powershell', 'title': 'API credentials'})
    save('bitwarden', True)
    assert capture.blocked({'app': 'bitwarden', 'title': 'Vault'})
    save('pythonw', True)
    assert capture.blocked({'app': 'pythonw', 'title': 'tk', 'friday_owned': True})


@pytest.mark.parametrize('name', ['../chrome', r'C:\chrome.exe', '*', 'chrome\n.exe', '', 'a/b', 'chrome.exe.exe'])
def test_paths_wildcards_and_control_characters_are_not_process_names(name):
    with pytest.raises(ValueError):
        app_name(name)


def test_repeated_executable_suffix_cannot_poison_the_saved_catalog():
    save('chrome', False)
    before = rules.path.read_bytes()
    with pytest.raises(ValueError):
        save('chrome.exe.exe.exe', True)
    assert rules.path.read_bytes() == before
    assert customization.snapshot('screen_apps')['items'][0]['name'] == 'chrome'


def test_invalid_or_conflicting_edits_preserve_policy_and_do_not_change_epoch():
    stale = customization.snapshot('screen_apps')['revision']
    save('chrome', False)
    before, epoch = rules.path.read_bytes(), service.watch.store.settings()['epoch']
    with pytest.raises(customization.Conflict):
        save('chrome', True, original='chrome', revision=stale)
    with pytest.raises(ValueError):
        save('../chrome', True)
    assert rules.path.read_bytes() == before and service.watch.store.settings()['epoch'] == epoch


def test_corrupt_policy_blocks_capture_and_is_preserved():
    rules.path.parent.mkdir(parents=True, exist_ok=True)
    rules.path.write_text('{not json')
    assert not rules.allowed('chrome')
    assert capture.blocked({'app': 'chrome', 'title': 'Notes'})
    with pytest.raises(customization.StoreUnavailable):
        customization.snapshot('screen_apps')
    assert rules.path.read_text() == '{not json'


def test_save_delete_preserve_pause_and_clear_private_conversation(aware):
    watch, _ = aware
    watch.control('pause')
    watch.dialogue[:] = [{'role': 'assistant', 'content': 'old private context'}]
    before = watch.store.settings()
    saved = save('reader', False)
    after = watch.store.settings()
    assert after['enabled'] == before['enabled'] and after['paused'] == before['paused']
    assert after['epoch'] > before['epoch'] and not watch.dialogue
    customization.change('screen_apps', original='reader', name='reader', value=None, revision=saved['revision'])
    assert rules.allowed('reader')


def test_blocked_app_history_is_removed_from_automatic_context(aware):
    watch, _ = aware
    assert watch.local_context()['recent_observations']
    save('reader', False)
    assert watch.local_context() is None
    assert watch.store.history()  # Blocking does not silently delete stored history.


def test_blocking_during_capture_discards_late_learning(screen, monkeypatch):
    original = service.inference.analyze
    async def later(*args, **kwargs):
        result = await original(*args, **kwargs)
        save('notepad', False)
        return result
    monkeypatch.setattr(service.inference, 'analyze', later)
    observe(screen)
    assert not screen.watch.store.history()


def test_blocking_during_conversation_discards_late_reply(aware, monkeypatch):
    watch, _ = aware
    async def later(*args, **kwargs):
        save('reader', False)
        return {'message': {'content': 'PRIVATE_LATE_RESULT'}}
    monkeypatch.setattr(companion.inference, 'local_chat', later)
    result = asyncio.run(companion.answer('Hello Friday.'))
    assert 'PRIVATE_LATE' not in result.content and not watch.dialogue


def test_local_api_edits_permissions_and_remote_clients_cannot():
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    url = '/api/v1/customization/screen_apps'
    current = client.get(url)
    assert current.status_code == 200 and current.headers['cache-control'] == 'no-store'
    result = client.put(url, json={'name': 'cmd.exe', 'value': {'allowed': False}, 'revision': current.json()['revision']})
    assert result.status_code == 200 and not rules.allowed('cmd')
    remote = TestClient(create_app(), base_url='http://127.0.0.1:8000', client=('192.0.2.1', 5000))
    assert remote.get(url).status_code == 403
    assert client.put(url, headers={'Origin': 'https://other.example'}, json={}).status_code == 403
