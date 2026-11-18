"""Deterministic notices through shared attention, executive and interruption budgets."""
import asyncio
from datetime import datetime
import hashlib
import inspect

KINDS = {'presence_question', 'presence_rule', 'presence_greeting', 'presence_anticipation', 'notification_digest', 'notification_vip',
         'care_question', 'care_notice', 'goal_question', 'goal_notice'}


def eligible(now, urgent=False, kind=None):
    from services.mind.care_safeguard import active
    if active(now):
        return False
    from services.proactive.watcher import nudges_active, is_busy
    from services.quiet_mode import suppresses
    from services.mind import talk
    from services.mind.life_state import current as life
    from .engine import current
    care = kind in {'care_question', 'care_notice'}
    private_coaching = care or kind in {'goal_question', 'goal_notice'}
    preferences = talk.load()
    if not nudges_active(now.timestamp()) or not preferences.get('on', True) or preferences.get('paused_until', 0) > now.timestamp():
        return False
    if urgent and not private_coaching:
        return True
    clock = now.strftime('%H:%M')
    hours = preferences.get('quiet_hours') or {}
    start, end = hours.get('start'), hours.get('end')
    quiet_clock = bool(isinstance(start, str) and isinstance(end, str) and
                       (start <= clock < end if start <= end else clock >= start or clock < end))
    if quiet_clock or suppresses() or is_busy():
        return False
    presence = current(now)
    rule = kind in {'presence_question', 'presence_rule'}
    winding_care = care and presence['state'] == 'winding_down'
    if presence['state'] == 'asleep' or presence['state'] == 'winding_down' and not (rule or winding_care):
        return False
    if care and presence['state'] in {'in_class', 'commuting'}:
        return False
    behavior = life(now)
    if behavior.get('can_initiate', False):
        return True
    allowed = {'presence_restraint'} if rule or winding_care else set()
    # Reviewed safe automation and companion notices may run away from the desk;
    # a fresh Ask prompt still requires the owner's laptop attention.
    if kind != 'presence_question' and presence.get('device') and presence.get('data_available'):
        allowed |= {'owner_away', 'phone_attention'}
    blocks = set(behavior.get('interruption_blocks', []))
    return bool(blocks) and blocks <= allowed


async def submit(text, kind, now=None, *, urgent=False, key='', on_send=None):
    from core.config import config
    from services.mind.cognition import cognition
    from services.mind.executive import executive
    from services.mind.inquiry import inquiry
    now = now or datetime.now()
    if kind not in KINDS or not isinstance(text, str) or not 1 <= len(text) <= 4000:
        return False
    if not await asyncio.to_thread(eligible, now, urgent, kind):
        return False
    from services.mind.training import allows_nudge
    if not await asyncio.to_thread(allows_nudge, 'F.R.I.D.A.Y', text, now=now.timestamp(), urgent=urgent):
        return False
    question = kind in {'presence_question', 'care_question', 'goal_question'}
    if question and not await asyncio.to_thread(inquiry.can_interrupt, now):
        return False
    # Keys are hashes, so raw places/packages/notification text never enter cognition.
    identity = hashlib.sha256((kind + ':' + key).encode()).hexdigest()
    reservation = await asyncio.to_thread(executive.reserve_local, identity, kind, now)
    if reservation is None:
        return False
    event = cognition.record('notification_decision', 'presence', 'Local metadata notice reviewed.', status='approved', public=False)
    if question and not await asyncio.to_thread(inquiry.reserve_external, event, now):
        cognition.finish(event, 'suppressed')
        return False
    if not await asyncio.to_thread(eligible, now, urgent, kind):
        cognition.finish(event, 'suppressed')
        return False
    from services.mind.care_safeguard import active
    if active(now):
        cognition.finish(event, 'suppressed')
        return False
    try:
        if on_send is None:
            from .engine import current
            presence = await asyncio.to_thread(current, now)
            if presence.get('device') and presence['state'] != 'at_desk':
                from .phone import send
                await asyncio.to_thread(send, 'notice', dict(text=text, owner=identity), ttl=120)
                accepted = True  # Queued for the phone, never a claim that it was read.
            else:
                from services.reminders.service import show_toast
                accepted = await asyncio.to_thread(show_toast, 'FRIDAY', text, mirror_telegram=False,
                                                  cognition_public=False, cognition_text='Presence notice delivered.',
                                                  urgency='critical' if urgent else 'normal')
        else:
            accepted = await asyncio.to_thread(on_send)
            if inspect.isawaitable(accepted):
                accepted = await accepted
        cognition.finish(event, 'submitted' if accepted is True else 'failed')
        return accepted is True
    except Exception:
        cognition.finish(event, 'failed')
        return False
