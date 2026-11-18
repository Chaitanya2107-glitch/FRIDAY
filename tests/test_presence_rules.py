import asyncio
from datetime import datetime

import pytest

from scenes_support import make_scenes, put_scene
from services.presence.rules import eligible, matches, parse, validate
from services.presence.rule_store import RuleStore


@pytest.fixture
def host(tmp_path, monkeypatch):
    from services import plugin_runtime
    value = make_scenes(tmp_path)
    monkeypatch.setattr(plugin_runtime, '_manager', value.manager)
    put_scene(value, name='reading', actions=[dict(type='set_volume', percent=20)])
    yield value
    value.engine.close(); value.api.stop(); value.manager.bus.close()


def state(host, place='home', name='at_home', edge=None, confidence=.9):
    return dict(state=name, place=place, confidence=confidence, since=host.clock.value, data_available=True,
                transition=None if edge is None else dict(id=edge, event='arrive', place=place, at=host.clock.value))


async def allowed(text, **options):
    return bool(options['on_send']())


def drain(host, submit=allowed):
    return asyncio.run(host.engine.presence.drain(datetime.fromtimestamp(host.clock.value), submit=submit))


def save(host, text='when I reach college start reading mode'):
    value = host.engine.presence.draft(parse(text))
    assert value['data']['awaiting_confirmation'] and not host.engine.presence.store.load()['rules']
    assert not host.desktop.calls
    host.engine.answer('yes')
    return host.engine.presence.store.load()['rules'][0]


def arrive(host, edge):
    presence = host.engine.presence
    presence.tick(presence=state(host))
    host.clock.value += 5
    presence.tick(presence=state(host, 'college', 'at_college_free', edge=edge))


@pytest.mark.parametrize('text,expected', [
    ('when I reach college start class mode', ('presence', 'arrive', 'class')),
    ('when I leave home tell me what is due today', ('presence', 'leave', 'read_due_today')),
    ('at 11 pm start sleep mode', ('time', '23:00', 'sleep')),
    ('at 12 am start reading mode', ('time', '00:00', 'reading')),
])
def test_finite_offline_grammar(text, expected):
    value = parse(text)
    assert value['trigger']['type'] == expected[0]
    assert value['trigger'].get('event', value['trigger'].get('at')) == expected[1]
    assert value['actions'][0].get('name', value['actions'][0]['type']) == expected[2]


@pytest.mark.parametrize('text', [
    'at 5:30pm tomorrow remind me to Call Mom',
    'Friday, could you please at 5:30pm tomorrow remind me to Call Mom',
    'when I leave home remind me to Call Mom',
    'open reading mode',
])
def test_presence_matcher_preserves_other_native_commands(monkeypatch, text):
    from services.presence import commands
    from types import SimpleNamespace
    # Other scene implementations need not provide presence-specific methods.
    monkeypatch.setattr(commands, 'controller', lambda: (None, SimpleNamespace(), None))
    assert not commands.match_command(text)


@pytest.mark.parametrize('definition', [
    dict(trigger=dict(type='presence', event='arrive', place='home', extra='x'), conditions={}, actions=[dict(type='read_due_today')]),
    dict(trigger=dict(type='presence', event='enter_state', state='invented'), conditions={}, actions=[dict(type='read_due_today')]),
    dict(trigger=dict(type='time', at='25:00'), conditions={}, actions=[dict(type='read_due_today')]),
    dict(trigger=dict(type='time', at='23:00'), conditions={'days': ['invented']}, actions=[dict(type='read_due_today')]),
    dict(trigger=dict(type='time', at='23:00'), conditions={}, actions=[dict(type='shell', text='run')]),
    dict(trigger=dict(type='time', at='23:00'), conditions={}, actions=[dict(type='phone_mode', ringer='silent', dnd='none')]),
])
def test_unknown_fields_and_risky_escape_hatches_are_rejected(definition):
    with pytest.raises(ValueError): validate(definition)


