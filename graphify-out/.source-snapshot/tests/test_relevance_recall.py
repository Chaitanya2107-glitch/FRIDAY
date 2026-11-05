import asyncio
import json
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.consolidation import Consolidation, MemoryThread
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate

NOW = datetime(2026, 10, 21, 15)


@pytest.fixture
def allow_semantic(monkeypatch):
    async def allow(*args, **kwargs):
        return True
    monkeypatch.setattr('services.mind.recall_review.supports', allow)


def checked(memory, query):
    return asyncio.run(memory.recall_checked(query))


def test_paraphrase_fallback_uses_originals_and_rechecks_forgetting(memory, monkeypatch, allow_semantic):
    from services.files import embed
    import numpy as np
    ident = memory.remember('The raincoat zipper is broken.', now=NOW)
    def encode(texts, **kwargs):
        assert any('raincoat zipper' in text for text in texts)
        return np.array([[1., 0.], [1., 0.]])
    monkeypatch.setattr(embed, 'encode_local', encode, raising=False)
    assert checked(memory, 'waterproof clothing fastening')[0]['id'] == f'owner_episode:{ident}'
    def forgotten(texts, **kwargs):
        memory.store.clear()
        return np.array([[1., 0.], [1., 0.]])
    monkeypatch.setattr(embed, 'encode_local', forgotten)
    assert checked(memory, 'waterproof clothing fastening') == []

def test_paraphrase_fallback_abstains_on_low_score_or_ambiguity(memory, monkeypatch, allow_semantic):
    from services.files import embed
    import numpy as np
    memory.remember('The raincoat zipper is broken.', now=NOW)
    monkeypatch.setattr(embed, 'encode_local', lambda texts, **kw: np.array([[1., 0.], [.5, .866]]), raising=False)
    assert checked(memory, 'waterproof clothing fastening') == []
    memory.remember('The waterproof trousers have a damaged zip.', now=NOW)
    monkeypatch.setattr(embed, 'encode_local', lambda texts, **kw: np.array([[1., 0.], [.9, .436], [.88, .475]]))
    assert checked(memory, 'waterproof clothing fastening') == []


def test_semantic_candidates_respect_corrections_channels_and_resource_failure(memory, monkeypatch, allow_semantic):
    from services.files import embed
    import numpy as np
    old, new = correct_exam(memory)
    memory.remember('Private Telegram passport location.', channel='telegram', now=NOW)
    seen = []
    def encode(texts, **kwargs):
        seen.extend(texts)
        assert not any('tomorrow' in text or 'passport' in text for text in texts)
        return np.array([[1., 0.], [1., 0.]])
    monkeypatch.setattr(embed, 'encode_local', encode)
    assert checked(memory, 'light science assessment rescheduled')[0]['id'] == f'owner_episode:{new}'
    assert seen
    def unavailable(texts, **kwargs):
        raise OSError('Installed assets unavailable')
    monkeypatch.setattr(embed, 'encode_local', unavailable)
    assert checked(memory, 'light science assessment rescheduled') == []
    assert memory.recall('optics exam')[0]['id'] == f'owner_episode:{new}'


def test_offline_embedding_load_cannot_download_missing_weights(monkeypatch):
    from services.files import embed
    from types import SimpleNamespace
    import sys
    calls = []
    monkeypatch.setattr(embed, '_model', None)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    def missing(name, **kwargs):
        calls.append(kwargs)
        raise OSError('Weights not cached')
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=missing))
    with pytest.raises(OSError):
        embed._load(local_only=True)
    assert calls == [{'device': 'cpu', 'local_files_only': True}]
    # Exercise the production local entry point despite the suite's isolation stub.
    with pytest.raises(OSError):
        embed.encode_local.__wrapped__(['test'])
    assert calls == [{'device': 'cpu', 'local_files_only': True}] * 2
    assert embed._model is None


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    return BrainMemory(Cognition(tmp_path / 'recall.db'))


def noise(memory, count=150):
    for index in range(count):
        memory.remember(f'Routine unrelated weather observation {index}', now=NOW + timedelta(minutes=index + 1))


def group(memory, *ids, subject='Report preparation'):
    saved = Consolidation(memory.store)
    with saved._db() as db:
        saved.save(db, [MemoryThread(subject=subject, evidence=[f'owner_episode:{i}' for i in ids])],
                   NOW, memory.evidence(limit=50))
    return saved


