import asyncio
import json
import time

import pytest

from core.config import config
from providers.base_provider import ProviderResponse


@pytest.mark.parametrize('query,report,word,equivalent', [
    ('wool pants replacement button', 'The wool trousers need a replacement button.', 'pants', 'trousers'),
    ('spectacles loose hinge', 'The reading glasses have a loose hinge.', 'spectacles', 'reading glasses'),
    ('running trainers worn soles', 'The running sneakers have worn soles.', 'trainers', 'sneakers'),
])
def test_semantic_review_receives_query_words_without_lossy_stemming(monkeypatch, query, report, word, equivalent):
    from services.mind.recall_review import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    calls = []
    async def complete(*args, **kwargs):
        data = json.loads(args[1][0].content)
        calls.append(data)
        assert data['MISSING_QUERY_TERMS'] == [word]
        assert kwargs['response_schema']['$defs']['ConceptCheck']['properties']['query_term']['enum'] == [word]
        return ProviderResponse(content=json.dumps({'checks': [{'query_term': word, 'source_span': equivalent,
            'same_meaning': True}], 'relation': 'compatible'}), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(supports(query, {'text': report, 'question': ''}, deadline=time.monotonic() + 2))
    assert len(calls) == 1


def test_old_stem_cannot_stand_in_for_the_requested_word(monkeypatch):
    from services.mind.recall_review import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def complete(*args, **kwargs):
        return ProviderResponse(content=json.dumps({'checks': [{'query_term': 'pant', 'source_span': 'trousers',
            'same_meaning': True}], 'relation': 'compatible'}), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert not asyncio.run(supports('pants', {'text': 'The trousers.', 'question': ''},
                                    deadline=time.monotonic() + 2))
