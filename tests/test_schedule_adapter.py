"""Use confirmed College Schedules stores without creating or altering files."""
from datetime import date, datetime, timedelta
import hashlib
import json
import sqlite3

import pytest

from core.config import config
from services.college import catalogs, store
from services.memory import schedule
from services.memory.semantic import semantic_memory
from services.mind.cognition import cognition, redact
from services.mind.reasoning_store import fingerprint
from services.proactive import attendance, class_sessions, deadlines, timetable
from services.schedule_adapter import ScheduleAdapter
from services.schedule_facts_readonly import facts, readonly

NOW = datetime(2030, 1, 7, 8)  # Monday
SLOT = dict(day='monday', subject='Physics', start='10:00', end='11:00', room='A-1')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def hashes(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for root in paths
            for p in ([root] if root.is_file() else root.rglob('*') if root.exists() else []) if p.is_file()}


@pytest.fixture
def adapter(monkeypatch):
    # All paths are already redirected to fresh external temp directories by conftest.
    monkeypatch.setattr(semantic_memory, 'db_path', config.MEMORY_DIR / 'owner.db')
    return ScheduleAdapter(now=lambda: NOW)


def test_no_data_does_not_initialize_storage_and_logs_once(adapter, caplog):
    paths = [config.MEMORY_DIR, timetable.path.parent, cognition.path.parent]
    before = hashes(paths)
    with caplog.at_level('INFO'):
        for _ in range(2):
            assert adapter.next_classes(2) == []
            assert adapter.classes_on(NOW.date()) == []
            assert adapter.due_items(7) == adapter.pending_homework() == adapter.upcoming_exams(7) == []
    assert before == hashes(paths)
    assert caplog.text.count('No College Schedules timetable yet') == 1


def test_faculty_room_dated_changes_and_no_writes(adapter):
    write(timetable.path, [SLOT])
    write(store.path('subjects.json'), {'physics': dict(subject='Physics', faculty='Prof. Ray', room='B-4')})
    changed = class_sessions.create(NOW.date(), SLOT)
    changed.update(due='2030-01-07T12:00', end='13:00', history=[dict(source='owner_report', quote='Class moved',
        old_due='2030-01-07T10:00', new_due='2030-01-07T12:00', old_end='11:00', new_end='13:00', noted=NOW.isoformat())])
    write(class_sessions.path(), [changed])
    paths = [config.MEMORY_DIR, timetable.path.parent, cognition.path.parent]
    before = hashes(paths)
    rows = adapter.classes_on(NOW.date())
    assert len(rows) == 1
    row = rows[0]
    assert (row.subject, row.faculty, row.room, row.kind) == ('Physics', 'Prof. Ray', 'B-4', 'class')
    assert (row.start.hour, row.end.hour) == (12, 13)
    assert row == adapter.next_classes(1)[0]
    assert row.id == adapter.classes_on(NOW.date())[0].id
    assert before == hashes(paths)


def test_holidays_and_owner_cancellations_are_honoured(adapter):
    write(timetable.path, [SLOT])
    write(attendance.path, dict(records=[], marks=[], holidays=[NOW.date().isoformat()], asked=[]))
    assert not adapter.classes_on(NOW.date())
    write(attendance.path, dict(records=[], marks=[], holidays=[], asked=[]))
    semantic_memory.db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(semantic_memory.db_path) as db:
        db.execute('CREATE TABLE schedule_facts (id INTEGER, text TEXT, created_at TEXT)')
        db.execute('INSERT INTO schedule_facts VALUES (1, ?, ?)', ('No classes today', NOW.isoformat()))
    assert not adapter.classes_on(NOW.date())
    assert adapter.next_classes(1)[0].start.date() == NOW.date()+timedelta(days=7)


def test_deadline_exam_and_homework_projection_excludes_completed(adapter):
    write(timetable.path, [SLOT])
    rows = [dict(id=str(n), what=title, kind=kind, subject='Physics', due=(NOW+timedelta(days=days)).isoformat(), done=done)
        for n, title, kind, days, done in [(1, 'Report', 'assignment', 1, False), (2, 'Practice', 'homework', 2, False),
            (3, 'Physics CIE', 'other', 5, False), (4, 'Old work', 'assignment', 1, True), (5, 'Far exam', 'exam', 10, False)]]
    write(deadlines.path, rows)
    before = deadlines.path.read_bytes()
    assert [row.title for row in adapter.due_items(2)] == ['Report', 'Practice']
    assert [row.title for row in adapter.upcoming_exams(7)] == ['Physics CIE']
    assert [row.title for row in adapter.pending_homework()] == ['Practice']
    assert deadlines.path.read_bytes() == before


def test_events_use_confirmed_catalog(adapter):
    write(store.path('events.json'), [dict(id='e1', title='College fair', date='2030-01-08', start='12:00',
                                         end='13:00', location='Hall', notes='')])
    assert adapter.upcoming_events(7)[0].room == 'Hall'
    assert adapter.upcoming_events(7)[0].kind == 'event'


