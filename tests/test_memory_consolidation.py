import asyncio
import json
from datetime import datetime, timedelta

import pytest

from memory_review_support import grounded_response

from core.config import config
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition

NOW = datetime(2026, 10, 21, 15)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    from services.mind.consolidation import Consolidation
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    store = Cognition(tmp_path / 'brain.db')
    return Consolidation(store), BrainMemory(store)


def proposal(*ids, **changes):
    from services.mind.consolidation import MemoryThread
    return MemoryThread(**{'subject': 'Report preparation',
        'evidence': [f'owner_episode:{ident}' for ident in ids], **changes})


def keep(memory, *values, known=None):
    summary, episodes = memory
    known = known if known is not None else {**episodes.evidence(), **summary.source_evidence()}
    with summary._db() as db:
        summary.save(db, values, NOW, known)


def pair(memory):
    _, episodes = memory
    a = episodes.remember('My report needs the lab notes', now=NOW)
    b = episodes.remember('Maybe Friday', question='When will the lab notes arrive?', now=NOW + timedelta(minutes=1))
    return a, b


def test_original_quotes_questions_dates_and_uncertainty_survive_retention_restart(memory):
    from services.mind.consolidation import Consolidation
    summary, episodes = memory
    a, b = pair(memory)
    keep(memory, proposal(a, b))
    for i in range(501):
        episodes.remember(f'Unrelated message {i}', now=NOW + timedelta(days=1))
    restored = Consolidation(Cognition(summary.store.path))
    row = next(iter(restored.evidence().values()))
    assert row['kind'] == 'memory_summary' and row['source'] == 'inferred_grouping'
    assert row['excerpts'][0]['text'] == 'My report needs the lab notes'
    assert row['excerpts'][1]['text'] == 'Maybe Friday'
    assert row['excerpts'][1]['question'] == 'When will the lab notes arrive?'
    assert row['excerpts'][1]['noted'] == (NOW + timedelta(minutes=1)).isoformat()
    assert len(restored.source_evidence()) == 2
    assert not any(str(a) == ref.split(':')[-1] for ref in episodes.evidence())


def test_duplicate_is_idempotent_and_overlapping_new_group_retires_old(memory):
    summary, episodes = memory
    a, b = pair(memory)
    keep(memory, proposal(a, b))
    keep(memory, proposal(b, a, subject='Different wording'))
    assert len(summary.evidence()) == 1
    c = episodes.remember('The lab notes have arrived', now=NOW + timedelta(minutes=2))
    keep(memory, proposal(b, c))
    assert len(summary.evidence()) == 1
    assert summary.status()['retired'] == 1


@pytest.mark.parametrize('bad', ['unknown', 'remote', 'recursive', 'duplicate', 'identical'])
def test_invalid_sources_rejected(memory, bad):
    summary, episodes = memory
    a, b = pair(memory)
    known = episodes.evidence()
    value = proposal(a, b)
    if bad == 'unknown': value.evidence[1] = 'owner_episode:999'
    if bad == 'remote': known[value.evidence[1]]['channel'] = 'telegram'
    if bad == 'recursive': known[value.evidence[1]]['kind'] = 'memory_summary'
    if bad == 'duplicate': value.evidence[1] = value.evidence[0]
    if bad == 'identical': known[value.evidence[1]].update(text=known[value.evidence[0]]['text'], question='')
    with pytest.raises(ValueError): keep(memory, value, known=known)
    assert not summary.evidence()


@pytest.mark.parametrize('field,value', [('text', 'Altered'), ('question', 'Different question'),
                                        ('noted', '2026-10-22T15:00:00'), ('channel', 'voice')])
def test_sources_rechecked_inside_save_transaction(memory, field, value):
    summary, episodes = memory
    a, b = pair(memory)
    stale = episodes.evidence()
    with episodes._db() as db:
        db.execute(f'UPDATE owner_episodes SET {field}=? WHERE id=?', (value, a))
    with pytest.raises(ValueError): keep(memory, proposal(a, b), known=stale)
    assert not summary.source_evidence()


def test_forget_clears_snapshots_and_stale_worker_cannot_resurrect(memory):
    summary, episodes = memory
    a, b = pair(memory)
    keep(memory, proposal(a, b))
    stale = episodes.evidence()
    summary.store.clear()
    assert not summary.evidence() and not summary.source_evidence()
    with pytest.raises(ValueError): keep(memory, proposal(a, b), known=stale)


