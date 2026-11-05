"""Shared college services and real intent-router interoperability, isolated stores."""
import asyncio
import copy
from datetime import datetime, timedelta
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.college import catalogs, models, overview, reading, schedules, service, store, work
from services.proactive import class_sessions, college, deadline_changes, deadlines, timetable
from services.automation import intent
from services.reminders.service import ReminderService

NOW = datetime(2030, 1, 7, 8)  # Monday
SLOT = {'day': 'tuesday', 'start': '09:00', 'end': '10:00', 'subject': 'DBMS'}
TASK = {'what': 'DBMS assignment', 'due': '2030-01-10T17:00', 'kind': 'assignment',
        'subject': 'DBMS', 'done': False, 'notes': 'Synthetic task', 'venue': ''}


def say(text):
    return asyncio.run(intent.try_system_action(text, 'openrouter'))


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(deadlines, 'datetime', Clock)
    monkeypatch.setattr(deadline_changes, 'datetime', Clock)
    return Clock


def add_task(value=None):
    data = work.snapshot()
    return work.change(None, value or TASK, data['revision'], now=NOW)


def test_registry_alias_does_not_change_template_or_dated_override(clock):
    timetable._save([SLOT])
    row = class_sessions.create((NOW + timedelta(days=1)).date(), SLOT)
    row['history'] = [{'source': 'owner_report', 'quote': 'Synthetic correction', 'old_due': row['due'],
                       'new_due': '2030-01-08T11:00', 'old_end': '10:00', 'new_end': '12:00', 'noted': NOW.isoformat()}]
    row.update(due='2030-01-08T11:00', end='12:00')
    with class_sessions.edit():
        class_sessions.save([row])
    before = timetable.path.read_bytes()
    registry = catalogs.subjects()
    catalogs.change_subject('dbms', {'subject': 'Database Management Systems', 'faculty': 'Dr Mira Shah', 'room': 'B-204'}, registry['revision'])
    assert catalogs.subject_for('DBMS')['faculty'] == 'Dr Mira Shah'
    assert timetable.path.read_bytes() == before
    assert timetable.classes_for_date((NOW + timedelta(days=1)).date())[0]['start'] == '11:00'
    data = overview.overview(NOW)
    assert data['next_class']['faculty'] == 'Dr Mira Shah'
    assert data['next_class']['room'] == 'B-204'
    assert 'B-204' in timetable.next_class(NOW)
    assert 'B-204' in timetable.today_line(NOW + timedelta(days=1))
    assert 'B-204' not in timetable.due_warnings((NOW + timedelta(days=1)).replace(hour=10, minute=55))[0]
    assert 'Dr Mira Shah' in college.run({'action': 'next_class_faculty'}, now=NOW)
    assert 'Dr Mira Shah' in say('who takes my next class').message


@pytest.mark.parametrize('mode', ['merge', 'replace'])
def test_import_unchanged_legacy_template_preserves_exact_dictionary(mode):
    rows = schedules.import_candidate([SLOT], [{**SLOT, 'room': None}], mode)
    assert rows == [SLOT]
    assert 'room' not in rows[0]


def test_noop_weekly_edit_keeps_missing_optional_and_extra_fields():
    original = {**SLOT, 'legacy_note': 'preserve this field'}
    timetable._save([original])
    data = schedules.snapshot()
    result = schedules.change('slot-0', SLOT, data['revision'])
    assert timetable.load() == [original]
    assert result['items'][0]['legacy_note'] == 'preserve this field'


def test_weekly_stale_write_and_overlap_refuse_without_changes():
    timetable._save([SLOT])
    data = schedules.snapshot()
    schedules.change(None, {**SLOT, 'day': 'wednesday'}, data['revision'])
    before = timetable.path.read_bytes()
    with pytest.raises(store.Conflict):
        schedules.change('slot-0', SLOT, data['revision'])
    with pytest.raises(ValueError, match='Overlapping'):
        schedules.change(None, {**SLOT, 'start': '09:30', 'end': '10:30'}, schedules.snapshot()['revision'])
    assert timetable.path.read_bytes() == before


@pytest.mark.parametrize('content', ['{}', '["bad row"]', '[{"day":"typo"}]'])
def test_corrupt_weekly_store_is_preserved(content):
    timetable.path.write_text(content)
    with pytest.raises(store.Unavailable):
        schedules.snapshot()
    assert timetable.path.read_text() == content