def test_broken_source_is_quiet_and_does_not_hide_other_sources(adapter, caplog):
    timetable.path.write_text('{broken')
    write(deadlines.path, [dict(id='task', what='Report', due='2030-01-08T12:00', kind='assignment')])
    with caplog.at_level('INFO'):
        assert adapter.next_classes(1) == []
        assert adapter.next_classes(1) == []
        assert adapter.due_items(2)[0].title == 'Report'
    assert caplog.text.count('College classes unavailable') == 1
    assert timetable.path.read_text() == '{broken'


@pytest.mark.parametrize('value', [-1, 367, True, '7'])
def test_window_boundary_validation(adapter, value):
    with pytest.raises(ValueError):
        adapter.due_items(value)


def test_readonly_sqlite_guards_and_applied_cancellation(adapter, monkeypatch):
    write(timetable.path, [SLOT])
    cognition.path.parent.mkdir(parents=True)
    quote = 'No regular classes today'
    canonical = dict(kind='owner_fact', id='reasoning_fact:1', quote=redact(quote), certainty='confirmed', noted=NOW.isoformat())
    body = dict(text=quote, start=NOW.date().isoformat(), end=NOW.date().isoformat(),
                effect=dict(type='class_availability', available=False, subject='', basis='owner'))
    with sqlite3.connect(cognition.path) as db:
        db.execute('CREATE TABLE reasoning_facts (id INTEGER, quote TEXT, certainty TEXT, noted TEXT, active INTEGER)')
        db.execute('INSERT INTO reasoning_facts VALUES (1, ?, ?, ?, 1)', (quote, 'confirmed', NOW.isoformat()))
        db.execute('CREATE TABLE reasoning_conclusions (id INTEGER, body TEXT, refs TEXT, noted TEXT, status TEXT)')
        db.execute('INSERT INTO reasoning_conclusions VALUES (1, ?, ?, ?, ?)',
                   (json.dumps(body), json.dumps({'reasoning_fact:1': fingerprint(canonical)}), NOW.isoformat(), 'applied'))
    original = sqlite3.connect
    connections = []
    def connect(path, **kwargs):
        assert '?mode=ro' in path and kwargs['uri'] is True
        connections.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    before = cognition.path.read_bytes()
    assert not adapter.classes_on(NOW.date())
    assert len(facts()) == 1
    with readonly(cognition.path) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute('DELETE FROM reasoning_facts')
    assert connections and before == cognition.path.read_bytes()
    assert not semantic_memory.db_path.exists()


def test_does_not_call_mutating_schedule_authority(adapter, monkeypatch):
    write(timetable.path, [SLOT])
    monkeypatch.setattr(schedule, 'facts', lambda: pytest.fail('Would initialize reasoning storage'))
    assert adapter.classes_on(date(2030, 1, 7))[0].subject == 'Physics'


def test_corrupt_optional_faculty_keeps_classes_and_deadlines(adapter):
    write(timetable.path, [SLOT])
    write(deadlines.path, [dict(id='task', what='Report', subject='Physics', due='2030-01-08T12:00', kind='assignment')])
    store.path('subjects.json').parent.mkdir(parents=True, exist_ok=True)
    store.path('subjects.json').write_text('{broken')
    row = adapter.classes_on(NOW.date())[0]
    assert (row.subject, row.faculty, row.room) == ('Physics', '', 'A-1')
    assert adapter.due_items(2)[0].title == 'Report'


def test_applied_evidence_uses_same_latest_twenty_cutoff(adapter):
    semantic_memory.db_path.parent.mkdir(parents=True, exist_ok=True)
    cognition.path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(semantic_memory.db_path) as db:
        db.execute('CREATE TABLE memories (id INTEGER, text TEXT, source TEXT, created_at TEXT)')
        db.executemany('INSERT INTO memories VALUES (?, ?, ?, ?)', [(n, 'Synthetic owner note', 'told', NOW.isoformat()) for n in range(1, 22)])
    canonical = dict(kind='owner_fact', quote='Synthetic owner note', noted=NOW.isoformat(), certainty='confirmed')
    body = dict(text='Inferred cancellation', start=NOW.date().isoformat(), end=NOW.date().isoformat(),
                effect=dict(type='class_availability', available=False, subject=''))
    with sqlite3.connect(cognition.path) as db:
        db.execute('CREATE TABLE reasoning_conclusions (id INTEGER, body TEXT, refs TEXT, noted TEXT, status TEXT)')
        db.execute('INSERT INTO reasoning_conclusions VALUES (1, ?, ?, ?, ?)',
                   (json.dumps(body), json.dumps({'memory:1': fingerprint(canonical)}), NOW.isoformat(), 'applied'))
    assert facts() == []  # memory:1 is outside the normal authority's evidence window.
