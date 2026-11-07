import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from activity_support import make_activity, advance
from services import activity_plugin, plugin_runtime
from services.friday_island_server.http import create_router

_installation_marker = activity_plugin.installed


def test_privacy_guard_starts_before_manifest_activation(tmp_path, monkeypatch):
    monkeypatch.setattr(activity_plugin, '__file__', str(tmp_path / 'services/activity_plugin.py'))
    assert not _installation_marker()
    folder = tmp_path / 'plugins/activity'
    folder.mkdir(parents=True)
    (folder / 'main.py').write_text('# staged plugin', encoding='utf-8')
    assert _installation_marker()
    assert not (folder / 'plugin.json').exists()


@pytest.fixture
def activity(tmp_path, monkeypatch):
    value = make_activity(tmp_path)
    monkeypatch.setattr(plugin_runtime, '_manager', value.manager)
    value.provider.choose('chrome.exe', 'SECRET DOCUMENT - YouTube')
    value.tracker.poll()
    advance(value, 4)
    yield value
    value.api.stop(); value.tracker.close(); value.manager.bus.close()


@pytest.mark.parametrize('surface', ['chat', 'voice', 'intent'])
def test_activity_queries_never_reach_context_models_or_history(activity, monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    from services.automation import intent
    from services.screen_watch import commands as screen_commands
    def forbidden(*args, **kwargs):
        pytest.fail('Activity request escaped its private local path')
    for module in [chat, voice]:
        for name in ['build_file_context', 'build_search_context', 'complete_with_failover']:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(screen_commands, 'handle', forbidden)
    monkeypatch.setattr(chat._memory, 'save_message', forbidden, raising=False)
    monkeypatch.setattr(voice._memory, 'save_message', forbidden, raising=False)
    spoken = []
    monkeypatch.setattr(voice, '_speak_in_background', lambda *args, **kwargs: spoken.append(kwargs))
    monkeypatch.setattr(chat, '_speak_in_background', lambda *args, **kwargs: spoken.append(kwargs))
    async def run():
        if surface == 'chat':
            result = await chat.chat(chat.ChatRequest(message='what am I doing', speak=True))
            assert result.private and result.model == 'activity' and 'YouTube' in result.response
        elif surface == 'voice':
            result = await voice._reply('what am I doing', voice.VoiceRequest(speak=True))
            assert result.private and result.model == 'activity' and 'YouTube' in result.response
        else:
            result = await intent.try_system_action('what did I do today', 'openrouter')
            assert 'YouTube' in result.message and result.memory_message == activity_plugin.PRIVATE_MEMORY
    asyncio.run(run())
    assert all(kwargs.get('local_only') is True for kwargs in spoken)


def test_remote_queries_are_refused_without_exposing_activity(activity):
    result = asyncio.run(activity_plugin.try_command('what am I doing', remote=True))
    assert not result.success and 'YouTube' not in result.message and result.speech == ''


@pytest.mark.parametrize('surface', ['chat', 'voice', 'intent', 'remote'])
def test_activity_debug_events_stay_private_too(activity, monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    from services.automation import intent
    import json
    activity.manager.management_command = lambda text: dict(ok=True, error=None,
        text=json.dumps(activity.manager.bus.recent()))
    def forbidden(*args, **kwargs):
        pytest.fail('Activity debug events escaped the local private path')
    for module in [chat, voice]:
        monkeypatch.setattr(module, 'build_file_context', forbidden)
        monkeypatch.setattr(module, 'build_search_context', forbidden)
        monkeypatch.setattr(module._memory, 'save_message', forbidden, raising=False)
        monkeypatch.setattr(module, '_speak_in_background', forbidden)
    async def run():
        if surface == 'chat':
            reply = await chat.chat(chat.ChatRequest(message='show recent events', speak=True))
            assert reply.private and 'YouTube' in reply.response
        elif surface == 'voice':
            reply = await voice._reply('show recent events', voice.VoiceRequest(speak=True))
            assert reply.private and 'YouTube' in reply.response
        else:
            reply = await activity_plugin.try_command('show recent events', remote=surface == 'remote')
            assert reply.memory_message == activity_plugin.PRIVATE_MEMORY
            assert ('YouTube' in reply.message) is (surface == 'intent')
    asyncio.run(run())


def test_failed_or_disabled_plugin_never_reactivates_legacy_or_model_fallback(activity, monkeypatch):
    from services.activity import log
    activity.manager.services.pop('activity')
    monkeypatch.setattr(activity_plugin, 'installed', lambda: True)
    assert activity_plugin.privacy_active()
    assert log.foreground_window() == (None, None)
    value = asyncio.run(activity_plugin.try_command('what am I doing'))
    assert not value.success and 'unavailable' in value.message


def test_internal_intent_routes_activity_privately_too(activity):
    from services.automation import intent
    value = asyncio.run(intent._try_system_action('what am I doing', 'openrouter'))
    assert 'YouTube' in value.message and value.memory_message == activity_plugin.PRIVATE_MEMORY


@pytest.mark.parametrize('surface', ['chat', 'voice'])
def test_composed_commands_keep_nested_activity_results_private(activity, monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    async def no_context(*args, **kwargs):
        return None
    async def composed(*args, **kwargs):
        return await activity_plugin.try_command('what am I doing')
    spoken = []
    for module in [chat, voice]:
        monkeypatch.setattr(module, 'build_file_context', no_context)
        monkeypatch.setattr(module, 'build_search_context', no_context)
        monkeypatch.setattr(module, 'try_system_action', composed)
        monkeypatch.setattr(module, '_speak_in_background', lambda *args, **kwargs: spoken.append(kwargs))
        monkeypatch.setattr(module._memory, 'get_recent_history', lambda: [])
        monkeypatch.setattr(module._memory, 'save_message', lambda *args, **kwargs: pytest.fail('Private composed reply was saved'), raising=False)
    async def run():
        if surface == 'chat':
            return await chat.chat(chat.ChatRequest(message='run activity routine', speak=True))
        return await voice._reply('run activity routine', voice.VoiceRequest(speak=True))
    result = asyncio.run(run())
    assert result.private and result.model == 'activity'
    assert spoken and all(value.get('local_only') for value in spoken)


def test_summary_route_reuses_existing_auth_and_returns_no_titles(activity):
    token = 'a' * 64
    app = FastAPI()
    activity.api.add_route('GET', 'summary', lambda request: activity.tracker.summary(request.get('query', {}).get('range', 'today')))
    def route(plugin_id, path, request):
        return activity.api.routes[path](request) if plugin_id == 'activity' and path in activity.api.routes else None
    activity.manager.route = route
    app.include_router(create_router(lambda: activity.manager,
        lambda: SimpleNamespace(connection=SimpleNamespace(token=token))))
    client = TestClient(app, base_url='http://127.0.0.1')
    try:
        assert client.get('/api/plugins/activity/summary?range=today').status_code == 401
        response = client.get('/api/plugins/activity/summary?range=today', headers={'X-Friday-Token': token})
        assert response.status_code == 200
        assert response.json()['active_seconds'] == 4
        assert 'SECRET' not in response.text
    finally:
        client.close()


def test_legacy_foreground_helper_never_reads_windows_when_plugin_active(activity, monkeypatch):
    from services.activity import log
    import ctypes
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=object()))
    assert log.foreground_window() == (None, None)


def test_legacy_background_title_and_history_sampler_is_suspended(activity, monkeypatch):
    from services.activity import log
    from services.mind import brain
    def forbidden(*args, **kwargs):
        pytest.fail('Legacy title/browser-history sampler ran while private activity was active')
    monkeypatch.setattr(log.activity_log, 'sample', forbidden)
    monkeypatch.setattr(brain, 'sense', forbidden)
    async def stop(*args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(log.asyncio, 'sleep', stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(log.watch_activity(log.activity_log))
    assert log.activity_log.title is log.activity_log.app is None
