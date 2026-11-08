"""Read-only real College Schedules command preview; no voice, UI or network.

Run from the repository: venv/Scripts/python.exe -B tests/schedule_briefings_preview.py
Private results stay in the ignored tasks directory. Calendar hashes must match.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import config
from plugins.briefings.content import Builder
from plugins.briefings.delivery import Briefings
from services.college import store
from services.memory.semantic import semantic_memory
from services.mind.cognition import cognition
from services.proactive import attendance, class_sessions, deadlines, timetable
from services.schedule_adapter import ScheduleAdapter


class PreviewAPI:
    def __init__(self, path, adapter):
        self.data_dir, self.settings = path, {'briefings.speak': False}
        self.services, self.events = {'schedule': adapter}, []

    def get_service(self, name):
        return self.services.get(name)

    def _active(self):
        pass

    def publish(self, topic, payload):
        self.events.append((topic, payload))

    def set_mood(self, *args, **kwargs):
        pass

    def run_background(self, fn):
        pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def snapshot():
    files = {timetable.path, deadlines.path, attendance.path, class_sessions.path(),
             Path(semantic_memory.db_path), Path(cognition.path), timetable.subjects_path}
    college = store.path('subjects.json').parent
    if college.exists():
        files.update(p for p in college.rglob('*') if p.is_file())
    for db in [Path(semantic_memory.db_path), Path(cognition.path)]:
        files.update(Path(str(db)+suffix) for suffix in ['-wal', '-shm'])
    return {str(path): digest(path) for path in sorted(files)}


def preview():
    before = snapshot()
    adapter = ScheduleAdapter()
    upcoming = adapter.next_classes(1)
    with tempfile.TemporaryDirectory(prefix='friday-brief-preview-') as temp:
        api = PreviewAPI(Path(temp), adapter)
        builder = Builder(api, battery=lambda: None, choose=lambda variants: variants[0])
        briefings = Briefings(api, builder, desktop=lambda: {'fullscreen': False}, quiet=lambda: False)
        reply = briefings.handle_command('brief me')
        assert reply['ok'] and 1 <= len(reply['text'].splitlines()) <= 6
        example = None
        if upcoming:
            sample_at = upcoming[0].start.replace(hour=6, minute=0, second=0, microsecond=0)
            api.services['schedule'] = ScheduleAdapter(now=lambda: sample_at)
            builder.now = lambda: sample_at
            example = dict(date=sample_at.date().isoformat(), text=builder.render('morning')[0])
        result = dict(checked_at=datetime.now().isoformat(), weekly_slots=len(timetable.load()),
            today_classes=len(adapter.classes_on(datetime.now().date())),
            pending_due_items=len(adapter.due_items(7)), morning_lines=len(reply['text'].splitlines()),
            morning_text=reply['text'], next_class_day_example=example)
    after = snapshot()
    assert before == after, 'An academic source changed during the read-only preview; inspect before claiming validation.'
    result.update(academic_sources_unchanged=True, source_hashes=before)
    output = ROOT / 'tasks/schedule-briefings/real-preview.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['weekly_slots', 'today_classes', 'pending_due_items',
        'morning_lines', 'academic_sources_unchanged']}))
    print(reply['text'])
    if example:
        print('Next class day example (' + example['date'] + '): ' + example['text'])


if __name__ == '__main__':
    preview()