def test_dated_move_uses_existing_history_duration_and_strict_clock(clock):
    timetable._save([SLOT])
    data = schedules.snapshot()
    body = models.DatedMove(revision=data['revision'], id='slot-0', date='2030-01-08', start='06:00')
    result = schedules.move_date(body, NOW)
    assert timetable.load() == [SLOT]
    assert result['effective'][0]['start'] == '06:00'
    assert result['effective'][0]['end'] == '07:00'
    assert class_sessions.load()[0]['history'][0]['origin'] == 'college_ui'
    with pytest.raises(store.Conflict):
        schedules.move_date(body, NOW)


def test_ui_deadline_is_read_by_real_router_and_chat_create_is_projected(clock):
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    api = TestClient(create_app(), base_url='http://127.0.0.1:8000')
    result = api.put('/api/v1/college/deadlines', json={
        'revision': api.get('/api/v1/college/deadlines').json()['revision'], 'value': TASK}).json()
    assert 'DBMS assignment' in say("what's due").message
    chat = say('OS homework due Friday 5pm')
    assert chat.success, chat.message
    assert {r['what'] for r in api.get('/api/v1/college/deadlines').json()['items']} == {'DBMS assignment', 'OS homework'}
    assert result['items'][0]['origin'] == 'college_ui'


def test_chat_due_change_updates_same_api_row_and_revision(clock):
    original = add_task()
    assert say('move deadline DBMS to 2030-01-14 at 5pm').success
    current = work.snapshot()
    assert current['items'][0]['due'] == '2030-01-14T17:00'
    assert current['revision'] != original['revision']
    with pytest.raises(store.Conflict):
        work.change(current['items'][0]['id'], TASK, original['revision'], now=NOW)


def test_ui_due_move_proposal_remains_reviewable_after_metadata_edit(clock):
    data = add_task()
    reminders = ReminderService()
    reminders.add_from_message('remind me tomorrow at 4pm to submit synthetic task', NOW)
    reminder = reminders.pending()[0]
    assert say('link reminder 1 to deadline DBMS').success
    data = work.snapshot()
    identifier = data['items'][0]['id']
    moved = work.change(identifier, {**TASK, 'due': '2030-01-14T17:00'}, data['revision'], now=NOW)
    row = deadlines.load()[0]
    assert row['reminder_updates'][0]['revision'] == row['revision']
    assert '1 reminder updates pending' in moved['message']
    before = reminders.pending()[0].due_at
    assert before == reminder.due_at
    edited = work.change(identifier, {**TASK, 'due': '2030-01-14T17:00', 'notes': 'Updated'}, moved['revision'], now=NOW)
    assert say('review reminder updates for DBMS').success
    assert say('apply reminder updates for DBMS').success
    assert reminders.pending()[0].due_at == before + 4 * 86400
    assert deadlines.load()[0]['history'][0]['source'] == 'owner_report'
    assert deadlines.load()[0]['history'][0]['origin'] == 'college_ui'


def test_ui_and_chat_completion_remove_active_history_and_keep_done_status(clock):
    data = add_task()
    identifier = data['items'][0]['id']
    data = work.change(identifier, {**TASK, 'done': True}, data['revision'], now=NOW)
    assert not deadlines.load()
    assert work.snapshot()['items'][0]['done'] is True
    assert 'No deadlines' in say("what's due").message
    assert deadlines.briefing_line(NOW) == ''
    deadlines.add('OS homework', NOW + timedelta(days=2), NOW)
    assert len(work.snapshot()['items']) == 2  # active saves preserve done rows
    assert say('done with OS homework').success
    assert all(r['done'] for r in work.snapshot()['items'])
    assert all(not r.get('history') and not r.get('linked_reminders') for r in deadlines.load(include_done=True))


def test_exams_use_unchanged_briefing_and_shared_deadline_store():
    data = work.snapshot('exams')
    work.change(None, {'subject': 'DS', 'date': '2030-01-17', 'time': '09:00', 'venue': 'Hall 4', 'notes': 'Bring ID'},
                data['revision'], 'exams', NOW)
    assert 'DS exam in 10 days' in college.exam_line(NOW)
    assert deadlines.load()[0]['kind'] == 'exam'
    assert work.snapshot('exams')['items'][0]['venue'] == 'Hall 4'