def test_temporal_correction_retires_summary_and_preserves_latest_original_after_retention(memory):
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    summary, episodes = memory
    temporal = TemporalMemory(summary.store)
    a = episodes.remember('My exam is tomorrow', now=NOW)
    b = episodes.remember('I need to revise optics for my exam', now=NOW)
    value = TemporalUpdate(source=f'owner_episode:{a}', quote='My exam is tomorrow', subject='exam',
        status='planned', date_phrase='tomorrow', start='2026-10-22', end='2026-10-22', supersedes=[])
    with temporal._db() as db: temporal.save(db, [value], NOW, episodes.evidence())
    keep(memory, proposal(a, b, subject='Exam preparation'))
    old = next(iter(temporal.evidence()))
    c = episodes.remember('My exam was postponed', now=NOW + timedelta(hours=1))
    correction = value.model_copy(update={'source': f'owner_episode:{c}', 'quote': 'My exam was postponed',
        'status': 'postponed', 'date_phrase': '', 'start': None, 'end': None, 'supersedes': [old]})
    with temporal._db() as db:
        temporal.save(db, [correction], NOW, {**episodes.evidence(), **temporal.evidence()})
    assert not summary.evidence()
    for i in range(501): episodes.remember(f'Unrelated {i}', now=NOW + timedelta(days=1))
    known = summary.source_evidence()
    assert known[f'owner_episode:{a}']['memory_replacements'] == [f'owner_episode:{c}']
    assert known[f'owner_episode:{c}']['text'] == 'My exam was postponed'
    with pytest.raises(ValueError): keep(memory, proposal(a, b), known=known)
    keep(memory, proposal(a, b, c), known=known)
    row = next(iter(summary.evidence().values()))
    assert len(row['excerpts']) == 3 and 'memory_replacements' in row['excerpts'][0]
    # A later correction compresses links to the latest source, even after original pruning.
    old = next(iter(temporal.evidence()))
    d = episodes.remember('My exam is now on Monday', now=NOW + timedelta(hours=2))
    newest = value.model_copy(update={'source': f'owner_episode:{d}', 'quote': 'My exam is now on Monday',
        'date_phrase': 'Monday', 'start': '2026-10-26', 'end': '2026-10-26', 'supersedes': [old]})
    with temporal._db() as db:
        temporal.save(db, [newest], NOW, {**summary.source_evidence(), **episodes.evidence(), **temporal.evidence()})
    assert not summary.evidence()
    with pytest.raises(ValueError): keep(memory, proposal(a, b, c), known=known)
    latest = summary.source_evidence()
    assert latest[f'owner_episode:{a}']['memory_replacements'] == [f'owner_episode:{d}']
    assert latest[f'owner_episode:{c}']['memory_replacements'] == [f'owner_episode:{d}']
    keep(memory, proposal(a, b, d), known=latest)
    assert len(summary.evidence()) == 1


def test_real_executive_generation_critique_schema_and_local_context(memory, monkeypatch):
    from providers.base_provider import ProviderResponse
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    summary, _ = memory
    a, b = pair(memory)
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle', 'away': False})
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(summary.store))
    calls = []
    async def complete(*args, **kwargs):
        calls.append((json.loads(args[1][0].content), kwargs))
        result = ({'facts': [], 'conclusions': [], 'questions': [], 'situations': [],
                   'memories': [proposal(a, b).model_dump()]} if len(calls) == 1 else
                  {'checks': [{'id': 0, 'supported': True, 'reason': 'Both reports concern the notes needed for the report.'}]})
        return ProviderResponse(content=json.dumps(grounded_response(args, result)), provider='ollama', model='local')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(executive.ExecutiveControl(summary.store).review(NOW))
    assert result['status'] == 'completed' and len(calls) == 3
    assert all(call[1]['purpose'] == 'cognitive_review' for call in calls)
    schema = calls[0][1]['response_schema']
    assert set(schema['$defs']['MemoryThread']['properties']['evidence']['items']['enum']) == {f'owner_episode:{a}', f'owner_episode:{b}'}
    assert calls[1][0]['check_items'][0]['kind'] == 'memory_thread'
    store = ReasoningStore(summary.store)
    assert not store.facts() and not store.conclusions(NOW)
    assert store.context(NOW)['memories'] and any(v['kind'] == 'memory_summary' for v in store.evidence().values())
    assert 'Maybe Friday' in reasoning.prompt_section(NOW)
    from services.automation.intent import remote_request
    token = remote_request.set(True)
    try: assert 'Maybe Friday' not in reasoning.prompt_section(NOW)
    finally: remote_request.reset(token)