def test_weekday_overnight_and_class_conditions():
    definition = parse('at 11 pm start sleep mode')
    definition['conditions'] = dict(days='weekdays', after='22:00', before='06:00', in_class=False)
    validate(definition)
    assert eligible(definition, datetime(2026, 11, 16, 23), {'in_class': False})
    assert not eligible(definition, datetime(2026, 11, 15, 23), {'in_class': False})
    assert not eligible(definition, datetime(2026, 11, 16, 12), {'in_class': False})
    assert not eligible(definition, datetime(2026, 11, 16, 23), {'in_class': True})


def test_save_requires_confirm_and_source_change_invalidates_approval(host):
    rule = save(host)
    assert rule['level'] == 'ask' and rule['confirmed']
    definition = parse('when I leave home tell me what is due today')
    host.engine.presence.draft(definition)
    host.engine.answer('no')
    assert len(host.engine.presence.store.load()['rules']) == 1
    data = host.engine.presence.store.load()
    data['rules'][0]['definition']['trigger']['place'] = 'library'
    from services.settings_store import save as write
    write(host.engine.presence.store.path, data)
    assert host.engine.presence.store.get(rule['id'])['confirmed'] is None


def test_staging_is_inert_budget_denial_and_duplicate_slots(host):
    save(host)
    arrive(host, 'arrival-one')
    assert not host.desktop.calls and not host.engine.pending
    async def denied(*a, **k): return False
    assert not drain(host, denied)
    assert not host.desktop.calls and not host.engine.pending
    host.engine.presence.tick(presence=state(host, 'college', 'at_college_free', 'arrival-one'))
    assert drain(host)
    assert host.engine.pending['kind'] == 'presence_run'
    assert not host.desktop.calls
    host.engine.answer('no')
    host.engine.presence.tick(presence=state(host, 'college', 'at_college_free', 'arrival-one'))
    assert not host.engine.presence.proposal


def test_accept_three_offer_once_promote_then_undo_and_down(host):
    rule = save(host)
    for index in range(3):
        arrive(host, f'arrival-{index}')
        assert drain(host)
        assert host.engine.answer('yes')['ok']
        assert host.engine.active and host.engine.active.get('remote_origin')
        assert host.engine.presence.store.get(rule['id'])['streak'] == index + 1
        host.engine.end()
    assert host.engine.presence.proposal['kind'] == 'promote'
    assert drain(host)
    assert host.engine.pending['kind'] == 'presence_promote'
    host.engine.answer('yes')
    assert host.engine.presence.store.get(rule['id'])['level'] == 'do_and_tell'
    arrive(host, 'automatic-arrival')
    assert drain(host) and host.engine.active and not host.engine.pending
    receipt = host.engine.presence.store.last_run()
    assert receipt['status'] == 'completed'
    assert host.engine.presence.undo()['ok']
    assert host.engine.active is None and host.desktop.audio['scalar'] == .734
    assert host.engine.presence.store.get(rule['id'])['level'] == 'ask'
    assert host.engine.presence.store.get(rule['id'])['promotion_offered'] is True


def test_risky_scene_and_phone_mode_never_promote(host):
    rule = save(host, 'when I reach college start class mode')
    assert host.engine.presence.actions.risky(rule['definition'])
    host.engine.presence.store.patch(rule['id'], level='do_and_tell', streak=3)
    arrive(host, 'class-arrival')
    assert drain(host)
    assert host.engine.pending['kind'] == 'presence_run'
    assert host.engine.presence.store.get(rule['id'])['level'] == 'ask'
    assert host.engine.presence.actions.risky(dict(actions=[dict(type='phone_mode', ringer='silent')]))


