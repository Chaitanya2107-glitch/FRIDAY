import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition

NOW = datetime(2026, 10, 20, 15)
LIVE = {'activity': 'coding', 'away': False, 'mode_name': 'normal', 'idle_band': 'present'}


@pytest.fixture
def state(tmp_path, monkeypatch):
    from services.mind.life_state import LifeState
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    return LifeState(Cognition(tmp_path / 'brain.db'))


def assess(state, now=NOW, known=None, live=None, preferences=None, **options):
    return state.assess(now, known or {}, dict(LIVE) if live is None else live,
                        preferences or {}, **options)


def test_quiet_preference_blocks_interruptions_but_allows_silent_reasoning(state):
    view = assess(state, preferences={'on': False})
    assert view['can_review'] and not view['can_initiate']
    assert view['posture'] == 'quiet' and 'conversation_disabled' in view['interruption_blocks']


@pytest.mark.parametrize('live,options,reason', [
    ({**LIVE, 'idle_band': 'typing'}, {}, 'typing'),
    ({**LIVE, 'mode_name': 'gaming'}, {}, 'gaming'),
    ({**LIVE, 'speaking': True}, {}, 'speaking'),
    ({**LIVE, 'listening': True}, {}, 'listening'),
    ({**LIVE, 'waiting_for_answer': True}, {}, 'pending_reply'),
    ({**LIVE, 'active_operations': [{'kind': 'request'}]}, {}, 'owner_request_active'),
    (LIVE, {'busy': True}, 'busy'), (LIVE, {'mic': True}, 'call'),
    ({'state': 'partly unavailable'}, {}, 'attention_unavailable'),
])
def test_attention_limits_review_and_initiation(state, live, options, reason):
    view = assess(state, live=live, **options)
    assert not view['can_review'] and not view['can_initiate']
    assert reason in view['review_blocks']


def test_absence_allows_private_review_and_does_not_invent_loneliness(state):
    view = assess(state, live={**LIVE, 'away': True, 'idle_band': 'away'})
    assert view['can_review'] and not view['can_initiate']
    assert view['posture'] == 'quiet'
    assert 'lonely' not in str(view) and 'bored' not in str(view) and 'sulky' not in str(view)


def test_commitments_and_unknowns_produce_source_linked_review_focus(state):
    known = {'temporal:1': {'kind': 'temporal_interpretation', 'status': 'planned',
                          'start': '2026-10-20', 'end': '2026-10-20'},
             'task:2': {'kind': 'task', 'status': 'active', 'blocker': 'Waiting for notes'}}
    view = assess(state, known=known)
    assert view['focus']['aim'] == 'support_commitment' and view['focus']['basis'] == ['temporal:1']
    assert view['responsibilities']['blocked'] == ['task:2']
    known.pop('temporal:1')
    view = assess(state, known=known)
    assert view['focus']['aim'] == 'resolve_uncertainty' and view['focus']['basis'] == ['task:2']


def test_imminent_timed_commitment_inhibits_questions_without_preventing_review(state):
    view = assess(state, known={'reminder:1': {'kind': 'reminder', 'due_at': NOW.timestamp() + 300}})
    assert view['can_review'] and not view['can_initiate']
    assert 'commitment_imminent' in view['interruption_blocks']


def test_past_due_and_uncertain_dates_never_mean_done_or_imminent(state):
    view = assess(state, known={
        'temporal:1': {'kind': 'temporal_interpretation', 'status': 'planned', 'start': '2026-10-19', 'end': '2026-10-19'},
        'temporal:2': {'kind': 'temporal_interpretation', 'status': 'postponed', 'start': None, 'end': None}})
    assert view['responsibilities']['overdue'] == ['temporal:1']
    assert view['responsibilities']['unresolved'] == ['temporal:2']
    assert view['can_initiate']


def test_contextual_declines_lengthen_cooldown_across_restart_and_are_deduplicated(state):
    from services.mind.life_state import LifeState
    context = assess(state)['context']
    state.feedback(context, 'shushed', 'offer:1', NOW)
    state.feedback(context, 'shushed', 'offer:1', NOW)  # callback replay
    state.feedback(context, 'shushed', 'offer:2', NOW + timedelta(minutes=5))
    restored = LifeState(Cognition(state.store.path))
    view = assess(restored, now=NOW + timedelta(minutes=70))
    assert view['engagement']['declines'] == 2 and view['can_review'] and not view['can_initiate']
    assert view['engagement']['cooldown_until'] == (NOW + timedelta(minutes=125)).timestamp()
    elsewhere = assess(restored, now=NOW + timedelta(minutes=70), live={**LIVE, 'activity': 'entertainment'})
    assert elsewhere['can_initiate']


