"""Private care/goal routing before history, models, training or generic confirmations."""
import asyncio
from datetime import datetime, timedelta
import json
import re
import sqlite3

from services.automation.results import ActionResult
from . import care

PRIVATE_MEMORY = 'Private coaching handled locally; no personal coaching text retained in conversation history.'
ALIASES = {'sleep': 'sleep', 'bedtime': 'sleep', 'break': 'breaks', 'breaks': 'breaks', 'eye rest': 'eye_rest',
           'eye-rest': 'eye_rest', 'water': 'water', 'stretch': 'stretch', 'wind down': 'wind_down', 'wind-down': 'wind_down',
           'phone use': 'phone_use', 'phone-use': 'phone_use', 'phone awareness': 'phone_use',
           'wellbeing': 'wellbeing', 'wellbeing check-in': 'wellbeing', 'weekly care review': 'weekly_review'}


def clean(text):
    from services.automation.command_words import strip_leading_filler
    return ' '.join(strip_leading_filler(text).strip().rstrip('.!?').split()).lower()


def care_kind(text):
    for name in sorted(ALIASES, key=len, reverse=True):
        if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text):
            return ALIASES[name]
    return None


def explicit_care(text):
    return bool(re.match(r'^(?:set up|setup|enable|start|turn on|change|disable|stop|turn off|move)\b', text) and care_kind(text)
                and (re.search(r'\bcare\b', text) or re.search(r'\bwellbeing(?: check-in)?\b', text))
                or text in {'care status', 'my care settings', 'weekly care review', 'show weekly care review', 'show private care check',
                            'my private care question', 'show care question', 'try care experiment', 'care experiments', 'offer phone dnd', 'my wellbeing check-ins'}
                or re.match(r'^(?:wellbeing|check-in|check in)\s+\d+\b', text)
                or text in {'i took a break', 'log care break', 'log eye rest', 'log water', 'log stretch'})


def pending():
    from . import goals
    return bool(care.store().pending() or goals.pending())


def cancel_pending():
    from . import goals
    care.store().cancel()
    goals.cancel_pending()


def private_turn(message):
    from . import care_safeguard, goals
    text = clean(message)
    return bool(care_safeguard.matches(message) or explicit_care(text) or goals.private_turn(message)
                or care.store().pending(include_expired=True))


def edit(proposal, text):
    d = dict(proposal['definition'])
    time_window = r'(?:from|between|window)\s+(\d{1,2}:\d{2})\s+(?:to|and|-)\s*(\d{1,2}:\d{2})'
    if found := re.search(time_window, text):
        d['window'] = [care.clock(value.zfill(5)) for value in found.groups()]
    if found := re.search(r'(?:cap|at most|max)\s+(\d+)', text):
        d['cap'] = int(found[1])
    if 'weekdays' in text:
        d['days'] = list(range(5))
    elif 'weekends' in text:
        d['days'] = [5, 6]
    elif 'daily' in text or 'every day' in text:
        d['days'] = list(range(7))
    if d['type'] in {'sleep', 'wind_down'}:
        bedtime_text = re.sub(r'wake\s+\d{1,2}:\d{2}', '', re.sub(time_window, '', text))
        if found := re.search(r'(?<!\d)(\d{1,2}:\d{2})', bedtime_text):
            d['limit'] = care.clock(found[1].zfill(5))
        if d['type'] == 'sleep' and (found := re.search(r'wake\s+(\d{1,2}:\d{2})', text)):
            d['wake'] = care.clock(found[1].zfill(5))
    elif found := re.search(r'(?:after|every|limit|to)?\s*(\d+)\s*(?:minutes?|mins?)\b', text):
        d['limit'] = int(found[1])
    if 'during study' in text or 'study blocks' in text:
        d['context'] = 'study'
    elif 'during class' in text:
        d['context'] = 'class'
    elif 'any context' in text:
        d['context'] = 'any'
    if found := re.search(r'categor(?:y|ies)\s+([a-z_, ]+?)(?=\s+(?:from|between|during|limit|cap|voice|every|after)\b|$)', text):
        d['categories'] = [v.strip().replace(' ', '_') for v in found[1].split(',')]
    if found := re.search(r'apps?\s+([a-z0-9_., ]+?)(?=\s+(?:from|between|during|limit|cap|voice|every|after)\b|$)', text):
        d['apps'] = [v.strip() for v in found[1].split(',')]
    if 'voice on' in text:
        d['voice'] = True
    if 'voice off' in text:
        d['voice'] = False
    return dict(proposal, definition=d)


