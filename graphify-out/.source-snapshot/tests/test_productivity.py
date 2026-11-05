"""Shared-data persistence, failure paths and real FRIDAY router integration."""
import asyncio
from datetime import date, timedelta

import pytest

from services.mind.cognition import Cognition, cognition
from services.mind.workspace import Workspace, workspace
from services.productivity.store import Tracker, tracker, streak
from services.productivity import commands


def test_habits_tasks_and_checkins_survive_restart_and_share_friday_workspace():
    habit = tracker.save_habit('Read 20 pages', list(range(7)), 'Before bed')
    task = tracker.save_task('Buy a book', date.today().isoformat(), 'high', 'Paperback')
    tracker.check(habit, date.today().isoformat(), True)
    restarted = Tracker(Workspace(Cognition(cognition.path)))
    data = restarted.snapshot()
    assert data['habits'][0]['checks'] == [date.today().isoformat()]
    assert data['habits'][0]['streak'] == 1
    assert data['tasks'][0]['priority'] == 'high'
    assert workspace.tasks()[0]['id'] == task
    workspace.task_state(task, 'completed', 'Bought it')
    assert restarted.snapshot()['tasks'][0]['status'] == 'completed'
    tracker.archive(habit, True)
    assert restarted.snapshot()['habits'][0]['archived']
    tracker.archive(habit, False)
    tracker.check(habit, date.today().isoformat(), False)
    assert restarted.snapshot()['habits'][0]['checks'] == []


def test_streak_skips_rest_days_and_allows_unfinished_today():
    habit = {'created': '2026-10-01', 'weekdays': [0, 1, 2, 3, 4], 'checks': ['2026-10-23', '2026-10-26']}
    assert streak(habit, date(2026, 10, 26)) == 2
    assert streak(habit, date(2026, 10, 27)) == 2
    assert streak(habit, date(2026, 10, 28)) == 0


def test_import_is_atomic_preserves_existing_and_skips_duplicates():
    tracker.save_habit('Read', [0, 1])
    assert tracker.import_habits('Read\nExercise\nexercise\nDrink water') == (2, 2)
    before = tracker.snapshot()
    with pytest.raises(ValueError, match='row 2'):
        tracker.import_habits('name,weekdays\nValid,"0,1"\nBad,9', True)
    assert tracker.snapshot() == before
    assert tracker.import_habits('name,weekdays,notes\nMeditate,"0,2,4",Morning', True) == (1, 0)
    assert tracker.snapshot()['habits'][-1]['weekdays'] == [0, 2, 4]
    with pytest.raises(ValueError):
        tracker.import_habits('other\nOops', True)
    with pytest.raises(ValueError):
        tracker.import_habits('x' * (1024 * 1024 + 1))


def test_stale_edits_and_checkins_do_not_overwrite_changes():
    ident = tracker.save_habit('Walk', list(range(7)))
    old = tracker.snapshot()['habits'][0]
    tracker.save_habit('Long walk', list(range(7)), ident=ident, revision=old['revision'])
    with pytest.raises(ValueError, match='changed elsewhere'):
        tracker.check(ident, date.today().isoformat(), True, old['revision'])
    with pytest.raises(ValueError, match='changed elsewhere'):
        tracker.save_habit('Lost edit', [0], ident=ident, revision=old['revision'])
    assert tracker.snapshot()['habits'][0]['name'] == 'Long walk'


def test_future_unscheduled_and_archived_checkins_are_rejected():
    ident = tracker.save_habit('Gym', [(date.today().weekday() + 1) % 7])
    with pytest.raises(ValueError):
        tracker.check(ident, date.today().isoformat(), True)
    with pytest.raises(ValueError):
        tracker.check(ident, (date.today() + timedelta(days=1)).isoformat(), True)
    tracker.archive(ident, True)
    with pytest.raises(ValueError):
        tracker.check(ident, date.today().isoformat(), True)
    with pytest.raises(ValueError):
        tracker.save_habit('No schedule', [])


def test_all_tasks_load_and_ui_never_bypasses_plans_or_stale_progress():
    for i in range(102):
        workspace.start_task(f'Task {i}')
    assert len(tracker.snapshot()['tasks']) == 102
    ident = workspace.start_task('Ship project')
    workspace.plan(ident, ['Test', 'Review'])
    old = next(t for t in tracker.snapshot()['tasks'] if t['id'] == ident)
    with pytest.raises(ValueError, match='each planned step'):
        tracker.task_action(ident, 'completed', 'done', old['updated'])
    tracker.task_action(ident, 'step', 'Tests passed', old['updated'])
    with pytest.raises(ValueError, match='changed elsewhere'):
        tracker.task_action(ident, 'step', 'Stale second click', old['updated'])
    current = next(t for t in tracker.snapshot()['tasks'] if t['id'] == ident)
    assert current['cursor'] == 1
    tracker.task_action(ident, 'step', 'Reviewed', current['updated'])
    assert workspace.resolve('task', str(ident))['status'] == 'completed'


def test_task_metadata_edit_conflict_and_no_secret_duplication(monkeypatch):
    monkeypatch.setattr('core.config.config.OPENROUTER_API_KEY', 'secret-example-987')
    ident = tracker.save_task('Read secret-example-987', priority='high')
    task = tracker.snapshot()['tasks'][0]
    assert 'secret-example-987' not in task['title']
    workspace.task_state(ident, 'paused')
    with pytest.raises(ValueError, match='changed elsewhere'):
        tracker.save_task('Stale edit', ident=ident, revision=task['updated'])
    assert tracker.snapshot()['tasks'][0]['priority'] == 'high'


def test_friday_commands_preserve_payload_and_share_data(monkeypatch):
    from services.automation.intent import try_system_action
    for phrase in ['add habit: Read And Reflect', 'add todo: Buy Tea And Coffee']:
        result = asyncio.run(try_system_action(phrase, 'ollama'))
        assert result and result.success, result
    assert tracker.snapshot()['habits'][0]['name'] == 'Read And Reflect'
    assert tracker.snapshot()['tasks'][0]['title'] == 'Buy Tea And Coffee'
    result = asyncio.run(try_system_action('check habit: Read And Reflect', 'ollama'))
    assert result.success
    assert 'done today' in commands.run({'action': 'habits'}).message
    assert commands.run({'action': 'finish_task', 'name': 'Buy Tea And Coffee'}).success
    launches = []
    monkeypatch.setattr('interfaces.productivity.launcher.launch', lambda view: launches.append(view))
    assert commands.run(commands.match_command('open habit tracker')).success
    assert launches == ['habits']
    assert not commands.run(commands.match_command('open to-do app'), remote=True).success
    assert commands.match_command('type add habit: This is text') is None


def test_tracked_habits_enter_shared_context_without_learned_habit_collision():
    from services.activity import habits
    tracker.save_habit('Meditate', list(range(7)))
    assert tracker.context()[0]['name'] == 'Meditate'
    assert habits.match_habit_command('show my habits')['action'] == 'list_habits'
    assert commands.match_command('show my habits') is None
    from services.mind.cognition_context import prompt_section
    assert 'Meditate' in prompt_section()


def test_checkin_dates_are_canonical_and_task_metadata_enters_friday_prompt():
    from services.mind.cognition_context import prompt_section
    ident = tracker.save_habit('Walk', list(range(7)))
    tracker.check(ident, date.today().strftime('%Y%m%d'), True)
    assert tracker.snapshot()['habits'][0]['checks'] == [date.today().isoformat()]
    tracker.save_task('Submit report', '2026-12-31', 'high', 'Include references')
    context = prompt_section()
    assert '2026-12-31' in context and 'Include references' in context