def test_correction_before_first_grouping_is_not_lost_and_stale_snapshot_rejected(memory):
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    summary, episodes = memory
    temporal = TemporalMemory(summary.store)
    a = episodes.remember('My exam is tomorrow', now=NOW)
    b = episodes.remember('I am revising optics for my exam', now=NOW)
    value = TemporalUpdate(source=f'owner_episode:{a}', quote='My exam is tomorrow', subject='exam',
        status='planned', date_phrase='tomorrow', start='2026-10-22', end='2026-10-22', supersedes=[])
    with temporal._db() as db: temporal.save(db, [value], NOW, episodes.evidence())
    stale = episodes.evidence()
    old = next(iter(temporal.evidence()))
    c = episodes.remember('My exam was postponed', now=NOW + timedelta(hours=1))
    change = value.model_copy(update={'source': f'owner_episode:{c}', 'quote': 'My exam was postponed',
        'status': 'postponed', 'date_phrase': '', 'start': None, 'end': None, 'supersedes': [old]})
    with temporal._db() as db:
        temporal.save(db, [change], NOW, {**episodes.evidence(), **temporal.evidence()})
    with pytest.raises(ValueError): keep(memory, proposal(a, b), known=stale)
    known = {**episodes.evidence(), **temporal.evidence()}
    temporal.annotate_history(known)
    with pytest.raises(ValueError): keep(memory, proposal(a, b), known=known)
    old = next(iter(temporal.evidence()))
    d = episodes.remember('My exam is now Monday', now=NOW + timedelta(hours=2))
    latest = value.model_copy(update={'source': f'owner_episode:{d}', 'quote': 'My exam is now Monday',
        'date_phrase': 'Monday', 'start': '2026-10-26', 'end': '2026-10-26', 'supersedes': [old]})
    with temporal._db() as db:
        temporal.save(db, [latest], NOW, {**episodes.evidence(), **temporal.evidence()})
    known = {**episodes.evidence(), **temporal.evidence()}
    temporal.annotate_history(known)
    keep(memory, proposal(a, b, d), known=known)
    assert summary.source_evidence()[f'owner_episode:{a}']['memory_replacements'] == [f'owner_episode:{d}']


def test_storage_bounded_and_unreferenced_snapshots_removed(memory):
    summary, episodes = memory
    # Bulk fixture setup avoids unrelated event logging; retention policy is real.
    with episodes._db() as db:
        for i in range(202):
            db.execute('INSERT INTO owner_episodes(source_key,channel,question,text,noted) VALUES(?,?,?,?,?)',
                       (str(i), 'chat', '', f'Report source {i}', NOW.isoformat()))
    with episodes._db() as db:
        known = {f"owner_episode:{r['id']}": episodes._episode(r) for r in db.execute('SELECT * FROM owner_episodes')}
    for i in range(1, 202, 2): keep(memory, proposal(i, i + 1), known=known)
    assert summary.status() == {'active': 100, 'retired': 0, 'sources': 200,
                               'thread_limit': 100, 'method': 'locally reviewed extractive grouping'}
    with summary._db() as db:
        assert not db.execute("SELECT 1 FROM consolidated_sources WHERE ref='owner_episode:1'").fetchone()


def test_critique_rejection_never_archives_model_grouping(memory, monkeypatch):
    from providers.base_provider import ProviderResponse
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    summary, episodes = memory
    a, b = pair(memory)
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle'})
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(summary.store))
    calls = []
    async def complete(*args, **kwargs):
        calls.append(kwargs)
        result = ({'checks': [{'id': 0, 'supported': False, 'reason': 'The subject asserts an unsupported cause.'}]}
                  if len(calls) % 2 == 0 else
                  {'facts': [], 'conclusions': [], 'questions': [], 'memories': [proposal(a, b).model_dump()]})
        return ProviderResponse(content=json.dumps(grounded_response(args, result)), provider='ollama', model='local')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(executive.ExecutiveControl(summary.store).review(NOW))
    assert result['status'] == 'unavailable' and len(calls) == 2
    assert not summary.evidence() and not summary.source_evidence()


def test_empty_evidence_disables_grouping_and_generated_recaps_are_rejected():
    from services.mind import reasoning
    assert all(branch['properties']['work_kind']['const'] == 'silence' for branch in reasoning.cognitive_schema({})['oneOf'])
    with pytest.raises(ValueError):
        proposal(1, 2, summary='An invented factual recap')