def response(text, ok=True, **extra):
    from .wording import plain
    return dict(text=plain(dict(kind='care', answer=text)), ok=ok, **extra)


def draft(kind, text, now):
    from . import goals
    goals.cancel_pending()
    proposal = edit(care.propose(kind, now), text)
    care.store().stage(dict(step='setup', proposal=proposal), now)
    return response(care.preview(proposal), awaiting_reply=True, phone_private=kind == 'phone_use')


def _scene_preview(now):
    from services.plugin_runtime import current_manager
    manager = current_manager()
    scene = manager.get_service('scenes') if manager else None
    if scene is None:
        raise ValueError('The scenes plugin must be enabled to review a wind-down scene.')
    definition = manager.invoke(scene.api, lambda: scene.catalog.get('sleep'))
    body = manager.invoke(scene.api, lambda: scene.preview(definition))
    care.store().stage(dict(step='wind_scene', binding=definition['hash']), now)
    return response(body + '\nStart this reviewed scene? Yes or no.', awaiting_reply=True)


def handle_care(text, now):
    data = care.store()
    kind = care_kind(text)
    if text in {'care status', 'my care settings'}:
        rows = data.settings()
        return response('\n'.join(care.preview(dict(definition=r['definition'])) for r in rows) if rows else 'All care types are off until you choose settings and confirm.',
                        phone_private=any(r['definition']['type'] == 'phone_use' for r in rows))
    if text in {'weekly care review', 'show weekly care review'}:
        from .care_review import weekly, finish_experiments
        if not data.settings('weekly_review'):
            return draft('weekly_review', '', now)
        results = finish_experiments(now)
        suffix = '\nExperiment result: ' + '; '.join(f"baseline {r['baseline']}, observed {r['observed']}, change {r.get('delta')}; {r['state']}. No causal conclusion." for r in results) if results else ''
        return response(weekly(now)['text'] + suffix + '\nIf you want one measurable experiment, say try care experiment.', phone_private=True)
    if text == 'try care experiment':
        from .care_review import propose_experiment
        if not data.settings('weekly_review'):
            raise ValueError('Confirm weekly care review before choosing an experiment.')
        proposal = propose_experiment(now)
        data.stage(dict(step='experiment', id=proposal['id']), now)
        return response(proposal['text'], awaiting_reply=True, phone_private=True)
    if text == 'care experiments':
        from .outcome_learning import OutcomeLearning
        from .cognition import cognition
        from .care_review import finish_experiments
        finish_experiments(now)
        rows = OutcomeLearning(cognition).private_experiments()
        return response('\n'.join(f"{r['definition']['name']}: baseline {r['baseline']}, observed {r['observed']}, change {r.get('delta')}; {r['state']}. No causal conclusion." for r in rows) or 'No private care experiment is recorded.', phone_private=True)
    if text in {'show private care check', 'my private care question'}:
        question = care.phone_question(now)
        return response(question['text'] if question['pending'] else 'No current private phone-use question.', phone_private=True)
    if text == 'show care question':
        with data.db() as db:
            row = db.execute('SELECT * FROM care_notices WHERE answer IS NULL AND sent>? ORDER BY sent DESC LIMIT 1', (now.timestamp() - 900,)).fetchone()
        if not row:
            return response('No current private care question.')
        setting = data.settings(row['kind'])
        if not setting or not care.in_window(setting['definition'], now):
            return response('That care window has ended. No action was taken.')
        if row['kind'] == 'phone_use':
            return response(json.loads(row['payload'])['text'], phone_private=True)
        if row['kind'] == 'weekly_review':
            from .care_review import weekly
            data.answer(row['id'], 'accept', now)
            return response(weekly(now)['text'] + '\nYou may choose one experiment with try care experiment.', phone_private=True)
        data.stage(dict(step='wellbeing' if row['kind'] == 'wellbeing' else 'notice', id=row['id'], type=row['kind']), now)
        return response(json.loads(row['payload'])['text'], awaiting_reply=True)
    if text == 'my wellbeing check-ins':
        rows = data.entries(now - timedelta(days=7), now + timedelta(seconds=1), 'wellbeing')
        return response('\n'.join(f"{datetime.fromtimestamp(r['at']):%Y-%m-%d}: {r['amount']:g}/5 (your own entry)." for r in rows) or 'No self-reported check-ins in this window.')
    if found := re.fullmatch(r'(?:wellbeing|check-in|check in)\s+(\d+)', text):
        care.log_wellbeing(int(found[1]), now)
        data.cancel()
        return response('Your private check-in was recorded locally. No mood or health condition was inferred.')
    logs = {'i took a break': 'breaks', 'log care break': 'breaks', 'log eye rest': 'eye_rest', 'log water': 'water', 'log stretch': 'stretch'}
    if text in logs:
        data.log(logs[text], now=now)
        data.cancel()
        return response('Your own care entry was recorded. It is not a verified health measurement.')
    if re.match(r'^(?:disable|stop|turn off)\b', text) and kind:
        data.disable(kind)
        return response('That care type is off. Your other choices stay as you set them.')
    if text == 'offer phone dnd':
        if not data.settings('wind_down'):
            raise ValueError('Set up and confirm wind-down care first.')
        data.stage(dict(step='phone_dnd'), now)
        return response('Request FRIDAY-owned priority Do Not Disturb on your paired phone for 15 minutes? It requires the separate phone grant and restores on expiry. Confirm yes or no; it never unlocks anything.', awaiting_reply=True)
    if text.startswith('move ') and kind == 'phone_use':
        row = data.settings(kind)
        if not row or row['trust']['streak'] < 3:
            raise ValueError('Phone awareness stays at Ask. Three accepted checks are needed before offering Do and tell.')
        data.stage(dict(step='promote', revision=row['revision']), now)
        return response('Move phone awareness to Do and tell? It can send a generic private cue within your windows/cap; details still require opening the private check. It will not block apps or automatically change settings. Confirm yes or no.', awaiting_reply=True, phone_private=True)
    if explicit_care(text) and kind and re.match(r'^(?:set up|setup|enable|start|turn on|change)\b', text):
        return draft(kind, text, now)
    pending = data.pending(now, include_expired=True)
    if pending:
        if pending.get('expired') or text in {'cancel', 'no', 'no thanks', 'leave it'}:
            data.cancel()
            return response('No new care action was taken. The setup was cancelled or expired.')
        if pending['step'] == 'setup':
            proposal = pending['proposal']
            if text in {'yes', 'yes please', 'confirm'}:
                care.validate(proposal['definition'])
                data.confirm(proposal['definition'], now)
                return response('Confirmed. This care type is on only inside the displayed windows and cap; it starts at Ask.', phone_private=proposal['definition']['type'] == 'phone_use')
            proposal = edit(proposal, text)
            data.stage(dict(step='setup', proposal=proposal), now)
            return response(care.preview(proposal), awaiting_reply=True, phone_private=proposal['definition']['type'] == 'phone_use')
        if pending['step'] == 'wellbeing' and re.fullmatch('[1-5]', text):
            care.log_wellbeing(int(text), now)
            data.cancel()
            return response('Your private, self-entered check-in was recorded locally.')
        if text not in {'yes', 'yes please', 'confirm'}:
            return response('Please answer yes or cancel this private question.', awaiting_reply=True)
        if pending['step'] == 'experiment':
            from .outcome_learning import OutcomeLearning
            from .cognition import cognition
            if OutcomeLearning(cognition).confirm_private_experiment(pending['id'], now=now) is None:
                raise ValueError('That experiment expired; review a fresh proposal.')
            data.cancel()
            return response('Experiment confirmed for the displayed seven-day window. Only its recorded result will be compared next week.')
        if pending['step'] == 'promote':
            row = data.settings('phone_use')
            if not row or row['revision'] != pending['revision']:
                raise ValueError('The awareness definition changed. Review it again.')
            with data.db() as db:
                trust = dict(row['trust'], level='do_and_tell', promotion_offered=True)
                db.execute("UPDATE care_settings SET trust=? WHERE kind='phone_use'", (json.dumps(trust),))
            data.cancel()
            return response('Phone awareness is at Do and tell. No or leave it on a check returns it to Ask.', phone_private=True)
        if pending['step'] == 'phone_dnd':
            from services.presence.phone import send
            import uuid
            send('mode', dict(mode='dnd', value=2, token=uuid.uuid4().hex), ttl=900)
            data.cancel()
            return response('The reviewed phone DND request was queued for at most 15 minutes; this is not confirmation that the phone applied it.')
        if pending['step'] == 'wind_scene':
            from services.plugin_runtime import current_manager
            manager = current_manager(); scene = manager.get_service('scenes') if manager else None
            if not scene or manager.invoke(scene.api, lambda: scene.catalog.get('sleep')['hash']) != pending['binding']:
                raise ValueError('That scene changed; ask to review wind-down again.')
            data.cancel()
            result = manager.invoke(scene.api, lambda: scene.request('sleep'), command=True)
            return response(result['text'] + '\nPhone DND is separate: say offer phone DND to review it.', ok=result['ok'])
        if pending['step'] == 'notice':
            identity, kind = pending['id'], pending['type']
            data.answer(identity, 'accept', now)
            data.cancel()
            if kind in {'sleep', 'wind_down'}:
                return _scene_preview(now)
            return response('Accepted. Log a break or rest only after you actually take it; accepting this question does not count as taking one.')
    question = care.phone_question(now)
    if question['pending'] and text in {'remind me in 15 minutes', '15 minutes', 'remind15', 'leave it', 'no'}:
        choice = 'leave' if text in {'leave it', 'no'} else 'remind15'
        care.answer_notice(question['id'], choice, now)
        return response('Recorded. A chosen reminder still obeys your window, context and cap.' if choice == 'remind15' else 'Left it. No apps are blocked; the awareness rule is at Ask.', phone_private=True)
    return None


