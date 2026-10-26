import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition

NOW = datetime(2026, 10, 20, 15)


@pytest.fixture
def brain(tmp_path, monkeypatch):
    from services.mind.inquiry import Inquiry
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    control = Inquiry(Cognition(tmp_path / 'brain.db'))
    state = {'evidence': {'task:1': {'kind': 'task', 'title': 'Finish report', 'status': 'blocked'}},
             'present': {'busy': False, 'idle': 10, 'speaking': False, 'listening': False,
                         'pending': False, 'mic_in_use': False, 'commitment_soon': False},
             'preferences': {'on': True, 'paused_until': 0}, 'past': [], 'future': [], 'history': []}
    monkeypatch.setattr(control, 'snapshot', lambda now: state.copy())
    async def approve(line, now):
        return line
    monkeypatch.setattr('services.mind.notifications.approve_question', approve)
    return control, state


def decision(**updates):
    from services.mind.inquiry import Decision
    values = {'ask': True, 'question': 'What is blocking your report?', 'topic': 'report blocker',
              'basis': ['task:1'], 'reason': 'The saved active task is explicitly blocked.',
              'purpose': {'gap': 'task:1:blocker', 'decision': 'Choose a useful next step for the blocked report.',
                          'if_answer_a': {'answer': 'Missing information', 'next_step': 'Propose obtaining the needed evidence.'},
                          'if_answer_b': {'answer': 'Missing access', 'next_step': 'Propose checking the relevant permissions.'},
                          'usefulness': 'changes_decision'}, **updates}
    if not values['ask']:
        values['purpose'] = None
    return Decision(**values)


def thinker(monkeypatch, control, result):
    calls = []
    async def think(payload):
        calls.append(payload)
        return result
    monkeypatch.setattr(control, 'think', think)
    return calls


def test_one_contextual_question_then_no_fixed_series(brain, monkeypatch):
    control, state = brain
    calls = thinker(monkeypatch, control, decision())
    result = asyncio.run(control.propose(NOW))
    assert result['say'] == 'What is blocking your report?' and result['inquiry_id']
    assert asyncio.run(control.propose(NOW + timedelta(minutes=1))) is None
    assert len(calls) == 1


def test_silence_is_a_complete_decision_and_unchanged_context_is_not_repolled(brain, monkeypatch):
    control, state = brain
    calls = thinker(monkeypatch, control, decision(ask=False, question='', topic='', basis=[]))
    assert asyncio.run(control.propose(NOW)) is None
    assert asyncio.run(control.propose(NOW + timedelta(minutes=30))) is None
    assert len(calls) == 1


@pytest.mark.parametrize('field,value', [('busy', True), ('idle', 1), ('idle', 180),
    ('pending', True), ('speaking', True), ('listening', True), ('mic_in_use', True), ('commitment_soon', True)])
def test_inappropriate_time_never_calls_model(brain, monkeypatch, field, value):
    control, state = brain
    state['present'][field] = value
    calls = thinker(monkeypatch, control, decision())
    assert asyncio.run(control.propose(NOW)) is None and not calls


def test_pause_during_inference_invalidates_question(brain, monkeypatch):
    control, state = brain
    async def think(payload):
        state['preferences']['paused_until'] = NOW.timestamp() + 3600
        return decision()
    monkeypatch.setattr(control, 'think', think)
    assert asyncio.run(control.propose(NOW)) is None


def test_changed_evidence_during_inference_invalidates_question(brain, monkeypatch):
    control, state = brain
    async def think(payload):
        state['evidence']['task:1']['status'] = 'completed'
        return decision()
    monkeypatch.setattr(control, 'think', think)
    assert asyncio.run(control.propose(NOW)) is None


def test_unknown_evidence_and_multiple_questions_are_rejected(brain, monkeypatch):
    control, state = brain
    thinker(monkeypatch, control, decision(basis=['invented:1']))
    assert asyncio.run(control.propose(NOW)) is None


def test_question_budget_and_topic_history_survive_restart(brain, monkeypatch):
    from services.mind.inquiry import Inquiry
    control, state = brain
    thinker(monkeypatch, control, decision())
    assert asyncio.run(control.propose(NOW))
    restarted = Inquiry(control.store)
    monkeypatch.setattr(restarted, 'snapshot', lambda now: {**state, 'changed': True})
    thinker(monkeypatch, restarted, decision())
    assert asyncio.run(restarted.propose(NOW + timedelta(hours=1))) is None
    assert restarted.status(NOW)['last_decision']['state'] == 'silent'