def test_unanswered_offer_is_weaker_than_explicit_decline_and_never_requires_a_reply(state):
    context = assess(state)['context']
    state.feedback(context, 'ignored', 'offer:1', NOW)
    ignored = assess(state, now=NOW + timedelta(minutes=1))
    assert ignored['engagement']['declines'] == 0 and ignored['engagement']['unanswered'] == 1
    assert ignored['posture'] == 'quiet' and ignored['can_review']
    assert 'rejected' not in str(ignored) and 'owed' not in str(ignored)


def test_positive_feedback_never_overrides_a_hard_pause(state):
    context = assess(state)['context']
    state.feedback(context, 'answered', 'offer:1', NOW)
    view = assess(state, preferences={'paused_until': NOW.timestamp() + 3600})
    assert not view['can_initiate'] and view['can_review']


def test_forgetting_removes_contextual_feedback(state):
    context = assess(state)['context']
    state.feedback(context, 'shushed', 'offer:1', NOW)
    state.store.clear()
    assert assess(state)['engagement']['declines'] == 0


def test_mood_does_not_punish_silence_or_a_quiet_request():
    from services.mind import life
    life.feel('shushed', NOW.timestamp())
    life.feel('ignored', NOW.timestamp())
    assert life.mood(NOW)[0] == 'content'
    assert life.mood(NOW, away_minutes=90)[0] == 'quiet'
    assert 'brushed off' not in life.day_line(NOW.date().isoformat())


def test_automatic_inquiry_obeys_shared_state_but_explicit_reply_is_scoped(monkeypatch):
    from services.mind.inquiry import Inquiry
    monkeypatch.setattr(config, 'REASONING_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    data = {'present': {'pending': False, 'idle': 10}, 'preferences': {},
            'life_state': {'can_initiate': False, 'interruption_blocks': ['learned_cooldown']}}
    assert not Inquiry._eligible(data, NOW, False)
    assert Inquiry._eligible(data, NOW, True)


def test_quiet_controls_record_only_offered_autonomous_questions(state, monkeypatch):
    from services.mind import talk, life_state
    monkeypatch.setattr(life_state, 'life_state', state)
    monkeypatch.setattr(talk.time, 'time', lambda: NOW.timestamp())
    context = assess(state)['context']
    for ident, explicit, offered in [(1, False, False), (2, True, True), (3, False, True)]:
        offered_job(state, ident, explicit=explicit, offered=offered)
        talk._save({'pending': {'where': 'coding', 'at': NOW.timestamp(), 'inquiry_id': ident,
                               'question': 'What is blocking the report?', 'behavior_context': context,
                               'explicit': explicit, 'offered': offered}})
        talk.pause(60)
    assert assess(state)['engagement']['declines'] == 1


def test_feedback_uses_original_interruption_context_not_current_activity(state, monkeypatch):
    from services.mind import talk, life_state
    monkeypatch.setattr(life_state, 'life_state', state)
    context = assess(state)['context']
    offered_job(state, 1)
    talk._save({'pending': {'where': 'coding', 'at': NOW.timestamp(), 'inquiry_id': 1,
                           'question': 'What is blocking the report?', 'behavior_context': context,
                           'explicit': False, 'offered': True}})
    monkeypatch.setattr(talk, '_learn_answer', lambda *args: None)
    talk.hear('I need the review notes from my teammate', now=NOW.timestamp() + 20)
    assert assess(state, now=NOW + timedelta(seconds=30))['engagement']['answers'] == 1
    assert assess(state, now=NOW + timedelta(seconds=30), live={**LIVE, 'activity': 'entertainment'})['engagement']['answers'] == 0


def offered_job(state, ident, explicit=False, offered=True):
    from services.mind.inquiry import Inquiry
    with Inquiry(state.store)._db() as db:
        db.execute('INSERT INTO inquiry_jobs(id,signature,token,epoch,expires,state,explicit,created,retry_at,question) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)', (ident, str(ident), 'synthetic', 0, NOW.timestamp() + 90,
                    'submitted' if offered else 'prepared', int(explicit), NOW.timestamp(), 0,
                    'What is blocking the report?'))


def test_notification_cannot_override_quiet_but_urgent_or_requested_notice_keeps_contract(monkeypatch):
    from services.mind import notifications
    monkeypatch.setattr(config, 'NOTIFICATION_REVIEW_ENABLED', True)
    snapshot = {'life_state': {'can_initiate': False}, 'live': {}, 'busy': False}
    assert not notifications._suitable(notifications.Candidate('An optional tip'), snapshot, snapshot, NOW)
    assert notifications._suitable(notifications.Candidate('A warning', urgent=True), snapshot, snapshot, NOW)
    assert notifications._suitable(notifications.Candidate('Your requested reminder', kind='reminder'), snapshot, snapshot, NOW)
    assert notifications._suitable(notifications.Candidate('Mode ended', kind='status'), snapshot, snapshot, NOW)
    assert notifications._suitable(notifications.Candidate('Requested work finished', kind='work_completion'), snapshot, snapshot, NOW)