def correct_exam(memory, *, archived=False):
    temporal = TemporalMemory(memory.store)
    first = memory.remember('My optics exam is tomorrow and I need a library card.', now=NOW)
    original = TemporalUpdate(source=f'owner_episode:{first}', quote='My optics exam is tomorrow',
        subject='optics exam', status='planned', date_phrase='tomorrow', start='2026-10-22',
        end='2026-10-22', supersedes=[])
    with temporal._db() as db:
        temporal.save(db, [original], NOW, memory.evidence())
    if archived:
        companion = memory.remember('The optics exam needs revision notes.', now=NOW)
        group(memory, first, companion, subject='Optics exam')
    second = memory.remember('My optics exam was postponed.', now=NOW + timedelta(hours=1))
    change = original.model_copy(update={'source': f'owner_episode:{second}',
        'quote': 'My optics exam was postponed.', 'status': 'postponed', 'date_phrase': '',
        'start': None, 'end': None, 'supersedes': list(temporal.evidence())})
    with temporal._db() as db:
        temporal.save(db, [change], NOW + timedelta(hours=1), {**memory.evidence(), **temporal.evidence()})
    return first, second


def test_retrieves_old_original_beyond_recent_100_and_abstains_without_match(memory):
    ident = memory.remember('The spectrometer calibration may need the amber reference sample.', now=NOW)
    noise(memory)
    rows = memory.recall('spectrometer calibration')
    assert rows and rows[0]['id'] == f'owner_episode:{ident}'
    assert rows[0]['noted'] == NOW.isoformat() and 'may need' in rows[0]['text']
    assert memory.recall('volcano eruption') == []
    assert memory.recall('what did I tell you about it') == []
    assert memory.recall('') == []


def test_archived_original_survives_retention_restart_without_ranking_inferred_label(memory):
    first = memory.remember('The terrarium lid may need a narrower rubber seal.', now=NOW)
    second = memory.remember('The terrarium humidity is unstable.', now=NOW)
    group(memory, first, second, subject='Invented teleportation reactor')
    noise(memory, 501)
    restored = BrainMemory(Cognition(memory.store.path))
    rows = restored.recall('terrarium rubber seal')
    assert rows and rows[0]['id'] == f'owner_episode:{first}'
    assert rows[0]['reviewed_threads']
    assert restored.recall('teleportation reactor') == []
    assert all(row['kind'] in {'owner_message', 'owner_answer'} for row in rows)


def test_paired_answer_is_ranked_from_its_original_question(memory):
    ident = memory.remember('Possibly the gasket.', question='Which part of the pressure chamber may be damaged?', now=NOW)
    noise(memory)
    row = memory.recall('pressure chamber')[0]
    assert row['id'] == f'owner_episode:{ident}' and row['text'] == 'Possibly the gasket.'
    assert row['question'] == 'Which part of the pressure chamber may be damaged?'


def test_corrected_episode_is_withheld_entirely_and_latest_original_is_recalled(memory):
    first, second = correct_exam(memory)
    rows = memory.recall('optics exam')
    assert [row['id'] for row in rows] == [f'owner_episode:{second}']
    assert memory.recall('library card') == []  # mixed source is conservatively withheld
    assert first != second


def test_pruned_history_cannot_reenable_a_superseded_original(memory):
    first, _ = correct_exam(memory)
    # Simulate the existing bounded superseded-history retention, without deleting originals.
    with TemporalMemory(memory.store)._db() as db:
        db.execute('DELETE FROM temporal_situations WHERE superseded_by IS NOT NULL')
    assert all(row['id'] != f'owner_episode:{first}' for row in memory.recall('optics exam'))
    assert memory.recall('library card') == []


def test_local_archives_never_enter_telegram_and_voice_can_recall_chat(memory):
    a = memory.remember('Local terrarium gasket note.', channel='chat', now=NOW)
    b = memory.remember('Local terrarium humidity note.', channel='voice', now=NOW)
    group(memory, a, b)
    memory.remember('Telegram terrarium shipping note.', channel='telegram', now=NOW)
    assert {row['channel'] for row in memory.recall('terrarium', channel='telegram')} == {'telegram'}
    assert {row['channel'] for row in memory.recall('terrarium', channel='voice')} == {'chat', 'voice'}


def test_forget_and_disable_remove_recall_without_a_cache(memory, monkeypatch):
    a = memory.remember('Private terrarium gasket note.', now=NOW)
    b = memory.remember('Private terrarium lid note.', now=NOW)
    group(memory, a, b)
    assert memory.recall('terrarium')
    monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    assert memory.recall('terrarium') == []
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    memory.store.clear()
    assert memory.recall('terrarium') == []


def test_whole_record_budget_limits_and_truncation_are_explicit(memory):
    for index in range(12):
        memory.remember('Spectrometer report ' + str(index) + ' uncertain ' * 160, now=NOW)
    rows = memory.recall('spectrometer', limit=100)
    assert 0 < len(rows) <= 8
    assert len(json.dumps(rows, ensure_ascii=False)) <= 4000
    assert all(row['excerpt_truncated'] for row in rows)
    assert memory.recall('spectrometer', limit=0) == []