def test_events_create_edit_delete_are_atomic_and_revision_guarded(monkeypatch):
    data = catalogs.events()
    value = {'title': 'Hackathon', 'date': '2030-01-12', 'start': '10:00', 'end': '18:00', 'location': 'Lab', 'notes': ''}
    created = catalogs.change_event(None, value, data['revision'])
    with pytest.raises(store.Conflict):
        catalogs.change_event(created['items'][0]['id'], None, data['revision'])
    original = store.path('events.json').read_bytes()
    from services import settings_store
    monkeypatch.setattr(settings_store.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('Synthetic publication failure')))
    with pytest.raises(OSError):
        catalogs.change_event(created['items'][0]['id'], {**value, 'title': 'Updated'}, created['revision'])
    assert store.path('events.json').read_bytes() == original


def test_concurrent_ui_writers_only_one_revision_wins():
    data = work.snapshot()
    def write(title):
        try:
            work.change(None, {**TASK, 'what': title}, data['revision'], now=NOW)
            return 'saved'
        except store.Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ['Task A', 'Task B']))
    assert sorted(results) == ['conflict', 'saved']


def test_next_class_helper_and_existing_prose_agree():
    timetable._save([SLOT])
    row = timetable.next_class_occurrence(NOW)
    assert row['date'] == '2030-01-08'
    assert row['start'] == '09:00'
    assert 'tomorrow at 9:00 am' in timetable.next_class(NOW)


def test_open_and_faculty_commands_are_laptop_only(monkeypatch):
    called = []
    monkeypatch.setattr('interfaces.college.launcher.launch', lambda: called.append(True))
    assert say('open college schedules').success
    assert called == [True]
    token = intent.remote_request.set(True)
    try:
        assert not say('open college schedules').success
        assert not say('who takes my next class').success
        assert not say('show college events').success
    finally:
        intent.remote_request.reset(token)
    assert called == [True]


def test_events_share_chat_overview_and_local_briefing_without_telegram():
    from services.proactive import briefing
    event = {'title': 'Synthetic campus meetup', 'date': '2030-01-08', 'start': '10:00', 'end': '11:00', 'location': 'Lab 3', 'notes': ''}
    data = catalogs.change_event(None, event, catalogs.events()['revision'])
    assert 'Synthetic campus meetup' in say('show college events').message
    assert overview.overview(NOW)['events'][0]['title'] == event['title']
    assert 'Synthetic campus meetup' in briefing._college_events(NOW)
    token = intent.remote_request.set(True)
    try:
        assert briefing._college_events(NOW) == ''
        assert not say('show college events').success
    finally:
        intent.remote_request.reset(token)


def test_finished_events_are_not_upcoming_but_ongoing_events_remain():
    event = {'title': 'Past event', 'date': '2030-01-07', 'start': '06:00', 'end': '07:00', 'location': '', 'notes': ''}
    first = catalogs.change_event(None, event, catalogs.events()['revision'])
    catalogs.change_event(None, {**event, 'title': 'Ongoing event', 'start': '07:30', 'end': '09:00'}, first['revision'])
    assert [r['title'] for r in reading.upcoming_events(NOW)] == ['Ongoing event']


def test_optional_metadata_failure_does_not_break_successful_class_writes():
    file = store.path('subjects.json')
    file.parent.mkdir(parents=True)
    file.write_text('broken metadata')
    result = timetable.run({'action': 'add_class', 'subject': 'DBMS', 'day': 'tuesday',
                            'start': '9am', 'end': '10am', 'room': 'Legacy room'}, NOW)
    assert result.startswith('Added') and len(timetable.load()) == 1
    assert 'Legacy room' in timetable.next_class(NOW)
    assert file.read_text() == 'broken metadata'
    with pytest.raises(store.Unavailable):
        catalogs.subjects()


def test_structured_telegram_briefing_does_not_read_private_subject_rooms():
    from services.proactive import briefing
    timetable._save([{**SLOT, 'room': 'Legacy room'}])
    catalogs.change_subject('dbms', {'subject': 'DBMS', 'room': 'Private new room'}, catalogs.subjects()['revision'])
    target = NOW + timedelta(days=1)
    assert 'Private new room' in briefing._classes_today(target)
    structured = briefing._classes_today(target, structured=True)
    assert 'Private new room' not in structured and 'Legacy room' in structured
    warning = timetable.due_warnings(target.replace(hour=8, minute=55))[0]
    assert 'Private new room' not in warning and 'Legacy room' not in warning


def test_reading_can_be_imported_first_in_a_fresh_interpreter():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-B', '-c',
        'from services.college.reading import events_message; from services.proactive import timetable; print("cold import ok")'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'cold import ok' in result.stdout
