import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from memory_review_support import grounded_response

from core.config import config
from core.errors import ProviderError
from providers.base_provider import Message, ProviderResponse
from services.mind.cognition import Cognition

NOW = datetime(2026, 10, 21, 15)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    from services.mind import reasoning
    from services.mind.brain_memory import BrainMemory
    from services.mind.reasoning_store import ReasoningStore
    store = Cognition(tmp_path / 'local-review.db')
    source = BrainMemory(store)
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    source.remember('The report uses the laboratory notes.', now=NOW)
    source.remember('Two pressure measurements may be missing.',
                    question='What might be missing from the laboratory notes?', now=NOW)
    memory = ReasoningStore(store)
    memory.evidence = source.evidence
    monkeypatch.setattr(reasoning, 'reasoning_store', memory)
    monkeypatch.setattr(reasoning, 'cognition', store)
    return store, memory


def memory_report():
    return {'facts': [], 'conclusions': [], 'questions': [], 'situations': [],
            'memories': [{'subject': 'Report laboratory notes', 'evidence': ['owner_episode:1', 'owner_episode:2']}]}


def run_review(engine):
    from services.mind import reasoning
    _, memory = engine
    return asyncio.run(reasoning.analyze('', now=NOW, cognitive=True, evidence=memory.evidence(), save=memory.save))


def test_provider_retains_component_metrics_and_missing_is_unknown(monkeypatch):
    from providers.ollama.client import OllamaProvider
    from providers.ollama import client as module
    data = {'message': {'content': '{}'}, 'done': True, 'done_reason': 'stop',
            'total_duration': 9_000_000, 'load_duration': 1_000_000,
            'prompt_eval_duration': 2_000_000, 'eval_duration': 5_000_000,
            'prompt_eval_count': 30, 'eval_count': 10}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: dict(data))
    monkeypatch.setattr(module.httpx, 'AsyncClient', Client)
    response = asyncio.run(OllamaProvider().complete([Message('user', 'synthetic')], system_prompt='synthetic'))
    assert response.metadata['prompt_eval_duration_ms'] == 2
    assert response.metadata['eval_duration_ms'] == 5
    assert response.metadata['prompt_eval_count'] == 30
    assert response.metadata['done_reason'] == 'stop'
    assert response.metadata['incomplete'] is False
    data.clear()
    data['message'] = {'content': '{}'}
    response = asyncio.run(OllamaProvider().complete([Message('user', 'synthetic')], system_prompt='synthetic'))
    assert response.metadata['prompt_eval_duration_ms'] is None
    assert response.metadata['load_duration_ms'] is None


def test_timeout_cause_is_preserved_without_changing_provider_policy(monkeypatch):
    from providers import failover
    class Provider:
        async def complete(self, **kwargs): raise TimeoutError()
    monkeypatch.setattr(failover, 'get_provider', lambda *args, **kwargs: Provider())
    monkeypatch.setattr(failover, 'provider_chain', lambda *args: ['ollama'])
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', False)
    with pytest.raises(ProviderError) as failure:
        asyncio.run(failover.complete_with_failover('ollama', [Message('user', 'synthetic')], 'synthetic', 20))
    assert isinstance(failure.value.__cause__, TimeoutError)
    assert 'TimeoutError' in str(failure.value)


@pytest.mark.parametrize('value', [None, True, -1, float('nan'), float('inf'), '100', {}, 10**999])
def test_bad_metrics_cannot_break_valid_completion(value):
    from providers.ollama.client import response_metrics
    data = response_metrics({'load_duration': value, 'done_reason': {}})
    assert data['load_duration_ms'] is None and data['done_reason'] is None


