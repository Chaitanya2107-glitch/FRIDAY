import asyncio
import json
import time

import pytest

from core.config import config
from providers.base_provider import ProviderResponse


@pytest.mark.parametrize('equivalents,expected', [
    ({'container': 'case', 'grip': 'handle'}, True),
    ({'container': 'case', 'grip': None}, False),
    ({'container': 'case'}, False),
    ({'container': 'case', 'grip': 'invented'}, False),
    ({'container': 'case', 'grip': 'handle', 'other': 'case'}, False),
    ({'container': 'case', 'grip': ' '}, False),
])
def test_compact_equivalents_require_complete_grounded_coverage(monkeypatch, equivalents, expected):
    from tasks.compact_recall_candidate import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    calls = []
    async def complete(*args, **kwargs):
        calls.append(kwargs)
        return ProviderResponse(content=json.dumps({'equivalents': equivalents, 'relation': 'compatible'}),
                                provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(supports('container grip', {'question': '', 'text': 'The case needs a handle.'},
                                deadline=time.monotonic() + 2)) is expected
    assert len(calls) == 1
    schema = calls[0]['response_schema']['properties']['equivalents']
    assert set(schema['required']) == {'container', 'grip'}
    assert schema['additionalProperties'] is False


@pytest.mark.parametrize('provider,metadata,relation', [
    ('openai', {}, 'compatible'),
    ('ollama', {'incomplete': True}, 'compatible'),
    ('ollama', {}, 'different'),
    ('ollama', {}, 'uncertain'),
])
def test_grounded_equivalent_does_not_override_response_gates(monkeypatch, provider, metadata, relation):
    from tasks.compact_recall_candidate import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def complete(*args, **kwargs):
        assert args[2] and args[3] == 192
        assert 0 < kwargs['attempt_timeout'] <= 2
        return ProviderResponse(content=json.dumps({'equivalents': {'grip': 'handle'}, 'relation': relation}),
                                provider=provider, model='synthetic', metadata=metadata)
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert not asyncio.run(supports('grip', {'question': '', 'text': 'The handle.'},
                                    deadline=time.monotonic() + 2))
