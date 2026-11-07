"""Six-line composition from optional local services; no model calls."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import random

from . import weather


def clean(value, limit=240):
    return ' '.join(str(value).split())[:limit]


class Builder:
    def __init__(self, api, *, now=datetime.now, battery=lambda: None, choose=random.choice, lines=None):
        self.api, self.now, self.battery, self.choose = api, now, battery, choose
        self.lines = json.loads((lines or Path(__file__).with_name('lines.json')).read_text(encoding='utf-8'))
        if (not isinstance(self.lines, dict) or any(not isinstance(rows, list) or not rows
                or any(not isinstance(row, str) or '\n' in row or len(row) > 500 for row in rows)
                for rows in self.lines.values())):
            raise ValueError('Briefing lines must be nonempty lists of single-line variants')

    def line(self, slot, **fields):
        values = {key: (' ' if key in {'faculty', 'room'} and value else '') + clean(value)
                  for key, value in fields.items()}
        return clean(self.choose(self.lines[slot]).format_map(values), 550)

    def source(self, name, method, *args):
        try:
            service = self.api.get_service(name)
            fn = getattr(service, method, None)
            return fn(*args) if callable(fn) else None
        except Exception:
            return None

    def classes(self, day, *, tomorrow=False):
        rows = self.source('schedule', 'classes_on', day)
        if not rows:
            return ''
        first = min(rows, key=lambda row: row.start)
        return self.line('tomorrow_class' if tomorrow else 'classes', subject=first.subject,
            time=first.start.strftime('%H:%M'), faculty=f' with {first.faculty}' if first.faculty else '',
            room=f' in {first.room}' if first.room else '', count=len(rows), class_word='class' if len(rows) == 1 else 'classes')

    @staticmethod
    def listed(rows):
        values = [clean(row.title, 80) for row in rows[:2]]
        return ', '.join(values) + (f' and {len(rows)-2} more' if len(rows) > 2 else '')

    def due(self, *, morning):
        today = self.now().date()
        rows = self.source('schedule', 'due_items', 2) or []
        lines = []
        for offset in ([0, 1] if morning else [1]):
            found = [row for row in rows if row.due_at and row.due_at.date() == today + timedelta(days=offset)
                     and (not morning or row.kind != 'exam')]
            if found:
                lines.append(self.line('due_today' if offset == 0 else 'due_tomorrow', items=self.listed(found)))
        if morning:
            exams = self.source('schedule', 'upcoming_exams', 7) or []
            if exams:
                detail = ', '.join(f'{clean(row.subject or row.title, 70)} in {(row.due_at.date()-today).days} days' for row in exams[:2])
                if len(exams) > 2:
                    detail += f' and {len(exams)-2} more'
                lines.append(self.line('exams', items=detail))
        return clean(' '.join(lines), 650)

    def work(self, *, morning):
        parts = []
        if morning:
            homework = self.source('schedule', 'pending_homework')
            if homework:
                parts.append(self.line('homework', count=len(homework)))
        todos = self.source('todo', 'snapshot')
        if isinstance(todos, dict) and isinstance(todos.get('items'), list):
            if morning:
                parts.append(self.line('todos', count=sum(not row.get('done') for row in todos['items'])))
            else:
                summary = self.source('todo', 'stats', 'today')
                if isinstance(summary, dict) and type(summary.get('completed')) is int:
                    parts.append(self.line('completed', count=summary['completed']))
                    return clean(' '.join(parts), 550)
                count, dated = 0, False
                for row in todos['items']:
                    if row.get('done') and row.get('done_at'):
                        try:
                            at = datetime.fromisoformat(row['done_at'])
                            at = at.astimezone() if at.tzinfo else at
                            count += at.date() == self.now().date()
                            dated = True
                        except (ValueError, TypeError):
                            pass
                if dated or not any(row.get('done') for row in todos['items']):
                    parts.append(self.line('completed', count=count))
        return clean(' '.join(parts), 550)

    def stats(self, period):
        parts = []
        focus = self.source('focus', 'stats', period)
        if isinstance(focus, dict) and type(focus.get('minutes')) in {int, float}:
            parts.append(self.line('focus', period=period.capitalize(), minutes=round(focus['minutes'])))
        activity = self.source('activity', 'summary', period)
        categories = activity.get('categories') if isinstance(activity, dict) else None
        if isinstance(categories, dict):
            categories = {key: value for key, value in categories.items() if key not in {'private', 'unknown'}
                          and type(value) in {int, float} and value > 0}
            if categories:
                parts.append(self.line('activity', category=max(categories, key=categories.get)))
        return clean(' '.join(parts), 550)

    def charge(self, morning):
        try:
            row = self.battery()
            if (not isinstance(row, dict) or type(row.get('percent')) not in {int, float}
                    or not 0 <= row['percent'] < (50 if morning else 40)
                    or row.get('plugged') is not False or row.get('charging') is True):
                return ''
            return self.line('battery' if morning else 'charge', percent=round(row['percent']))
        except Exception:
            return ''

    def render(self, kind, previous=None):
        if kind not in {'morning', 'night'}:
            raise ValueError('Use morning or night')
        now, morning = self.now(), kind == 'morning'
        slot = kind + '_openers'
        choices = [row for row in self.lines[slot] if row != previous] or self.lines[slot]
        opener = self.choose(choices)
        greeting = 'Good morning' if now.hour < 12 else 'Good afternoon' if now.hour < 17 else 'Good evening'
        name = clean(self.api.settings.get('user_name', ''), 60)
        honorific = clean(self.api.settings.get('honorific', ''), 40)
        address = ', ' + ' '.join(v for v in [honorific, name] if v) if name or honorific else ''
        first = clean(opener.format(greeting=greeting, address=address), 550)
        outside = weather.fetch(self.api.settings)
        if morning:
            first = clean(first + ' ' + outside, 650)
            parts = [first, self.classes(now.date()), self.due(morning=True), self.work(morning=True),
                     self.stats('yesterday'), self.charge(True)]
        else:
            parts = [first, clean(self.stats('today') + ' ' + self.work(morning=False), 650),
                     self.classes(now.date()+timedelta(days=1), tomorrow=True), self.due(morning=False),
                     clean(self.charge(False) + ' ' + outside, 650), self.line('closings')]
        return '\n'.join(part for part in parts if part)[:3900], opener

    def tomorrow_summary(self):
        parts = [self.classes(self.now().date()+timedelta(days=1), tomorrow=True), self.due(morning=False)]
        return '\n'.join(part for part in parts if part) or 'Nothing is recorded for tomorrow yet.'
