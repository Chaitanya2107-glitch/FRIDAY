import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.mind import care, care_triggers, care_review, coaching_commands, coaching_metrics as metrics

NOW = datetime(2026, 11, 17, 10, 30)


def definition(kind, **changes):
    row = dict(type=kind, limit=50, window=['09:00', '21:00'], days=list(range(7)), cap=2,
               categories=[], apps=[], context='any', voice=False)
    if kind in {'sleep', 'wind_down'}:
        row['limit'] = '23:00'; row['window'] = ['22:00', '01:00']
    if kind == 'sleep':
        row['wake'] = '07:00'
    if kind == 'phone_use':
        row['categories'] = ['entertainment']; row['context'] = 'study'
    return dict(row, **changes)


def observed(now=NOW):
    start = now.replace(hour=9, minute=0).timestamp()
    return dict(segments=[dict(device='laptop', app='notes', category='study', start=start, end=start + 3600),
                          dict(device='phone', device_id='phone', app='approved.package', category='entertainment', start=start + 1200, end=now.timestamp())],
                focus=[dict(id='focus', label='study', start=start, end=now.timestamp())], events=[], contexts=[])


@pytest.mark.parametrize('kind', sorted(care.TYPES))
def test_each_type_remains_off_until_explicit_confirmation(kind):
    proposal = care.propose(kind, NOW, observed())
    care.store().stage(dict(step='setup', proposal=proposal), NOW)
    assert care.store().settings(kind) is None
    assert care_triggers.candidates(care.store().settings(), NOW, observed()) == []
    assert not care.status(NOW)['wellbeing']['confirmed']


def test_baseline_is_observed_cross_device_union_and_setup_can_be_changed(monkeypatch):
    monkeypatch.setattr(metrics, 'snapshot', lambda *a: observed())
    proposed = care.propose('breaks', NOW)
    assert proposed['baseline']['days'] == 1
    assert proposed['definition']['limit'] == 90  # Laptop+phone overlap is counted once.
    reply = coaching_commands.handle_care('set up breaks care after 55 minutes from 09:00 to 20:00 cap 2', NOW)
    assert reply['awaiting_reply'] and care.store().settings('breaks') is None
    coaching_commands.handle_care('yes', NOW)
    assert care.store().settings('breaks')['definition']['limit'] == 55


def test_sleep_window_edit_does_not_replace_bedtime_and_requires_wake():
    proposal = dict(definition=definition('sleep'), baseline={})
    edited = coaching_commands.edit(proposal, 'from 21:00 to 23:30 wake 08:00')
    assert edited['definition']['limit'] == '23:00'
    assert edited['definition']['wake'] == '08:00'
    care.validate(edited['definition'])
    del edited['definition']['wake']
    with pytest.raises(ValueError): care.validate(edited['definition'])


def test_continuous_focus_survives_device_switch_but_resets_after_gap():
    care.store().confirm(definition('breaks'), NOW - timedelta(hours=2))
    rows = care.store().settings()
    found = care_triggers.candidates(rows, NOW, observed())
    assert found and '90 recorded screen minutes' in found[0]['text']
    data = observed(); data['segments'][1]['start'] = NOW.timestamp() - 600
    assert not care_triggers.candidates(rows, NOW, data)


def test_phone_question_optin_cap_dedupe_context_and_followup():
    data = observed()
    assert not care_triggers.candidates([], NOW, data, context='study')
    with pytest.raises(ValueError): care.store().confirm(definition('phone_use', categories=[]), NOW)
    care.store().confirm(definition('phone_use'), NOW - timedelta(hours=2))
    candidate = care_triggers.candidates(care.store().settings(), NOW, data, context='study')[0]
    identity = care.store().claim(candidate, NOW)
    assert identity and care.store().claim(candidate, NOW) is None
    assert 'approved.package' not in candidate['text']  # Only categories were permitted.
    assert care.phone_question(NOW)['id'] == identity
    care.answer_notice(identity, 'remind15', NOW)
    with care.store().db() as db:
        followups = [dict(row) for row in db.execute('SELECT * FROM care_followups')]
    later = NOW + timedelta(minutes=16)
    assert not care_triggers.candidates(care.store().settings(), later, data, context='free', followups=followups)
    reminder = [r for r in care_triggers.candidates(care.store().settings(), later, data, context='study', followups=followups) if r['key'].startswith('followup:')][0]
    assert care.store().claim(reminder, later)
    assert care.store().claim(dict(reminder, key='different'), later) is None
    assert not care_triggers.candidates(care.store().settings(), NOW.replace(hour=22), data, context='study')


