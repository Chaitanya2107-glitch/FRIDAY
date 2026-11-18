import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from services.mind import care, coaching_runtime as runtime, goals
from services.presence import delivery, engine, phone
from tests.test_care import NOW, definition, observed


@pytest.fixture
def runtime_inputs(monkeypatch):
    from services import schedule_adapter
    from services.presence import runtime as presence
    monkeypatch.setattr(runtime, 'available', lambda: True)
    monkeypatch.setattr(runtime.coaching_metrics, 'snapshot', lambda *a: observed())
    monkeypatch.setattr(goals, 'weekly_candidates', lambda *a: [])
    monkeypatch.setattr(schedule_adapter, 'classes_on', lambda *a: [])
    monkeypatch.setattr(presence, 'situation', lambda *a: 'study')
    monkeypatch.setattr(engine, 'current', lambda *a: dict(state='at_desk', device=None))


def test_runtime_without_confirmation_does_not_collect_or_submit(runtime_inputs, monkeypatch):
    monkeypatch.setattr(runtime.coaching_metrics, 'snapshot', lambda *a: pytest.fail('Off means no care snapshot'))

    async def unexpected(*a, **k):
        pytest.fail('Unconfirmed care submitted a nudge')

    assert asyncio.run(runtime.tick(NOW, submit=unexpected)) == []


def test_quiet_rejection_does_not_claim_a_private_notice(runtime_inputs, monkeypatch):
    care.store().confirm(definition('breaks'), NOW - timedelta(hours=2))
    monkeypatch.setattr(delivery, 'eligible', lambda *a: False)
    assert asyncio.run(runtime.tick(NOW)) == []
    with care.store().db() as db:
        assert db.execute('SELECT COUNT(*) FROM care_notices').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM care_counts').fetchone()[0] == 0


def test_phone_detail_is_only_in_private_view_and_daily_slot_does_not_repeat(runtime_inputs, monkeypatch):
    care.store().confirm(definition('phone_use'), NOW - timedelta(hours=2))
    submitted, sent = [], []
    monkeypatch.setattr(phone, 'send', lambda *a, **k: sent.append((a, k)))

    async def review(text, kind, now, **kwargs):
        submitted.append((text, kind))
        return kwargs['on_send']()

    assert asyncio.run(runtime.tick(NOW, submit=review)) == ['phone_use']
    assert asyncio.run(runtime.tick(NOW, submit=review)) == []
    assert len(sent) == 1 and all('phone_use' not in text and 'entertainment' not in text for text, _ in submitted)
    assert 'entertainment' not in str(sent) and 'approved.package' not in str(sent)
    question = care.phone_question(NOW)
    assert question['pending'] and 'entertainment' in question['text']
    assert care.store().settings('phone_use')['trust']['level'] == 'ask'


def test_delivery_rechecks_window_after_budget_wait(runtime_inputs, monkeypatch):
    care.store().confirm(definition('breaks', window=['10:00', '10:31']), NOW - timedelta(hours=2))
    ticks = iter((0, 120))
    monkeypatch.setattr(runtime, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))

    async def review(text, kind, now, **kwargs):
        return kwargs['on_send']()

    assert asyncio.run(runtime.tick(NOW, submit=review)) == []
    with care.store().db() as db:
        assert db.execute('SELECT COUNT(*) FROM care_notices').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['care_question', 'goal_question'])
def test_coaching_uses_existing_three_question_budget(kind, tmp_path, monkeypatch):
    from core.config import config
    from services.mind import executive as executive_module, inquiry as inquiry_module, training
    from services.mind.cognition import Cognition
    from services.mind.executive import ExecutiveControl
    from services.mind.inquiry import Inquiry
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    control, questions = ExecutiveControl(Cognition(tmp_path / 'review.db')), Inquiry(Cognition(tmp_path / 'questions.db'))
    monkeypatch.setattr(executive_module, 'executive', control)
    monkeypatch.setattr(inquiry_module, 'inquiry', questions)
    monkeypatch.setattr(delivery, 'eligible', lambda *a: True)
    monkeypatch.setattr(training, 'allows_nudge', lambda *a, **k: True)
    for index in range(4):
        assert asyncio.run(delivery.submit('A private owner-confirmed check is ready.', kind,
            NOW + timedelta(minutes=45 * index), key=str(index), on_send=lambda: True)) is (index < 3)
    assert questions.status(NOW + timedelta(hours=3))['automatic_questions_today'] == 3