def test_summary_has_priority_over_duplicate_raw_context_and_marks_short_excerpts(memory):
    from services.mind.executive import ExecutiveControl
    summary, episodes = memory
    a = episodes.remember('Report background ' * 60 + 'but this may change', now=NOW)
    b = episodes.remember('The report still needs review', now=NOW)
    keep(memory, proposal(a, b))
    known = {f'owner_episode:{i}': {'kind': 'owner_message', 'text': 'X' * 1200} for i in range(100, 125)}
    known.update(summary.evidence())
    reviewed = ExecutiveControl._build(NOW, known, {'activity': 'idle'}, 'background')['evidence']
    row = next(v for v in reviewed.values() if v['kind'] == 'memory_summary')
    assert row['excerpts'][0]['excerpt_truncated'] is True
    assert summary.source_evidence()[f'owner_episode:{a}']['text'].endswith('but this may change')


def test_real_forget_command_clears_threads_and_source_snapshots(memory, monkeypatch):
    from services.memory import semantic
    from services.mind import executive
    summary, _ = memory
    a, b = pair(memory)
    keep(memory, proposal(a, b))
    monkeypatch.setattr(executive, 'executive', executive.ExecutiveControl(summary.store))
    from services.mind.training import reviews
    monkeypatch.setattr(reviews, 'forget_facts', lambda *args: [])
    monkeypatch.setattr(semantic.reasoning_store, 'forget', lambda *args: None)
    monkeypatch.setattr('services.memory.schedule.forget', lambda *args: None)
    monkeypatch.setattr(semantic.semantic_memory, 'forget', lambda *args: None)
    semantic.run_memory_command({'action': 'forget_memory', 'text': 'report notes'})
    assert not summary.evidence() and not summary.source_evidence()


