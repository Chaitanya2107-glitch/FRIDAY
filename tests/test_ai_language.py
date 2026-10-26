import asyncio
from types import SimpleNamespace

import pytest

from core.config import config
from core.errors import ProviderError
from providers import failover
from providers.base_provider import Message, ProviderResponse
from services.automation import intent


@pytest.fixture(autouse=True)
def language_mode(monkeypatch):
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_LANGUAGE_ENABLED', True, raising=False)
    monkeypatch.setattr(config, 'AI_WORDING_ENABLED', False)


def model(monkeypatch, content):
    calls = []
    async def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return ProviderResponse(content=content, provider='openrouter', model='test')
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    return calls


def test_messy_request_reaches_ai_then_local_executor(monkeypatch):
    calls = model(monkeypatch, '{"command":"set volume to 23"}')
    effects = []
    monkeypatch.setattr(intent.system, 'set_volume', lambda n: effects.append(n) or 'Volume 23%.')
    result = asyncio.run(intent.try_system_action('bro the speakers r too loud bring em down to 23', 'openrouter'))
    assert result.success and effects == [23]
    assert len(calls) == 1 and calls[0][1]['purpose'] == 'understanding'
    assert 'tools' not in calls[0][1]


def test_known_command_stays_local(monkeypatch):
    calls = model(monkeypatch, '')
    monkeypatch.setattr(intent.system, 'set_mute', lambda value: 'Muted.')
    assert asyncio.run(intent.try_system_action('mute', 'openrouter')).success
    assert not calls


@pytest.mark.parametrize('content', [
    'bad json', '{"command":"yes"}', '{"command":"do a completely unknown thing"}',
    '{"command":"mute","confirmed":true}', '{"command":["mute"]}',
])
def test_invalid_or_unrecognised_model_output_never_executes(monkeypatch, content):
    calls = model(monkeypatch, content)
    effects = []
    monkeypatch.setattr(intent.system, 'set_mute', lambda value: effects.append(value))
    asyncio.run(intent.try_system_action('could u handle that awkward request', 'openrouter'))
    assert not effects and len(calls) == 1


def test_ai_batch_is_validated_before_any_action(monkeypatch):
    model(monkeypatch, '{"command":"mute then do a completely unknown thing"}')
    effects = []
    monkeypatch.setattr(intent.system, 'set_mute', lambda value: effects.append(value))
    result = asyncio.run(intent.try_system_action('hush the pc and do that other thing', 'openrouter'))
    assert not result.success and not effects


def test_model_command_keeps_remote_restrictions(monkeypatch):
    model(monkeypatch, '{"command":"read clipboard"}')
    token = intent.remote_request.set(True)
    try:
        result = asyncio.run(intent.try_system_action('show me what i last copied pls', 'openrouter'))
    finally:
        intent.remote_request.reset(token)
    assert not result.success and 'Telegram' in result.message


def test_ai_chat_uses_history_without_tools(monkeypatch):
    from services.mind import language
    calls = model(monkeypatch, 'Yes, we can work through that together.')
    result = asyncio.run(language.answer('can we talk about that?', 'openrouter',
        [Message('assistant', 'Your project sounds difficult.')], 200))
    assert result.provider == 'openrouter'
    assert calls[0][1]['purpose'] == 'conversation'
    assert calls[0][0][1][-1].content == 'can we talk about that?'
    assert calls[0][0][1][0].role == 'assistant'
    assert 'tools' not in calls[0][1]


@pytest.mark.parametrize('purpose', ['cognitive_review', 'notification_review'])
def test_background_thinking_never_falls_back_to_cloud(monkeypatch, purpose):
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'NOTIFICATION_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'test')
    calls = []
    def provider(name, **kwargs):
        calls.append(name)
        async def complete(**params):
            raise ProviderError('offline')
        return SimpleNamespace(complete=complete)
    monkeypatch.setattr(failover, 'get_provider', provider)
    with pytest.raises(ProviderError):
        asyncio.run(failover.complete_with_failover('openrouter', [Message('user', 'review')],
            'review', 100, purpose=purpose))
    assert calls == ['ollama']


def test_language_purposes_cannot_request_tools(monkeypatch):
    with pytest.raises(ProviderError):
        asyncio.run(failover.complete_with_failover('openrouter', [], '', 100,
            purpose='understanding', tools=[object()]))


@pytest.mark.parametrize('surface', ['chat', 'voice'])
def test_real_entrypoints_use_ai_for_conversation(monkeypatch, surface):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    calls = []
    async def complete(*args, **kwargs):
        calls.append(kwargs['purpose'])
        content = '{"command":""}' if kwargs['purpose'] == 'understanding' else 'Tell me what has been on your mind.'
        return ProviderResponse(content=content, provider='openrouter', model='language-test')
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    memory = SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *args: None)
    monkeypatch.setattr(chat, '_memory', memory)
    monkeypatch.setattr(voice, '_memory', memory)
    if surface == 'chat':
        client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
        response = client.post('/api/v1/chat', json={'message': 'bro can we just talk for a bit', 'speak': False})
        assert response.status_code == 200
        result = response.json()
    else:
        result = asyncio.run(voice._reply('bro can we just talk for a bit', voice.VoiceRequest(speak=False))).model_dump()
    assert result['model'] == 'language-test'
    assert result['response'] == 'Tell me what has been on your mind.'
    assert calls == ['understanding', 'conversation']


def test_interpreted_file_change_still_requires_owner_confirmation(monkeypatch, tmp_path):
    model(monkeypatch, '{"command":"organise downloads"}')
    monkeypatch.setitem(intent.FOLDER_MAP, 'downloads', str(tmp_path))
    monkeypatch.setattr(intent.system, 'count_files_to_organise', lambda path: 3)
    effects = []
    monkeypatch.setattr(intent.system, 'organise_folder', lambda path: effects.append(path) or 'Organised.')
    result = asyncio.run(intent.try_system_action('sort the stuff in my downloads into neat groups pls', 'openrouter'))
    assert result.success and intent.is_awaiting_confirmation() and not effects
    assert 'yes' in result.message


def test_model_cannot_add_close_target_in_batch(monkeypatch):
    model(monkeypatch, '{"command":"mute then close notepad"}')
    effects = []
    monkeypatch.setattr(intent.system, 'set_mute', lambda value: effects.append('mute') or 'Muted.')
    monkeypatch.setattr(intent.system, 'close_app', lambda name: effects.append(name) or 'Closed.')
    result = asyncio.run(intent.try_system_action('could u quieten things and tidy the screen', 'openrouter'))
    assert not result.success and not effects


def test_language_failure_is_explicit_and_keeps_commands_working(monkeypatch):
    from services.mind import language
    async def down(*args, **kwargs):
        raise ProviderError('unavailable')
    monkeypatch.setattr(failover, 'complete_with_failover', down)
    result = asyncio.run(language.answer('hello', 'openrouter', [], 100))
    assert "can't reach my language AI" in result.content and result.provider == 'local'
    monkeypatch.setattr(intent.system, 'set_mute', lambda value: 'Muted.')
    assert asyncio.run(intent.try_system_action('mute', 'openrouter')).success
