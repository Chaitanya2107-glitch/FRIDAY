import asyncio
import copy
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition

from services.mind.notifications import approve_question as REAL_APPROVE, _reason as REAL_REASON

NOW = datetime(2026, 10, 21, 15)


def test_gap_ranking_prefers_current_focus_and_excludes_resolved_or_readable_state():
    from services.mind.curiosity import gaps
    known = {'task:1': {'kind': 'task', 'status': 'blocked', 'title': 'Report', 'blocker': 'Waiting for notes'},
             'task:2': {'kind': 'task', 'status': 'blocked', 'title': 'Review', 'blocker': ''},
             'task:3': {'kind': 'task', 'status': 'completed', 'blocker': 'Old issue'},
             'focus:local': {'kind': 'focus', 'targets': {'task': 2}},
             'temporal:1': {'kind': 'temporal_interpretation', 'subject': 'Exam', 'status': 'postponed', 'start': None, 'end': None},
             'temporal:2': {'kind': 'temporal_interpretation', 'subject': 'Trip', 'status': 'planned', 'start': '2026-10-22', 'end': '2026-10-22'},
             'outcome_lesson:set_volume': {'kind': 'outcome_lesson', 'unverified_streak': 2}}
    result = gaps(known)
    assert result[0]['basis'] == ['task:2']
    assert {r['basis'][0] for r in result} == {'task:1', 'task:2', 'temporal:1'}


def test_gap_versions_ignore_clock_noise_but_track_meaningful_changes():
    from services.mind.curiosity import gaps
    known = {'task:1': {'kind': 'task', 'status': 'blocked', 'title': 'Report', 'blocker': 'Waiting for notes', 'updated': 1}}
    first = gaps(known)[0]
    known['task:1']['updated'] = 99
    known['runtime:current'] = {'kind': 'runtime', 'activity': 'another app'}
    assert gaps(known)[0]['version'] == first['version']
    known['task:1']['blocker'] = 'Missing access to the source folder'
    assert gaps(known)[0]['id'] == first['id'] and gaps(known)[0]['version'] != first['version']


def test_commitment_revision_ids_do_not_alone_reopen_a_date_gap():
    from services.mind.curiosity import gaps
    row = {'kind': 'temporal_interpretation', 'subject': 'Final exam', 'status': 'postponed', 'start': None, 'end': None}
    first = gaps({'temporal:1': row})[0]
    second = gaps({'temporal:2': {**row, 'noted': '2026-10-23'}})[0]
    assert first['id'] == second['id'] and first['version'] == second['version']



@pytest.fixture
def control(tmp_path, monkeypatch):
    from services.mind.inquiry import Inquiry
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    brain = Inquiry(Cognition(tmp_path / 'brain.db'))
    data = {'evidence': {'task:1': {'kind': 'task', 'title': 'Report', 'status': 'blocked', 'blocker': 'Waiting for notes'}},
            'present': {'idle': 10, 'pending': False}, 'preferences': {'on': True}, 'history': []}
    monkeypatch.setattr(brain, 'snapshot', lambda now: copy.deepcopy(data))
    async def approve(line, now):
        assert line.get('purpose')
        return line
    monkeypatch.setattr('services.mind.notifications.approve_question', approve)
    return brain, data


def proposal(**updates):
    from services.mind.inquiry import Decision
    purpose = {'gap': 'task:1:blocker', 'decision': 'Choose whether to continue the report now or defer it.',
               'if_answer_a': {'answer': 'Notes expected today', 'next_step': 'Plan to continue the report after they arrive.'},
               'if_answer_b': {'answer': 'Notes expected later', 'next_step': 'Defer the blocked part and consider available work.'},
               'usefulness': 'changes_decision'}
    return Decision(**{'ask': True, 'question': 'When are the review notes expected?', 'topic': 'report notes timing',
                       'basis': ['task:1'], 'reason': 'Timing changes the next report step; the saved blocker has no ETA.',
                       'purpose': purpose, **updates})


def answerer(monkeypatch, brain, value=None):
    calls = []
    async def think(payload):
        calls.append(payload)
        return value if value is not None else proposal()
    monkeypatch.setattr(brain, 'think', think)
    return calls


