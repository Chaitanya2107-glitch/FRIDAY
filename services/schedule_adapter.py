"""Read-only College Schedules projection. No initialization, edits or AI calls."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import logging


@dataclass(frozen=True)
class ScheduleItem:
    id: str
    title: str
    subject: str = ''
    faculty: str = ''
    room: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    due_at: datetime | None = None
    kind: str = 'class'


class ScheduleAdapter:
    def __init__(self, *, now=datetime.now, log=None, facts_reader=None):
        self.now, self.log = now, log or logging.getLogger(__name__)
        self._warned = set()
        if facts_reader is None:
            from services.schedule_facts_readonly import facts
            facts_reader = facts
        self.facts_reader = facts_reader

    def _read(self, source, fn):
        try:
            return fn()
        except Exception as error:
            self._once(source, f'College {source} unavailable ({type(error).__name__}); skipping it.')
            return []

    def _once(self, key, text):
        if key not in self._warned:
            self._warned.add(key)
            self.log.info(text)

    @staticmethod
    def _days(value):
        if type(value) is not int or not 0 <= value <= 366:
            raise ValueError('Use 0 to 366 days')
        return value

    def _classes(self, day, known):
        from services.proactive import attendance, timetable
        if day.isoformat() in attendance.load()['holidays']:
            return []
        rows = []
        for row in timetable.classes_for_date(day, known=known):
            metadata = self._metadata(row['subject'])
            start = datetime.fromisoformat(f"{day.isoformat()}T{row['start']}")
            end = datetime.fromisoformat(f"{day.isoformat()}T{row['end']}")
            # Academic occurrence identity is independent of faculty/room display metadata.
            identity = f"{day.isoformat()}:{row['subject']}:{row['start']}"
            ident = hashlib.sha256(identity.encode()).hexdigest()
            rows.append(ScheduleItem(ident, row['subject'], row['subject'], metadata.get('faculty', ''),
                metadata.get('room') or row.get('room'), start, end))
        return rows

    def classes_on(self, day: date | str) -> list[ScheduleItem]:
        day = date.fromisoformat(day) if isinstance(day, str) else day
        if not isinstance(day, date) or isinstance(day, datetime):
            raise ValueError('Use a calendar date')
        def read():
            from services.proactive import timetable
            if not timetable.load():
                self._once('empty', 'No College Schedules timetable yet; schedule alerts remain quiet.')
                return []
            return self._classes(day, self.facts_reader())
        return self._read('classes', read)

    def next_classes(self, n: int = 1) -> list[ScheduleItem]:
        if type(n) is not int or not 1 <= n <= 128:
            raise ValueError('Use 1 to 128 classes')
        def read():
            from services.proactive import timetable
            if not timetable.load():
                self._once('empty', 'No College Schedules timetable yet; schedule alerts remain quiet.')
                return []
            now, found, known = self.now(), [], self.facts_reader()
            for offset in range(367):
                day = now.date() + timedelta(days=offset)
                found.extend(row for row in self._classes(day, known) if row.start >= now)
                if len(found) >= n:
                    break
            return found[:n]
        return self._read('classes', read)

    def _metadata(self, subject):
        from services.college import catalogs
        return self._read('subject metadata', lambda: catalogs.subject_for(subject)) or {}

    def _work(self):
        from services.college import work
        rows = []
        for row in work.snapshot()['items']:
            if row.get('done'):
                continue
            kind = 'exam' if work.is_exam(row) else row.get('kind', 'other')
            if kind == 'other':
                title = row['what'].casefold()
                kind = 'homework' if 'homework' in title else 'assignment' if 'assignment' in title else kind
            metadata = self._metadata(row.get('subject', ''))
            rows.append(ScheduleItem(str(row['id']), row['what'], row.get('subject', ''), metadata.get('faculty', ''),
                room=row.get('venue') or metadata.get('room') or None,
                due_at=datetime.fromisoformat(row['due']), kind=kind))
        return sorted(rows, key=lambda item: item.due_at)

    def due_items(self, within_days: int = 7) -> list[ScheduleItem]:
        end = self.now() + timedelta(days=self._days(within_days))
        return self._read('deadlines', lambda: [row for row in self._work() if row.due_at <= end])

    def upcoming_exams(self, within_days: int = 7) -> list[ScheduleItem]:
        now = self.now()
        return [row for row in self.due_items(within_days) if row.kind == 'exam' and row.due_at >= now]

    def pending_homework(self) -> list[ScheduleItem]:
        return self._read('homework', lambda: [row for row in self._work() if row.kind == 'homework'])

    def upcoming_events(self, within_days: int = 7) -> list[ScheduleItem]:
        days = self._days(within_days)
        def read():
            from services.college.reading import upcoming_events
            return [ScheduleItem(str(row['id']), row['title'], room=row['location'] or None,
                start=datetime.fromisoformat(row['date'] + 'T' + row['start']),
                end=datetime.fromisoformat(row['date'] + 'T' + row['end']) if row['end'] else None, kind='event')
                for row in upcoming_events(self.now(), days=days)]
        return self._read('events', read)


_adapter = ScheduleAdapter()
next_classes = _adapter.next_classes
classes_on = _adapter.classes_on
due_items = _adapter.due_items
upcoming_exams = _adapter.upcoming_exams
pending_homework = _adapter.pending_homework