def test_scene_preview_acceptance_counts_only_after_actual_start(host):
    put_scene(host, name='reading', actions=[dict(type='set_volume', percent=20)], confirm_first_run=True)
    rule = save(host)
    arrive(host, 'preview-arrival'); drain(host)
    host.engine.answer('yes')
    assert host.engine.pending['kind'] == 'start' and not host.engine.active
    assert host.engine.presence.store.get(rule['id'])['streak'] == 0
    assert host.engine.presence.store.last_run()['status'] == 'awaiting_confirmation'
    host.engine.answer('yes')
    assert host.engine.presence.store.get(rule['id'])['streak'] == 1
    assert host.engine.presence.store.last_run()['status'] == 'completed'


def test_bootstrap_old_arrivals_and_stale_answer_do_not_act(host):
    save(host)
    first = state(host, 'college', 'at_college_free', 'startup-arrival')
    host.engine.presence.tick(presence=first)
    host.engine.presence.tick(presence=first)
    assert not host.engine.presence.proposal
    arrive(host, 'new-arrival'); drain(host)
    host.engine.presence.tick(presence=state(host, 'home', 'at_home'))
    assert not host.engine.answer('yes')['ok'] and not host.desktop.calls


def test_scene_file_changes_require_rule_review_again(host):
    rule = save(host)
    host.engine.presence.store.patch(rule['id'], level='do_and_tell')
    put_scene(host, name='reading', actions=[dict(type='set_volume', percent=30)])
    arrive(host, 'changed-scene')
    drain(host)
    assert host.engine.pending['kind'] == 'presence_review' and not host.desktop.calls
    host.engine.answer('yes')
    assert host.engine.presence.store.get(rule['id'])['level'] == 'ask'


def test_presence_json_trigger_cannot_bypass_confirmed_once(host):
    put_scene(host, name='test', actions=[dict(type='set_volume', percent=20)],
              triggers=[dict(type='presence', event='arrive', place='college', auto=True)])
    arrive(host, 'json-arrival')
    drain(host)
    assert host.engine.pending['kind'] == 'presence_review' and not host.desktop.calls
    host.engine.answer('yes')
    assert not host.desktop.calls


def test_run_receipt_precedes_effect_and_undo_does_not_steal_new_scene(host, monkeypatch):
    save(host)
    actual = host.engine.presence.actions.effect
    def effect(*args):
        assert host.engine.presence.store.last_run()['status'] == 'running'
        return actual(*args)
    monkeypatch.setattr(host.engine.presence.actions, 'effect', effect)
    arrive(host, 'durable-arrival'); drain(host); host.engine.answer('yes')
    host.engine.request('game')
    host.engine.answer('yes')
    assert not host.engine.presence.can_undo()


def test_rule_commands_stay_private_and_remote_cannot_confirm(host, monkeypatch):
    from services.presence import commands
    from services.automation.intent import remote_request
    value = asyncio.run(commands.try_command('when I reach college start reading mode'))
    assert value.success and value.memory_message == commands.PRIVATE_MEMORY
    token = remote_request.set(True)
    try:
        assert not asyncio.run(commands.try_command('yes')).success
        assert host.engine.pending['kind'] == 'presence_save'
    finally:
        remote_request.reset(token)
    assert asyncio.run(commands.try_command('no')).success


def test_phone_mode_requires_grant_and_undo_restores_only_its_owner(host, monkeypatch):
    import services.presence
    calls = []
    from types import SimpleNamespace
    grant = [False]
    def send(kind, payload, ttl):
        if not grant[0]:
            raise ValueError('Phone mode was not granted')
        calls.append((kind, payload))
        return 'a' * 32
    monkeypatch.setattr(services.presence, 'phone', SimpleNamespace(send=send, cancel=lambda identity: False), raising=False)
    definition = parse('when I reach college start reading mode')
    definition['actions'] = [dict(type='phone_mode', ringer='silent')]
    host.engine.presence.draft(definition); host.engine.answer('yes')
    rule = host.engine.presence.store.load()['rules'][0]
    arrive(host, 'ungranted-mode'); drain(host)
    assert not host.engine.answer('yes')['ok'] and not calls
    assert host.engine.presence.store.get(rule['id'])['streak'] == 0
    grant[0] = True
    arrive(host, 'granted-mode'); drain(host)
    assert host.engine.answer('yes')['ok']
    owner = calls[0][1]['owner']
    assert calls[0][1]['ringer'] == 'silent'
    assert host.engine.presence.undo()['ok']
    assert calls[-1] == ('mode', {'restore_owner': owner})


