from datetime import datetime, timedelta

import pytest

from services.activity import attention, log
from services.mind import state, talk, temporal_memory, thoughts
from services.presence import engine
from services.reminders.service import Reminder, reminders


NOW = datetime(2026, 11, 18, 13, 0)


def test_snapshot_samples_once_and_is_deeply_immutable(monkeypatch):
    samples = []

    def idle():
        samples.append('idle')
        return 12

    def present(now, *, laptop_idle):
        samples.append(('presence', now, laptop_idle))
        return {'state': 'at_desk', 'confidence': .9}

    def attending(now, *, laptop_idle, publish):
        samples.append(('attention', now, laptop_idle, publish))
        return {'attention': 'laptop', 'confidence': .9, 'data_available': True}

    monkeypatch.setattr(log, 'idle_seconds', idle)
    monkeypatch.setattr(engine, 'current', present)
    monkeypatch.setattr(attention, 'where_is_attention', attending)
    monkeypatch.setattr(talk, 'load', lambda: {'on': False})
    monkeypatch.setattr(reminders, 'pending', lambda: [Reminder(7, 'Water the plant', (NOW + timedelta(minutes=5)).timestamp())])
    thoughts.add('new', 'editor', {'noticed': 'A new editor', 'details': {'apps': ['editor']}}, .8, NOW)

    first = state.snapshot(NOW)
    assert state.snapshot(NOW + timedelta(seconds=1)) is first
    assert samples == ['idle', ('presence', NOW, 12), ('attention', NOW, 12, False)]
    assert first['idle'] == 12 and first['live']['idle_band'] == 'present'
    assert first['life_state']['phone_attention'] == {
        key: first['attention'][key] for key in ('attention', 'confidence')
    }
    assert first['posture'] == first['life_state']['posture'] == 'quiet'
    assert first['quiet']
    assert first['due_next']['kind'] == 'reminder' and first['due_next']['title'] == 'Water the plant'
    assert first['strongest_thought']['subject'] == 'editor'
    assert first.keys() == state.explain().keys()
    with pytest.raises(TypeError):
        first['posture'] = 'different'
    with pytest.raises(TypeError):
        first['strongest_thought']['data']['details']['apps'][0] = 'changed'
    copy = state.as_json(first)
    copy['strongest_thought']['data']['details']['apps'].append('changed')
    assert first['strongest_thought']['data']['details']['apps'] == ('editor',)
    assert state.snapshot(NOW + timedelta(seconds=4)) is not first


def test_snapshot_refuses_a_cached_private_situation_after_forgetting(monkeypatch):
    from services.mind.cognition import cognition

    known = {'subject': 'exam', 'start': '2026-11-20'}
    monkeypatch.setattr(temporal_memory, 'situation', lambda _: {'upcoming': [known] if known else []})
    first = state.snapshot(NOW)
    assert first['situation']['upcoming'][0]['subject'] == 'exam'
    known.clear()
    cognition.record('owner_episode', 'chat', 'private disposable report')
    cognition.clear()
    current = state.snapshot(NOW + timedelta(seconds=1))
    assert current['situation']['upcoming'] == ()
    assert current is not first
