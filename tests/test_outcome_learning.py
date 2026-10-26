import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition

NOW = datetime(2026, 10, 21, 14)


@pytest.fixture
def learning(tmp_path, monkeypatch):
    from services.mind.outcome_learning import OutcomeLearning
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    return OutcomeLearning(Cognition(tmp_path / 'brain.db'))


def test_request_applied_and_verified_have_distinct_receipts(learning):
    job = learning.begin('set_volume', {'volume': 30, 'muted': False}, NOW)
    assert learning.recent(NOW)[0]['state'] == 'requested'
    learning.applied(job, NOW)
    assert learning.recent(NOW)[0]['state'] == 'applied'
    learning.finish(job, {'volume': 30, 'muted': False}, True, NOW)
    receipt = learning.recent(NOW)[0]
    assert receipt['state'] == 'verified' and receipt['matched'] is True
    assert receipt['expected'] == receipt['observed']


@pytest.mark.parametrize('observed,driver,state', [
    ({'volume': 70}, True, 'failed'), (None, True, 'unknown'),
    ({'volume': 30}, False, 'failed'), (None, None, 'unknown'),
])
def test_mismatch_missing_read_and_driver_failure_remain_distinct(learning, observed, driver, state):
    job = learning.begin('set_volume', {'volume': 30}, NOW)
    learning.finish(job, observed, driver, NOW)
    assert learning.recent(NOW)[0]['state'] == state


def test_restart_never_turns_an_abandoned_request_into_success_or_replays_it(learning):
    from services.mind.outcome_learning import OutcomeLearning
    learning.begin('start_mode', {'mode': 'gaming'}, NOW)
    restarted = OutcomeLearning(Cognition(learning.store.path))
    receipt = restarted.recent(NOW + timedelta(minutes=1))[0]
    assert receipt['state'] == 'unknown' and receipt['observed'] is None


def test_repeated_unverified_results_produce_a_lesson_and_success_resets_it(learning):
    for n, observed in enumerate(({'volume': 10}, None)):
        job = learning.begin('set_volume', {'volume': 30}, NOW + timedelta(seconds=n))
        learning.finish(job, observed, True, NOW + timedelta(seconds=n))
    lesson = learning.lessons()[0]
    assert lesson['unverified_streak'] == 2 and lesson['failed'] == 1 and lesson['unknown'] == 1
    assert 'check' in lesson['advice'].lower()
    job = learning.begin('set_volume', {'volume': 30}, NOW + timedelta(seconds=3))
    learning.finish(job, {'volume': 30}, True, NOW + timedelta(seconds=3))
    assert not learning.lessons()


def test_forgetting_fences_late_completion_without_resurrecting_private_state(learning):
    job = learning.begin('start_mode', {'mode': 'study'}, NOW)
    learning.store.clear()
    assert learning.finish(job, {'mode': 'study'}, True, NOW) is None
    assert not learning.recent(NOW) and not learning.lessons()


def test_a_terminal_receipt_cannot_be_rewritten_by_a_delayed_callback(learning):
    job = learning.begin('set_mute', {'muted': True}, NOW)
    learning.finish(job, {'muted': True}, True, NOW)
    assert learning.finish(job, {'muted': False}, True, NOW) is None
    assert learning.recent(NOW)[0]['state'] == 'verified'


@pytest.mark.parametrize('action,expected', [('run_shell', {'command': 'private command'}),
    ('set_volume', {'volume': True}), ('set_mute', {'muted': 'true'}),
    ('start_mode', {'mode': 'study', 'raw_message': 'private'})])
def test_only_whitelisted_targets_enter_the_ledger(learning, action, expected):
    with pytest.raises(ValueError):
        learning.begin(action, expected, NOW)
    assert not learning.recent(NOW)


