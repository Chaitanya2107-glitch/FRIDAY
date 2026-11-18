from datetime import datetime, timedelta

import pytest

from core.config import config
from services.mind.cognition import Cognition
from services.mind import goals, goals_math, goals_parser
from services.mind.temporal_memory import TemporalMemory

NOW = datetime(2026, 11, 17, 10)


@pytest.fixture
def coach(tmp_path, monkeypatch):
    store = Cognition(tmp_path / 'private-coaching.db')
    monkeypatch.setattr(config, 'REASONING_ENABLED', False)
    monkeypatch.setattr(config, 'AI_WORDING_ENABLED', False)
    from services.mind import wording
    def plain(raw):
        assert raw['kind'] == 'goal_coaching'
        return raw['answer']
    monkeypatch.setattr(wording, 'plain', plain)
    async def forbidden(*args, **kwargs):
        pytest.fail('Private coaching attempted a model call')
    from providers import failover
    monkeypatch.setattr(failover, 'complete_with_failover', forbidden)
    def handle(text, now=NOW, **options):
        return goals.handle(text, now, store=store, measure=options.pop('measure', lambda *args: None), **options)
    return store, handle


@pytest.mark.parametrize('text,target,unit,cadence', [
    ('finish 100 DSA problems by Dec 15', 100, 'problems', None),
    ('study 2 hours every weekday', 120, 'minutes', 'day'),
    ('gym 3 times a week', 3, 'visits', 'week'),
    ('walk 8000 steps every day', 8000, 'steps', 'day'),
    ('read 20 pages every day', 20, 'pages', 'day'),
    ('solve 5 DSA problems every weekday', 5, 'problems', 'day'),
    ('complete 30 problems by 2026-12-15', 30, 'problems', None),
    ('study 120 minutes every day', 120, 'minutes', 'day'),
    ('go to gym three times a week', 3, 'visits', 'week'),
    ('walk 50000 steps a week', 50000, 'steps', 'week'),
])
def test_ten_fully_local_quantified_goals(text, target, unit, cadence):
    result = goals_parser.parse(text, NOW)
    assert result['target'] == target and result['unit'] == unit
    assert (result['cadence']['period'] if result['cadence'] else None) == cadence
    assert result['review_window'] == dict(day=6, start='18:00', end='21:00')


def test_preview_confirm_change_and_manual_idempotent_log(coach):
    store, handle = coach; memory = TemporalMemory(store)
    preview = handle('finish 100 DSA problems by Dec 15')
    assert preview['awaiting_reply'] and '18:00' in preview['text']
    assert not memory.private_commitments()
    assert handle('no')['ok'] and not memory.private_commitments()
    handle('finish 100 DSA problems by Dec 15'); saved = handle('yes')
    assert saved['ok'] and len(memory.private_commitments()) == 1
    logged = goals.log_progress(1, 10, event_id='tap-event-12345', now=NOW + timedelta(minutes=1), store=store)
    assert '10/100' in logged['text'] and logged['win']
    again = goals.log_progress(1, 10, event_id='tap-event-12345', now=NOW + timedelta(minutes=2), store=store)
    assert not again['win'] and len(memory.private_logs(1)) == 1
    with pytest.raises(ValueError):
        goals.log_progress(1, 20, event_id='tap-event-12345', now=NOW, store=store)
    handle('change goal 1 target to 80')
    assert memory.private_commitments()[0]['definition']['target'] == 100
    assert handle('yes')['ok']
    assert memory.private_commitments()[0]['definition']['target'] == 80
    handle('move goal 1 deadline to 2026-12-20'); assert handle('yes')['ok']
    assert memory.private_commitments()[0]['definition']['deadline'] == '2026-12-20'


def test_unknown_ambiguous_and_malformed_words_do_not_guess(coach):
    _, handle = coach
    assert handle('open calculator') is None
    assert handle('at 5:30pm remind me to Call Mom') is None
    assert not handle('my goal is be better')['ok']
    assert not handle('finish 100 DSA problems by next Friday')['ok']
    assert not handle('finish 100 DSA problems by 2020-01-01')['ok']
    assert not handle('study 0 hours every day')['ok']


def test_source_rebinding_requires_confirm_starts_new_measurement_and_gym_stays_manual(coach):
    store, handle = coach; memory = TemporalMemory(store)
    handle('gym 3 times a week'); handle('yes')
    assert memory.private_commitments()[0]['definition']['source'] == {'kind': 'manual'}
    calls = []
    def measure(source, start, end):
        calls.append((source, start)); return 2
    preview = handle('use visits to gym for goal 1')
    assert preview['awaiting_reply'] and not calls
    assert memory.private_commitments()[0]['definition']['source'] == {'kind': 'manual'}
    accepted = NOW + timedelta(minutes=1)
    assert handle('yes', accepted, measure=measure)['ok']
    handle('goal 1 progress', accepted + timedelta(minutes=1), measure=measure)
    assert calls[-1] == ({'kind': 'visits', 'place': 'gym'}, accepted)
    assert not handle('use focus category study for goal 1')['ok']
    assert not handle('log 1 visits for goal 1')['ok']