def test_readiness_loads_without_prompt_and_reuses_resident_model(monkeypatch):
    from providers.ollama.runtime import OllamaRuntime
    from providers.ollama import runtime as module
    runtime = OllamaRuntime()
    posts = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'models': [{'name': config.OLLAMA_MODEL, 'context_length': 16384}]} if posts else {'models': []})
        async def post(self, *args, **kwargs):
            posts.append(kwargs['json'])
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'done': True, 'done_reason': 'load', 'load_duration': 20_000_000})
    monkeypatch.setattr(module.httpx, 'AsyncClient', Client)
    async def ready(*args): pass
    monkeypatch.setattr(runtime, 'ensure_running', ready)
    first = asyncio.run(runtime.prepare_model())
    second = asyncio.run(runtime.prepare_model())
    assert first['was_resident'] is False and first['load_duration_ms'] == 20
    assert second['was_resident'] is True and len(posts) == 1
    assert 'prompt' not in posts[0] and 'messages' not in posts[0] and 'tools' not in posts[0]
    assert posts[0]['options']['num_ctx'] == 16384


def test_cold_start_and_inference_share_the_executive_lease(engine, monkeypatch):
    from services.mind import executive, review_metrics
    from services.mind.reasoning_store import ReasoningStore
    from providers.ollama.runtime import runtime
    store, _ = engine
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle'})
    calls = []
    async def prepare():
        calls.append('startup')
        return {'was_resident': False, 'load_duration_ms': 30}
    async def complete(*args, **kwargs):
        calls.append('model')
        data = {'checks': [{'id': 0, 'supported': True, 'reason': 'Same report laboratory notes.'}]} if 'check_items' in json.loads(args[1][0].content) else memory_report()
        return ProviderResponse(content=json.dumps(grounded_response(args, data)), provider='ollama', model='installed')
    monkeypatch.setattr(runtime, 'prepare_model', prepare)
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(executive.ExecutiveControl(store).review(NOW))
    assert result['status'] == 'completed' and calls == ['startup', 'model', 'model', 'model']
    trace = review_metrics.latest(store)
    assert trace['startup']['was_resident'] is False
    assert trace['inference_budget_ms'] <= 25000 and trace['lease_budget_ms'] < 45000


def test_private_trace_covers_generation_critique_retry_and_forgetting(engine, monkeypatch):
    from services.mind import review_metrics
    store, _ = engine
    calls = []
    async def complete(*args, **kwargs):
        calls.append(kwargs)
        if 'check_items' not in json.loads(args[1][0].content):
            data = memory_report()
        else:
            # A label can be repaired; an explicit relationship refusal cannot be polled again.
            data = {'checks': [{'id': 0, 'supported': len(calls) != 3, 'reason': 'Synthetic evidence judgment.'}]}
        return ProviderResponse(content=json.dumps(grounded_response(args, data)), provider='ollama', model='installed',
            metadata={'load_duration_ms': 1, 'prompt_eval_duration_ms': 2, 'eval_duration_ms': 3,
                      'prompt_eval_count': 40, 'eval_count': 20, 'raw_private': 'SECRET OWNER TEXT'})
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert run_review(engine)['status'] == 'completed'
    trace = review_metrics.latest(store)
    assert trace['state'] == 'completed' and trace['rejections'] == 1
    assert [c['phase'] for c in trace['calls']] == ['generation', 'critique', 'critique',
                                                 'generation', 'critique', 'critique']
    assert [c.get('stage') for c in trace['calls']] == [None, 'memory_relatedness', 'memory_label',
                                                     None, 'memory_relatedness', 'memory_label']
    assert trace['accepted']['memories'] == 1
    assert trace['calls'][2]['review_error'] == 'evidence_rejected'
    text = json.dumps(trace)
    assert 'SECRET' not in text and 'laboratory' not in text and 'owner_episode:' not in text
    assert all(not event['public'] for event in store.recent(30) if event['kind'] == 'local_review')
    store.clear()
    assert review_metrics.latest(store) is None


