"""Private, deterministic pause tests use temporary storage and fake transports only."""
import asyncio
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from core.config import config
from services.mind import care_safeguard as safeguard


@pytest.mark.parametrize('text', list(safeguard.PATTERNS) + [
    "Friday, I really want to die tonight.", "I'm going to hurt myself", "I can't keep myself safe",
    "Please help. I don't want to live anymore.", "I’m thinking about suicide.",
])
def test_reviewable_first_person_phrases(text):
    assert safeguard.matches(text)


@pytest.mark.parametrize('text', [
    'I do not want to hurt myself', 'I am not suicidal', 'I want to live',
    'It is not true that I want to die.', 'I am not saying I want to die.',
    'I do not think I want to die.', 'She says I want to die.',
    'My friend said I want to kill myself.', "My girlfriend said I'm thinking about suicide.",
    'Write a regex for I want to die.', 'Translate I want to die into French.',
    'Build a safeguard for I want to hurt myself.', 'If I say I want to die, pause nudges.',
    'The example is "I want to die".', "The example is 'I want to hurt myself'.",
    '```python\nmessage = "I want to die"\n```', '`I am suicidal` is a test case.',
    'My friend wants to hurt herself', 'I am tired after class', 'I died in the game',
])
def test_negated_quoted_reported_or_code_examples_are_not_disclosures(text):
    assert not safeguard.matches(text)


def test_default_off_and_only_deadline_is_stored_with_exact_24h_expiry(monkeypatch):
    import services.remote
    monkeypatch.setattr(services.remote, '_service', None)
    now = datetime.now()
    assert not safeguard.active(now) and not safeguard.path().exists()
    text = "I want to hurt myself"
    assert safeguard.matches(text)
    until = safeguard.activate(now)
    assert until == now.timestamp() + 86400
    assert json.loads(safeguard.path().read_text()) == {'paused_until': until}
    assert text not in safeguard.path().read_text()
    assert safeguard.active(now + timedelta(hours=23, minutes=59))
    assert not safeguard.active(now + timedelta(hours=24))
    assert not safeguard.active(now + timedelta(hours=25))
    assert not (config.MEMORY_DIR / 'phone' / 'transport.db').exists()


@pytest.mark.parametrize('contents', ['broken', '{}', '{"paused_until":NaN}', '{"paused_until":false}',
                                      '{"paused_until":-1}', '{"paused_until":0,"text":"forbidden"}'])
def test_damaged_pause_state_fails_closed(contents):
    safeguard.path().parent.mkdir(parents=True, exist_ok=True)
    safeguard.path().write_text(contents)
    assert safeguard.active()


def test_unreadable_state_and_failed_write_remain_paused(monkeypatch):
    from services import settings_store
    now = datetime.now()
    monkeypatch.setattr(settings_store, 'save', lambda *args: (_ for _ in ()).throw(OSError('read only')))
    safeguard.activate(now)
    assert safeguard.active(now + timedelta(hours=1))
    assert not safeguard.active(now + timedelta(hours=24))


def test_activation_withholds_old_question_without_learning_rejection(monkeypatch):
    from services.mind import talk
    from services.proactive import watcher
    from services.mind.inquiry import inquiry
    talk._save({'on': True, 'pending': {'question': 'An old optional question', 'inquiry_id': 4}})
    watcher._held.append('old nudge')
    talk.asks().put_nowait('old queued speech')
    marks = []
    monkeypatch.setattr(inquiry, 'mark', lambda identity, state: marks.append((identity, state)))
    safeguard.activate()
    assert not watcher._held and 'pending' not in talk.load() and talk.asks().empty()
    assert marks == [(4, 'withheld')]
    assert talk.load()['on'] is True


