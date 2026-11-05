from datetime import datetime, timedelta

from core.config import config
from services.mind.cognition import Cognition
from services.mind.reasoning_store import ReasoningStore


def test_short_answer_retains_question_provenance_and_original_time(tmp_path):
    from services.mind.brain_memory import BrainMemory
    store = Cognition(tmp_path / 'brain.db')
    memory = BrainMemory(store)
    when = datetime(2026, 10, 20, 14)
    ident = memory.remember('pizza', question='What food do you like?', channel='chat', source='turn-one', now=when)
    assert memory.remember('pizza', question='What food do you like?', channel='chat', source='turn-one', now=when) == ident
    rows = memory.recall('food', channel='chat', now=when + timedelta(days=1))
    assert len(rows) == 1 and rows[0]['question'] == 'What food do you like?'
    assert rows[0]['text'] == 'pizza' and rows[0]['noted'] == when.isoformat()
    assert rows[0]['source'] == 'owner_report'
    evidence = ReasoningStore(store).evidence()
    assert evidence[f'owner_episode:{ident}']['kind'] == 'owner_answer'


def test_episode_recall_keeps_telegram_separate_and_redacts_credentials(tmp_path, monkeypatch):
    from services.mind.brain_memory import BrainMemory
    memory = BrainMemory(Cognition(tmp_path / 'brain.db'))
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'private-credential')
    memory.remember('My local note private-credential', channel='chat', source='local')
    memory.remember('My remote note', channel='telegram', source='remote')
    assert 'private-credential' not in str(memory.evidence())
    remote = memory.recall('note', channel='telegram')
    assert len(remote) == 1 and remote[0]['text'] == 'My remote note'


def test_forgetting_clears_dialogue_derived_memory(tmp_path):
    from services.mind.brain_memory import BrainMemory
    store = Cognition(tmp_path / 'brain.db')
    memory = BrainMemory(store)
    memory.remember('A private preference', channel='chat', source='one')
    store.clear()
    assert not memory.evidence()


def test_owner_answer_is_reconsidered_by_local_executive_reasoning(tmp_path, monkeypatch):
    import asyncio
    import json
    from services.mind import executive as module, reasoning
    from services.mind.brain_memory import BrainMemory
    from providers.base_provider import ProviderResponse
    store = Cognition(tmp_path / 'brain.db')
    local = module.ExecutiveControl(store)
    when = datetime(2026, 10, 20, 15)
    ident = BrainMemory(store).remember('I need my teammate review notes', question='What is blocking the report?',
                                        source='answer-one', channel='chat', now=when)
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(module, 'attention_state', lambda: {'activity': 'coding', 'away': False})
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(store))
    payloads = []
    async def complete(*args, **kwargs):
        payloads.append(json.loads(args[1][0].content))
        if len(payloads) == 1:
            result = {'facts': [], 'conclusions': [{'kind': 'implication',
                'text': 'The owner reports needing teammate review notes before proceeding.',
                'evidence': [f'owner_episode:{ident}'], 'confidence': .9, 'start': None, 'end': None,
                'effect': {'type': 'guidance'}}], 'questions': []}
        else:
            result = {'checks': [{'id': 0, 'supported': True, 'reason': 'The paired owner answer explicitly says so.'}]}
        return ProviderResponse(content=json.dumps(result), provider='ollama', model='local')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    result = asyncio.run(local.review(when))
    assert result['status'] == 'completed'
    assert any(f'owner_episode:{ident}' in payload.get('evidence', {}) for payload in payloads)
    assert not ReasoningStore(store).facts()  # an interpretation is not promoted into a new owner quote
    assert ReasoningStore(store).context(when)['conclusions']


def test_shared_reasoning_reads_actual_integration_state(tmp_path, monkeypatch):
    from services.spotify import auth
    from services.mind.cognition_context import operational_state
    monkeypatch.setattr(auth, 'is_connected', lambda: True)
    current = operational_state()
    assert current['spotify_login_saved'] is True
    known = ReasoningStore(Cognition(tmp_path / 'brain.db')).evidence()
    assert known['runtime:current']['spotify_login_saved'] is True
