"""Brain liveness and durable diagnostics, independent of raw observations."""

import asyncio
from datetime import datetime, timedelta
import json

import pytest

from core.config import config
from services.mind import cognitive_runtime, review_metrics
from services.mind.cognition import Cognition
from services.mind.cognitive_health import CognitiveHealth, HISTORY_LIMIT, sanitized


def test_startup_failure_never_reports_a_live_attention_task(monkeypatch):
    from services.mind import evening

    def fail():
        raise OSError("private startup detail")

    monkeypatch.setattr(evening, "stop", fail)

    async def scenario():
        try:
            task = asyncio.create_task(cognitive_runtime.run())
            await asyncio.gather(task, return_exceptions=True)
            assert not cognitive_runtime.running()
        finally:
            cognitive_runtime._loop = cognitive_runtime._wake = None

    asyncio.run(scenario())
    from services.mind.cognitive_health import health
    assert health.latest('attention')['reason'] == 'startup_failed'
    assert 'private startup detail' not in json.dumps(health.history())


def test_review_diagnostics_survive_event_retention(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COGNITION_MAX_EVENTS", 3)
    store = Cognition(tmp_path / "cognition.db")
    trace = review_metrics.ReviewTrace(store)
    trace.state, trace.reason = "completed", "silence"
    trace.record()
    for index in range(6):
        store.record("observation", "activity", "Activity observation")
    latest = review_metrics.latest(store)
    assert latest is not None and latest["state"] == "completed"
    assert latest["reason"] == "silence"


def test_actual_live_task_completes_a_review_then_stops_cleanly(monkeypatch):
    from services.mind import evening
    from services.mind.executive import executive
    from services.mind.cognitive_health import health
    monkeypatch.setattr(evening, 'stop', lambda: None)
    monkeypatch.setattr(cognitive_runtime, 'available', lambda: True)
    checked = asyncio.Event()

    async def review(*args, **kwargs):
        checked.set()
        return {'status': 'completed'}

    monkeypatch.setattr(executive, 'review', review)

    async def scenario():
        task = asyncio.create_task(cognitive_runtime.run())
        await asyncio.wait_for(checked.wait(), 2)
        assert cognitive_runtime.running()
        for _ in range(100):
            if any(row['state'] == 'completed' for row in health.history()):
                break
            await asyncio.sleep(.005)
        assert any(row['state'] == 'completed' for row in health.history())
        assert not any(row['reason'] == 'check_failed' for row in health.history())
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not cognitive_runtime.running()

    asyncio.run(scenario())
    assert health.latest('attention')['reason'] == 'cancelled'


def test_running_receipt_from_prior_runtime_is_interrupted(tmp_path):
    store = Cognition(tmp_path / 'state.db')
    review_metrics.ReviewTrace(store)
    restored = Cognition(store.path)
    result = review_metrics.latest(restored)
    assert result['state'] == 'interrupted' and result['elapsed_ms'] is None
    assert not result['current_runtime']


def test_forgetting_prevents_a_late_trace_from_restoring_diagnostics(tmp_path):
    store = Cognition(tmp_path / 'state.db')
    trace = review_metrics.ReviewTrace(store)
    store.clear()
    trace.state, trace.reason = 'completed', 'accepted'
    trace.record()
    assert review_metrics.latest(store) is None
    assert CognitiveHealth(store).history() == []


def test_metadata_allowlist_excludes_source_payloads_and_malformed_fields():
    data = {'phase': ['private'], 'reason': 'private text', 'elapsed_ms': float('nan'),
            'prompt': 'OWNER SECRET', 'owner_episode': 'PRIVATE SOURCE', 'startup': {'url': 'private URL'},
            'calls': [{'phase': 'generation', 'prompt_chars': 10, 'raw_reply': 'SECRET',
                       'done_reason': ['SECRET'], 'eval_count': 10 ** 500}],
            'accepted': {'memories': 1, 'secret': 'SECRET'}, 'blocks': ['call', 'owner secret']}
    result = sanitized(data)
    encoded = json.dumps(result)
    assert 'SECRET' not in encoded and 'private' not in encoded.lower()
    assert result['reason'] == 'unavailable'
    assert result['accepted'] == {'memories': 1} and result['blocks'] == ['call']
    assert result['calls'] == [{'phase': 'generation', 'prompt_chars': 10}]


def test_health_history_is_bounded_and_survives_observation_eviction(tmp_path):
    store = Cognition(tmp_path / 'state.db')
    health = CognitiveHealth(store)
    for index in range(HISTORY_LIMIT + 5):
        health.record('attention', 'waiting', 'typing' if index % 2 else 'call')
    with health._db() as db:
        assert db.execute('SELECT COUNT(*) FROM cognitive_health_history').fetchone()[0] == HISTORY_LIMIT
    for _ in range(3):
        store.record('observation', 'system', 'observation')
    assert health.latest('attention')['reason'] == 'call'


def test_disabled_cognition_exposes_no_previous_health(tmp_path, monkeypatch):
    health = CognitiveHealth(Cognition(tmp_path / 'state.db'))
    assert health.record('attention', 'waiting', 'typing')
    monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    assert health.latest('attention') is None and health.history() == []
    assert not health.record('attention', 'waiting', 'ready')


@pytest.mark.parametrize('blocked,reason', [(True, 'call'), (False, None)])
def test_life_gate_reason_is_preserved_without_allowing_review(monkeypatch, blocked, reason):
    from services.mind import cognition_context, life_state
    from services.proactive import watcher
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    monkeypatch.setattr('services.activity.log.idle_seconds', lambda: 10)
    monkeypatch.setattr(watcher, 'is_busy', lambda: False)
    monkeypatch.setattr(cognition_context, 'live_state', lambda: {'state': 'ready'})
    monkeypatch.setattr(life_state, 'current', lambda **kw: {'can_review': not blocked, 'review_blocks': [reason] if blocked else []})
    assert cognitive_runtime.available() is (not blocked)
    assert cognitive_runtime._last_blocks == ([reason] if blocked else [])


def test_executive_claim_gates_are_explained_without_spending_attempts(monkeypatch):
    from services.mind.cognition import cognition
    from services.mind.executive import ExecutiveControl, HOURLY_LIMIT
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    control = ExecutiveControl(cognition)
    now = datetime(2026, 11, 5, 12)
    assert control.wait_reason(now) == 'nothing_pending'
    with control._db() as db:
        db.execute('INSERT INTO executive_attempts(started) VALUES(?)', (now.timestamp(),))
    assert control.wait_reason(now + timedelta(seconds=1)) == 'minimum_gap'
    with control._db() as db:
        for _ in range(HOURLY_LIMIT - 1):
            db.execute('INSERT INTO executive_attempts(started) VALUES(?)', (now.timestamp(),))
    assert control.wait_reason(now) == 'hourly_limit'
    with control._db() as db:
        assert db.execute('SELECT COUNT(*) FROM executive_attempts').fetchone()[0] == HOURLY_LIMIT


def test_local_health_api_is_explicitly_denied_to_nonlocal_clients():
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    local = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    result = local.get('/api/v1/mind/health')
    assert result.status_code == 200 and 'attention' in result.json()
    remote = TestClient(create_app(), base_url='http://127.0.0.1:8000', client=('192.0.2.5', 50000))
    assert remote.get('/api/v1/mind/health').status_code == 403
