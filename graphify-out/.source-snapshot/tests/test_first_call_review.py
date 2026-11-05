"""Small local date reviews preserve provenance, refusal and resource boundaries."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from test_dialogue_followups import conversation, say


def test_date_review_omits_optional_context_and_keeps_independent_provenance(conversation, monkeypatch):
    from providers import failover
    from services.mind import cognition_context, life_state
    sentinel = 'IRRELEVANT_PRIVATE_ACTIVITY_' * 1000
    monkeypatch.setattr(cognition_context, 'live_state', lambda: {'activity': 'idle', 'optional': sentinel})
    monkeypatch.setattr(life_state, 'current', lambda *a, **kw: {'can_review': True, 'optional': sentinel})
    captured = []
    original = failover.complete_with_failover
    async def capture(*args, **kwargs):
        captured.append((json.loads(args[1][0].content), args[2], {**kwargs, 'max_tokens': args[3]}))
        return await original(*args, **kwargs)
    monkeypatch.setattr(failover, 'complete_with_failover', capture)
    question = say('My exam was postponed')
    assert say('Robotics, November 3').success
    assert len(captured) == 2
    generation, prompt, options = captured[0]
    critique = captured[1][0]
    assert len(prompt) < 1800
    assert sentinel not in json.dumps(captured)
    assert set(generation) == {'evidence', 'pending_temporal_corrections', 'review_purpose'}
    assert 'report' not in critique and set(critique['source']) == {'evidence'}
    assert critique['source']['evidence'] == generation['evidence']
    source = next(value for value in generation['evidence'].values() if value.get('kind') == 'owner_answer')
    assert source['text'] == 'Robotics, November 3' and source['question'] == question.message
    assert source['noted'] and source['date_clarification']['origin']['text'] == 'My exam was postponed'
    assert source['date_clarification']['version']
    assert options['purpose'] == 'cognitive_review' and options['attempt_timeout'] == 8
    assert options['max_tokens'] == 1400
    schema = options['response_schema']
    assert {row['properties']['work_kind']['const'] for row in schema['oneOf']} == {'situations', 'silence'}
    assert len(conversation[2].history('robotics exam')) == 2


@pytest.mark.parametrize('extra', ['other_report', 'runtime', 'inquiry', 'historical', 'remote'])
def test_compaction_cannot_hide_other_evidence_or_broaden_a_link(conversation, monkeypatch, extra):
    from services.mind import date_review
    _, episodes, temporal, _ = conversation
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My exam was postponed')
    say('Robotics, November 3')
    known = {**temporal.evidence(), **episodes.evidence()}
    pending = temporal.pending_corrections(known)
    source, targets = next(iter(pending.items()))
    bounded = {key: known[key] for key in (source, *targets)}
    assert date_review.scoped(bounded, pending)
    if extra in {'other_report', 'runtime'}:
        bounded['extra'] = {'kind': 'owner_message' if extra == 'other_report' else 'runtime',
                            'text': 'The exam date did not change.'}
    else:
        bounded[source] = {**bounded[source]}
        if extra == 'inquiry':
            bounded[source]['date_clarification'] = {**bounded[source]['date_clarification'], 'kind': 'inquiry'}
        elif extra == 'historical':
            bounded[source]['historical_recall'] = True
        else:
            bounded[source]['channel'] = 'telegram'
    assert not date_review.scoped(bounded, pending)


def test_extra_report_keeps_full_generation_and_independent_review_context(conversation, monkeypatch):
    from providers import failover
    from services.mind import cognition_context, reasoning
    _, episodes, temporal, _ = conversation
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
    say('My exam was postponed')
    say('Robotics, November 3')
    known = {**temporal.evidence(), **episodes.evidence()}
    source, targets = next(iter(temporal.pending_corrections(known).items()))
    evidence = {key: known[key] for key in (source, *targets)}
    evidence['owner_episode:9999'] = {'kind': 'owner_message', 'channel': 'chat',
        'text': 'The robotics exam date did not change.', 'noted': known[source]['noted']}
    monkeypatch.setattr(cognition_context, 'live_state', lambda: {'activity': 'idle', 'context': 'retained'})
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    captured, original = [], failover.complete_with_failover
    async def capture(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        captured.append((payload, args[2]))
        if 'check_items' in payload:
            return ProviderResponse(content=json.dumps({'checks': [{'id': 0, 'supported': False,
                'reason': 'The extra owner report contradicts the proposed date.'}]}), provider='ollama', model='synthetic')
        return await original(*args, **kwargs)
    monkeypatch.setattr(failover, 'complete_with_failover', capture)
    def forbidden(*args):
        pytest.fail('Rejected evidence reached persistence')
    result = asyncio.run(reasoning.analyze('', cognitive=True, evidence=evidence, save=forbidden))
    assert result['status'] == 'unavailable' and len(temporal.history('robotics exam')) == 1
    assert len(captured) == 4  # One repair stays inside the same reviewed evidence.
    for payload, prompt in captured:
        context = payload['source'] if 'check_items' in payload else payload
        assert context['evidence'] == evidence and context['live']['context'] == 'retained'
        assert 'class_calendar' in context and 'life_state' in context
        if 'check_items' in payload:
            assert 'report' in payload
        else:
            assert prompt == reasoning.COGNITIVE_PROMPT


@pytest.mark.parametrize('verdict', ['false', 'missing', 'wrong_id', 'incomplete'])
def test_compact_review_cannot_accept_bad_independent_checks(conversation, monkeypatch, verdict):
    from providers import failover
    original = failover.complete_with_failover
    async def check(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        if 'check_items' not in payload:
            return await original(*args, **kwargs)
        checks = [] if verdict == 'missing' else [{'id': 99 if verdict == 'wrong_id' else 0,
            'supported': verdict != 'false', 'reason': 'Synthetic source check.'}]
        return ProviderResponse(content=json.dumps({'checks': checks}), provider='ollama', model='synthetic',
                                metadata={'incomplete': verdict == 'incomplete'})
    monkeypatch.setattr(failover, 'complete_with_failover', check)
    say('My exam was postponed')
    result = say('Robotics, November 3')
    assert not result.success and len(conversation[2].history('robotics exam')) == 1


@pytest.mark.parametrize('context', [16384, 4096, None, '16384'])
def test_readiness_records_stages_and_requires_known_matching_context(monkeypatch, context):
    from providers.ollama.runtime import OllamaRuntime
    from providers.ollama import runtime as module
    runtime, posts = OllamaRuntime(), []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs):
            model = {'name': config.OLLAMA_MODEL}
            if context is not None:
                model['context_length'] = context
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'models': [model]})
        async def post(self, *args, **kwargs):
            posts.append(kwargs['json'])
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'done': True, 'done_reason': 'load', 'eval_count': 0})
    async def ready(*args): pass
    monkeypatch.setattr(module.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(runtime, 'ensure_running', ready)
    result = asyncio.run(runtime.prepare_model())
    assert all(type(result[key]) in (int, float) and result[key] >= 0
               for key in ('server_ready_ms', 'resident_check_ms', 'model_load_request_ms'))
    assert bool(posts) is (context != 16384)
    assert result['was_resident'] is (True if context == 16384 else False if context == 4096 else None)
    if posts:
        assert 'prompt' not in posts[0] and 'messages' not in posts[0] and posts[0]['options']['num_ctx'] == 16384
