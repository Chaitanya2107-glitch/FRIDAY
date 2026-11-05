"""A plausible group verdict cannot bypass individual source grounding."""
import asyncio
import json
from datetime import datetime

import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from memory_review_support import grounded_response
from services.mind import reasoning
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.consolidation import Consolidation
from services.mind.reasoning_store import ReasoningStore

NOW = datetime(2026, 10, 21, 15)


@pytest.fixture
def grounded(tmp_path, monkeypatch):
    store = Cognition(tmp_path / 'grounding.db')
    episodes = BrainMemory(store)
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    episodes.remember('My bank account transfer may be delayed.', now=NOW)
    episodes.remember('The river bank in my sketch needs darker shading.', now=NOW)
    source = ReasoningStore(store)
    source.evidence = episodes.evidence
    monkeypatch.setattr(reasoning, 'cognition', store)
    monkeypatch.setattr(reasoning, 'reasoning_store', source)
    return store, source


def report():
    return reasoning.CognitiveReport.model_validate({'conclusions': [], 'questions': [],
        'work_kind': 'memories', 'memories': [{'subject': 'Sketch shading',
            'evidence': ['owner_episode:2', 'owner_episode:1']}]})


def checks(*, relatedness_only=True):
    result = {'checks': [{'id': 0, 'supported': True, 'reason': 'Synthetic overall approval.',
        'sources': [
            {'source': 'owner_episode:1', 'quote': 'My bank account transfer may be delayed.', 'supported': True},
            {'source': 'owner_episode:2', 'quote': 'The river bank in my sketch needs darker shading.', 'supported': True}]}]}
    if relatedness_only:
        result['checks'][0]['relation'] = 'same_situation'
        for row in result['checks'][0]['sources']:
            row.update(entity=row['quote'], meaning='Synthetic source-specific meaning.')
    return result


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'invented', 'wrong_quote', 'question_only',
                                'tiny_quote', 'source_rejected', 'legacy_boolean'])
