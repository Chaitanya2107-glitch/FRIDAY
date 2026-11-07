import asyncio

import pytest

from scenes_support import make_scenes, put_scene
from services import plugin_runtime, scene_runtime


@pytest.fixture
def host(tmp_path, monkeypatch):
    value = make_scenes(tmp_path)
    monkeypatch.setattr(plugin_runtime, '_manager', value.manager)
    put_scene(value, name='test', actions=[dict(type='set_volume', percent=20)], confirm_first_run=True)
    yield value
    value.engine.close(); value.api.stop(); value.manager.bus.close()


@pytest.mark.parametrize('surface', ['chat', 'voice', 'intent'])
def test_scenes_route_locally_before_legacy_modes_models_files_and_web(host, monkeypatch, surface):
    from interfaces.api.routes import chat, voice
    from services.automation import intent, modes
    def forbidden(*a, **kw): pytest.fail('Scene request escaped its finite local path')
    monkeypatch.setattr(modes, 'start', forbidden, raising=False)
    for module in [chat, voice]:
        monkeypatch.setattr(module, 'build_file_context', forbidden)
        monkeypatch.setattr(module, 'build_search_context', forbidden)
        monkeypatch.setattr(module, 'complete_with_failover', forbidden)
        monkeypatch.setattr(module._memory, 'save_message', forbidden, raising=False)
    spoken = []
    monkeypatch.setattr(chat, '_speak_in_background', lambda *a, **kw: spoken.append(kw))
    monkeypatch.setattr(voice, '_speak_in_background', lambda *a, **kw: spoken.append(kw))
    async def run():
        if surface == 'chat':
            reply = await chat.chat(chat.ChatRequest(message='test mode', speak=True))
            assert reply.private and reply.model == 'focus_scenes' and reply.awaiting_reply
        elif surface == 'voice':
            reply = await voice._reply('test mode', voice.VoiceRequest(speak=True))
            assert reply.private and reply.model == 'focus_scenes' and reply.awaiting_reply
        else:
            reply = await intent.try_system_action('test mode', 'openrouter')
            assert reply.memory_message == scene_runtime.PRIVATE_MEMORY
        assert host.engine.awaiting() and host.desktop.calls == []
        answer = await scene_runtime.try_command('yes')
        assert answer.success and host.desktop.audio['scalar'] == .2
    asyncio.run(run())
    assert all(row.get('local_only') for row in spoken)


def test_confirmation_clears_old_destructive_pending_and_unrelated_turn_expires_scene_question(host):
    from services.automation import intent
    intent._pending[False] = intent.PendingAction({'action': 'shutdown'}, 10**12)
    asyncio.run(scene_runtime.try_command('test mode'))
    assert False not in intent._pending and intent.is_awaiting_confirmation()
    old = host.engine.pending['nonce']
    assert asyncio.run(scene_runtime.try_command('what time is it')) is None
    assert not host.engine.awaiting()
    assert not host.engine.answer('yes', old)['ok'] and not host.desktop.calls


def test_remote_controls_refuse_and_failed_installed_plugin_cannot_fall_into_legacy(host, monkeypatch):
    reply = asyncio.run(scene_runtime.try_command('test mode', remote=True))
    assert not reply.success and not host.desktop.calls and not host.engine.pending
    host.manager.services.clear()
    monkeypatch.setattr(scene_runtime, 'installed', lambda name: True)
    assert scene_runtime.owns('study mode')
    reply = asyncio.run(scene_runtime.try_command('study mode'))
    assert not reply.success and 'unavailable' in reply.message


def test_remote_unrelated_turn_cannot_cancel_local_confirmation(host):
    host.engine.request('test')
    nonce = host.engine.pending['nonce']
    assert asyncio.run(scene_runtime.try_command('hello', remote=True)) is None
    assert host.engine.pending['nonce'] == nonce
    assert not asyncio.run(scene_runtime.try_command('yes', remote=True)).success
    assert host.engine.pending['nonce'] == nonce and not host.desktop.calls


def test_owned_scene_phrases_override_legacy_only_when_known_and_debug_is_private(host):
    assert plugin_runtime.builtin_matches('test mode') is False
    assert not scene_runtime.owns('some old mode')
    host.manager.management_command = lambda text: dict(ok=True, text='Synthetic event labels', error=None)
    reply = asyncio.run(scene_runtime.try_command('show recent events'))
    assert reply.memory_message == scene_runtime.PRIVATE_MEMORY and reply.speech == ''


def test_invalid_scene_name_in_differently_named_file_is_still_owned_and_refused(host):
    from services import settings_store
    settings_store.save(host.engine.catalog.folder / 'different.json', dict(name='blocked', aliases=['start blocked now'],
        actions=[dict(type='shutdown')]))
    assert host.engine.matches('blocked mode') and host.engine.matches('start blocked now')
    reply = asyncio.run(scene_runtime.try_command('blocked mode'))
    assert not reply.success and 'Forbidden' in reply.message and not host.desktop.calls