def test_shared_question_cannot_be_stolen_by_staged_rule(host):
    from services.automation import intent
    save(host)
    arrive(host, 'busy-arrival')
    intent._ask_first({'action': 'delete_installers'}, 'Delete?')
    try:
        assert not drain(host)
        assert not host.engine.pending and not host.desktop.calls
        assert intent.is_awaiting_confirmation()
    finally:
        intent.cancel_pending_confirmation()


def test_queries_are_estimates_and_never_touch_a_model(host, monkeypatch):
    from services.presence import commands
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'services.presence.engine', SimpleNamespace(current=lambda: {
        'state': 'at_college_free', 'confidence': .8, 'reason': 'college place and no current class', 'data_available': True}))
    value = asyncio.run(commands.try_command('where am I'))
    assert value.success and 'estimate' in value.message and '80%' in value.message
    assert value.memory_message == commands.PRIVATE_MEMORY


def test_forget_clears_phone_trust_and_receipts_without_undoing_scene(host):
    phone = save(host)
    now = datetime.fromtimestamp(host.clock.value)
    time_definition = parse(f'at {(now.hour + 2) % 24:02}:{now.minute:02} start reading mode')
    host.engine.presence.draft(time_definition); host.engine.answer('yes')
    time_rule = host.engine.presence.store.load()['rules'][1]
    host.engine.presence.store.patch(time_rule['id'], level='do_and_tell', streak=4, promotion_offered=True)
    host.engine.presence.store.patch(phone['id'], level='do_and_tell', streak=4, promotion_offered=True)
    arrive(host, 'forget-arrival'); drain(host)
    active = host.engine.active['id']
    host.engine.presence.forget('phone-device')
    assert host.engine.active['id'] == active  # Forget must never touch laptop hardware.
    assert host.engine.presence.store.get(phone['id'])['level'] == 'ask'
    assert host.engine.presence.store.get(phone['id'])['confirmed']
    assert host.engine.presence.store.get(time_rule['id'])['level'] == 'do_and_tell'
    assert not host.engine.presence.store.load()['runs']


def test_actual_place_is_rechecked_before_auto_action(host):
    row = save(host)
    host.engine.presence.store.patch(row['id'], level='do_and_tell', streak=3, promotion_offered=True)
    arrive(host, 'left-before-dispatch')
    host.engine.presence.read_current = lambda now: {'state': 'away', 'confidence': .9, 'data_available': True,
                                                    'place': None, 'transition': {'event': 'leave', 'place': 'college'}}
    assert not drain(host) and not host.engine.active


def test_scene_end_releases_phone_mode_owned_by_the_same_run(host, monkeypatch):
    import services.presence
    from types import SimpleNamespace
    cancelled = []
    monkeypatch.setattr(services.presence, 'phone', SimpleNamespace(cancel=lambda identity: cancelled.append(identity) or True), raising=False)
    row = save(host)
    arrive(host, 'owned-scene'); drain(host); host.engine.answer('yes')
    run = host.engine.presence.store.last_run()
    host.engine.presence.store.checkpoint(run['id'], run['tokens'] + [dict(type='phone_mode', id='phone-mode', owner='presence:' + 'a' * 32)])
    host.engine.end()
    assert cancelled == ['phone-mode']
    assert not host.engine.presence.store.last_run().get('restore_phone_pending')
