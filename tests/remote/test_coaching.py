"""Care taps are finite, scoped, live-only and never expose personal scores."""
import json
import sys
from types import SimpleNamespace

import pytest

from services.mind import __name__ as mind_name
from services.remote import coaching
from services.remote.security import Denied


@pytest.fixture
def private_care(remote, monkeypatch):
    calls = []
    state = dict(confirmed=True, can_log=True, logged_today=False, score=5,
                 raw_text='private check-in value must not leave care')

    def log(score):
        if not state['confirmed'] or not state['can_log']:
            raise ValueError('Private care setting unavailable')
        calls.append(score)
        return dict(recorded=True, score=score, raw_text=state['raw_text'])

    question = dict(pending=True, id='a' * 32, text='About 50 minutes on short videos in your study block. Remind you in 15 minutes, or leave it?',
                    choices=['remind15', 'leave'], raw='private source rows')
    def answer(identity, choice):
        if not state['confirmed'] or not state['can_log'] or identity != question['id']:
            raise ValueError('Private care question unavailable')
        calls.append((identity, choice))
        return dict(recorded=True, private='must not be projected')
    care = SimpleNamespace(status=lambda: dict(wellbeing=state, sleep='private sleep baseline'), log_wellbeing=log,
                           phone_question=lambda: question, answer_notice=answer)
    import services.mind
    monkeypatch.setitem(sys.modules, mind_name + '.care', care)
    monkeypatch.setattr(services.mind, 'care', care, raising=False)
    if 'care_status' not in remote.service.registry.commands:
        coaching.register(remote.service.registry)
    return state, calls


@pytest.mark.parametrize('args', [None, {}, {'score': True}, {'score': False}, {'score': 0}, {'score': 6},
    {'score': 3.0}, {'score': '3'}, {'score': None}, {'score': [3]}, {'score': 3, 'text': 'private'},
    {'score': 3, 'when': 'tomorrow'}, {'score': 3, 'confirmed': True}])
def test_numeric_checkin_has_no_content_or_consent_override_fields(args):
    with pytest.raises(Denied):
        coaching.checkin_args(args)


def test_status_is_only_consent_window_and_recorded_booleans(remote, private_care):
    state, _ = private_care
    reply = remote.command('care_status')
    assert reply.status_code == 200
    assert reply.json()['data'] == dict(wellbeing=dict(confirmed=True, can_log=True, logged_today=False))
    state.update(confirmed='yes', can_log=1, logged_today='false')
    assert remote.command('care_status').json()['data'] == dict(wellbeing=dict(
        confirmed=False, can_log=False, logged_today=False))
    assert remote.command('care_status', dict(score=2)).status_code == 404


def test_checkin_uses_gate_and_allowlist_without_echo_or_private_audit(remote, private_care):
    _, calls = private_care
    path = '/remote/v1/commands'
    raw = json.dumps(dict(command='care_checkin', args=dict(score=4))).encode()
    assert remote.client.post(path, content=raw).status_code == 404
    assert not calls
    reply = remote.command('care_checkin', dict(score=4))
    assert reply.status_code == 200 and reply.json()['data'] == dict(recorded=True)
    assert calls == [4]
    audit = remote.service.audit.path.read_text(encoding='utf-8')
    assert 'score' not in audit and 'private check-in' not in audit and 'sleep baseline' not in audit
    assert remote.service.registry.get('care_checkin').risk == 'safe'
    assert remote.service.registry.get('care_status').risk == 'safe'
    remote.service.fence_off()
    assert remote.command('care_checkin', dict(score=4)).status_code == 404
    assert calls == [4]


@pytest.mark.parametrize('setting', ['confirmed', 'can_log'])
def test_no_tap_before_confirmation_or_outside_window(remote, private_care, setting):
    state, calls = private_care
    state[setting] = False
    assert remote.command('care_checkin', dict(score=3)).status_code == 404
    assert not calls


def test_checkin_never_enters_safe_offline_queue(remote, private_care):
    _, calls = private_care
    path = '/remote/v1/queue'
    raw = json.dumps(dict(id='private-checkin-123456', command='care_checkin', args=dict(score=5),
                         created=remote.now[0], expires_at=remote.now[0] + 900)).encode()
    assert remote.client.post(path, content=raw, headers=remote.signed('POST', path, raw)).status_code == 404
    assert not calls


@pytest.mark.parametrize('args', [None, {}, {'id': 'a' * 32}, {'id': True, 'choice': 'leave'},
    {'id': 'A' * 32, 'choice': 'leave'}, {'id': 'a' * 31, 'choice': 'leave'},
    {'id': 'a' * 32, 'choice': True}, {'id': 'a' * 32, 'choice': 'block'},
    {'id': 'a' * 32, 'choice': 'leave', 'text': 'private'},
    {'id': 'a' * 32, 'choice': 'remind15', 'minutes': 10}])
def test_private_answer_is_bound_to_one_question_and_two_finite_choices(args):
    with pytest.raises(Denied):
        coaching.answer_args(args)


