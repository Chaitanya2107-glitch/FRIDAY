"""Finite private care controls through the existing signed command endpoint."""
import math
import re

from .commands import fields, no_args
from .security import Denied


def checkin_args(args):
    fields(args, ('score',))
    if type(args['score']) is not int or not 1 <= args['score'] <= 5:
        raise Denied('invalid_arguments')
    return dict(score=args['score'])


def care_status(service, device, args):
    no_args(args)
    from services.mind import care
    wellbeing = care.status().get('wellbeing') or {}
    # Scores, baselines and other private care data never enter this projection.
    return dict(wellbeing={key: wellbeing.get(key) is True
                           for key in ('confirmed', 'can_log', 'logged_today')})


def care_checkin(service, device, args):
    score = checkin_args(args)['score']
    from services.mind import care
    try:
        result = care.log_wellbeing(score)
    except (ValueError, PermissionError):
        raise Denied('care_checkin_unavailable') from None
    if result.get('recorded') is not True:
        raise Denied('care_checkin_unavailable')
    return dict(recorded=True)  # Do not echo the score to activity, chat or speech clients.


def answer_args(args):
    fields(args, ('id', 'choice'))
    if (not isinstance(args['id'], str) or not re.fullmatch('[a-f0-9]{32}', args['id'])
            or not isinstance(args['choice'], str) or args['choice'] not in {'remind15', 'leave'}):
        raise Denied('invalid_arguments')
    return dict(args)


def care_question(service, device, args):
    no_args(args)
    from services.mind import care
    value = care.phone_question()
    if value.get('pending') is not True:
        return dict(pending=False)
    identity, text = value.get('id'), value.get('text')
    if (not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity)
            or not isinstance(text, str) or not 1 <= len(text) <= 2000 or '\x00' in text):
        raise Denied('care_question_unavailable')
    return dict(pending=True, id=identity, text=text, choices=['remind15', 'leave'])


def care_answer(service, device, args):
    args = answer_args(args)
    from services.mind import care
    try:
        result = care.answer_notice(args['id'], args['choice'])
    except (ValueError, PermissionError):
        raise Denied('care_question_unavailable') from None
    if result.get('recorded') is not True:
        raise Denied('care_question_unavailable')
    return dict(recorded=True)


def goal_args(args):
    fields(args, ('id', 'value', 'receipt'))
    if (type(args['id']) is not int or args['id'] <= 0
            or type(args['value']) not in (int, float) or not 0 < args['value'] <= 1e6
            or not math.isfinite(args['value']) or not isinstance(args['receipt'], str)
            or not re.fullmatch('[a-f0-9]{32}', args['receipt'])):
        raise Denied('invalid_arguments')
    return dict(args)


def goal_status(service, device, args):
    no_args(args)
    from services.mind import goals
    try:
        value = goals.status()
    except (ValueError, PermissionError):
        raise Denied('goal_status_unavailable') from None
    return dict(goals=[{key: goal.get(key) for key in ('id', 'title', 'unit', 'manual', 'done', 'target')}
                       for goal in value.get('goals', [])])


def goal_log(service, device, args):
    args = goal_args(args)
    from services.mind import goals
    try:
        result = goals.manual_tap(args['id'], args['value'], args['receipt'], device_id=device['id'])
    except (ValueError, PermissionError):
        raise Denied('goal_log_unavailable') from None
    if result.get('recorded') is not True:
        raise Denied('goal_log_unavailable')
    return dict(recorded=True)


def register(registry):
    registry.register('care_status', care_status, risk='safe', validate=no_args)
    registry.register('care_checkin', care_checkin, risk='safe', validate=checkin_args)
    registry.register('care_question', care_question, risk='safe', validate=no_args)
    registry.register('care_answer', care_answer, risk='safe', validate=answer_args)
    registry.register('goal_status', goal_status, risk='safe', validate=no_args)
    registry.register('goal_log', goal_log, risk='safe', validate=goal_args)