def test_activation_removes_only_undelivered_automatic_companion_notices(monkeypatch):
    import services.remote
    from services.remote.transport_store import TransportStore
    monkeypatch.setattr(services.remote, '_service', None)
    store = TransportStore(config.MEMORY_DIR / 'phone' / 'transport.db')
    device = 'test-phone'
    removed = [store.put(device, kind, {'kind': label, 'text': 'automatic'})
               for kind, label in [('notice', 'presence'), ('notice', 'care'), ('text', 'goal')]]
    kept = [store.put(device, kind, payload) for kind, payload in [
        ('text', {'text': 'owner handoff'}), ('link', {'url': 'https://example.com'}),
        ('ring', {}), ('approval', {}), ('phone_mode', {'restore': True}),
    ]]
    delivered = store.put(device, 'notice', {'kind': 'care'})
    store.ack(device, [delivered])
    safeguard.activate()
    with store.db() as db:
        ids = {row[0] for row in db.execute('SELECT id FROM outbox')}
    assert not ids.intersection(removed) and ids == set(kept + [delivered])


def test_pause_prevents_model_review_and_rechecks_a_late_queue(monkeypatch):
    from services.mind import notifications
    now = datetime.now()
    calls = []
    async def forbidden(*a, **k): pytest.fail('Paused/private coaching called model review')
    monkeypatch.setattr(notifications, '_reason', forbidden)
    for kind in ('care_question', 'care_notice', 'goal_question', 'goal_notice'):
        assert not asyncio.run(notifications.notify('private care data', kind=kind, transport=lambda *a: calls.append(a), now=now))
    safeguard.activate(now)
    batch = notifications.Batch(now, [notifications.Candidate('old queued nudge', transport=lambda *a, **k: calls.append(a), urgent=True)])
    assert not asyncio.run(notifications.dispatch(batch)) and not calls
    assert not asyncio.run(notifications.consider(batch.candidates, now))['0'][0]


def test_pause_during_notification_review_withholds_transport(monkeypatch):
    from services.mind import notifications
    now = datetime.now()
    calls = []
    async def review(*args):
        safeguard.activate(now)
        result = notifications.Decisions({'0': (True, None)})
        result.context = {}
        return result
    monkeypatch.setattr(notifications, 'consider', review)
    batch = notifications.Batch(now, [notifications.Candidate('queued before pause', transport=lambda *a, **k: calls.append(a))])
    assert not asyncio.run(notifications.dispatch(batch)) and not calls


def test_paused_talk_never_saves_or_speaks_and_owner_commands_still_work(monkeypatch):
    from services.mind import talk
    from services.memory.sqlite_memory import MemoryService
    from interfaces.api.routes import voice
    now = datetime.now()
    safeguard.activate(now)
    monkeypatch.setattr(MemoryService, 'save_message', lambda *a, **k: pytest.fail('Paused talk was stored'))
    monkeypatch.setattr(voice, '_speak_in_background', lambda *a, **k: pytest.fail('Paused talk was spoken'))
    assert not talk.may_talk({'on': True}, now.timestamp(), False, 10)
    asyncio.run(talk.deliver('an old queued question'))
    # The pause does not change the normal owner command setting.
    assert talk.run({'action': 'talk_on'})
    assert safeguard.active(now)


def test_focus_keeps_history_while_completion_nudge_is_silent(tmp_path):
    from test_focus_plugin import FakeAPI, FakeClock
    from plugins.focus.timer import Focus
    api, clock = FakeAPI(tmp_path / 'focus'), FakeClock(datetime.now().astimezone())
    focus = Focus(api, clock)
    assert focus.start(1)['ok']
    safeguard.activate(clock.now())
    clock.advance(60)
    focus.tick()
    assert focus.data['history'][0]['completed'] and not api.notifications and not api.moods
    assert any(topic == 'focus.done' for topic, payload in api.events)


def test_automatic_and_delayed_briefing_speech_are_held_but_manual_text_works(tmp_path):
    from briefing_fakes import make_brief
    brief, clock, api = make_brief(tmp_path)
    assert brief.request('morning', reason='manual')['ok']
    jobs = list(api.jobs)
    safeguard.activate(clock.now())
    for job in jobs:
        job(api.stop_event)
    assert not api.spoken
    count = len(api.payloads('briefing.ready'))
    brief.request('night', reason='clock')
    assert len(api.payloads('briefing.ready')) == count
    assert brief.request('night', reason='manual')['ok']
    assert len(api.payloads('briefing.ready')) == count + 1