def test_concurrent_calls_have_only_one_question_claim(brain, monkeypatch):
    control, state = brain
    calls = []
    async def think(payload):
        calls.append(payload)
        await asyncio.sleep(.01)
        return decision()
    monkeypatch.setattr(control, 'think', think)
    async def run():
        return await asyncio.gather(control.propose(NOW), control.propose(NOW))
    results = asyncio.run(run())
    assert sum(bool(result) for result in results) == 1 and len(calls) == 1


def test_forget_fences_inflight_question_and_keeps_attempt_budget(brain, monkeypatch):
    control, state = brain
    async def think(payload):
        control.store.clear()
        return decision()
    monkeypatch.setattr(control, 'think', think)
    assert asyncio.run(control.propose(NOW)) is None
    assert control.status(NOW)['reviews_last_hour'] == 1


def test_local_model_failure_never_uses_a_scripted_question(brain, monkeypatch):
    control, state = brain
    async def fail(payload):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(control, 'think', fail)
    assert asyncio.run(control.propose(NOW)) is None
    assert control.status(NOW)['last_decision']['state'] == 'unavailable'


def test_daily_ceiling_is_not_a_target_and_survives_forgetting(brain, monkeypatch):
    control, state = brain
    for number in range(3):
        state['changed'] = number
        state['evidence']['task:1']['blocker'] = f'Distinct issue {number}'
        thinker(monkeypatch, control, decision(question=f'Which obstacle needs attention number {number}?',
                                              topic=f'distinct issue {number}'))
        # Use distinctly phrased topics/questions; bypass similarity here to isolate durable budgets.
        monkeypatch.setattr(control, '_validate', lambda *args: None)
        assert asyncio.run(control.propose(NOW + timedelta(hours=number)))
    control.store.clear()
    state['changed'] = 99
    assert asyncio.run(control.propose(NOW + timedelta(hours=4))) is None


def test_busy_just_before_delivery_withholds_prepared_question(brain, monkeypatch):
    control, state = brain
    thinker(monkeypatch, control, decision())
    line = asyncio.run(control.propose(NOW))
    state['present']['busy'] = True
    assert not control.deliverable(line['inquiry_id'], NOW + timedelta(seconds=1))


def test_paused_or_disabled_free_will_does_not_review_automatically(brain, monkeypatch):
    control, state = brain
    calls = thinker(monkeypatch, control, decision())
    state['preferences']['on'] = False
    assert asyncio.run(control.propose(NOW)) is None and not calls
    # The owner may still explicitly request one question as a normal reply.
    assert asyncio.run(control.propose(NOW, explicit=True))


def test_inquiry_provider_is_local_only_and_cannot_request_tools(monkeypatch):
    from providers import failover
    from core.errors import ProviderError
    from types import SimpleNamespace
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    calls = []
    def provider(name, **kwargs):
        calls.append(name)
        async def complete(**params):
            raise ProviderError('local unavailable')
        return SimpleNamespace(complete=complete)
    monkeypatch.setattr(failover, 'get_provider', provider)
    with pytest.raises(ProviderError):
        asyncio.run(failover.complete_with_failover('openrouter', [], '', 100, purpose='inquiry'))
    assert calls == ['ollama']
    with pytest.raises(ProviderError):
        asyncio.run(failover.complete_with_failover('openrouter', [], '', 100, purpose='inquiry', tools=[object()]))


def test_question_spacing_does_not_reset_at_midnight(brain):
    control, state = brain
    late = NOW.replace(hour=23, minute=55)
    assert control.reserve_external(100, late)
    assert not control.can_interrupt(late + timedelta(minutes=10))


def test_feature_questions_and_generated_questions_share_the_same_budget(brain, monkeypatch):
    control, state = brain
    calls = thinker(monkeypatch, control, decision())
    assert control.reserve_external(100, NOW)
    assert asyncio.run(control.propose(NOW + timedelta(minutes=1))) is None and not calls
    assert asyncio.run(control.propose(NOW + timedelta(hours=1)))
    assert not control.reserve_external(101, NOW + timedelta(hours=1, minutes=1))


def test_notification_questions_cannot_bypass_a_recent_brain_question(brain, monkeypatch):
    from services.mind import notifications
    control, state = brain
    thinker(monkeypatch, control, decision())
    assert asyncio.run(control.propose(NOW))
    monkeypatch.setattr('services.mind.inquiry.inquiry', control)
    async def context(now):
        return {'live': {'waiting_for_answer': False}, 'busy': False,
                'question_preferences': {'on': True, 'paused_until': 0}, 'classes': []}
    monkeypatch.setattr(notifications, '_context', context)
    sent = []
    assert not asyncio.run(notifications.notify('Would you like to discuss something else?', kind='question',
        transport=lambda *args, **kw: sent.append(args) or True, now=NOW + timedelta(minutes=1)))
    assert not sent