def test_no_gap_means_no_model_call_and_an_explained_silent_receipt(control, monkeypatch):
    brain, data = control
    data['evidence'] = {'task:1': {'kind': 'task', 'title': 'Report', 'status': 'active'}}
    calls = answerer(monkeypatch, brain)
    assert asyncio.run(brain.propose(NOW)) is None and calls == []
    last = brain.status(NOW)['last_decision']
    assert last['state'] == 'silent' and 'gap' in last['reason']


def test_question_persists_its_decision_and_conditional_next_steps(control, monkeypatch):
    brain, data = control
    calls = answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    assert line and line['purpose']['gap'] == 'task:1:blocker'
    assert calls[0]['curiosity']['gaps'][0]['basis'] == ['task:1']
    last = brain.status(NOW)['last_decision']
    assert last['purpose']['decision'].startswith('Choose whether')
    assert last['gap_version']


@pytest.mark.parametrize('patch', [
    {'usefulness': 'background_interest'}, {'gap': 'invented:gap'},
    {'if_answer_b': {'answer': 'Notes expected today', 'next_step': 'Plan a different investigation instead.'}},
])
def test_a_question_without_distinct_useful_grounded_branches_is_withheld(control, monkeypatch, patch):
    brain, data = control
    base = proposal().purpose.model_dump()
    answerer(monkeypatch, brain, proposal(purpose={**base, **patch}))
    assert asyncio.run(brain.propose(NOW)) is None


def test_answered_gap_stays_closed_after_restart_and_clock_or_activity_changes(control, monkeypatch):
    from services.mind.inquiry import Inquiry
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    restarted = Inquiry(Cognition(brain.store.path))
    data['evidence']['task:1']['updated'] = NOW.timestamp() + 86400
    data['evidence']['runtime:current'] = {'kind': 'runtime', 'activity': 'another app'}
    monkeypatch.setattr(restarted, 'snapshot', lambda now: copy.deepcopy(data))
    calls = answerer(monkeypatch, restarted)
    assert asyncio.run(restarted.propose(NOW + timedelta(days=8))) is None and not calls


def test_meaningful_change_reopens_same_gap_without_bypassing_global_spacing(control, monkeypatch):
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    data['evidence']['task:1']['blocker'] = 'Notes arrived but the source folder is inaccessible'
    calls = answerer(monkeypatch, brain)
    assert asyncio.run(brain.propose(NOW + timedelta(minutes=1))) is None and not calls
    # The wording/topic may repeat only for this same gap with changed semantics.
    assert asyncio.run(brain.propose(NOW + timedelta(hours=1)))
    assert len(calls) == 1


def test_semantic_change_before_delivery_withholds_even_when_unrelated_metadata_is_stable(control, monkeypatch):
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    data['evidence']['task:1']['blocker'] = 'Resolved'
    assert not brain.deliverable(line['inquiry_id'], NOW + timedelta(seconds=1))



def test_a_return_to_an_earlier_blocker_can_be_a_new_meaningful_circumstance(control, monkeypatch):
    brain, data = control
    answerer(monkeypatch, brain)
    for index, blocker in enumerate(('Waiting for notes', 'Missing folder access', 'Waiting for notes')):
        data['evidence']['task:1']['blocker'] = blocker
        line = asyncio.run(brain.propose(NOW + timedelta(hours=index)))
        assert line
        brain.mark(line['inquiry_id'], 'answered')


def test_case_and_punctuation_changes_do_not_reopen_an_answered_blocker(control, monkeypatch):
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    data['evidence']['task:1']['blocker'] = '  WAITING for notes. '
    calls = answerer(monkeypatch, brain)
    assert asyncio.run(brain.propose(NOW + timedelta(hours=1))) is None and not calls


