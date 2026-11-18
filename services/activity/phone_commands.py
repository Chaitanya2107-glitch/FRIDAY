"""Anchored, private, model-free phone timeline queries."""
import re
from datetime import datetime, timedelta
from services.activity import timeline
from services.automation.results import ActionResult

PRIVATE_MEMORY = 'Phone activity handled locally; raw phone data was not retained in chat.'


def pending_reply(message):
    from services.mind import talk
    from services.automation.intent import remote_request, _match_local_step
    pending = talk.load().get('pending') or {}
    return bool(pending.get('phone_device') and not remote_request.get() and not _match_local_step(message))


def match_command(message):
    text = ' '.join(message.replace('’', "'").split()).strip(' .!?')
    text = re.sub(r'^(?:(?:hey |okay |ok )?friday[, ]+|please )+', '', text, flags=re.I)
    for expression, action in ((r'what am i using on my phone', 'current'), (r'which device have i used more today', 'compare'), (r'when did i last use my phone', 'last'), (r'what did i do after class', 'after_class')):
        if re.fullmatch(expression, text, re.I):
            return dict(action=action)
    found = re.fullmatch(r'how long was i on (.{1,200}) today', text, re.I)
    return dict(action='duration', app=found[1]) if found else None


def answer(parsed, now=None):
    from services.mind import wording
    now = now or datetime.now(); start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if parsed['action'] == 'last':
        start = now-timedelta(days=30)
    rows = timeline.segments(start, now); phone = [r for r in rows if r['device'] == 'phone']
    kind = parsed['action']
    if kind == 'compare':
        sums = timeline.totals(rows)
        text = f"Recorded today: laptop {round(sums['laptop']/60)} min; phone {round(sums['phone']/60)} min. Missing observations are not zero actual use."
    elif kind == 'duration':
        matching = [r for r in phone if parsed['app'].casefold() in {r['app'].casefold(), r.get('label', '').casefold()}]
        text = f"Recorded {parsed['app']} phone time today: {round(timeline.totals(matching)['phone']/60)} min."
    elif kind == 'after_class':
        from services.proactive import timetable
        ends = [datetime.combine(now.date(), datetime.strptime(c['end'], '%H:%M').time()).timestamp() for c in timetable.classes_for_date(now.date())]
        past = [t for t in ends if t <= now.timestamp()]
        after = [dict(r, start=max(r['start'], max(past))) for r in rows if past and r['end'] > max(past)]
        text = 'Recorded after the last scheduled class: ' + ', '.join(f"{r['device']} {r['app']} ({round((r['end']-r['start'])/60)} min)" for r in after[:12]) if after else 'No observations after a completed scheduled class are available.'
    elif phone:
        last = max(phone, key=lambda r: r['end']); age = now.timestamp()-last['end']
        text = (f"Last recorded phone app: {last.get('label', last['app'])}, ending {datetime.fromtimestamp(last['end']):%H:%M}. " + ('Recent observation, not live foreground proof.' if age <= 180 else 'The observation is stale.'))
    else:
        text = 'No phone app observations are available today.'
    return wording.plain(dict(kind='phone_answer', answer=text))


async def handle(message, provider=None):
    import asyncio
    from services.automation.intent import remote_request
    if remote_request.get():
        return ActionResult(False, 'Phone activity queries are local-only; use the signed timeline panel.', memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
    return ActionResult(True, await asyncio.to_thread(answer, match_command(message)), memory_message=PRIVATE_MEMORY, repeatable=False, speech='')
