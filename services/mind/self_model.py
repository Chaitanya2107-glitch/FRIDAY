"""Calibrate phrasing and autonomy from recorded outcomes and owner verdicts."""

from collections import defaultdict
import json
import sqlite3

from core.config import config
from core.logger import logger

LABELS = {'class_schedule': 'class schedule changes', 'inferred_deadlines': 'deadlines I inferred',
          'app_explanation': 'app explanations', 'knowledge_explanation': 'general explanations',
          'next_app': 'which app you might open next', 'set_volume': 'setting volume', 'set_mute': 'muting audio',
          'start_mode': 'starting modes', 'end_mode': 'ending modes', 'reasoning': 'reviewed suggestions',
          'presence_rule': 'presence rules'}


def label(kind):
    return LABELS.get(kind, kind.replace('_', ' '))


def suggestion_kind(claim):
    effect = claim.get('effect', {}).get('type')
    return {'reminder_move': 'inferred_deadlines', 'class_availability': 'class_schedule',
            'task_plan': 'task_plans'}.get(effect, 'reasoning')


def _outcomes():
    from services.automation import autonomy
    from services.mind import knowledge
    from services.mind.outcome_learning import outcome_learning
    from services.mind.reasoning_store import reasoning_store

    groups = defaultdict(list)
    if not config.COGNITION_ENABLED:
        return groups
    for row in outcome_learning.recent(limit=200):
        if row['state'] == 'verified' or row['state'] == 'failed':
            groups[row['action']].append(row['state'] == 'verified')
    try:
        runs = autonomy.load()['runs']
    except (OSError, ValueError) as error:
        logger.debug('Autonomy feedback unavailable (%s)', type(error).__name__)
        runs = []
    for row in reversed(runs):
        automatic = row.get('origin') == 'automatic'
        rule = 'rule' in row
        if (automatic and (row.get('demoted') or row.get('reviewed'))
                or rule and (row.get('demoted') or row.get('accepted') and row.get('status') == 'completed')):
            skill = 'presence_rule' if 'rule' in row else row.get('action')
            if skill:
                groups[skill].append(not row.get('demoted'))
    with knowledge.db() as db:
        for row in db.execute("SELECT verdict FROM prediction_reviews WHERE verdict IN ('correct','wrong') "
                              'ORDER BY verified_at DESC,thought_id DESC LIMIT 200'):
            groups['next_app'].append(row['verdict'] == 'correct')
        for row in db.execute("SELECT key,state FROM app_explanations WHERE description!='' "
                              "AND state IN ('confirmed','corrected','rejected') ORDER BY resolved_at DESC LIMIT 200"):
            kind = 'app_explanation' if row['key'].startswith('app:') else 'knowledge_explanation'
            groups[kind].append(row['state'] == 'confirmed')
    with reasoning_store._db() as db:
        for row in db.execute("SELECT status FROM temporal_proposals WHERE status IN ('accepted','rejected') ORDER BY id DESC LIMIT 200"):
            groups['inferred_deadlines'].append(row['status'] == 'accepted')
        for row in db.execute("SELECT body,status FROM reasoning_conclusions WHERE status IN ('applied','rejected') ORDER BY id DESC LIMIT 200"):
            claim = json.loads(row['body'])
            groups[suggestion_kind(claim)].append(row['status'] == 'applied')
    return groups


def _profile(records):
    right = sum(records)
    corrected = len(records) - right
    recent, previous = records[:5], records[5:10]
    drift = (sum(recent) / len(recent) - sum(previous) / len(previous)) if previous else 0
    trend = ('improving' if drift >= .15 else 'declining' if drift <= -.15 else 'steady') if previous else 'too early to tell'
    return {'right': right, 'corrected': corrected, 'confidence': (right + 1) / (len(records) + 2), 'trend': trend}


def profiles():
    try:
        return {kind: _profile(rows) for kind, rows in _outcomes().items() if rows}
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        logger.debug('Self-model outcome history unavailable (%s)', type(error).__name__)
        return {}


def ceiling(kind):
    """An index into the existing Ask, Do and tell, Just do ladder."""
    row = profiles().get(kind)
    if not row or not row['corrected']:
        return 2
    if row['corrected'] >= 2 and row['confidence'] < .5:
        return 0
    return 1 if row['confidence'] < .75 or row['trend'] == 'declining' else 2


def qualify(kind, text):
    row = profiles().get(kind)
    if row and row['corrected'] and row['confidence'] < .75:
        return f"I'm less sure about {label(kind)}. {text}"
    return text


def describe():
    rows = profiles()
    if not rows:
        return 'I can read class times from your timetable. I have too few checked outcomes to say which skills I get right most often.'
    parts = []
    for kind, row in sorted(rows.items(), key=lambda item: (-item[1]['confidence'], item[0])):
        confidence = 'usually right' if row['right'] >= 3 and row['confidence'] >= .7 else 'still learning'
        parts.append(f"I'm {confidence} about {label(kind)}. {row['right']} right, {row['corrected']} corrected or failed, "
                     f"trend {row['trend']}.")
    return 'I read class times from your timetable.\n' + '\n'.join(parts)
