import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from providers.base_provider import ProviderResponse
from services.mind.cognition import cognition


def test_meaningful_events_wake_local_executive_without_a_question_timer(monkeypatch):
    from services.mind import cognitive_runtime
    from services.mind.executive import executive
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    calls = []
    async def review(*args, **kwargs):
        calls.append(kwargs)
        return {'status': 'completed'}
    monkeypatch.setattr(executive, 'review', review)
    monkeypatch.setattr(cognitive_runtime, 'available', lambda: True)
    async def run():
        task = asyncio.create_task(cognitive_runtime.run())
        await asyncio.sleep(.01)
        cognition.record('action', 'system', 'set_volume', public=True)
        await asyncio.sleep(.03)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    assert calls and len(calls) <= 2


def test_typing_or_active_request_defers_background_deliberation(monkeypatch):
    from services.mind import cognitive_runtime
    monkeypatch.setattr('services.activity.log.idle_seconds', lambda: 1)
    assert not cognitive_runtime.available()


def test_conversation_enters_shared_owner_memory_with_original_input(monkeypatch):
    from interfaces.api.routes import chat
    from services.mind.brain_memory import brain_memory
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_LANGUAGE_ENABLED', True)
    monkeypatch.setattr(chat, '_memory', SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    async def complete(*args, **kwargs):
        return ProviderResponse(content='{"command":""}' if kwargs.get('purpose') == 'understanding' else 'Understood.',
                                provider='ollama', model='local-model')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    response = client.post('/api/v1/chat', json={'message': 'My presentation is tomorrow and I feel unprepared'})
    assert response.status_code == 200
    assert any('presentation' in row['text'] for row in brain_memory.evidence().values())


def test_direct_command_has_a_pre_action_brain_event_without_private_payload(monkeypatch):
    from services.automation import intent
    seen = []
    def mute(value):
        seen.extend(cognition.recent(10))
        return 'Muted.'
    monkeypatch.setattr(intent.system, 'set_mute', mute)
    assert asyncio.run(intent.try_system_action('mute', 'openrouter')).success
    assert any(event['kind'] == 'action_intent' for event in seen)


def test_feature_writes_share_operation_lifecycle_without_capturing_body():
    app = create_app()
    @app.post('/api/v1/test-feature')
    def feature():
        return {'ok': True}
    client = TestClient(app, base_url='http://127.0.0.1:8000')
    result = client.post('/api/v1/test-feature', json={'private': 'private-feature-text'})
    assert result.status_code == 200
    events = [row for row in cognition.recent(20) if row['kind'] == 'feature_request']
    assert events and events[-1]['status'] == 'completed'
    assert 'private-feature-text' not in str(events)


def test_command_cannot_be_learned_as_answer_to_an_unrelated_question(monkeypatch):
    from services.automation import intent
    from services.mind import talk
    from services.mind.brain_memory import brain_memory
    talk._record({'say': 'What food do you prefer?'}, 'asked', time.time())
    async def mode(*args, **kwargs):
        return intent.ActionResult(True, 'Gaming mode on.', repeatable=False)
    monkeypatch.setattr(intent, '_start_mode', mode)
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    assert client.post('/api/v1/chat', json={'message': 'start gaming mode'}).status_code == 200
    assert talk.load().get('pending', {}).get('question') == 'What food do you prefer?'
    assert not any(row.get('question') for row in brain_memory.evidence().values())


def test_disabled_computer_request_keeps_its_input_ephemeral(monkeypatch):
    from services.mind.brain_memory import brain_memory
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    client = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    assert client.post('/api/v1/chat', json={'message': '\\c private ephemeral task'}).status_code == 200
    assert not any('private ephemeral task' in row['text'] for row in brain_memory.evidence().values())