def test_forgotten_inquiry_cannot_restore_timing_state(state):
    from services.mind import life_state
    context = assess(state)['context']
    offered_job(state, 1)
    state.store.clear()
    state.feedback(context, 'shushed', 'inquiry:1', NOW)
    assert assess(state)['engagement']['declines'] == 0


def test_feedback_and_forgetting_are_serialized_across_connections(state):
    from concurrent.futures import ThreadPoolExecutor
    from services.mind.life_state import LifeState
    context = assess(state)['context']
    offered_job(state, 1)
    other = LifeState(Cognition(state.store.path))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(other.feedback, context, 'shushed', 'inquiry:1', NOW),
                   pool.submit(state.store.clear)]
        for future in futures:
            future.result()
    assert assess(state)['engagement']['declines'] == 0


def test_prepared_or_explicit_job_cannot_be_mislabeled_as_autonomous_feedback(state):
    context = assess(state)['context']
    offered_job(state, 1, offered=False)
    offered_job(state, 2, explicit=True)
    state.feedback(context, 'shushed', 'inquiry:1', NOW)
    state.feedback(context, 'answered', 'inquiry:2', NOW)
    view = assess(state)['engagement']
    assert view['declines'] == view['answers'] == 0


def test_behavior_does_not_change_every_second_or_with_our_model_thinking(state):
    one = assess(state)
    two = assess(state, now=NOW + timedelta(seconds=10), live={**LIVE, 'thinking': True})
    assert one == two


def test_notification_rechecks_life_state_after_model_approval(monkeypatch):
    from services.mind import notifications
    monkeypatch.setattr(config, 'NOTIFICATION_REVIEW_ENABLED', True)
    sent, calls = [], []
    async def context(now):
        return {'life_state': {'can_initiate': not calls}, 'live': {}, 'busy': False}
    async def reason(*args):
        calls.append(True)
        return [notifications.Choice(id='0', send=True, reason='Initially suitable')]
    monkeypatch.setattr(notifications, '_context', context)
    monkeypatch.setattr(notifications, '_reason', reason)
    candidate = notifications.Candidate('An optional tip', transport=lambda *a, **kw: sent.append(a) or True)
    asyncio.run(notifications.dispatch(notifications.Batch(NOW, [candidate])))
    assert calls and not sent


def test_inquiry_respects_quiet_without_calling_a_model_and_allows_own_pending_delivery(state, monkeypatch):
    import copy
    from services.mind.inquiry import Inquiry, Decision
    from services.mind import talk
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    control = Inquiry(state.store)
    data = {'evidence': {'task:1': {'kind': 'task', 'status': 'active', 'blocker': 'Waiting for notes'}},
            'present': {'pending': False, 'idle': 10}, 'preferences': {}, 'history': [],
            'life_state': assess(state, preferences={'on': False})}
    monkeypatch.setattr(control, 'snapshot', lambda now: copy.deepcopy(data))
    calls = []
    async def think(payload):
        calls.append(payload)
        return Decision(ask=True, question='When will the review notes arrive?', topic='review notes',
                        basis=['task:1'], reason='A useful blocker timing gap',
                        purpose={'gap': 'task:1:blocker', 'decision': 'Choose whether to continue the report now.',
                                 'if_answer_a': {'answer': 'Notes expected soon', 'next_step': 'Propose continuing the blocked report later today.'},
                                 'if_answer_b': {'answer': 'Notes delayed', 'next_step': 'Propose deferring the blocked part.'},
                                 'usefulness': 'changes_decision'})
    async def approve(line, now):
        return line
    monkeypatch.setattr(control, 'think', think)
    monkeypatch.setattr('services.mind.notifications.approve_question', approve)
    assert asyncio.run(control.propose(NOW)) is None and not calls
    data['life_state'] = assess(state)
    line = asyncio.run(control.propose(NOW))
    assert line and line['behavior_context'] == assess(state)['context']
    talk._save({'pending': {'inquiry_id': line['inquiry_id'], 'at': NOW.timestamp()}})
    data['present']['pending'] = True
    data['life_state'] = {**data['life_state'], 'can_initiate': False, 'interruption_blocks': ['pending_reply']}
    assert control.deliverable(line['inquiry_id'], NOW)
    data['life_state']['interruption_blocks'].append('learned_cooldown')
    assert not control.deliverable(line['inquiry_id'], NOW)