def test_no_returns_to_ask_and_promotion_never_happens_by_itself():
    care.store().confirm(definition('phone_use'), NOW)
    for index in range(3):
        when = NOW + timedelta(days=index)
        row = care.store().settings('phone_use')
        identity = care.store().claim(dict(type='phone_use', key=str(index), text='Private question', revision=row['revision']), when)
        care.answer_notice(identity, 'accept', when)
    assert care.store().settings('phone_use')['trust']['level'] == 'ask'
    coaching_commands.handle_care('move phone-use care to do and tell', NOW + timedelta(days=2))
    coaching_commands.handle_care('yes', NOW + timedelta(days=2))
    assert care.store().settings('phone_use')['trust']['level'] == 'do_and_tell'
    when = NOW + timedelta(days=3)
    identity = care.store().claim(dict(type='phone_use', key='decline', text='Private question', revision=1), when)
    care.answer_notice(identity, 'leave', when)
    assert care.store().settings('phone_use')['trust']['level'] == 'ask'


def test_water_uses_only_chosen_interval_and_sleep_cites_timetable():
    for kind in ('water', 'stretch'):
        care.store().confirm(definition(kind, limit=60), NOW - timedelta(minutes=59))
    assert not care_triggers.candidates(care.store().settings(), NOW, observed())
    assert {r['type'] for r in care_triggers.candidates(care.store().settings(), NOW + timedelta(minutes=2), observed())} == {'water', 'stretch'}
    care.store().confirm(definition('sleep'), NOW)
    night = NOW.replace(hour=23, minute=15)
    first = SimpleNamespace(start=(night + timedelta(days=1)).replace(hour=9, minute=0), subject='Math')
    found = care_triggers.candidates([care.store().settings('sleep')], night, observed(), classes=[first])
    assert '09:00' in found[0]['text'] and 'uncertain' in found[0]['text']


def test_wellbeing_is_user_entered_and_missing_consent_window_or_invalid_score_fails():
    with pytest.raises(ValueError): care.log_wellbeing(3, NOW)
    care.store().confirm(definition('wellbeing'), NOW)
    for score in (True, 0, 6, '3'):
        with pytest.raises(ValueError): care.log_wellbeing(score, NOW)
    care.log_wellbeing(3, NOW); care.log_wellbeing(4, NOW)
    entries = care.store().entries(NOW - timedelta(hours=1), NOW + timedelta(seconds=1), 'wellbeing')
    assert len(entries) == 1 and entries[0]['amount'] == 4
    with pytest.raises(ValueError): care.log_wellbeing(3, NOW.replace(hour=22))


def test_weekly_numbers_compare_only_present_records_and_owner_logged_breaks():
    start = NOW.replace(hour=0, minute=0)
    data = observed()
    current = care_review.numbers(start, NOW, data=data, entries=[{'kind': 'breaks'}])
    previous = dict(current, focus_minutes=30, breaks_taken=0)
    report = care_review.weekly(NOW, current=current, previous=previous)
    assert current['screen_minutes'] == 90 and current['sleep_minutes'] is None
    assert current['focus_minutes'] == 90 and current['breaks_taken'] == 1
    assert 'previous seven days' in report['text'] and 'Sleep average unavailable' in report['text']


def test_health_aggregates_are_latest_daily_values_not_summed():
    data = observed()
    data['events'] = [dict(device='phone', id=str(i), timestamp=NOW.timestamp() + i, type='steps', payload=dict(date=NOW.date().isoformat(), count=count)) for i, count in enumerate([1000, 3000, 5000])]
    assert metrics.measure(dict(kind='steps'), NOW.replace(hour=0), NOW + timedelta(seconds=10), data) == 5000