def test_legacy_job_schema_migrates_without_losing_history(tmp_path):
    import sqlite3
    from services.mind.inquiry import Inquiry
    store = Cognition(tmp_path / 'legacy.db')
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TABLE inquiry_jobs(id INTEGER PRIMARY KEY,signature TEXT,token TEXT,epoch INTEGER,expires REAL,state TEXT,explicit INTEGER,created REAL,retry_at REAL,question TEXT,topic TEXT,reason TEXT,basis TEXT)")
        db.execute("INSERT INTO inquiry_jobs VALUES(1,'old','token',0,0,'answered',0,0,0,'Old question?','old topic','old reason','{}')")
    last = Inquiry(store).status(NOW)['last_decision']
    assert last['state'] == 'answered' and last['purpose'] == {} and last['gap'] == ''


def test_forgetting_during_generation_never_resurrects_private_purpose(control, monkeypatch):
    brain, data = control
    async def think(payload):
        brain.store.clear()
        return proposal()
    monkeypatch.setattr(brain, 'think', think)
    assert asyncio.run(brain.propose(NOW)) is None
    assert brain.status(NOW)['last_decision'] is None
    assert brain.status(NOW)['reviews_last_hour'] == 1


def test_explicit_request_without_other_gaps_can_have_one_scoped_question(control, monkeypatch):
    brain, data = control
    data['evidence'] = {}
    purpose = proposal().purpose.model_dump()
    purpose.update(gap='context:request', decision='Choose a direction for this requested conversation.',
                   if_answer_a={'answer': 'Work topic', 'next_step': 'Discuss the project the owner chooses.'},
                   if_answer_b={'answer': 'Personal topic', 'next_step': 'Discuss the personal subject the owner chooses.'})
    answerer(monkeypatch, brain, proposal(basis=['context:request'], purpose=purpose))
    data['preferences']['on'] = False
    line = asyncio.run(brain.propose(NOW, explicit=True, intention='ask one useful question'))
    assert line and line['explicit']
    assert brain.status(NOW)['automatic_questions_today'] == 0


def test_real_talk_answer_keeps_original_question_and_closes_gap_without_completing_task(control, monkeypatch):
    from services.mind import talk, inquiry, brain_memory
    from services.mind.brain_memory import BrainMemory
    from services.mind.workspace import Workspace
    brain, data = control
    work = Workspace(brain.store)
    ident = work.start_task('Report')
    work.task_state(ident, 'blocked', 'Waiting for notes')
    data['evidence'] = {'task:1': {'kind': 'task', **work.tasks()[0]}}
    monkeypatch.setattr(inquiry, 'inquiry', brain)
    memory = BrainMemory(brain.store)
    monkeypatch.setattr(brain_memory, 'brain_memory', memory)
    monkeypatch.setattr(talk, '_learn_answer', lambda *args: None)
    answerer(monkeypatch, brain)
    monkeypatch.setattr(talk.time, 'time', lambda: NOW.timestamp())
    question = asyncio.run(talk.ask_now(None, NOW))
    assert question.endswith('?')
    assert talk.hear('My teammate will send the notes tomorrow afternoon.', NOW.timestamp() + 5) == 'answered'
    episode = next(iter(memory.evidence().values()))
    assert episode['question'] == question and 'tomorrow afternoon' in episode['text']
    calls = answerer(monkeypatch, brain)
    assert asyncio.run(brain.propose(NOW + timedelta(hours=1))) is None and not calls
    assert work.tasks()[0]['status'] == 'blocked'



def test_closed_high_ranked_gaps_do_not_starve_a_later_open_gap(control):
    from services.mind.curiosity import gaps
    brain, data = control
    data['evidence'] = {f'task:{index}': {'kind': 'task', 'title': f'Task {index}', 'status': 'blocked'}
                        for index in range(1, 10)}
    candidates = gaps(data['evidence'])
    for index, gap in enumerate(candidates[:8]):
        job = brain.claim(f'closed-{index}', NOW - timedelta(days=2), True)
        question = proposal(basis=gap['basis'], purpose={**proposal().purpose.model_dump(), 'gap': gap['id']})
        assert brain.finish(job, 'prepared', question.reason, NOW - timedelta(days=2), question, data['evidence'], gap)
        brain.mark(job['id'], 'answered')
    prepared = brain._prepare(copy.deepcopy(data), NOW, False)
    assert len(prepared['curiosity']['gaps']) == 1



