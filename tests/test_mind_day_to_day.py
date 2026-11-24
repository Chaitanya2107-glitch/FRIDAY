import asyncio
from collections import Counter
from datetime import datetime, timedelta

import pytest

from core.config import config
from providers import failover
from providers.base_provider import ProviderResponse
from services.automation import autonomy, intent
from services.mind import app_learning, emotion, knowledge, rhythm, self_model, speech_budget, state
from services.presence import delivery, engine
from services.proactive import deadlines, timetable


MONDAY = datetime(2026, 11, 16)


@pytest.fixture(scope='module', params=('off', 'on'))
def mode(request):
    return request.param


@pytest.fixture(autouse=True)
def settings(monkeypatch, mode):
    monkeypatch.setattr(config, 'FRIDAY_LLM', mode)
    monkeypatch.setattr(config, 'AI_KNOWLEDGE_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'JOURNAL_HOUR', '22')


def command(text):
    return asyncio.run(intent.try_system_action(text, 'ollama'))


def test_simulated_week_stays_below_ceiling_and_explains_every_line(monkeypatch):
    monkeypatch.setattr(delivery, 'eligible', lambda *args: True)
    monkeypatch.setattr(engine, 'current', lambda *args, **kwargs: {'state': 'at_desk', 'confidence': .91})
    sent = []

    async def week():
        for day in range(7):
            for slot in range(5):
                at = MONDAY + timedelta(days=day, hours=9, minutes=30 * slot)
                text = f'Check-in {day}/{slot}'
                def transport():
                    sent.append((at, text))
                    return True
                if await delivery.submit(text, 'presence_greeting', at, key=text, on_send=transport):
                    ident = speech_budget.budget.latest_since(at, 1)
                    if day <= 1:
                        speech_budget.feedback(ident, 'acted_on' if slot == 0 else 'answered', at + timedelta(seconds=10))
                    elif day <= 3:
                        speech_budget.feedback(ident, 'shushed', at + timedelta(seconds=10))

    asyncio.run(week())
    counts = Counter(at.date() for at, _ in sent)
    assert len(counts) == 7 and max(counts.values()) == speech_budget.DAILY_LIMIT == 3
    assert counts[(MONDAY + timedelta(days=3)).date()] < speech_budget.DAILY_LIMIT
    for at, text in sent:
        reply = command(f'why did you say "{text}"?')
        assert reply.success and 'presence_confidence=0.91' in reply.message
        assert 'mood' in reply.message and 'hard maximum 3' in reply.message and 'welcome counts' in reply.message
    assert 'no recorded cause' in command('why did you say "I never said this"?').message
    with speech_budget.budget._db() as db:
        assert db.execute("SELECT COUNT(*) FROM speech_decisions WHERE decision='blocked'").fetchone()[0] == 35 - len(sent)
        assert {row[0] for row in db.execute('SELECT DISTINCT reaction FROM life_reactions')} >= {'acted_on', 'answered', 'ignored', 'shushed'}


@pytest.mark.parametrize('state_name,reason', [('exam', 'exam mode'), ('study', 'focus'), ('sleep', 'sleep'), ('quiet', 'quiet mode')])
def test_hard_states_win_over_positive_feedback(monkeypatch, state_name, reason):
    from services import quiet_mode
    from services.mind.life_state import life_state

    now = MONDAY.replace(hour=14)
    context, _, _ = speech_budget.current(now)
    for i in range(6):
        life_state.feedback(context, 'acted_on', str(i), now - timedelta(minutes=i + 1))
    if state_name == 'quiet':
        quiet_mode.set_owner('behavior-test', True)
    else:
        monkeypatch.setattr(state, 'focus_state', lambda: (state_name, {}, state_name == 'study'))
    assert speech_budget.budget.decide(now, 'test', 'Optional line', reason='A useful observation.') is None
    with speech_budget.budget._db() as db:
        import json
        row = db.execute('SELECT cause,charged FROM speech_decisions ORDER BY id DESC LIMIT 1').fetchone()
        assert json.loads(row['cause'])['budget_reason'] == reason and row['charged'] == 0


def test_timetable_phase_reaches_snapshot_and_emotion(monkeypatch):
    timetable._save([dict(day='monday', start='09:00', end='10:00', subject='Physics', room=None)])
    at = {'data_available': False}
    assert rhythm.current(MONDAY.replace(hour=6, minute=59), attention=at)['phase'] == 'asleep'
    wake = rhythm.current(MONDAY.replace(hour=7), attention=at)
    assert wake['phase'] == 'waking' and wake['source'] == 'timetable'
    assert rhythm.current(MONDAY.replace(hour=9), attention=at)['phase'] == 'active'
    assert rhythm.current(MONDAY + timedelta(days=1, hours=7), attention=at)['phase'] == 'asleep'
    wind = state.snapshot(MONDAY.replace(hour=22, minute=5), fresh=True)
    assert wind['rhythm']['phase'] == 'winding_down' and wind['rhythm']['nightly_due']
    assert wind['emotion']['drives']['tiredness'] >= .26
    assert emotion.snapshot(MONDAY.replace(hour=12), daily_rhythm=rhythm.current(MONDAY.replace(hour=12), attention=at))['drives']['tiredness'] < .26


def test_p3_sleep_estimate_takes_precedence_and_adds_tiredness(monkeypatch):
    sleep = dict(data_available=True, sleep_estimate=True, confidence=.65, attention='away')
    early = MONDAY.replace(hour=6)
    asleep = rhythm.current(early, attention=sleep)
    assert asleep['source'] == 'phone_sleep_estimate' and asleep['phase'] == 'asleep'
    monkeypatch.setattr(rhythm, '_completed_sleep', lambda now: {'first_unlock': early.timestamp(), 'seconds': 4 * 3600,
                                                               'health_minutes': None})
    awake = rhythm.current(early + timedelta(minutes=20), attention={**sleep, 'sleep_estimate': False, 'attention': 'phone'})
    assert awake['phase'] == 'waking' and awake['source'] == 'phone_wake_estimate'
    assert awake['sleep_minutes_estimate'] == 240 and awake['tiredness'] > .17


def test_winding_down_closes_diary_and_consolidates_once(monkeypatch):
    from services.activity import insights, journal
    from services.mind import learner, life, reflection
    from services.mind.brain_memory import brain_memory
    from services.mind.consolidation import consolidation
    from services.proactive import watcher

    monkeypatch.setattr(journal, 'evening_note', lambda *args: None)
    monkeypatch.setattr(insights, 'write_command_dataset', lambda *args: None)
    monkeypatch.setattr(learner, 'train', lambda *args: None)
    async def no_reflection(*args):
        return None
    monkeypatch.setattr(reflection, 'reflect', no_reflection)
    brain_memory.remember('The draft is ready.', question='How is the lab report going?', now=MONDAY.replace(hour=15))
    brain_memory.remember('I finished the conclusion.', question='How is the lab report going?', now=MONDAY.replace(hour=19))

    async def exercise():
        for hour in (21, 22, 23):
            now = MONDAY.replace(hour=hour)
            observed = rhythm.current(now, attention={'data_available': False})
            await watcher._close_day_if_due(now, observed)
            if hour == 21:
                assert not life.diary_path.exists() and not consolidation.evidence()

    asyncio.run(exercise())
    assert len(life.diary_path.read_text(encoding='utf-8').splitlines()) == 1
    threads = list(consolidation.evidence().values())
    assert len(threads) == 1 and len(threads[0]['excerpts']) == 2


def test_outcome_history_lowers_wording_confidence_and_effective_autonomy():
    from services.mind.outcome_learning import outcome_learning

    autonomy.update(lambda state: state['actions'].update(set_mute={'level': autonomy.SILENT, 'streak': 0}))
    for i, observed in enumerate([True, False]):
        at = MONDAY + timedelta(hours=9, minutes=i)
        outcome_learning.finish(outcome_learning.begin('set_mute', {'muted': True}, at), {'muted': observed}, True, at)
        if i == 0:
            confidence = self_model.profiles()['set_mute']['confidence']
            assert autonomy.action_level('set_mute') == autonomy.SILENT
    row = self_model.profiles()['set_mute']
    assert (row['right'], row['corrected'], row['trend']) == (1, 1, 'too early to tell')
    assert row['confidence'] < confidence and autonomy.action_level('set_mute') == autonomy.TELL
    assert self_model.qualify('set_mute', 'I can mute the audio.').startswith("I'm less sure")
    assert '1 right, 1 corrected' in command('what are you good at?').message


def test_unknown_app_is_only_used_after_confirmation(mode, monkeypatch):
    from services.activity import categories

    calls = []
    async def complete(provider, messages, *args, **kwargs):
        calls.append((messages[0].content, kwargs['purpose']))
        return ProviderResponse('{"known":true,"what":"A local music editor.","category":"music"}', 'ollama', 'fake')
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    answer = command('learn app Starlightdesk')
    thing = knowledge.get('app:starlightdesk')
    assert answer.success and thing.about is None and not thing.placed
    assert categories.app_category('starlightdesk') == 'other'
    row = app_learning.pending(thing.key)[0]
    if mode == 'off':
        assert calls == [] and row['provider'] == 'waiting for model' and 'inbox' in answer.message
        assert command('yes').success and knowledge.get(thing.key).about is None
        assert 'waiting for an answer' in command('what did you learn this week?').message
        assert command('verify app Starlightdesk').success
        assert command('It is a music editor.').success
    else:
        assert calls == [('What is "Starlightdesk"?', 'knowledge')]
        assert row['provider'] == 'ollama' and 'Is that right?' in answer.message
        assert command('yes').success
    assert knowledge.get(thing.key).about and categories.app_category('starlightdesk') == 'music'
    assert not app_learning.pending(thing.key)
    assert 'Starlightdesk' in command('what did you learn this week?').message.split('Pending')[0]


@pytest.mark.parametrize('prompt,key', [
    ('learn course code CS404', 'course:cs404'),
    ('identify place Willow Square', 'place:willow square'),
    ('what is lexical entrainment?', 'topic:lexical entrainment'),
])
def test_teacher_uses_one_inbox_for_named_things(mode, monkeypatch, prompt, key):
    async def complete(*args, **kwargs):
        assert mode == 'on' and kwargs['purpose'] == 'knowledge'
        return ProviderResponse('{"known":true,"what":"An example definition.","category":"other"}', 'ollama', 'fake')

    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    offer = command(prompt)
    assert offer.success and offer.memory_message == 'I asked you to review an unverified explanation.'
    thing = knowledge.get(key)
    assert thing.about is None and app_learning.pending(key)
    assert command('yes' if mode == 'on' else 'It is an example definition.').success
    assert knowledge.get(key).about == ('An example definition.' if mode == 'on' else 'an example definition.')


def test_risky_assisted_parse_needs_a_fresh_yes(mode, monkeypatch):
    calls, closed = [], []
    async def complete(*args, **kwargs):
        calls.append(kwargs['purpose'])
        return ProviderResponse('{"command":"close chrome"}', 'ollama', 'fake')

    monkeypatch.setattr(config, 'AI_ASSIST_ONLY', True)
    monkeypatch.setattr(config, 'AI_LANGUAGE_ENABLED', True)
    monkeypatch.setattr(failover, 'complete_with_failover', complete)
    monkeypatch.setattr(intent.system, 'list_apps', lambda: ['chrome'])
    monkeypatch.setattr(intent.system, 'close_app', lambda name: closed.append(name) or f'Closed {name}.')
    result = command('I have finished with Chrome, dismiss its windows for me')
    assert not closed
    if mode == 'on':
        assert calls == ['understanding'] and result and 'Reply yes or no' in result.message
        assert command('yes').success and closed == ['chrome']
    else:
        assert not calls and not intent.is_awaiting_confirmation()


def test_exact_batch_runs_through_public_router_and_keeps_time(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 19, 14, tzinfo=tz)

    monkeypatch.setattr(deadlines, 'datetime', Clock)
    monkeypatch.setattr(intent, 'datetime', Clock)
    deadlines.add('Physics homework', Clock(2026, 11, 21, 17, 30), Clock.now())
    deadlines.add('Optics report', Clock(2026, 11, 19, 18, 30), Clock.now())
    def physics_due():
        return next(row['due'] for row in deadlines.load() if row['what'] == 'Physics homework')

    result = command('push my physics homework to Friday and tell me what is due tomorrow')
    assert result.success and 'Physics homework at 5:30 PM' in result.message and 'Optics report' not in result.message
    assert physics_due() == '2026-11-20T17:30'
    question = command('move my Physics homework')
    assert not question.success and 'What date' in question.message
    assert command('Monday').success and physics_due() == '2026-11-23T17:30'