def test_quiet_state_still_reaches_actual_executive_model_review(state, monkeypatch):
    import json
    from services.mind import executive, reasoning
    from services.mind.reasoning_store import ReasoningStore
    from providers.base_provider import ProviderResponse
    for flag in ('COGNITION_ENABLED', 'REASONING_ENABLED', 'COGNITIVE_REVIEW_ENABLED'):
        monkeypatch.setattr(config, flag, True)
    known = {'task:1': {'kind': 'task', 'status': 'active', 'title': 'Finish report', 'blocker': 'Waiting for notes'}}
    policy = assess(state, known=known, preferences={'on': False})
    monkeypatch.setattr(executive, 'attention_state', lambda: {**LIVE, 'life_state': policy})
    monkeypatch.setattr('services.mind.cognition_context.live_state', lambda: dict(LIVE))
    monkeypatch.setattr('services.mind.talk.load', lambda: {'on': False})
    source_store = ReasoningStore(state.store)
    monkeypatch.setattr(reasoning, 'reasoning_store', source_store)
    monkeypatch.setattr(source_store, 'evidence', lambda: known)
    control = executive.ExecutiveControl(state.store)
    monkeypatch.setattr(control, '_known', lambda: known)
    calls = []
    async def complete(*args, **kwargs):
        calls.append(json.loads(args[1][0].content))
        assert all(branch['properties']['work_kind']['const'] != 'situations'
                   for branch in kwargs['response_schema']['oneOf'])
        assert kwargs['response_schema']['$defs']['Conclusion']['properties']['evidence']['items']['enum'] == ['task:1']
        return ProviderResponse(content='{"work_kind":"silence"}',
                                provider='ollama', model='test')
    monkeypatch.setattr('providers.failover.complete_with_failover', complete)
    assert asyncio.run(control.review(NOW))['status'] == 'completed'
    assert calls[0]['life_state']['focus']['aim'] == 'resolve_uncertainty'
    assert calls[0]['life_state']['can_review'] and not calls[0]['life_state']['can_initiate']


def test_local_api_and_feeling_share_behavior_without_remote_context(monkeypatch):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from services.mind import life, life_state
    from services.automation.intent import remote_request
    value = {'posture': 'quiet', 'reason': 'You requested quiet time.', 'can_review': True, 'can_initiate': False}
    monkeypatch.setattr(life_state, 'current', lambda *args, **kwargs: value)
    client = TestClient(create_app(), base_url='http://127.0.0.1')
    assert client.get('/api/v1/mind/life').json() == value
    assert life.feeling(NOW)['life_state'] == value
    token = remote_request.set(True)
    try:
        assert 'life_state' not in life.feeling(NOW) and 'situation' not in life.feeling(NOW)
    finally:
        remote_request.reset(token)


def test_cognitive_schema_allows_only_supplied_local_owner_and_revision_ids():
    from services.mind.reasoning import cognitive_schema
    known = {'owner_episode:4': {'kind': 'owner_answer', 'channel': 'voice'},
             'owner_episode:5': {'kind': 'owner_message', 'channel': 'telegram'},
             'temporal:7': {'kind': 'temporal_interpretation'}}
    schema = cognitive_schema(known)
    temporal = schema['$defs']['TemporalUpdate']['properties']
    assert temporal['source']['enum'] == ['owner_episode:4']
    assert temporal['supersedes']['items']['enum'] == ['temporal:7']
    assert [branch['properties']['work_kind']['const'] for branch in cognitive_schema({})['oneOf']] == ['silence']


@pytest.mark.parametrize('decline_before_delivery', [False, True])
def test_actual_question_delivery_and_quiet_control_drive_timing_feedback(state, monkeypatch, decline_before_delivery):
    from services.mind import talk, inquiry, life_state
    from services.reminders import service as transport
    monkeypatch.setattr(life_state, 'life_state', state)
    control = inquiry.Inquiry(state.store)
    monkeypatch.setattr(inquiry, 'inquiry', control)
    monkeypatch.setattr(control, 'deliverable', lambda *args: True)
    monkeypatch.setattr(talk.time, 'time', lambda: NOW.timestamp())
    monkeypatch.setattr('interfaces.api.routes.voice._speak_in_background', lambda *args: None)
    submitted = []
    monkeypatch.setattr(transport, 'show_toast', lambda *args, **kwargs: submitted.append(args) or True)
    offered_job(state, 1, offered=False)
    talk._record({'say': 'What is blocking the report?', 'inquiry_id': 1, 'explicit': False,
                  'behavior_context': assess(state)['context']}, 'coding', NOW.timestamp())
    if decline_before_delivery:
        talk.pause(60)
    asyncio.run(talk.deliver('What is blocking the report?'))
    if not decline_before_delivery:
        assert talk.load()['pending']['offered'] is True
        talk.pause(60)
    assert len(submitted) == (0 if decline_before_delivery else 1)
    assert assess(state)['engagement']['declines'] == (0 if decline_before_delivery else 1)