def test_other_plugins_withhold_nudges_but_keep_owner_cards(tmp_path):
    from services.plugin_api import PluginAPI
    calls = []
    manager = SimpleNamespace(notify=lambda *a: calls.append(a),
                              bus=SimpleNamespace(publish=lambda *a, **k: calls.append((a, k))))
    api = PluginAPI(manager, 'test', tmp_path / 'plugin')
    safeguard.activate()
    assert api.notify('A break?', 'old nudge', 'critical') is False
    api.publish('ui.card', {'title': 'Automatic', 'urgency': 'normal'})
    api.publish('activity.nudge', {})
    assert not calls
    api.publish('ui.card', {'title': 'Owner confirmation', 'urgency': 'critical'})
    assert len(calls) == 1


def test_private_questions_share_existing_daily_budget_without_model(tmp_path, monkeypatch):
    from services.mind.cognition import Cognition
    from services.mind import executive as executive_module, inquiry as inquiry_module, training
    from services.mind.executive import ExecutiveControl
    from services.mind.inquiry import Inquiry
    from services.presence import delivery
    monkeypatch.setattr(config, 'COGNITION_ENABLED', True)
    monkeypatch.setattr(config, 'COGNITIVE_REVIEW_ENABLED', True)
    monkeypatch.setattr(config, 'REASONING_ENABLED', False)
    monkeypatch.setattr(executive_module, 'executive', ExecutiveControl(Cognition(tmp_path / 'review.db')))
    questions = Inquiry(Cognition(tmp_path / 'questions.db'))
    monkeypatch.setattr(inquiry_module, 'inquiry', questions)
    monkeypatch.setattr(delivery, 'eligible', lambda *a: True)
    monkeypatch.setattr(training, 'allows_nudge', lambda *a, **k: True)
    monkeypatch.setattr(training, 'show_toast', lambda *a, **k: pytest.fail('Private coaching entered training recorder'))
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    sent = []
    for i, kind in enumerate(('care_question', 'goal_question', 'care_question', 'goal_question')):
        allowed = asyncio.run(delivery.submit('private care numbers', kind, now + timedelta(minutes=45 * i), key=str(i),
                                             on_send=lambda: sent.append(True) or True))
        assert allowed is (i < 3)
    assert len(sent) == 3


def test_presence_and_private_callbacks_recheck_pause_after_reservation(tmp_path, monkeypatch):
    from services.presence import delivery
    from services.mind import executive, training
    now, sent = datetime.now(), []
    monkeypatch.setattr(delivery, 'eligible', lambda *a: True)
    monkeypatch.setattr(training, 'allows_nudge', lambda *a, **k: True)
    def reserve(*args):
        safeguard.activate(now)
        return 'reserved'
    monkeypatch.setattr(executive.executive, 'reserve_local', reserve)
    assert not asyncio.run(delivery.submit('a private notice', 'care_notice', now, on_send=lambda: sent.append(True)))
    assert not sent


def test_winding_down_care_is_narrow_and_never_bypasses_owner_quiet(monkeypatch):
    from services.presence import delivery, engine
    from services.proactive import watcher
    from services.mind import talk, life_state
    from services import quiet_mode
    monkeypatch.setattr(watcher, 'nudges_active', lambda stamp: True)
    monkeypatch.setattr(watcher, 'is_busy', lambda: False)
    monkeypatch.setattr(talk, 'load', lambda: {'on': True})
    monkeypatch.setattr(quiet_mode, 'suppresses', lambda: False)
    state = dict(state='winding_down', device='phone', data_available=True)
    monkeypatch.setattr(engine, 'current', lambda now: state)
    monkeypatch.setattr(life_state, 'current', lambda now: dict(can_initiate=False, interruption_blocks=['presence_restraint']))
    now = datetime.now()
    assert delivery.eligible(now, kind='care_question')
    assert delivery.eligible(now, kind='care_notice')
    assert not delivery.eligible(now, kind='goal_notice')
    for name in ('asleep', 'in_class', 'commuting'):
        state['state'] = name
        assert not delivery.eligible(now, kind='care_notice', urgent=True)
    state['state'] = 'winding_down'
    monkeypatch.setattr(quiet_mode, 'suppresses', lambda: True)
    assert not delivery.eligible(now, kind='care_notice', urgent=True)