def test_same_next_step_for_different_answers_is_not_a_useful_question(control, monkeypatch):
    brain, data = control
    purpose = proposal().purpose.model_dump()
    purpose['if_answer_b']['next_step'] = purpose['if_answer_a']['next_step']
    answerer(monkeypatch, brain, proposal(purpose=purpose))
    assert asyncio.run(brain.propose(NOW)) is None


def test_delayed_delivery_receipt_cannot_reopen_an_answered_gap(control, monkeypatch):
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    brain.mark(line['inquiry_id'], 'withheld')
    assert brain.status(NOW)['last_decision']['state'] == 'answered'
    data['unrelated_activity'] = 'another app'
    calls = answerer(monkeypatch, brain)
    assert asyncio.run(brain.propose(NOW + timedelta(days=8))) is None and not calls


def test_conflicting_current_commitment_identities_are_not_guessed():
    from services.mind.curiosity import gaps
    a = {'kind': 'temporal_interpretation', 'subject': 'Exam', 'status': 'postponed', 'start': None, 'end': None}
    b = {**a, 'status': 'uncertain'}
    assert gaps({'temporal:1': a, 'temporal:2': b}) == []
    assert len(gaps({'temporal:1': a, 'temporal:2': dict(a)})) == 1



def test_empty_planning_decision_is_not_a_question_purpose(control, monkeypatch):
    brain, data = control
    purpose = proposal().purpose.model_dump()
    purpose['decision'] = ' ' * 12
    answerer(monkeypatch, brain, proposal(purpose=purpose))
    assert asyncio.run(brain.propose(NOW)) is None


def test_earlier_question_history_is_marked_historical_when_its_blocker_changes(control):
    from services.mind.curiosity import gaps
    brain, data = control
    original = gaps(data['evidence'])[0]
    data['history'] = [{'question': 'When will notes arrive?', 'gap': original['id'], 'gap_version': original['version']}]
    data['evidence']['task:1']['blocker'] = 'Notes arrived; manager approval pending'
    prepared = brain._prepare(copy.deepcopy(data), NOW, False)
    assert prepared['history'][0]['gap_context'] == 'historical_version'



@pytest.mark.parametrize('send', [True, False])
def test_actual_notification_reviewer_receives_purpose_and_can_withhold_it(control, monkeypatch, send):
    import json
    from types import SimpleNamespace
    from providers import failover
    from services.mind import notifications, inquiry
    brain, data = control
    monkeypatch.setattr(config, 'NOTIFICATION_REVIEW_ENABLED', True)
    monkeypatch.setattr(notifications, 'approve_question', REAL_APPROVE)
    monkeypatch.setattr(notifications, '_reason', REAL_REASON)
    monkeypatch.setattr(notifications, 'cognition', brain.store)
    monkeypatch.setattr(inquiry, 'inquiry', brain)
    async def context(now):
        return {'live': {'waiting_for_answer': False}, 'busy': False,
                'question_preferences': {'on': True}, 'life_state': {'can_initiate': True}}
    monkeypatch.setattr(notifications, '_context', context)
    captured = []
    async def complete(*args, **kwargs):
        payload = json.loads(args[1][0].content)
        captured.append(payload)
        assert kwargs['purpose'] == 'notification_review'
        return SimpleNamespace(content=json.dumps({'decisions': [{'id': '0', 'send': send,
                               'reason': 'This question may change the next report step.'}]}), metadata={})
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    assert bool(line) is send
    purpose = captured[0]['candidates'][0]['evidence']['purpose']
    assert purpose['gap'] == 'task:1:blocker' and purpose['if_answer_a']['answer']
    event = brain.store.latest('notification_decision')
    assert event is not None and not event['public']


