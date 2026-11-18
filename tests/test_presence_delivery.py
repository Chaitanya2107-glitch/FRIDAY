from datetime import datetime, timedelta
import asyncio

from services.presence import anticipation, delivery
from services.mind.executive import ExecutiveControl
from services.mind.cognition import Cognition


def test_local_review_shares_executive_budget_without_model(tmp_path, monkeypatch):
    from core.config import config
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', False)
    store = Cognition(tmp_path / 'brain.db')
    control = ExecutiveControl(store)
    now = datetime(2026, 11, 16, 10)
    assert control.reserve_local('first', 'presence_rule', now)
    assert control.reserve_local('other', 'presence_rule', now + timedelta(seconds=1)) is None
    for i in range(1, 4):
        assert control.reserve_local(str(i), 'presence_rule', now + timedelta(minutes=5 * i))
    assert control.reserve_local('fifth', 'presence_rule', now + timedelta(minutes=25)) is None
    assert control.reserve_local('evil', 'arbitrary_shell', now + timedelta(hours=2)) is None
    control.set_enabled(False)
    assert control.reserve_local('sixth', 'presence_rule', now + timedelta(hours=2)) is None


def test_anticipation_uses_confirmed_estimates_and_reasons():
    now = datetime(2026, 11, 16, 8, 20)
    presence = {'state': 'at_home', 'confidence': .8}
    commute = dict(seconds=1800, samples=4, confirmed=True)
    rows = anticipation.candidates(now, presence, classes=[{'start': '09:00', 'end': '10:00'}], commute=commute)
    assert len(rows) == 1 and '10 minutes' in rows[0]['text'] and 'Reason:' in rows[0]['text']
    assert not anticipation.candidates(now, presence, classes=[{'start': '09:00', 'end': '10:00'}], commute=dict(commute, confirmed=False))
    assert not anticipation.candidates(now, {'state': 'in_class', 'confidence': .9}, commute=commute)


def test_deadline_and_study_never_assert_unconfirmed_habits():
    now = datetime(2026, 11, 16, 19)
    presence = dict(state='at_home', confidence=.8)
    due = [{'what': 'Lab record', 'due': '2026-11-17T09:00', 'done': False}]
    assert 'no timed plan is recorded' in anticipation.candidates(now, presence, deadlines=due)[0]['text']
    assert not anticipation.candidates(now, presence, deadlines=due, planned=True)
    assert not anticipation.candidates(now, presence, study=dict(minute=1140, confirmed=False))
    assert anticipation.candidates(now, presence, study=dict(minute=1140, confirmed=True))


def test_quiet_hours_and_nudges_off_override_local_candidates(monkeypatch):
    from services.proactive import watcher
    from services.mind import talk
    monkeypatch.setattr(watcher, 'nudges_active', lambda stamp: False)
    assert not delivery.eligible(datetime(2026, 11, 16, 12), urgent=True)
    monkeypatch.setattr(watcher, 'nudges_active', lambda stamp: True)
    monkeypatch.setattr(talk, 'load', lambda: {'on': True, 'quiet_hours': {'start': '23:00', 'end': '07:00'}})
    assert not delivery.eligible(datetime(2026, 11, 16, 23))


def test_rejected_candidate_cannot_execute_callback(monkeypatch):
    monkeypatch.setattr(delivery, 'eligible', lambda *a: False)
    called = []
    result = asyncio.run(delivery.submit('Start class mode?', 'presence_question', datetime(2026, 11, 16, 10),
                                        on_send=lambda: called.append(True)))
    assert not result and not called


def test_trusted_rule_can_run_away_but_cannot_bypass_quiet_or_active_exchange(monkeypatch):
    from services.proactive import watcher
    from services.mind import talk, life_state
    from services import quiet_mode
    from services.presence import engine
    monkeypatch.setattr(watcher, 'nudges_active', lambda stamp: True)
    monkeypatch.setattr(watcher, 'is_busy', lambda: False)
    monkeypatch.setattr(talk, 'load', lambda: {'on': True})
    monkeypatch.setattr(quiet_mode, 'suppresses', lambda: False)
    monkeypatch.setattr(engine, 'current', lambda now: dict(state='at_college_free', device='phone', data_available=True))
    blocks = ['owner_away', 'phone_attention']
    monkeypatch.setattr(life_state, 'current', lambda now: dict(can_initiate=False, interruption_blocks=blocks))
    now = datetime(2026, 11, 16, 12)
    assert delivery.eligible(now, kind='presence_rule')
    assert not delivery.eligible(now, kind='presence_question')
    blocks.append('pending_reply')
    assert not delivery.eligible(now, kind='presence_rule')
    blocks.pop()
    monkeypatch.setattr(quiet_mode, 'suppresses', lambda: True)
    assert not delivery.eligible(now, kind='presence_rule')


def test_question_ladder_uses_the_existing_three_a_day_budget_without_llm(tmp_path, monkeypatch):
    from core.config import config
    from services.mind import executive as executive_module, inquiry as inquiry_module
    from services.mind.inquiry import Inquiry
    from services.mind import training
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', False)
    control = ExecutiveControl(Cognition(tmp_path / 'review.db'))
    inquiry = Inquiry(Cognition(tmp_path / 'questions.db'))
    monkeypatch.setattr(executive_module, 'executive', control)
    monkeypatch.setattr(inquiry_module, 'inquiry', inquiry)
    monkeypatch.setattr(delivery, 'eligible', lambda *args: True)
    monkeypatch.setattr(training, 'allows_nudge', lambda *args, **kwargs: True)
    now = datetime(2026, 11, 16, 10)
    called = []
    for index in range(4):
        allowed = asyncio.run(delivery.submit('Start a reviewed rule?', 'presence_question',
                    now + timedelta(minutes=45 * index), key=str(index), on_send=lambda: called.append(True) or True))
        assert allowed is (index < 3)
    assert len(called) == 3 and inquiry.status(now + timedelta(hours=3))['automatic_questions_today'] == 3