@pytest.mark.parametrize('phase', ['generation', 'critique'])
def test_incomplete_even_valid_json_cannot_be_accepted(engine, monkeypatch, phase):
    from services.mind import review_metrics
    from services.mind.consolidation import Consolidation
    store, _ = engine
    async def complete(*args, **kwargs):
        critic = 'check_items' in json.loads(args[1][0].content)
        data = {'checks': [{'id': 0, 'supported': True, 'reason': 'Related original reports.'}]} if critic else memory_report()
        return ProviderResponse(content=json.dumps(grounded_response(args, data)), provider='ollama', model='installed',
            metadata={'incomplete': critic == (phase == 'critique')})
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert run_review(engine)['status'] == 'unavailable'
    assert not Consolidation(store).evidence()
    assert review_metrics.latest(store)['reason'] == 'incomplete_output'


@pytest.mark.parametrize('change', ['forget', 'attention', 'disable'])
def test_startup_cannot_think_from_forgotten_or_changed_attention(engine, monkeypatch, change):
    from services.mind import executive, review_metrics
    from providers.ollama.runtime import runtime
    store, _ = engine
    attention = {'activity': 'idle'}
    monkeypatch.setattr(executive, 'attention_state', lambda: dict(attention))
    async def prepare():
        if change == 'forget': store.clear()
        elif change == 'attention': attention['speaking'] = True
        else: monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', False)
        return {'was_resident': False}
    async def no_model(*args, **kwargs):
        pytest.fail('Changed owner state must be checked before any inference')
    monkeypatch.setattr(runtime, 'prepare_model', prepare)
    monkeypatch.setattr('providers.failover.complete_with_failover', no_model)
    result = asyncio.run(executive.ExecutiveControl(store).review(NOW))
    assert result['status'] in {'unavailable', 'superseded'}
    trace = review_metrics.latest(store)
    if change == 'forget': assert trace is None
    else: assert trace['calls'] == [] and trace['state'] == 'unavailable'


def test_startup_timeout_is_bounded_and_cannot_start_generation(engine, monkeypatch):
    from services.mind import reasoning, review_metrics
    from providers.ollama.runtime import runtime
    store, memory = engine
    async def prepare():
        await asyncio.sleep(.1)
        return {'was_resident': False}
    async def no_model(*args, **kwargs): pytest.fail('Startup exceeded its owned deadline')
    monkeypatch.setattr(runtime, 'prepare_model', prepare)
    monkeypatch.setattr('providers.failover.complete_with_failover', no_model)
    async def run():
        return await reasoning.analyze('', now=NOW, cognitive=True, evidence=memory.evidence(),
            save=memory.save, deadline=asyncio.get_running_loop().time() + .03)
    assert asyncio.run(run())['status'] == 'unavailable'
    assert review_metrics.latest(store)['reason'] == 'startup_timeout'


def test_cancelled_review_records_no_completion_or_source_content(engine, monkeypatch):
    from services.mind import reasoning, review_metrics
    store, memory = engine
    async def complete(*args, **kwargs): raise asyncio.CancelledError()
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    with pytest.raises(asyncio.CancelledError): run_review(engine)
    trace = review_metrics.latest(store)
    assert trace['state'] == 'cancelled' and trace['reason'] == 'cancelled'
    assert not memory.facts() and 'laboratory' not in json.dumps(trace)
    assert review_metrics.active.get() is None


def test_pure_memory_critique_receives_only_original_citations(engine, monkeypatch):
    from services.mind import reasoning
    _, memory = engine
    known = memory.evidence()
    known['unrelated:1'] = {'kind': 'observation', 'text': 'IRRELEVANT PRIVATE CONTEXT ' * 200}
    memory.evidence = lambda: dict(known)
    payloads = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        payloads.append(payload)
        data = {'checks': [{'id': 0, 'supported': True, 'reason': 'Shared report laboratory notes.'}]} if 'check_items' in payload else memory_report()
        return ProviderResponse(content=json.dumps(grounded_response(args, data)), provider='ollama', model='installed')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert run_review(engine)['status'] == 'completed'
    check = payloads[1]
    assert set(check['source']['evidence']) == {'owner_episode:1', 'owner_episode:2'}
    assert 'live' not in check['source'] and 'IRRELEVANT' not in json.dumps(check)