def test_real_inquiry_provider_contract_requires_purpose_and_actual_gap_ids(control, monkeypatch):
    import json
    from types import SimpleNamespace
    from providers import failover
    brain, data = control
    payload = brain._prepare(copy.deepcopy(data), NOW, False)
    captured = []
    async def complete(*args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(content=proposal().model_dump_json(), tool_calls=[], metadata={})
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    result = asyncio.run(brain.think(payload))
    args, kwargs = captured[0]
    assert args[0] == 'ollama' and kwargs['purpose'] == 'inquiry'
    schema = kwargs['response_schema']
    assert 'purpose' in schema['required']
    assert schema['$defs']['Purpose']['properties']['gap']['enum'] == ['task:1:blocker']
    view = json.loads(args[1][0].content)
    assert view['curiosity']['gaps'][0]['priority'] == 'other_recorded_need'
    assert 'version' not in view['curiosity']['gaps'][0]
    assert result.purpose.gap == 'task:1:blocker'


def test_high_priority_goal_ranks_its_blocked_task_before_background_work():
    from services.mind.curiosity import gaps
    known = {'task:1': {'kind': 'task', 'title': 'Background report', 'status': 'blocked'},
             'task:2': {'kind': 'task', 'title': 'Important report', 'status': 'blocked', 'goal_id': 5},
             'goal:5': {'kind': 'goal', 'priority': 3}}
    assert gaps(known)[0]['id'] == 'task:2:blocker'



def test_question_purpose_reaches_shared_reasoning_without_promoting_it_to_a_fact(control, monkeypatch):
    from services.mind.reasoning_store import ReasoningStore
    from services.mind.executive import ExecutiveControl
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    evidence = ReasoningStore(brain.store).evidence()
    row = evidence[f"inquiry:{line['inquiry_id']}"]
    assert row['kind'] == 'question_review' and row['state'] == 'answered'
    assert row['purpose']['if_answer_a']['answer']
    captured = ExecutiveControl(brain.store).capture(NOW, known=evidence, attention={})
    assert row['id'] in captured['evidence']
    assert ReasoningStore(brain.store).facts() == []


def test_last_question_purpose_remains_inspectable_after_later_silence(control, monkeypatch):
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    data['activity'] = 'changed unrelated activity'
    asyncio.run(brain.propose(NOW + timedelta(hours=1)))
    status = brain.status(NOW + timedelta(hours=1))
    assert status['last_decision']['state'] == 'silent'
    assert status['last_question']['state'] == 'answered'
    assert status['last_question']['purpose']['gap'] == 'task:1:blocker'



def test_private_question_review_conclusions_are_omitted_from_remote_prompts_and_offers(control, monkeypatch):
    from services.mind import reasoning
    from services.automation.intent import remote_request
    brain, data = control
    claim = {'id': 1, 'status': 'proposed', 'kind': 'proposal', 'text': 'Private conditional report plan.',
             'evidence': ['inquiry:1'], 'confidence': .9, 'noted': NOW.isoformat()}
    monkeypatch.setattr(reasoning.reasoning_store, 'context', lambda now: {'facts': [], 'conclusions': [claim]})
    assert reasoning.suggestion(NOW) is None
    token = remote_request.set(True)
    try:
        assert 'Private conditional' not in reasoning.prompt_section(NOW)
    finally:
        remote_request.reset(token)


def test_local_brain_diagnostics_explain_the_latest_question_after_silence(control, monkeypatch):
    from services.mind import inquiry, cognition_commands
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    brain.mark(line['inquiry_id'], 'answered')
    data['other'] = True
    asyncio.run(brain.propose(NOW + timedelta(hours=1)))
    monkeypatch.setattr(inquiry, 'inquiry', brain)
    result = cognition_commands.run('brain_status')
    assert result.success and 'Choose whether' in result.message and 'conditional' in result.message.lower()
    remote = cognition_commands.run('brain_status', remote=True)
    assert not remote.success and 'Choose whether' not in remote.message


def test_real_snapshot_history_carries_gap_versions_from_persisted_jobs(control, monkeypatch):
    from services.mind.inquiry import Inquiry
    from services.mind import cognition_context
    brain, data = control
    answerer(monkeypatch, brain)
    line = asyncio.run(brain.propose(NOW))
    saved = brain.status(NOW)['last_question']
    fresh = Inquiry(brain.store)
    # Actual canonical adapters are isolated by the shared test fixture.
    view = fresh.snapshot(NOW)
    assert view['history'][0]['gap'] == saved['gap']
    assert view['history'][0]['gap_version'] == saved['gap_version']