def test_details_need_an_explicit_signed_request_and_answers_drop_private_fields(remote, private_care):
    _, calls = private_care
    assert remote.command('care_question', dict(text='private')).status_code == 404
    reply = remote.command('care_question')
    assert reply.status_code == 200
    question = reply.json()['data']
    assert question == dict(pending=True, id='a' * 32,
        text='About 50 minutes on short videos in your study block. Remind you in 15 minutes, or leave it?',
        choices=['remind15', 'leave'])
    assert remote.command('care_answer', dict(id=question['id'], choice='leave')).json()['data'] == dict(recorded=True)
    assert calls == [(question['id'], 'leave')]
    assert 'short videos' not in remote.service.audit.path.read_text(encoding='utf-8')
    assert remote.command('care_answer', dict(id='b' * 32, choice='remind15')).status_code == 404
    assert calls == [(question['id'], 'leave')]


@pytest.fixture
def private_goals(remote, monkeypatch):
    calls, seen = [], set()
    state = dict(allowed=True, gets=0, recorded=True)
    values = [dict(id=1, title='Private water goal', unit='glasses', manual=True, done=0.0,
                   target=8.0, raw='Private source rows'),
              dict(id=2, title='Study', unit='minutes', manual=False, done=None, target=25.0)]

    def status():
        state['gets'] += 1
        return dict(goals=values, private='not projected')

    def tap(identity, value, receipt, *, device_id):
        if not state['allowed']:
            raise PermissionError('Private goal safeguard')
        if identity != 1:
            raise ValueError('Automatic goals cannot be logged manually')
        calls.append((identity, value, receipt, device_id))
        if receipt not in seen:
            seen.add(receipt)
            values[0]['done'] += value
        return dict(recorded=state['recorded'], private='not projected')

    goals = SimpleNamespace(status=status, manual_tap=tap)
    import services.mind
    monkeypatch.setitem(sys.modules, mind_name + '.goals', goals)
    monkeypatch.setattr(services.mind, 'goals', goals, raising=False)
    if 'goal_status' not in remote.service.registry.commands:
        coaching.register(remote.service.registry)
    return state, calls, values


@pytest.mark.parametrize('change', [dict(id=True), dict(id=0), dict(id=-1), dict(id=1.0),
    dict(id='1'), dict(value=True), dict(value=0), dict(value=-1), dict(value='1'),
    dict(value=None), dict(value=float('nan')), dict(value=float('inf')), dict(value=1_000_001),
    dict(value=10 ** 400), dict(receipt=True), dict(receipt='a' * 31), dict(receipt='A' * 32),
    dict(receipt='../' + 'a' * 29), dict(title='private'), dict(device_id='override')])
def test_manual_goal_args_are_finite_and_do_not_accept_content_or_device_override(change):
    args = dict(id=1, value=1, receipt='a' * 32)
    args.update(change)
    with pytest.raises(Denied):
        coaching.goal_args(args)


@pytest.mark.parametrize('args', [None, {}, dict(id=1), dict(id=1, value=1)])
def test_manual_goal_args_need_exact_fields(args):
    with pytest.raises(Denied):
        coaching.goal_args(args)


def test_goal_details_are_explicit_projected_and_no_args(remote, private_goals):
    state, _, values = private_goals
    assert state['gets'] == 0
    assert remote.command('goal_status', dict(id=1)).status_code == 404
    assert state['gets'] == 0
    response = remote.command('goal_status')
    assert response.status_code == 200
    assert response.json()['data'] == dict(goals=[{key: row[key] for key in
        ('id', 'title', 'unit', 'manual', 'done', 'target')} for row in values])
    assert state['gets'] == 1
    assert remote.service.registry.get('goal_status').risk == 'safe'


def test_goal_tap_uses_signed_gate_device_receipt_and_private_ack_only(remote, private_goals):
    _, calls, values = private_goals
    args = dict(id=1, value=1, receipt='a' * 32)
    path = '/remote/v1/commands'
    raw = json.dumps(dict(command='goal_log', args=args)).encode()
    assert remote.client.post(path, content=raw).status_code == 404
    assert not calls
    for _ in range(2):
        reply = remote.command('goal_log', args)
        assert reply.status_code == 200 and reply.json()['data'] == dict(recorded=True)
    assert calls == [(1, 1, 'a' * 32, remote.device['id'])] * 2
    assert values[0]['done'] == 1
    assert remote.service.registry.get('goal_log').risk == 'safe'
    audit = remote.service.audit.path.read_text(encoding='utf-8')
    assert 'Private water goal' not in audit and 'receipt' not in audit and 'glasses' not in audit
    remote.service.fence_off()
    assert remote.command('goal_log', args).status_code == 404
    assert len(calls) == 2


def test_manual_goal_rejects_automatic_source_safeguard_and_unrecorded_reply(remote, private_goals):
    state, calls, _ = private_goals
    args = dict(id=2, value=1, receipt='a' * 32)
    assert remote.command('goal_log', args).status_code == 404
    state['allowed'] = False
    assert remote.command('goal_log', dict(args, id=1)).status_code == 404
    assert not calls
    state.update(allowed=True, recorded=False)
    assert remote.command('goal_log', dict(args, id=1)).status_code == 404


@pytest.mark.parametrize('command,args', [('goal_status', {}), ('goal_log', dict(id=1, value=1, receipt='a' * 32))])
def test_private_goals_never_enter_offline_queue(remote, private_goals, command, args):
    state, calls, _ = private_goals
    path = '/remote/v1/queue'
    raw = json.dumps(dict(id='private-goal-log-123456', command=command, args=args,
                         created=remote.now[0], expires_at=remote.now[0] + 900)).encode()
    assert remote.client.post(path, content=raw, headers=remote.signed('POST', path, raw)).status_code == 404
    assert not calls and state['gets'] == 0