def test_diagnostics_failure_cannot_invalidate_valid_memory(engine, monkeypatch):
    from services.mind import review_metrics
    async def complete(*args, **kwargs):
        data = {'checks': [{'id': 0, 'supported': True, 'reason': 'Shared report sources.'}]} if 'check_items' in json.loads(args[1][0].content) else memory_report()
        return ProviderResponse(content=json.dumps(grounded_response(args, data)), provider='ollama', model='installed')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    def fail_record(self): raise RuntimeError('Diagnostic store unavailable')
    monkeypatch.setattr(review_metrics.ReviewTrace, 'record', fail_record)
    assert run_review(engine)['status'] == 'completed'


def test_native_contract_has_only_single_work_or_silence(engine):
    from services.mind.reasoning import cognitive_schema
    _, memory = engine
    schema = cognitive_schema(memory.evidence())
    assert 'properties' not in schema
    assert schema['$defs']['Conclusion']['properties']['text']['maxLength'] == 240
    assert 'Fact' not in schema['$defs'] and 'TaskPlan' not in schema['$defs']
    enabled = []
    for branch in schema['oneOf']:
        assert next(iter(branch['properties'])) == 'work_kind'
        kind = branch['properties']['work_kind']['const']
        fields = {'work_kind'} if kind == 'silence' else {'work_kind', 'items' if kind == 'situations' else 'item'}
        assert set(branch['properties']) == set(branch['required']) == fields
        assert branch['additionalProperties'] is False
        enabled.append(kind)
    assert set(enabled) == {'situations', 'memories', 'conclusions', 'silence'}
    empty = cognitive_schema({})
    assert len(empty['oneOf']) == 1 and empty['$defs'] == {}


def test_empty_timetable_does_not_offer_class_projection_to_local_model():
    from services.mind.reasoning import cognitive_schema
    schema = cognitive_schema({'timetable': {'kind': 'weekly_template', 'classes': []}})
    assert 'ClassAvailability' not in schema['$defs']


@pytest.mark.parametrize('kind', ['silence', 'situations', 'conclusions'])
def test_explicit_work_choice_cannot_disagree_with_memory_payload(kind):
    from services.mind.reasoning import CognitiveReport
    with pytest.raises(ValueError): CognitiveReport.model_validate({**memory_report(), 'work_kind': kind})


def test_typed_work_choice_accepts_one_memory_and_refuses_mixed_work():
    from services.mind.reasoning import CognitiveReport
    value = {**memory_report(), 'work_kind': 'memories'}
    assert CognitiveReport.model_validate(value).work_kind == 'memories'
    value['questions'] = ['Should I ask a question without inquiry review?']
    with pytest.raises(ValueError): CognitiveReport.model_validate(value)


@pytest.mark.parametrize('kind', ['memories', 'situations', 'silence'])
def test_compact_native_response_runs_through_independent_critique_and_save(engine, monkeypatch, kind):
    from services.mind.brain_memory import BrainMemory
    from services.mind.consolidation import Consolidation
    from services.mind.temporal_memory import TemporalMemory
    store, _ = engine
    if kind == 'situations':
        ident = BrainMemory(store).remember('My exam is tomorrow', now=NOW)
        wire = {'work_kind': kind, 'items': [{'source': f'owner_episode:{ident}', 'quote': 'My exam is tomorrow',
            'subject': 'exam', 'status': 'planned', 'date_phrase': 'tomorrow', 'supersedes': []}]}
    elif kind == 'memories':
        wire = {'work_kind': kind, 'item': memory_report()['memories'][0]}
    else:
        wire = {'work_kind': 'silence'}
    calls = []
    async def complete(*args, **kwargs):
        calls.append(json.loads(args[1][0].content))
        data = {'checks': [{'id': 0, 'supported': True, 'reason': 'Original owner evidence supports this work.'}]} if 'check_items' in calls[-1] else wire
        return ProviderResponse(content=json.dumps(grounded_response(args, data)), provider='ollama', model='installed')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert run_review(engine)['status'] == 'completed'
    assert len(calls) == (1 if kind == 'silence' else 3 if kind == 'memories' else 2)
    assert not engine[1].facts()
    if kind == 'memories': assert Consolidation(store).evidence()
    if kind == 'situations': assert TemporalMemory(store).snapshot(NOW)['upcoming'][0]['start'] == '2026-10-22'