def test_audio_driver_reads_the_setting_after_writing_and_detects_a_lying_driver(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation.system_control import SystemControl, AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    calls = []
    class Endpoint:
        def SetMasterVolumeLevelScalar(self, value, context):
            assert learning.recent()[0]['state'] == 'requested'
            calls.append('set')
        def SetMute(self, value, context):
            pass
        def GetMasterVolumeLevelScalar(self):
            calls.append('read')
            return .7
        def GetMute(self):
            return 0
    controller = SystemControl()
    monkeypatch.setattr(controller, '_endpoint_volume', lambda: Endpoint())
    with pytest.raises(AutomationError, match='(?i)verif'):
        controller.set_volume(30)
    assert calls == ['set', 'read'] and learning.recent()[0]['state'] == 'failed'


def test_unknown_readback_never_claims_audio_success(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation.system_control import SystemControl, AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    class Endpoint:
        def SetMute(self, value, context):
            pass
        def GetMute(self):
            raise OSError('Private driver detail')
    controller = SystemControl()
    monkeypatch.setattr(controller, '_endpoint_volume', lambda: Endpoint())
    with pytest.raises(AutomationError, match='(?i)confirm') as error:
        controller.set_mute(True)
    assert 'Private driver detail' not in str(error.value)
    assert learning.recent()[0]['state'] == 'unknown'


def test_audio_verification_still_runs_with_memory_disabled(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation.system_control import SystemControl, AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', False)
    class Endpoint:
        def SetMute(self, value, context):
            pass
        def GetMute(self):
            return 0
    controller = SystemControl()
    monkeypatch.setattr(controller, '_endpoint_volume', lambda: Endpoint())
    with pytest.raises(AutomationError):
        controller.set_mute(True)


def test_mode_controller_checks_strict_saved_state_instead_of_success_text(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation import intent, modes
    from services.automation.results import ActionResult
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    async def optimistic(*args, **kwargs):
        assert learning.recent()[0]['state'] == 'requested'
        return ActionResult(True, 'Gaming mode on.')
    monkeypatch.setattr(intent, '_start_mode_impl', optimistic)
    result = asyncio.run(intent._start_mode('gaming', 'ollama'))
    assert not result.success and 'normal' in result.message.lower()
    assert learning.recent()[0]['state'] == 'failed' and modes.active() is None


def test_partial_mode_setup_keeps_the_true_selected_mode(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation import intent, modes
    from services.automation.results import ActionResult
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    async def partial(*args, **kwargs):
        modes.begin('gaming', None)
        return ActionResult(False, 'Gaming mode on. Some setup steps failed.')
    monkeypatch.setattr(intent, '_start_mode_impl', partial)
    result = asyncio.run(intent._start_mode('gaming', 'ollama'))
    assert not result.success and result.message.startswith('Gaming mode on.')
    receipt = learning.recent()[0]
    assert receipt['state'] == 'failed' and receipt['matched'] is True


def test_changed_target_cannot_move_the_goalpost_after_execution(learning):
    job = learning.begin('set_mute', {'muted': True}, NOW)
    job['expected'] = {'muted': False}
    assert learning.finish(job, {'muted': False}, True, NOW) is None
    assert learning.recent()[0]['state'] == 'requested'


def test_concurrent_completions_write_one_terminal_receipt(learning):
    from concurrent.futures import ThreadPoolExecutor
    job = learning.begin('set_mute', {'muted': True}, NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda value: learning.finish(job, {'muted': value}, True, NOW), [True, False]))
    assert sum(result is not None for result in results) == 1
    assert learning.recent()[0]['state'] in {'verified', 'failed'}


def test_concurrent_forget_never_restores_targets_or_lessons(learning):
    from concurrent.futures import ThreadPoolExecutor
    job = learning.begin('start_mode', {'mode': 'private focus'}, NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        done = pool.submit(learning.finish, job, {'mode': 'private focus'}, True, NOW)
        forgotten = pool.submit(learning.store.clear)
        done.result()
        forgotten.result()
    assert learning.recent() == [] and learning.lessons() == []


def test_broken_receipt_storage_does_not_bypass_real_verification(learning, monkeypatch):
    from contextlib import contextmanager
    from services.mind import outcome_learning
    from services.automation.system_control import AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    @contextmanager
    def broken():
        raise OSError('unavailable')
        yield
    monkeypatch.setattr(learning.store, '_connect', broken)
    with pytest.raises(AutomationError, match='verification'):
        outcome_learning.verified_change('set_mute', {'muted': True}, lambda: None,
                                        lambda: {'muted': False}, 'Muted.')
    assert learning.context()['status'] == 'unavailable'


def test_repeated_mismatch_changes_actual_reply_and_explicit_retry_can_recover(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation.system_control import AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    replies = []
    for _ in range(2):
        with pytest.raises(AutomationError) as error:
            outcome_learning.verified_change('set_mute', {'muted': True}, lambda: None,
                                            lambda: {'muted': False}, 'Muted.')
        replies.append(str(error.value))
    assert 'control permissions' not in replies[0] and 'control permissions' in replies[1]
    assert outcome_learning.verified_change('set_mute', {'muted': True}, lambda: None,
                                           lambda: {'muted': True}, 'Muted.') == 'Muted.'
    assert learning.lessons() == []


def test_repeated_driver_errors_also_explain_the_learned_next_check(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation.system_control import AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    def broken():
        raise AutomationError('Audio control failed.')
    for _ in range(2):
        with pytest.raises(AutomationError) as error:
            outcome_learning.verified_change('set_mute', {'muted': True}, broken, lambda: {'muted': True}, 'Muted.')
    assert 'control permissions' in str(error.value)


@pytest.mark.parametrize('observed,state', [({'volume': 29}, 'verified'), ({'volume': 32}, 'failed')])
def test_master_volume_readback_allows_one_percent_rounding(learning, observed, state):
    job = learning.begin('set_volume', {'volume': 30}, NOW)
    assert learning.finish(job, observed, True, NOW)['state'] == state


def test_real_end_controller_reports_normal_but_failed_cleanup(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation import intent, modes
    from services.automation.system_control import AutomationError
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    modes.begin('study', 30)
    monkeypatch.setattr(intent.activity_log, 'flush', lambda: None)
    def fail(*args):
        raise AutomationError('Unverified volume.')
    monkeypatch.setattr(intent.system, 'set_volume', fail)
    result = intent._end_mode('study')
    assert not result.success and 'Study mode off' in result.message and 'cleanup steps failed' in result.message
    receipt = learning.recent()[0]
    assert receipt['state'] == 'failed' and receipt['matched'] is True and receipt['observed'] == {'mode': 'normal'}


def test_mode_readback_unavailable_does_not_claim_success(learning, monkeypatch):
    from services.mind import outcome_learning
    from services.automation import intent
    from services.automation.results import ActionResult
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    monkeypatch.setattr(intent, '_end_mode_impl', lambda name: ActionResult(True, 'Mode off.'))
    def corrupt():
        raise ValueError('Corrupt state')
    monkeypatch.setattr(intent, '_observed_mode', corrupt)
    result = intent._end_mode('study')
    assert not result.success and 'could not confirm' in result.message
    assert learning.recent()[0]['state'] == 'unknown'


def test_outcomes_reach_shared_evidence_life_focus_and_executive_capture(learning):
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.life_state import LifeState
    from services.mind.executive import ExecutiveControl
    for _ in range(2):
        job = learning.begin('set_volume', {'volume': 30}, NOW)
        learning.finish(job, {'volume': 70}, True, NOW)
    known = ReasoningStore(learning.store).evidence()
    lesson = known['outcome_lesson:set_volume']
    assert all(ref in known for ref in lesson['evidence'])
    live = {'activity': 'coding', 'mode_name': 'normal', 'idle_band': 'present'}
    state = LifeState(learning.store).assess(NOW, known, live, {'on': False})
    assert state['focus']['aim'] == 'check_action_outcome' and state['can_review'] and not state['can_initiate']
    captured = ExecutiveControl(learning.store).capture(NOW, known=known, attention=live)
    assert 'outcome_lesson:set_volume' in captured['evidence']
    assert all(ref in captured['evidence'] for ref in lesson['evidence'])
    assert not ReasoningStore(learning.store).facts()


def test_local_prompt_includes_history_but_remote_prompt_omits_private_targets(learning, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import ReasoningStore
    from services.automation.intent import remote_request
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    monkeypatch.setattr(reasoning, 'reasoning_store', ReasoningStore(learning.store))
    job = learning.begin('start_mode', {'mode': 'private study'}, NOW)
    learning.finish(job, {'mode': 'private study'}, True, NOW)
    assert 'private study' in reasoning.prompt_section(NOW)
    token = remote_request.set(True)
    try:
        assert 'private study' not in reasoning.prompt_section(NOW)
    finally:
        remote_request.reset(token)
    assert all('private study' not in event['text'] for event in learning.store.recent(20))


def test_outcome_api_returns_historical_scope_without_running_an_action(learning, monkeypatch):
    from services.mind import outcome_learning
    from interfaces.api.routes.mind import get_action_outcomes
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    job = learning.begin('set_mute', {'muted': True}, NOW)
    learning.finish(job, {'muted': True}, True, NOW)
    result = asyncio.run(get_action_outcomes())
    assert result['receipts'][0]['state'] == 'verified' and 'Historical' in result['scope']
    assert len(learning.recent()) == 1


@pytest.mark.parametrize('change_during_review', [False, True])
def test_guarded_local_generation_and_critique_use_outcomes_without_executing(change_during_review, learning, monkeypatch):
    import copy
    import json
    from types import SimpleNamespace
    from providers import failover
    from services.mind import executive, reasoning, cognition_context, life_state
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.workspace import Workspace
    for _ in range(2):
        job = learning.begin('set_volume', {'volume': 30}, NOW)
        learning.finish(job, {'volume': 70}, True, NOW)
    work = Workspace(learning.store)
    work.start_task('Review a synthetic report')
    before = work.tasks()
    known = learning.evidence()
    live = {'activity': 'coding', 'mode_name': 'normal', 'idle_band': 'present'}
    behavior = life_state.LifeState(learning.store).assess(NOW, known, live, {'on': False})
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(executive, 'attention_state', lambda: {**live, 'life_state': behavior})
    monkeypatch.setattr(cognition_context, 'live_state', lambda: dict(live))
    monkeypatch.setattr(life_state, 'current', lambda *args, **kwargs: copy.deepcopy(behavior))
    monkeypatch.setattr(reasoning, 'cognition', learning.store)
    local = ReasoningStore(learning.store)
    monkeypatch.setattr(local, 'evidence', learning.evidence)
    monkeypatch.setattr(reasoning, 'reasoning_store', local)
    control = executive.ExecutiveControl(learning.store)
    monkeypatch.setattr(control, '_known', learning.evidence)
    calls = []
    async def complete(provider, messages, prompt, *args, **kwargs):
        payload = json.loads(messages[0].content)
        calls.append(kwargs.get('purpose'))
        if len(calls) == 1:
            assert 'outcome_lesson:set_volume' in payload['evidence']
            if change_during_review:
                job = learning.begin('set_volume', {'volume': 30}, NOW)
                learning.finish(job, {'volume': 30}, True, NOW)
            value = {'facts': [], 'conclusions': [{'kind': 'proposal',
                     'text': 'Check the Windows audio endpoint before trying this method again.',
                     'evidence': ['outcome_lesson:set_volume'], 'confidence': .8,
                     'start': None, 'end': None, 'effect': {'type': 'guidance'}}],
                     'questions': [], 'situations': []}
        else:
            assert payload['check_items'][0]['value']['effect'] == {'type': 'guidance'}
            value = {'checks': [{'id': 0, 'supported': True, 'reason': 'Two recorded mismatches support investigating the controller.'}]}
        return SimpleNamespace(content=json.dumps(value), provider='ollama', model='test-local')
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    result = asyncio.run(control.review(NOW))
    assert calls == ['cognitive_review', 'cognitive_review']
    conclusions = local.conclusions(NOW, learning.evidence())
    if change_during_review:
        assert result['status'] == 'unavailable' and conclusions == []
    else:
        assert result['status'] == 'completed' and len(conclusions) == 1
        assert conclusions[0]['effect'] == {'type': 'guidance'} and conclusions[0]['status'] == 'inferred'
    assert work.tasks() == before and not local.facts()


def test_private_outcome_conclusions_do_not_enter_remote_prompts_or_mirrored_offers(learning, monkeypatch):
    from services.mind import reasoning, reasoning_commands
    from services.automation.intent import remote_request
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    claim = {'id': 1, 'text': 'Private study mode needs checking.', 'kind': 'proposal', 'status': 'proposed',
             'evidence': ['action_outcome:1'], 'confidence': .9, 'noted': NOW.isoformat()}
    monkeypatch.setattr(reasoning.reasoning_store, 'context', lambda now: {'facts': [], 'conclusions': [claim]})
    assert reasoning.suggestion(NOW) is None
    token = remote_request.set(True)
    try:
        assert 'Private study' not in reasoning.prompt_section(NOW)
        result = asyncio.run(reasoning_commands.run({'action': 'show'}))
        assert not result.success and 'local-only' in result.message
    finally:
        remote_request.reset(token)



def test_cognitive_schema_cannot_attach_diagnostic_guidance_to_an_invented_task():
    from services.mind.reasoning import cognitive_schema
    only = cognitive_schema({'action_outcome:1': {'kind': 'action_outcome'}})
    effect = only['$defs']['Conclusion']['properties']['effect']
    assert effect['oneOf'] == [{'$ref': '#/$defs/Guidance'}]
    with_task = cognitive_schema({'task:42': {'kind': 'task'}})
    assert with_task['$defs']['TaskPlan']['properties']['task_id']['enum'] == [42]
    assert 'reminder_move' not in with_task['$defs']['Conclusion']['properties']['effect']['discriminator']['mapping']



def test_rejecting_a_private_diagnostic_plan_keeps_reaction_event_generic(learning, monkeypatch):
    import importlib
    from services.mind import reasoning_commands
    cognition_module = importlib.import_module('services.mind.cognition')
    monkeypatch.setattr(cognition_module, 'cognition', learning.store)
    claim = {'status': 'proposed', 'text': 'Inspect private study mode setup.', 'evidence': ['outcome_lesson:start_mode:private study']}
    monkeypatch.setattr(reasoning_commands.reasoning_store, 'get', lambda *args: claim)
    monkeypatch.setattr(reasoning_commands.reasoning_store, 'claim', lambda *args: True)
    monkeypatch.setattr(reasoning_commands.reasoning_store, 'finish', lambda *args: None)
    result = asyncio.run(reasoning_commands.run({'action': 'reject', 'id': '1'}))
    assert result.success
    event = learning.store.latest('reaction')
    assert not event['public'] and 'private study' not in event['text']



def test_concurrent_attempts_learn_in_observed_completion_order(learning):
    older = learning.begin('set_volume', {'volume': 30}, NOW)
    recovered = learning.begin('set_volume', {'volume': 30}, NOW + timedelta(seconds=1))
    learning.finish(recovered, {'volume': 30}, True, NOW + timedelta(seconds=2))
    learning.finish(older, {'volume': 70}, True, NOW + timedelta(seconds=3))
    latest = learning.begin('set_volume', {'volume': 30}, NOW + timedelta(seconds=4))
    learning.finish(latest, {'volume': 70}, True, NOW + timedelta(seconds=5))
    assert learning.lessons()[0]['unverified_streak'] == 2
    assert [row['state'] for row in learning.recent()] == ['failed', 'failed', 'verified']



@pytest.mark.parametrize('observed', [{'mode': 'normal'}, None])
def test_failed_partial_controller_does_not_override_missing_or_mismatched_readback(learning, monkeypatch, observed):
    from services.mind import outcome_learning
    from services.automation.results import ActionResult
    monkeypatch.setattr(outcome_learning, 'outcome_learning', learning)
    job = learning.begin('start_mode', {'mode': 'gaming'})
    result = outcome_learning.verified_result(job, 'start_mode', {'mode': 'gaming'},
             ActionResult(False, 'Gaming mode on. Some setup steps failed.'), lambda: observed)
    assert not result.success and result.message.startswith('Mode verification failed: current mode is ')
    assert ('Normal' if observed else 'Unknown') in result.message.split('Controller reported:')[0]
    assert 'Controller reported: Gaming mode on.' in result.message
