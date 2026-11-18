"""Quiet, bounded private cues. No models, public care text or automatic settings changes."""
import asyncio
from datetime import datetime, timedelta
import time

from . import care, care_safeguard, coaching_metrics, care_triggers


def available():
    from . import coaching_commands
    from services.automation.intent import is_awaiting_confirmation
    from services import scene_runtime
    return not (coaching_commands.pending() or is_awaiting_confirmation() or scene_runtime.pending())


def deliver(candidate, now):
    if care_safeguard.active(now) or not available():
        return False
    from services.presence.runtime import situation
    identity = care.store().claim(candidate, now, context=situation(now))
    if not identity:
        return False
    generic = 'A private FRIDAY check is ready. Open the PWA private check, or ask FRIDAY to show your care question.'
    if care_safeguard.active(now):
        return False
    from services.presence.engine import current
    presence = current(now)
    if candidate['type'] == 'phone_use' or presence.get('device') and presence['state'] != 'at_desk':
        from services.presence.phone import send
        send('notice', dict(text=generic if candidate['type'] == 'phone_use' else candidate['text'], owner=identity), ttl=120)
        return True
    from services.reminders.service import show_toast
    return show_toast('FRIDAY', candidate['text'], mirror_telegram=False, cognition_public=False,
                      cognition_text='Private coaching cue delivered.') is True


async def tick(now=None, *, submit=None):
    from services.presence.delivery import submit as bounded_submit
    from services.presence.runtime import situation
    from services import schedule_adapter
    from . import goals
    now = now or datetime.now()
    started = time.monotonic()
    delivery_time = lambda: now + timedelta(seconds=max(0, time.monotonic() - started))
    if care_safeguard.active(now):
        return []
    submit = submit or bounded_submit
    sent = []
    settings = await asyncio.to_thread(care.store().settings)
    if settings:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        data = await asyncio.to_thread(coaching_metrics.snapshot, start, now)
        context = await asyncio.to_thread(situation, now)
        classes = await asyncio.to_thread(schedule_adapter.classes_on, now.date() + timedelta(days=1))
        entries = await asyncio.to_thread(care.store().entries, start, now)
        with care.store().db() as db:
            followups = [dict(r) for r in db.execute('SELECT * FROM care_followups WHERE expires>?', (now.timestamp(),))]
        for candidate in care_triggers.candidates(settings, now, data, classes=classes, context=context, followups=followups, entries=entries):
            if not available() or care_safeguard.active(now):
                break
            kind = 'care_notice' if next(r for r in settings if r['definition']['type'] == candidate['type'])['trust']['level'] == 'do_and_tell' else 'care_question'
            accepted = await submit('A private owner-confirmed care check is ready.', kind, now, key=candidate['key'],
                                    on_send=lambda c=candidate: deliver(c, delivery_time()))
            if accepted:
                sent.append(candidate['type'])
    for candidate in await asyncio.to_thread(goals.weekly_candidates, now):
        if not available() or care_safeguard.active(now):
            break
        def send_goal(c=candidate):
            moment = delivery_time()
            if care_safeguard.active(moment) or not available() or not any(row['key'] == c['key'] for row in goals.weekly_candidates(moment)):
                return False
            from services.reminders.service import show_toast
            generic = 'Your private weekly goal check is ready. Open private goals in the PWA, or ask for your coaching goals to see the numbers.'
            from services.presence.engine import current
            presence = current(moment)
            if presence.get('device') and presence['state'] != 'at_desk':
                from services.presence.phone import send
                import hashlib
                send('notice', dict(text=generic, owner=hashlib.sha256(c['key'].encode()).hexdigest()), ttl=120)
                goals.mark_weekly_sent(c['key'], moment)
                return True
            accepted = show_toast('FRIDAY', generic,
                                  mirror_telegram=False, cognition_public=False, cognition_text='Private goal cue delivered.') is True
            if accepted:
                goals.mark_weekly_sent(c['key'], now)
            return accepted
        if await submit('A private owner-confirmed goal check is ready.', 'goal_question', now, key=candidate['key'], on_send=send_goal):
            sent.append('goals')
    return sent