def test_one_experiment_needs_confirm_then_reports_plain_measured_difference(monkeypatch):
    from services.mind.outcome_learning import OutcomeLearning
    from services.mind.cognition import cognition
    monkeypatch.setattr(metrics, 'snapshot', lambda *a: observed())
    proposal = care_review.propose_experiment(NOW)
    assert care_review.propose_experiment(NOW)['id'] == proposal['id']
    assert not care_review.finish_experiments(NOW + timedelta(days=8))
    outcomes = OutcomeLearning(cognition)
    outcomes.confirm_private_experiment(proposal['id'], now=NOW)
    later = NOW + timedelta(days=7, seconds=1)
    data = observed(later)
    data['segments'][1]['start'] = later.timestamp() - 1800
    monkeypatch.setattr(metrics, 'snapshot', lambda *a: data)
    measured = care_review.finish_experiments(later)[0]
    assert measured['baseline'] == 70 and measured['observed'] == 30 and measured['delta'] == -40
    assert 'not proof' in measured['meaning']
    care.forget_phone('phone')
    outcomes.forget_private_phone('phone')
    assert not outcomes.private_experiments()


@pytest.mark.parametrize('text', ['start sleep mode', 'start break timer', 'stop focus', 'enable eye breaks', 'at 5:30pm tomorrow remind me to Call Mom'])
def test_care_does_not_steal_existing_timer_scene_or_reminder_commands(text):
    assert not coaching_commands.explicit_care(text)


def test_expired_private_reply_does_not_fall_through_to_model():
    care.store().stage(dict(step='setup', proposal=dict(definition=definition('water'))), NOW - timedelta(hours=1))
    result = asyncio.run(coaching_commands.try_command('60 minutes from 09:00 to 21:00', now=NOW))
    assert result and 'expired' in result.message


def test_forget_cannot_be_overtaken_by_an_inflight_experiment(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from services.mind import phone_patterns
    from services.mind.outcome_learning import OutcomeLearning
    from services.mind.cognition import cognition
    entered, checked = threading.Event(), threading.Event()
    probe = []

    def snapshot(*args):
        entered.set()
        assert checked.wait(5)
        return observed()

    def forget():
        assert entered.wait(5)
        acquired = phone_patterns.lock.acquire(blocking=False)
        probe.append(acquired)
        if acquired:
            phone_patterns.lock.release()
        checked.set()
        with phone_patterns.lock:
            pass  # The real source deletion uses this same boundary before derived deletion.
        care.forget_phone('phone')
        OutcomeLearning(cognition).forget_private_phone('phone')

    monkeypatch.setattr(metrics, 'snapshot', snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        proposing = pool.submit(care_review.propose_experiment, NOW)
        forgetting = pool.submit(forget)
        proposing.result(timeout=10)
        forgetting.result(timeout=10)
    assert probe == [False]
    assert not OutcomeLearning(cognition).private_experiments()


def test_forget_invalidates_candidates_already_read_from_phone_data():
    care.store().confirm(definition('phone_use'), NOW - timedelta(hours=2))
    candidate = care_triggers.candidates(care.store().settings(), NOW, observed(), context='study')[0]
    care.forget_phone('phone')
    assert care.store().settings('phone_use')['definition']['categories'] == ['entertainment']
    assert care.store().claim(candidate, NOW, context='study') is None
    assert not care.phone_question(NOW)['pending']


def test_experiment_deleted_during_measurement_has_no_stale_result(monkeypatch):
    from services.mind.outcome_learning import OutcomeLearning
    from services.mind.cognition import cognition
    monkeypatch.setattr(metrics, 'snapshot', lambda *a: observed())
    proposal = care_review.propose_experiment(NOW)
    outcomes = OutcomeLearning(cognition)
    outcomes.confirm_private_experiment(proposal['id'], now=NOW)

    def forgotten(*args):
        outcomes.forget_private_phone('phone')
        return observed()

    monkeypatch.setattr(metrics, 'snapshot', forgotten)
    assert care_review.finish_experiments(NOW + timedelta(days=8)) == []