async def try_command(message, *, conversation=None, now=None):
    from . import care_safeguard, goals
    from services.remote.context import conversation_only
    from services.automation.intent import remote_request
    now = now or datetime.now()
    if care_safeguard.matches(message):
        await asyncio.to_thread(care_safeguard.activate, now)
        await asyncio.to_thread(cancel_pending)
        return ActionResult(True, care_safeguard.RESPONSE, PRIVATE_MEMORY, False, speech=care_safeguard.RESPONSE)
    text = clean(message)
    phone_answer = care.phone_question(now).get('pending') and text in {'remind me in 15 minutes', '15 minutes', 'remind15', 'leave it', 'no'}
    if not (explicit_care(text) or care.store().pending(now, include_expired=True) or goals.private_turn(message) or phone_answer):
        return None
    isolated = conversation_only.get() if conversation is None else conversation
    if isolated or remote_request.get():
        return ActionResult(False, 'Care and goal conversations stay private at the laptop. Use the signed private check-in controls on your phone. This text was not sent to a model.', PRIVATE_MEMORY, False, speech='')
    if care_safeguard.active(now):
        return ActionResult(True, 'Coaching and nudges are paused for the current 24-hour quiet period. You can still ask for ordinary help.', PRIVATE_MEMORY, False, speech='')
    try:
        if not explicit_care(text):
            from .goals_parser import parse as goal_definition
            if goal_definition(message, now) is not None:
                care.store().cancel()
        if explicit_care(text) or care.store().pending(now, include_expired=True) or phone_answer:
            value = await asyncio.to_thread(handle_care, text, now)
        else:
            care.store().cancel()
            sleep = care.store().settings('sleep')
            bounds = (sleep['definition']['limit'], sleep['definition']['wake']) if sleep else None
            value = await asyncio.to_thread(goals.handle, message, now, sleep=bounds)
        value = value or response('Use a confirmed care or measurable goal command; this private text was not sent to a model.', ok=False)
        if value.get('win'):
            from services.event_bus import event_bus
            event_bus.publish('mood.set', dict(mood='celebrating', duration_s=4, priority=1), plugin_id='coaching')
        phone_setting = care.store().settings('phone_use') if value.get('phone_private') else None
        allow_speech = not value.get('phone_private') or bool(phone_setting and phone_setting['definition']['voice'])
        return ActionResult(value.get('ok', True), value['text'], PRIVATE_MEMORY, False,
                            speech=value['text'] if allow_speech else '')
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        text = str(error) if isinstance(error, ValueError) else 'Private coaching data is unavailable; nothing was sent to a model.'
        return ActionResult(False, text, PRIVATE_MEMORY, False, speech='')