@pytest.mark.parametrize('wire', [
    {'work_kind': 'silence', 'item': {'text': 'Hidden work'}},
    {'work_kind': 'memories', 'item': {}, 'unexpected': 'injected'},
    {'work_kind': 'situations', 'items': [{'start': '2026-10-25'}]},
    {'work_kind': 'situations', 'items': 'not an array'},
    {'work_kind': 'unknown'},
])
def test_compact_wire_cannot_smuggle_fields_or_model_dates(wire):
    from services.mind.review_schema import unpack
    with pytest.raises(ValueError): unpack(wire)


def test_old_process_review_is_interrupted_not_still_thinking(engine):
    from services.mind import review_metrics
    store, _ = engine
    review_metrics.ReviewTrace(store)
    assert review_metrics.latest(store)['state'] == 'running'
    restored = Cognition(store.path)
    last = review_metrics.latest(restored)
    assert last['state'] == 'interrupted' and last['elapsed_ms'] is None
    assert 'unknown' in review_metrics.describe(last)


@pytest.mark.parametrize('url,local', [('http://localhost:11434', True), ('http://127.0.0.1:11434', True),
    ('http://[::1]:11434', True), ('https://localhost:11434', False), ('http://example.org', False), ('https://example.org', False)])
def test_fast_http_setup_is_only_for_unencrypted_loopback(url, local):
    from providers.ollama.runtime import local_http_options
    options = local_http_options(url)
    if local: assert options == {'verify': False, 'trust_env': False}
    else: assert options == {}


@pytest.mark.parametrize('quote,expected', [
    ('My exam is tomorrow', '2026-10-22'),
    ('My exam is the day after tomorrow', '2026-10-23'),
    ('My exam is Friday', '2026-10-23'),
    ('My exam is tomorrow or Friday', None),
    ('My exam is next Friday', None),
    ('My exam is not tomorrow', None),
    ('My exam is 5 November instead of tomorrow', None),
])
def test_missing_date_phrase_recovers_only_one_unambiguous_quote_date(quote, expected):
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    value = TemporalUpdate(source='owner_episode:1', quote=quote, subject='exam', status='planned',
        date_phrase='', start=None, end=None, supersedes=[])
    known = {'owner_episode:1': {'text': quote, 'noted': NOW.isoformat()}}
    resolved = TemporalMemory.resolve([value], known)[0]
    assert resolved.start == expected
    if expected: assert resolved.date_phrase in quote


def test_date_recovery_does_not_restore_a_postponed_or_corrected_date():
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    for status, supersedes in [('postponed', []), ('planned', ['temporal:1'])]:
        value = TemporalUpdate(source='owner_episode:1', quote='The exam was postponed from tomorrow', subject='exam',
            status=status, date_phrase='', start=None, end=None, supersedes=supersedes)
        resolved = TemporalMemory.resolve([value], {'owner_episode:1': {'noted': NOW.isoformat()}})[0]
        assert resolved.start is None and resolved.date_phrase == ''


def test_identical_temporal_repetition_is_deduplicated_but_conflicts_still_fail():
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    quote = 'My exam is tomorrow'
    value = TemporalUpdate(source='owner_episode:1', quote=quote, subject='exam', status='planned',
        date_phrase='', start=None, end=None, supersedes=[])
    known = {'owner_episode:1': {'kind': 'owner_message', 'channel': 'chat', 'text': quote, 'noted': NOW.isoformat()}}
    resolved = TemporalMemory.resolve([value, value], known)
    assert len(resolved) == 1 and resolved[0].start == '2026-10-22'
    conflicting = TemporalMemory.resolve([value, value.model_copy(update={'status': 'uncertain'})], known)
    with pytest.raises(ValueError): TemporalMemory.validate(conflicting, known)
