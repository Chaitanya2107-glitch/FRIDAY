"""Audit regressions for races at model/context boundaries."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from providers.base_provider import ProviderResponse
from services.mind.brain_memory import BrainMemory
from services.mind.cognition import Cognition
from services.mind.temporal_memory import TemporalMemory, TemporalUpdate


@pytest.mark.parametrize('change', ['none', 'forget', 'revision', 'disable', 'guard_failure'])
def test_dialogue_handoff_rechecks_whole_brain_context(tmp_path, monkeypatch, change):
    from services.mind import brain_memory, executive, language, life_state, temporal_memory
    from core.config import config
    now = datetime(2026, 10, 21, 12)
    memory = BrainMemory(Cognition(tmp_path / 'audit.db'))
    ident = memory.remember('My confidential dental appointment is tomorrow.', now=now)
    temporal = TemporalMemory(memory.store)
    known = memory.evidence()
    item = TemporalUpdate(source=f'owner_episode:{ident}',
        quote='My confidential dental appointment is tomorrow.', subject='dental appointment',
        status='planned', date_phrase='tomorrow', start='2026-10-22', end='2026-10-22', supersedes=[])
    with temporal._db() as db:
        temporal.save(db, [item], now, known)
    monkeypatch.setattr(brain_memory, 'brain_memory', memory)
    monkeypatch.setattr(temporal_memory, 'temporal_memory', temporal)
    monkeypatch.setattr('services.mind.cognition_context.operational_state', lambda: {})
    def during_context():
        if change == 'forget':
            memory.store.clear()
        elif change == 'revision':
            ident = memory.remember('My dental appointment was cancelled.', now=datetime(2026, 10, 21, 13))
            value = item.model_copy(update={'source': f'owner_episode:{ident}',
                'quote': 'My dental appointment was cancelled.', 'status': 'cancelled',
                'date_phrase': '', 'start': None, 'end': None, 'supersedes': list(temporal.evidence())})
            with temporal._db() as db:
                temporal.save(db, [value], now, {**memory.evidence(), **temporal.evidence()})
        elif change == 'disable':
            monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
        elif change == 'guard_failure':
            def unavailable(self):
                raise OSError('Synthetic version read failure')
            monkeypatch.setattr(executive.ExecutiveControl, 'context_version', unavailable)
        return {}
    monkeypatch.setattr(life_state, 'current', during_context)
    prompts = []
    async def complete(*args, **kwargs):
        prompts.append(args[2])
        return ProviderResponse(content='A response.', provider='ollama', model='synthetic')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    asyncio.run(language.answer('hello', 'ollama', [], 100))
    assert prompts and ('confidential dental' in prompts[0]) == (change == 'none')


def test_expired_recall_deadline_does_not_infer_after_cold_load(monkeypatch):
    from services.files import embed
    actual_encode = embed.encode_local.__wrapped__
    clock, calls = [0.], []
    monkeypatch.setattr(embed.time, 'monotonic', lambda: clock[0])
    def load(**kwargs):
        clock[0] = 5.
        return SimpleNamespace(encode=lambda *a, **kw: calls.append(a) or np.zeros((1, 384)))
    monkeypatch.setattr(embed, '_load', load)
    with pytest.raises(RuntimeError):
        actual_encode(['synthetic audit'], deadline=2.)
    assert not calls


def test_expired_deadline_between_recall_batches_discards_partial_vectors(monkeypatch):
    from services.files import embed
    actual_encode = embed.encode_local.__wrapped__
    clock, calls = [0.], []
    monkeypatch.setattr(embed.time, 'monotonic', lambda: clock[0])
    def encode(texts, **kwargs):
        calls.append(len(texts))
        clock[0] = 5.
        return np.zeros((len(texts), 384))
    monkeypatch.setattr(embed, '_load', lambda **kw: SimpleNamespace(encode=encode))
    with pytest.raises(RuntimeError):
        actual_encode(['audit'] * (embed.BATCH_SIZE + 1), deadline=2.)
    assert calls == [embed.BATCH_SIZE]