def test_forget_during_real_review_fences_acceptance(memory, monkeypatch):
    from providers.base_provider import ProviderResponse
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    summary, _ = memory
    a, b = pair(memory)
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle'})
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(summary.store))
    calls = []
    async def complete(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            result = {'facts': [], 'conclusions': [], 'questions': [], 'memories': [proposal(a, b).model_dump()]}
        else:
            summary.store.clear()
            result = {'checks': [{'id': 0, 'supported': True, 'reason': 'Both sources are about report preparation.'}]}
        return ProviderResponse(content=json.dumps(grounded_response(args, result)), provider='ollama', model='local')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(executive.ExecutiveControl(summary.store).review(NOW))
    assert result['status'] in {'unavailable', 'superseded'}
    assert not summary.evidence() and not summary.source_evidence()


def test_independent_corrections_in_one_episode_survive_pruning(memory):
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    summary, episodes = memory
    temporal = TemporalMemory(summary.store)
    a = episodes.remember('My exam is tomorrow and my meeting is Friday', now=NOW)
    b = episodes.remember('I am preparing notes for my exam and meeting', now=NOW)
    first = [TemporalUpdate(source=f'owner_episode:{a}', quote='My exam is tomorrow and my meeting is Friday',
        subject=subject, status='planned', date_phrase=phrase, start=day, end=day, supersedes=[])
        for subject, phrase, day in [('exam', 'tomorrow', '2026-10-22'), ('meeting', 'Friday', '2026-10-23')]]
    with temporal._db() as db: temporal.save(db, first, NOW, episodes.evidence())
    keep(memory, proposal(a, b, subject='Exam and meeting preparation'))
    corrections = []
    for i, subject in enumerate(('exam', 'meeting')):
        c = episodes.remember(f'My {subject} was postponed', now=NOW + timedelta(hours=i+1))
        old = next(ref for ref, row in temporal.evidence().items() if row['subject'] == subject)
        change = first[i].model_copy(update={'source': f'owner_episode:{c}', 'quote': f'My {subject} was postponed',
            'status': 'postponed', 'date_phrase': '', 'start': None, 'end': None, 'supersedes': [old]})
        with temporal._db() as db:
            temporal.save(db, [change], NOW, {**episodes.evidence(), **temporal.evidence()})
        corrections.append(c)
    with episodes._db() as db: db.execute('DELETE FROM owner_episodes')
    known = summary.source_evidence()
    assert set(known[f'owner_episode:{a}']['memory_replacements']) == {f'owner_episode:{c}' for c in corrections}
    assert len(known) == 4 and not summary.evidence()
    with pytest.raises(ValueError): keep(memory, proposal(a, b, corrections[-1]), known=known)
    keep(memory, proposal(a, b, *corrections), known=known)
    assert len(summary.evidence()) == 1


def test_provenance_limit_evicts_whole_thread_instead_of_dropping_corrections(memory):
    summary, _ = memory
    a, b = pair(memory)
    keep(memory, proposal(a, b))
    base = summary.source_evidence()[f'owner_episode:{a}']
    with summary._db() as db:
        db.execute('UPDATE consolidated_sources SET corrections=? WHERE ref=?',
                   (json.dumps({'exam': 'owner_episode:3'}), f'owner_episode:{a}'))
        for i in range(3, 802):
            source = {**base, 'id': f'owner_episode:{i}', 'text': f'Synthetic correction {i}'}
            links = {f'new commitment {i}': f'owner_episode:{i+1}'} if i < 801 else {}
            db.execute('INSERT INTO consolidated_sources(ref,body,corrections) VALUES(?,?,?)',
                       (source['id'], json.dumps(source), json.dumps(links)))
        summary._prune(db)
    assert summary.status()['sources'] == 0 and summary.status()['active'] == 0


@pytest.mark.parametrize('source', ['consolidation:1', 'owner_episode:1'])
def test_private_summary_conclusions_do_not_enter_remote_prompts_or_mirrored_offers(monkeypatch, source):
    from services.mind import reasoning
    from services.automation.intent import remote_request
    claim = {'id': 1, 'status': 'proposed', 'kind': 'proposal', 'text': 'Private report preparation plan.',
             'evidence': [source], 'confidence': .9, 'noted': NOW.isoformat()}
    monkeypatch.setattr(reasoning.reasoning_store, 'context', lambda now: {'facts': [], 'conclusions': [claim]})
    assert reasoning.suggestion(NOW) is None
    token = remote_request.set(True)
    try: assert 'Private report preparation' not in reasoning.prompt_section(NOW)
    finally: remote_request.reset(token)


def test_local_brain_api_and_reasoning_inspection_show_retained_provenance(memory, monkeypatch):
    from interfaces.api.routes import mind
    from services.mind import cognition_commands, consolidation, reasoning_commands
    from services.mind.reasoning_store import ReasoningStore
    summary, _ = memory
    a, b = pair(memory)
    keep(memory, proposal(a, b))
    monkeypatch.setattr(consolidation, 'consolidation', summary)
    monkeypatch.setattr(reasoning_commands, 'reasoning_store', ReasoningStore(summary.store))
    assert asyncio.run(mind.brain_status())['consolidation']['active'] == 1
    result = cognition_commands.run('brain_status')
    assert 'Memory consolidation: 1 active historical threads' in result.message
    shown = asyncio.run(reasoning_commands.run({'action': 'show'}))
    assert 'Maybe Friday' in shown.message and 'owner_episode:' in shown.message
    assert 'When will the lab notes arrive?' in shown.message


def test_mixed_model_output_defers_optional_grouping_without_losing_valid_commitment(memory, monkeypatch):
    from providers.base_provider import ProviderResponse
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    summary, episodes = memory
    a = episodes.remember('My exam is tomorrow', now=NOW)
    b = episodes.remember('I am revising optics for my exam', now=NOW)
    temporal = TemporalMemory(summary.store)
    update = TemporalUpdate(source=f'owner_episode:{a}', quote='My exam is tomorrow', subject='exam',
        status='planned', date_phrase='tomorrow', start=None, end=None, supersedes=[])
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle'})
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(summary.store))
    calls = []
    async def complete(*args, **kwargs):
        calls.append(json.loads(args[1][0].content))
        result = ({'facts': [], 'conclusions': [], 'questions': [], 'situations': [update.model_dump()],
                   'memories': [proposal(a, b, subject='Exam preparation').model_dump()]} if len(calls) == 1 else
                  {'checks': [{'id': 0, 'supported': True, 'reason': 'Actual owner exam commitment; original tomorrow date.'}]})
        return ProviderResponse(content=json.dumps(grounded_response(args, result)), provider='ollama', model='local')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(executive.ExecutiveControl(summary.store).review(NOW))
    assert result['status'] == 'completed' and len(calls) == 2
    assert [item['kind'] for item in calls[1]['check_items']] == ['temporal_interpretation']
    assert temporal.snapshot(NOW)['upcoming'][0]['start'] == '2026-10-22'
    assert not summary.evidence() and not summary.source_evidence()