def test_focused_old_original_reaches_shared_evidence_and_local_context(memory, monkeypatch):
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.workspace import Workspace
    from services.mind import executive, reasoning
    first = memory.remember('The spectrometer calibration may require the amber reference sample.', now=NOW)
    noise(memory)
    work = Workspace(memory.store)
    task = work.start_task('Spectrometer calibration')
    work.focus('task', task)
    for index in range(20):
        memory.remember('Unrelated weather report ' + str(index) + ' observation ' * 150, now=NOW)
    source = ReasoningStore(memory.store)
    known = source.evidence()
    ref = f'owner_episode:{first}'
    assert known[ref]['historical_recall'] is True
    assert ref in executive.ExecutiveControl._build(NOW, known, {}, 'background')['evidence']
    assert source.context(NOW)['historical_recall'][0]['id'] == ref
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    monkeypatch.setattr(reasoning, 'reasoning_store', source)
    assert 'amber reference sample' in reasoning.prompt_section(NOW)
    from services.automation.intent import remote_request
    token = remote_request.set(True)
    try:
        assert 'amber reference sample' not in reasoning.prompt_section(NOW)
    finally:
        remote_request.reset(token)


def test_conversation_rechecks_forgetting_after_async_context_assembly(memory, monkeypatch):
    import asyncio
    from providers.base_provider import ProviderResponse
    from services.mind import brain_memory, language, life_state, temporal_memory
    memory.remember('The spectrometer uses the amber reference sample.', now=NOW)
    monkeypatch.setattr(brain_memory, 'brain_memory', memory)
    monkeypatch.setattr(temporal_memory, 'situation', lambda: {})
    def forget_during_context():
        memory.store.clear()
        return {}
    monkeypatch.setattr(life_state, 'current', forget_during_context)
    calls = []
    async def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return ProviderResponse(content='No retained source is available.', provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    asyncio.run(language.answer('spectrometer amber reference', 'ollama', [], 100))
    assert len(calls) == 1
    assert 'amber reference sample' not in calls[0][0][2]


def test_conversation_does_not_wait_for_cold_recall(memory, monkeypatch):
    import asyncio
    from providers.base_provider import ProviderResponse
    from services.mind import brain_memory, language, life_state, temporal_memory
    monkeypatch.setattr(brain_memory, 'brain_memory', memory)
    monkeypatch.setattr(language, 'RECALL_WAIT_SECONDS', .001)
    monkeypatch.setattr(temporal_memory, 'situation', lambda: {})
    monkeypatch.setattr(life_state, 'current', lambda: {'priorities': 'still supplied'})
    original_thread = asyncio.to_thread
    cancelled = []
    async def thread(function, *args, **kwargs):
        if function == memory.recall:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        return await original_thread(function, *args, **kwargs)
    monkeypatch.setattr(asyncio, 'to_thread', thread)
    prompts = []
    async def complete(*args, **kwargs):
        prompts.append(args[2])
        return ProviderResponse(content='Reply remains available.', provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(language.answer('reworded report', 'ollama', [], 100))
    assert result.content == 'Reply remains available.'
    assert cancelled == [True] and 'still supplied' in prompts[0]


def test_revalidation_excludes_newly_corrected_and_changed_originals(memory):
    first, _ = correct_exam(memory)
    old = memory.evidence()[f'owner_episode:{first}']
    assert memory.valid_recall([old]) == []
    rows = memory.recall('optics exam')
    with memory._db() as db:
        db.execute("UPDATE owner_episodes SET text='Altered report' WHERE id=?", (int(rows[0]['id'].split(':')[1]),))
    assert memory.valid_recall(rows) == []


def test_current_turn_is_not_recalled_as_its_own_support(memory):
    from services.mind.cognition import _turn
    memory.remember('Spectrometer calibration query?', source='active-turn', now=NOW)
    token = _turn.set('active-turn')
    try:
        assert memory.recall('spectrometer calibration') == []
    finally:
        _turn.reset(token)


def test_historical_retrieval_cannot_create_a_new_commitment(memory, monkeypatch):
    from services.mind.reasoning import cognitive_schema
    ref = memory.remember('My spectroscopy exam is tomorrow.', now=NOW)
    known = memory.evidence()
    ident = f'owner_episode:{ref}'
    known[ident]['historical_recall'] = True
    assert 'situations' not in {branch['properties']['work_kind']['const'] for branch in cognitive_schema(known)['oneOf']}
    value = TemporalUpdate(source=ident, quote='My spectroscopy exam is tomorrow.', subject='spectroscopy exam',
        status='planned', date_phrase='tomorrow', start='2026-10-22', end='2026-10-22', supersedes=[])
    with pytest.raises(ValueError):
        TemporalMemory.validate([value], known)


def test_current_turn_cannot_reenter_through_an_archived_snapshot(memory):
    from services.mind.cognition import _turn
    first = memory.remember('Spectrometer calibration query?', source='active-turn', now=NOW)
    second = memory.remember('Spectrometer calibration may need a new reference sample.', now=NOW)
    group(memory, first, second, subject='Calibration')
    token = _turn.set('active-turn')
    try:
        assert [row['id'] for row in memory.recall('spectrometer calibration')] == [f'owner_episode:{second}']
    finally:
        _turn.reset(token)


def test_archived_correction_survives_raw_pruning_and_restart(memory):
    first, second = correct_exam(memory, archived=True)
    noise(memory, 501)
    restored = BrainMemory(Cognition(memory.store.path))
    rows = restored.recall('optics exam')
    assert f'owner_episode:{first}' not in {row['id'] for row in rows}
    assert f'owner_episode:{second}' in {row['id'] for row in rows}
    assert restored.recall('library card') == []


def test_legacy_migration_backfills_retained_correction_exclusions(memory):
    first, _ = correct_exam(memory)
    with memory._db() as db:
        db.execute('ALTER TABLE owner_episodes RENAME TO legacy_episodes')
        db.execute('''CREATE TABLE owner_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT UNIQUE NOT NULL,
            channel TEXT NOT NULL, question TEXT NOT NULL, text TEXT NOT NULL, noted TEXT NOT NULL)''')
        db.execute('INSERT INTO owner_episodes SELECT id,source_key,channel,question,text,noted FROM legacy_episodes')
        db.execute('DROP TABLE legacy_episodes')
    restored = BrainMemory(Cognition(memory.store.path))
    assert restored.recall('library card') == []
    with restored._db() as db:
        assert db.execute('SELECT recall_withheld FROM owner_episodes WHERE id=?', (first,)).fetchone()[0] == 1


def test_provenance_read_failure_never_falls_back_to_recent_dialogue(memory, monkeypatch):
    import sqlite3
    from services.mind import recall
    memory.remember('Private spectrometer report.', now=NOW)
    def unavailable(*args):
        raise sqlite3.OperationalError('Synthetic database unavailable')
    monkeypatch.setattr(recall, '_pool', unavailable)
    assert memory.recall('spectrometer') == []


def test_executive_can_cite_old_retrieved_original_without_promoting_it_to_a_fact(memory, monkeypatch):
    import asyncio
    from providers.base_provider import ProviderResponse
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.workspace import Workspace
    first = memory.remember('The spectrometer calibration may require the amber reference sample.', now=NOW)
    noise(memory)
    work = Workspace(memory.store)
    task = work.start_task('Spectrometer calibration')
    work.focus('task', task)
    source = ReasoningStore(memory.store)
    for flag in ('REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED', 'AI_ASSIST_ONLY'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr(reasoning, 'cognition', memory.store)
    monkeypatch.setattr(reasoning, 'reasoning_store', source)
    monkeypatch.setattr(executive, 'attention_state', lambda: {'activity': 'idle'})
    calls = []
    ref = f'owner_episode:{first}'
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        calls.append(payload)
        if 'check_items' in payload:
            data = {'checks': [{'id': 0, 'supported': True, 'reason': 'Historical report supports reviewing the sample.'}]}
        else:
            assert payload['evidence'][ref]['historical_recall']
            data = {'work_kind': 'conclusions', 'item': {'kind': 'proposal',
                'text': 'Review the historically reported reference sample before calibrating.',
                'evidence': [ref, f'task:{task}'], 'confidence': .7, 'start': None, 'end': None,
                'effect': {'type': 'guidance'}}}
        return ProviderResponse(content=json.dumps(data), provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(executive.ExecutiveControl(memory.store).review(NOW))['status'] == 'completed'
    assert len(calls) == 2 and not source.facts()
    assert source.conclusions(NOW)[0]['evidence'] == [ref, f'task:{task}']
    memory.store.clear()
    assert not source.conclusions(NOW)


def test_pruned_correction_provenance_cannot_be_rearchived_as_an_uncorrected_source(memory):
    first, second = correct_exam(memory)
    with TemporalMemory(memory.store)._db() as db:
        db.execute('DELETE FROM temporal_situations WHERE superseded_by IS NOT NULL')
    with pytest.raises(ValueError):
        group(memory, first, second, subject='Optics exam')
    assert not Consolidation(memory.store).source_evidence()
    noise(memory, 501)
    assert memory.recall('library card') == []
