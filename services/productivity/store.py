"""Transactional tracker data in FRIDAY's existing cognition/workspace database."""
from contextlib import contextmanager
import csv
from datetime import date, timedelta
import io
import json
import time

from services.mind.cognition import redact
from services.mind.workspace import workspace


def text(value: str, limit: int = 160, optional: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError('Enter text for this field.')
    value = redact(value.strip())
    if (not value and not optional) or len(value) > limit:
        raise ValueError(f'Use {"0" if optional else "1"} to {limit} characters.')
    return value


def days(value) -> list[int]:
    if not isinstance(value, (list, tuple)) or not value or any(type(d) is not int or d not in range(7) for d in value):
        raise ValueError('Choose at least one weekday (Monday=0 to Sunday=6).')
    return sorted(set(value))


def streak(habit: dict, today: date) -> int:
    """An unfinished today does not break yesterday's streak; rest days are skipped."""
    done, count = set(habit['checks']), 0
    cursor = today
    if cursor.isoformat() not in done:
        cursor -= timedelta(days=1)
    created = date.fromisoformat(habit['created'])
    while cursor >= created:
        if cursor.weekday() in habit['weekdays']:
            if cursor.isoformat() not in done:
                break
            count += 1
        cursor -= timedelta(days=1)
    return count


class Tracker:
    def __init__(self, work=None):
        self.work = work or workspace

    @contextmanager
    def db(self):
        with self.work._db() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS tracker_habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                weekdays TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1)''')
            conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS tracker_active_name
                ON tracker_habits(lower(name)) WHERE archived=0''')
            conn.execute('''CREATE TABLE IF NOT EXISTS tracker_checks (
                habit_id INTEGER NOT NULL, day TEXT NOT NULL,
                PRIMARY KEY(habit_id,day))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS tracker_task_meta (
                task_id INTEGER PRIMARY KEY, due TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'normal', notes TEXT NOT NULL DEFAULT '')''')
            yield conn

    def snapshot(self, today: date | None = None) -> dict:
        today = today or date.today()
        with self.db() as conn:
            habits = []
            for row in conn.execute('SELECT * FROM tracker_habits ORDER BY archived, id'):
                item = dict(row)
                item['weekdays'] = json.loads(item['weekdays'])
                item['checks'] = [r[0] for r in conn.execute(
                    'SELECT day FROM tracker_checks WHERE habit_id=? ORDER BY day', (row['id'],))]
                item['streak'] = streak(item, today)
                habits.append(item)
            tasks = []
            # The desktop loads all saved tasks; Workspace's conversational view is bounded to 100.
            for row in conn.execute('SELECT id FROM workspace_tasks ORDER BY updated DESC,id DESC'):
                item = self.work._task(conn, row['id'])
                meta = conn.execute('SELECT due,priority,notes FROM tracker_task_meta WHERE task_id=?', (row['id'],)).fetchone()
                item.update(dict(meta) if meta else {'due': '', 'priority': 'normal', 'notes': ''})
                tasks.append(item)
        return {'date': today.isoformat(), 'habits': habits, 'tasks': tasks}

    def context(self) -> list[dict]:
        today = date.today()
        with self.db() as conn:
            rows = conn.execute('SELECT h.id,h.name,h.weekdays,c.day FROM tracker_habits h '
                                'LEFT JOIN tracker_checks c ON c.habit_id=h.id AND c.day=? '
                                'WHERE h.archived=0 ORDER BY h.id LIMIT 5', (today.isoformat(),)).fetchall()
            return [{'name': r['name'], 'scheduled_today': today.weekday() in json.loads(r['weekdays']),
                     'done_today': bool(r['day']), 'source': 'owner_report'} for r in rows]

    def task_context(self, task_ids: list[int]) -> dict:
        with self.db() as conn:
            # Caller supplies the already bounded shared task list.
            return {ident: dict(row) for ident in task_ids if (row := conn.execute(
                'SELECT due,priority,notes FROM tracker_task_meta WHERE task_id=?', (ident,)).fetchone())}

    @staticmethod
    def _habit(conn, ident, revision=None):
        row = conn.execute('SELECT * FROM tracker_habits WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError('That habit no longer exists. Refresh the list.')
        if revision is not None and row['revision'] != revision:
            raise ValueError('This habit changed elsewhere. Close the draft and refresh before editing again.')
        return row

    def save_habit(self, name: str, weekdays, notes: str = '', ident=None, revision=None) -> int:
        name, weekdays, notes = text(name), days(weekdays), text(notes, 1000, True)
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            duplicate = conn.execute('SELECT id FROM tracker_habits WHERE lower(name)=lower(?) AND archived=0', (name,)).fetchone()
            if duplicate and duplicate['id'] != ident:
                raise ValueError('A habit with this name already exists.')
            if ident is None:
                ident = conn.execute('INSERT INTO tracker_habits(name,weekdays,notes,created) VALUES(?,?,?,?)',
                                     (name, json.dumps(weekdays), notes, date.today().isoformat())).lastrowid
            else:
                self._habit(conn, ident, revision)
                conn.execute('UPDATE tracker_habits SET name=?,weekdays=?,notes=?,revision=revision+1 WHERE id=?',
                             (name, json.dumps(weekdays), notes, ident))
        self.work.store.record('habit', 'tracker', f'Owner saved habit {ident}')
        return ident

    def archive(self, ident: int, archived: bool, revision=None) -> None:
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._habit(conn, ident, revision)
            if not archived and conn.execute('SELECT 1 FROM tracker_habits WHERE lower(name)=lower(?) AND archived=0 AND id<>?',
                                             (row['name'], ident)).fetchone():
                raise ValueError('Rename the active habit with this name before restoring this one.')
            conn.execute('UPDATE tracker_habits SET archived=?,revision=revision+1 WHERE id=?', (bool(archived), ident))
        self.work.store.record('habit', 'tracker', f'Owner {"archived" if archived else "restored"} habit {ident}')

    def check(self, ident: int, day: str, done: bool, revision=None) -> None:
        when = date.fromisoformat(day)
        day = when.isoformat()
        if type(done) is not bool or when > date.today():
            raise ValueError('Check-ins must be today or in the past.')
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._habit(conn, ident, revision)
            if row['archived'] or day < row['created'] or when.weekday() not in json.loads(row['weekdays']):
                raise ValueError('Choose a scheduled day on or after this habit was created.')
            if done:
                conn.execute('INSERT OR IGNORE INTO tracker_checks(habit_id,day) VALUES(?,?)', (ident, day))
            else:
                conn.execute('DELETE FROM tracker_checks WHERE habit_id=? AND day=?', (ident, day))
            conn.execute('UPDATE tracker_habits SET revision=revision+1 WHERE id=?', (ident,))
        self.work.store.record('habit', 'tracker', f'Owner reported habit {ident} {"done" if done else "unchecked"} on {day}', status='reported')

    def import_habits(self, content: str, csv_format: bool = False) -> tuple[int, int]:
        if len(content.encode('utf-8')) > 1024 * 1024:
            raise ValueError('Choose a habit list smaller than 1 MB.')
        if csv_format:
            reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')))
            if not reader.fieldnames or 'name' not in reader.fieldnames:
                raise ValueError('CSV needs a name column; optional columns: weekdays, notes.')
            raw = list(reader)
        else:
            raw = [{'name': line} for line in content.splitlines() if line.strip()]
        if not 1 <= len(raw) <= 500:
            raise ValueError('Import between 1 and 500 habits at a time.')
        prepared = []
        for row in raw:
            try:
                schedule = [int(d.strip()) for d in row.get('weekdays', '').split(',')] if row.get('weekdays') else list(range(7))
                prepared.append((text(row['name']), json.dumps(days(schedule)), text(row.get('notes') or '', 1000, True)))
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError(f'Invalid import row {len(prepared) + 1}: {error}') from error
        added = skipped = 0
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for name, schedule, notes in prepared:
                if conn.execute('SELECT 1 FROM tracker_habits WHERE lower(name)=lower(?) AND archived=0', (name,)).fetchone():
                    skipped += 1
                    continue
                conn.execute('INSERT INTO tracker_habits(name,weekdays,notes,created) VALUES(?,?,?,?)',
                             (name, schedule, notes, date.today().isoformat()))
                added += 1
        self.work.store.record('habit', 'tracker', f'Owner imported {added} habits; skipped {skipped} duplicates')
        return added, skipped

    def save_task(self, title: str, due: str = '', priority: str = 'normal', notes: str = '', ident=None, revision=None) -> int:
        title, notes = text(title), text(notes, 1000, True)
        if due:
            due = date.fromisoformat(due).isoformat()
        if priority not in {'low', 'normal', 'high'}:
            raise ValueError('Choose low, normal or high priority.')
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if ident is None:
                ident = conn.execute("INSERT INTO workspace_tasks(title,status,updated) VALUES(?,'active',?)", (title, time.time())).lastrowid
            else:
                row = self.work._task(conn, ident)
                if row['updated'] != revision:
                    raise ValueError('This task changed elsewhere. Close the draft and refresh before editing again.')
                if row['status'] in {'completed', 'cancelled'}:
                    raise ValueError('Finished tasks are read-only. Add a new task to continue.')
                conn.execute('UPDATE workspace_tasks SET title=?,updated=? WHERE id=?', (title, time.time(), ident))
            conn.execute('INSERT INTO tracker_task_meta(task_id,due,priority,notes) VALUES(?,?,?,?) '
                         'ON CONFLICT(task_id) DO UPDATE SET due=excluded.due,priority=excluded.priority,notes=excluded.notes',
                         (ident, due, priority, notes))
        self.work.store.record('task', 'tracker', f'Owner saved task {ident}')
        return ident

    def task_action(self, ident: int, action: str, note: str = '', revision=None) -> None:
        # Workspace owns plan/evidence semantics and validates terminal states.
        if action == 'step':
            self.work.advance(ident, note, expected_updated=revision)
        else:
            self.work.task_state(ident, action, note, expected_updated=revision)


tracker = Tracker()