def test_group_approval_cannot_bypass_missing_or_rejected_source(grounded, monkeypatch, bad):
    store, source = grounded
    result = checks()
    rows = result['checks'][0]['sources']
    if bad == 'missing': rows.pop()
    if bad == 'duplicate': rows[1] = dict(rows[0])
    if bad == 'invented': rows[1]['source'] = 'owner_episode:999'
    if bad == 'wrong_quote': rows[0]['quote'] = rows[1]['quote']
    if bad == 'question_only': rows[0]['quote'] = 'Which sketch needs shading?'
    if bad == 'tiny_quote': rows[0]['quote'] = 'bank'
    if bad == 'source_rejected': rows[0]['supported'] = False
    if bad == 'legacy_boolean': result['checks'][0].pop('sources')
    async def complete(*args, **kwargs):
        if 'check_items' in json.loads(args[1][0].content):
            data = result
        else:
            data = {'work_kind': 'memories', 'item': report().memories[0].model_dump()}
        return ProviderResponse(content=json.dumps(data), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    outcome = asyncio.run(reasoning.analyze('', now=NOW, cognitive=True,
        evidence=source.evidence(), save=source.save))
    assert outcome['status'] == 'unavailable'
    assert not Consolidation(store).evidence()


def test_exact_source_grounding_is_required_in_native_schema(grounded, monkeypatch):
    _, source = grounded
    calls = []
    async def complete(*args, **kwargs):
        calls.append((json.loads(args[1][0].content), kwargs))
        blind = 'subject' not in calls[-1][0]['check_items'][0]['value']
        return ProviderResponse(content=json.dumps(checks(relatedness_only=blind)), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    payload = {'review_purpose': 'cognitive_review', 'evidence': source.evidence(),
               'time': NOW.isoformat(), 'live': {}}
    asyncio.run(reasoning.critique(report(), payload, 'ollama'))
    assert len(calls) == 2
    assert set(calls[0][0]['check_items'][0]['value']) == {'evidence'}
    assert calls[1][0]['check_items'][0]['value']['subject'] == 'Sketch shading'
    schema = calls[0][1]['response_schema']
    assert 'sources' in schema['$defs']['RelationshipCheck']['required']
    assert set(schema['$defs']['EntitySourceCheck']['properties']['source']['enum']) == set(source.evidence())
    assert calls[0][1]['attempt_timeout'] == reasoning.COGNITIVE_ATTEMPT_SECONDS


def test_blind_relatedness_rejection_prevents_label_review(grounded, monkeypatch):
    _, source = grounded
    calls = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        assert 'subject' not in payload['check_items'][0]['value']
        response = checks()
        response['checks'][0]['sources'][1]['supported'] = False
        return ProviderResponse(content=json.dumps(response), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    with pytest.raises(reasoning.UnsupportedConclusion):
        asyncio.run(reasoning.critique(report(), {'review_purpose': 'cognitive_review',
            'evidence': source.evidence(), 'time': NOW.isoformat(), 'live': {}}, 'ollama'))
    assert len(calls) == 1


@pytest.mark.parametrize('relation', ['broad_category', 'unrelated', 'uncertain'])
@pytest.mark.parametrize('bad_quote', [False, True])
def test_overall_true_cannot_override_a_non_specific_relationship(grounded, monkeypatch, relation, bad_quote):
    store, source = grounded
    calls = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' not in payload:
            data = {'work_kind': 'memories', 'item': report().memories[0].model_dump()}
        else:
            data = checks()
            data['checks'][0]['relation'] = relation
            if bad_quote:
                data['checks'][0]['sources'][0]['quote'] = 'An invented excerpt'
        return ProviderResponse(content=json.dumps(data), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(reasoning.analyze('', now=NOW, cognitive=True,
        evidence=source.evidence(), save=source.save))
    assert result['status'] == 'unavailable' and not Consolidation(store).evidence()
    assert len(calls) == 2  # no re-polling after an explicit relationship rejection


@pytest.mark.parametrize('bad', ['invented_entity', 'missing_meaning', 'unknown_relation'])
def test_entity_disambiguation_must_be_grounded_and_typed(grounded, monkeypatch, bad):
    _, source = grounded
    data = checks()
    if bad == 'invented_entity': data['checks'][0]['sources'][0]['entity'] = 'The same artwork'
    if bad == 'missing_meaning': data['checks'][0]['sources'][0].pop('meaning')
    if bad == 'unknown_relation': data['checks'][0]['relation'] = 'generally_similar'
    async def complete(*args, **kwargs):
        return ProviderResponse(content=json.dumps(data), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    with pytest.raises(ValueError):
        asyncio.run(reasoning.critique(report(), {'review_purpose': 'cognitive_review',
            'evidence': source.evidence(), 'time': NOW.isoformat(), 'live': {}}, 'ollama'))


@pytest.mark.parametrize('next_kind', ['situations', 'silence', 'memories'])
@pytest.mark.parametrize('first_invalid', ['unknown_source', 'malformed_body'])
def test_correction_retry_stays_with_the_selected_work_or_silence(grounded, monkeypatch, next_kind, first_invalid):
    from services.mind.temporal_memory import TemporalMemory
    store, source = grounded
    generations = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        if 'check_items' in payload:
            data = grounded_response(args, {'checks': [{'id': 0, 'supported': True, 'reason': 'Synthetic support.'}]})
        else:
            generations.append(payload)
            if len(generations) == 1:
                item = report().memories[0].model_dump()
                if first_invalid == 'unknown_source': item['evidence'][0] = 'owner_episode:999'
                else: item['subject'] = 'x'
                data = {'work_kind': 'memories', 'item': item}
            elif next_kind == 'situations':
                data = {'work_kind': 'situations', 'items': [{'source': 'owner_episode:1',
                    'quote': 'My bank account transfer may be delayed.', 'subject': 'Transfer',
                    'status': 'uncertain', 'date_phrase': '', 'supersedes': []}]}
            elif next_kind == 'silence':
                data = {'work_kind': 'silence'}
            else:
                data = {'work_kind': 'memories', 'item': report().memories[0].model_dump()}
        return ProviderResponse(content=json.dumps(data), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(reasoning.analyze('', now=NOW, cognitive=True,
        evidence=source.evidence(), save=source.save))
    assert len(generations) == 2
    assert result['status'] == ('unavailable' if next_kind == 'situations' else 'completed')
    assert not TemporalMemory(store).evidence()
    assert bool(Consolidation(store).evidence()) == (next_kind == 'memories')
