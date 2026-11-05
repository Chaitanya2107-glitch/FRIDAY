import asyncio
import json
import time

import numpy as np
import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from services.files import embed
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition


@pytest.mark.parametrize('relation,expected', [('compatible', True), ('different', False), ('uncertain', False)])
def test_referent_review_is_local_and_grounds_missing_concepts(monkeypatch, relation, expected):
    from services.mind.recall_review import supports
    for name in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, name, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    calls = []
    async def complete(*args, **kwargs):
        calls.append((args, kwargs))
        data = json.loads(args[1][0].content)
        spans = {'container': 'case', 'grip': 'handle'}
        return ProviderResponse(content=json.dumps({'checks': [{'query_term': term,
            'source_span': spans.get(term, ''), 'same_meaning': expected}
            for term in data['MISSING_QUERY_TERMS']], 'relation': relation}), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    row = {'text': 'The cello case needs a replacement handle.', 'question': ''}
    result = asyncio.run(supports('container grip' if expected else 'violin carrier grip damaged',
                                 row, deadline=time.monotonic() + 2))
    assert result is expected
    assert len(calls) == 1 and calls[0][0][0] == 'ollama'
    assert calls[0][1]['purpose'] == 'cognitive_review' and 'tools' not in calls[0][1]


def test_semantic_candidate_cannot_escape_check_and_forgetting(tmp_path, monkeypatch):
    from services.mind import recall_review
    memory = BrainMemory(Cognition(tmp_path / 'checked.db'))
    memory.remember('The cello case needs a replacement handle.')
    monkeypatch.setattr(embed, 'encode_local', lambda *a, **kw: np.array([[1., 0.], [1., 0.]]))
    async def reject(*a, **kw):
        return False
    monkeypatch.setattr(recall_review, 'supports', reject)
    assert asyncio.run(memory.recall_checked('violin carrier grip damaged')) == []
    async def forget(*a, **kw):
        memory.store.clear()
        return True
    monkeypatch.setattr(recall_review, 'supports', forget)
    assert asyncio.run(memory.recall_checked('string instrument container grip')) == []


@pytest.mark.parametrize('content', [
    'invalid json',
    json.dumps({'checks': [{'query_term': 'violin', 'source_span': 'cello', 'same_meaning': True}], 'relation': 'compatible'}),
    json.dumps({'checks': [{'query_term': term, 'source_span': 'invented', 'same_meaning': True}
                           for term in ('violin', 'carrier')], 'relation': 'compatible'}),
    json.dumps({'checks': [{'query_term': term, 'source_span': 'cello', 'same_meaning': term != 'violin'}
                           for term in ('violin', 'carrier')], 'relation': 'compatible'}),
    json.dumps({'checks': [{'query_term': 'violin', 'source_span': 'cello', 'same_meaning': True}] * 2,
                'relation': 'compatible'}),
    json.dumps({'checks': [{'query_term': term, 'source_span': ' ', 'same_meaning': True}
                           for term in ('violin', 'carrier')], 'relation': 'compatible'}),
])
def test_malformed_or_ungrounded_review_abstains(monkeypatch, content):
    from services.mind.recall_review import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def complete(*a, **kw):
        return ProviderResponse(content=content, provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert not asyncio.run(supports('violin carrier', {'text': 'The cello case.', 'question': ''},
                                    deadline=time.monotonic() + 2))


def test_unavailable_resources_and_zero_limit_cannot_infer(tmp_path, monkeypatch):
    from services.mind.recall_review import supports
    async def forbidden(*a, **kw):
        pytest.fail('A resource gate allowed inference')
    monkeypatch.setattr('providers.failover.complete_with_failover', forbidden)
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    row = {'text': 'The cello case.', 'question': ''}
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://example.com:11434')
    assert not asyncio.run(supports('violin carrier', row, deadline=time.monotonic() + 2))
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    assert not asyncio.run(supports('violin carrier', row, deadline=time.monotonic() - 1))
    memory = BrainMemory(Cognition(tmp_path / 'limit.db'))
    memory.remember('The cello case.')
    assert asyncio.run(memory.recall_checked('violin carrier', limit=0)) == []


def test_cancelled_review_propagates_and_disabled_review_cannot_infer(monkeypatch):
    from services.mind.recall_review import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    calls = []
    async def cancelled(*a, **kw):
        calls.append(True)
        raise asyncio.CancelledError
    monkeypatch.setattr('providers.failover.complete_with_failover', cancelled)
    row = {'text': 'The cello case.', 'question': ''}
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(supports('violin carrier', row, deadline=time.monotonic() + 2))
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    assert not asyncio.run(supports('violin carrier', row, deadline=time.monotonic() + 2))
    assert len(calls) == 1


def test_disabling_review_during_inference_discards_its_result(monkeypatch):
    from services.mind.recall_review import supports
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    async def disabled(*a, **kw):
        monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
        return ProviderResponse(content=json.dumps({'checks': [
            {'query_term': 'bike', 'source_span': 'bicycle', 'same_meaning': True}],
            'relation': 'compatible'}), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', disabled)
    assert not asyncio.run(supports('bike tyre', {'text': 'The bicycle tyre.', 'question': ''},
                                    deadline=time.monotonic() + 2))


def test_shared_deadline_cancels_semantic_review_without_returning_candidate(tmp_path, monkeypatch):
    from services.mind import recall_review
    memory = BrainMemory(Cognition(tmp_path / 'deadline.db'))
    memory.remember('The cello case.')
    monkeypatch.setattr(embed, 'encode_local', lambda *a, **kw: np.array([[1., 0.], [1., 0.]]))
    started = []
    async def slow(*a, **kw):
        started.append(True)
        await asyncio.Event().wait()
        return True
    monkeypatch.setattr(recall_review, 'supports', slow)
    assert asyncio.run(memory.recall_checked('violin carrier', deadline=time.monotonic() + .3)) == []
    assert started


@pytest.mark.parametrize('quote,expected', [
    ('My biology practical was moved to Monday', '2026-10-26'),
    ('My biology practical was moved from Friday to Monday', '2026-10-26'),
    ('My biology practical was postponed to Saturday', '2026-10-24'),
    ('My biology practical was not moved to Monday', None),
    ('My biology practical might be moved to Monday', None),
    ('Was my biology practical moved to Monday?', None),
    ('My biology practical was moved from Monday', None),
    ('My biology practical was moved to Monday or Tuesday', None),
    ('My biology practical was moved to next Monday', None),
])
def test_correction_recovers_only_explicit_unambiguous_new_target(quote, expected):
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    known = {'owner_episode:2': {'text': quote, 'noted': '2026-10-22T12:00:00'}}
    value = TemporalUpdate(source='owner_episode:2', quote=quote, subject='biology practical',
        status='planned', date_phrase='in 3 days', start=None, end=None, supersedes=['temporal:1'])
    if expected is None and ' to ' in quote:
        with pytest.raises(ValueError):
            TemporalMemory.resolve([value], known)
        return
    result = TemporalMemory.resolve([value], known)[0]
    assert result.start == result.end == expected
    if expected:
        assert result.date_phrase in quote and result.date_phrase != 'in 3 days'


def test_recovered_rescheduling_target_persists_with_original_history(tmp_path):
    from datetime import datetime, timedelta
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    memory = BrainMemory(Cognition(tmp_path / 'dates.db'))
    temporal = TemporalMemory(memory.store)
    now = datetime(2026, 10, 22, 12)
    first = memory.remember('My biology practical is on Friday', now=now)
    value = TemporalUpdate(source=f'owner_episode:{first}', quote='My biology practical is on Friday',
        subject='biology practical', status='planned', date_phrase='Friday', start=None, end=None, supersedes=[])
    known = memory.evidence()
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([value], known), now, known)
    later = now + timedelta(hours=1)
    quote = 'My biology practical was moved from Friday to Monday'
    second = memory.remember(quote, now=later)
    known = {**memory.evidence(), **temporal.evidence()}
    correction = value.model_copy(update={'source': f'owner_episode:{second}', 'quote': quote,
        'date_phrase': 'Friday', 'supersedes': list(temporal.evidence())})
    with temporal._db() as db:
        temporal.save(db, temporal.resolve([correction], known), later, known)
    history = temporal.history('biology practical')
    assert [row['start'] for row in history] == ['2026-10-26', '2026-10-23']
    assert history[1]['superseded_by'] == history[0]['id']
    recalled = memory.recall('biology practical Friday')
    assert [row['id'] for row in recalled] == [f'owner_episode:{second}']
