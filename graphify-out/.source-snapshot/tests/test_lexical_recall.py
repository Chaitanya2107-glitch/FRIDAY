import asyncio
import json
import time

import pytest

from core.config import config
from providers.base_provider import ProviderResponse


@pytest.mark.parametrize('kind,word,expected', [
    ('synonym', 'sofa', True),
    ('related', 'sofa', False),
    ('unknown', '', False),
    ('synonym', 'couch', False),
    ('synonym', 'cushion', False),
    ('synonym', '', False),
])
def test_lexical_checker_requires_synonym_to_an_unmatched_source_word(monkeypatch, kind, word, expected):
    from tasks.lexical_recall_candidate import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    calls = []
    async def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return ProviderResponse(content=json.dumps({'matches': {'couch': {'word': word,
            'query_meaning': 'padded seat for several people', 'source_meaning': 'padded seat for several people',
            'kind': kind}}}),
                                provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(supports('couch cushion coffee stain',
        {'question': '', 'text': 'The sofa cushion has a coffee stain.'}, deadline=time.monotonic() + 2)) is expected
    assert len(calls) == 1 and calls[0][0][0] == 'ollama' and calls[0][0][3] == 192
    data = json.loads(calls[0][0][1][0].content)
    assert data == {'QUERY_WORDS': ['couch'], 'SOURCE_WORDS': ['sofa']}
    assert calls[0][1]['purpose'] == 'cognitive_review'


def test_meanings_are_required_before_classifying_a_pair(monkeypatch):
    from tasks.lexical_recall_candidate import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def complete(*args, **kwargs):
        return ProviderResponse(content=json.dumps({'matches': {'couch': {'word': 'sofa', 'kind': 'synonym'}}}),
                                provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert not asyncio.run(supports('couch', {'question': '', 'text': 'The sofa.'},
                                    deadline=time.monotonic() + 2))


def test_model_sees_original_words_instead_of_lossy_stems(monkeypatch):
    from tasks.lexical_recall_candidate import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def complete(*args, **kwargs):
        data = json.loads(args[1][0].content)
        assert data['QUERY_WORDS'] == ['pants']
        return ProviderResponse(content=json.dumps({'matches': {'pants': {'word': 'trousers',
            'query_meaning': 'garment covering both legs', 'source_meaning': 'garment covering both legs',
            'kind': 'synonym'}}}), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(supports('wool pants replacement button',
        {'question': '', 'text': 'The wool trousers need a replacement button.'}, deadline=time.monotonic() + 2))


@pytest.mark.parametrize('matches', [
    {},
    {'container': {'word': 'case', 'kind': 'synonym'}},
    {'container': {'word': 'case', 'kind': 'synonym'}, 'grip': {'word': 'handle', 'kind': 'related'}},
    {'container': {'word': 'case', 'kind': 'synonym'}, 'grip': {'word': 'invented', 'kind': 'synonym'}},
    {'container': {'word': 'case', 'kind': 'synonym'}, 'grip': {'word': 'handle', 'kind': 'synonym'},
     'extra': {'word': 'case', 'kind': 'synonym'}},
])
def test_lexical_checker_cannot_omit_or_invent_concepts(monkeypatch, matches):
    from tasks.lexical_recall_candidate import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def complete(*args, **kwargs):
        complete_matches = {term: {'query_meaning': 'container part', 'source_meaning': 'container part', **match}
                            for term, match in matches.items()}
        return ProviderResponse(content=json.dumps({'matches': complete_matches}), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert not asyncio.run(supports('container grip', {'question': '', 'text': 'The case needs a handle.'},
                                    deadline=time.monotonic() + 2))