def test_unknown_automatic_measurement_is_never_zero(coach):
    _, handle = coach
    handle('study 2 hours every weekday'); handle('yes')
    result = handle('goal 1 progress')
    assert 'unavailable' in result['text'] and '0/120' not in result['text']
    assert 'daily step totals' in handle('walk 8000 steps every day')['text']


def test_stale_confirmation_cannot_overwrite_a_changed_goal(coach):
    store, handle = coach; memory = TemporalMemory(store)
    handle('read 20 pages every day'); handle('yes')
    handle('change goal 1 target to 30')
    row = memory.private_commitments()[0]
    memory.save_private_commitment(dict(row['definition'], target=25), 'Confirmed separately', identity=1, expected_revision=1, now=NOW)
    assert not handle('yes')['ok']
    assert memory.private_commitments()[0]['definition']['target'] == 25


def test_pace_projection_slack_and_zero_available_days():
    definition = goals_parser.parse('finish 100 DSA problems by 2026-11-26', NOW)
    created = NOW.replace(day=17, hour=0)
    result = goals_math.progress(definition, 20, NOW.replace(day=21), created)
    assert result['remaining_days'] == 6 and result['needed_per_day'] == pytest.approx(80 / 6)
    assert result['pace_per_day'] == 4 and result['shortfall'] == 20  # No shortfall is charged for today's unfinished day.
    assert result['projected_finish'] == '2026-12-10'
    unavailable = goals_math.progress(definition, None, NOW, created)
    assert unavailable['done'] is None and unavailable['projected_finish'] is None
    overdue = goals_math.progress(definition, 20, NOW.replace(day=27), created)
    assert overdue['remaining_days'] == 0 and overdue['needed_per_day'] is None and overdue['overdue']


def test_free_slots_avoid_classes_sleep_existing_blocks_and_exam():
    slots = goals_math.free_slots(NOW.replace(hour=8), 30,
        classes=[dict(start='08:00', end='10:00')],
        blocks=[dict(start='2026-11-17T10:00:00', end='2026-11-17T10:30:00')],
        sleep=('21:00', '08:00'))
    assert slots[0]['start'] == '2026-11-17T10:30:00'
    assert not goals_math.free_slots(NOW, scene='exam')
    assert not goals_math.free_slots(NOW, scene='sleep')
    assert all('08:00' <= slot['start'][11:16] < '21:00' for slot in slots)


def test_projection_uses_selected_days_and_new_goals_have_no_shortfall():
    created = datetime(2026, 11, 20, 10)
    definition = goals_parser.parse('gym 3 times a week', created)
    definition['cadence']['days'] = list(range(5))
    assert goals_math.progress(definition, 0, created, created)['shortfall'] == 0
    result = goals_math.progress(definition, 1, created, created)
    assert result['projected_finish'] == '2026-11-23'


@pytest.mark.parametrize('text', ['show my goals', 'please show my goals', 'Friday, could you list my goals', 'add goal high: Learn cooking'])
def test_coaching_preserves_existing_workspace_commands(text):
    assert not goals.private_turn(text)


def test_blocks_need_selection_then_fresh_yes_and_recheck_effective_classes(coach):
    store, handle = coach; memory = TemporalMemory(store)
    handle('study 2 hours every weekday'); handle('yes')
    classes = []
    result = handle('suggest study blocks for goal 1', classes=classes, scene='normal')
    assert result['awaiting_reply'] and not memory.private_commitments('study_block')
    assert not handle('yes', classes=classes, scene='normal')['ok']
    handle('suggest study blocks for goal 1', classes=classes, scene='normal')
    handle('add block 1', classes=classes, scene='normal')
    assert not memory.private_commitments('study_block')
    classes.append(dict(start='10:00', end='11:00'))
    assert not handle('yes', classes=classes, scene='normal')['ok']
    handle('suggest study blocks for goal 1', classes=classes, scene='normal')
    handle('add block 1', classes=classes, scene='normal')
    assert handle('yes', classes=classes, scene='normal')['ok']
    assert len(memory.private_commitments('study_block')) == 1


def test_weekly_checkin_is_one_candidate_in_confirmed_window_and_never_repeats(coach):
    store, handle = coach
    for text in ('gym 3 times a week', 'read 20 pages every day'):
        handle(text); handle('yes')
    sunday = datetime(2026, 11, 22, 19)
    assert not goals.weekly_candidates(sunday.replace(hour=17), store=store)
    assert not goals.weekly_candidates(sunday.replace(hour=21), store=store)
    choices = goals.weekly_candidates(sunday, store=store)
    assert len(choices) == 1 and 'Goal 1' in choices[0]['text'] and 'Goal 2' in choices[0]['text']
    goals.mark_weekly_sent(choices[0]['key'], sunday, store=store)
    assert not goals.weekly_candidates(sunday + timedelta(minutes=20), store=store)


def test_pending_decline_and_expiry_are_scoped_to_store_and_never_save(coach, tmp_path):
    store, handle = coach
    handle('read 20 pages every day')
    assert goals.pending(store=store, now=NOW)
    other = Cognition(tmp_path / 'other.db')
    assert not goals.pending(store=other, now=NOW)
    assert handle('yes', NOW + timedelta(minutes=3)) is None
    assert not TemporalMemory(store).private_commitments()
