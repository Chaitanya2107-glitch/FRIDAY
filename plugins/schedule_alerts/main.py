"""Persistent, offline schedule lead alerts. Academic stores are never changed."""
from datetime import datetime, timedelta
import hashlib
import json
import math
import threading

from services import settings_store
from services.schedule_adapter import ScheduleAdapter


class Alerts:
    def __init__(self, api, adapter, now=datetime.now):
        self.api, self.adapter, self.now = api, adapter, now
        self.path, self.lock = api.data_dir / 'alerts.json', threading.RLock()
        self._load()

    def _load(self):
        if not self.path.exists():
            return {'version': 1, 'sent': {}}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('sent'), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data['sent'].items())):
            raise ValueError('Invalid alerts.json; restore it before resuming alerts')
        return data

    def leads(self, key, default):
        value = self.api.settings.get('schedule_alerts.' + key, default)
        maximum = {'class_minutes': 10080, 'assignment_hours': 8784, 'exam_days': 366}[key]
        if (not isinstance(value, list) or not value or len(value) > 12
                or any(type(v) is not int or not 1 <= v <= maximum for v in value)):
            self.api.log.warning('Invalid schedule alert lead setting %s; using defaults', key)
            return default
        return sorted(set(value), reverse=True)

    def _check(self, row, leads, unit):
        now = self.now()
        target = row.start if row.kind == 'class' else row.due_at
        remaining = (target - now).total_seconds()
        crossed = [lead for lead in leads if 0 < remaining <= lead * unit]
        if not crossed:
            return
        lead = min(crossed)
        with self.lock, settings_store.lock:
            state = self._load()
            def identity(value):
                return hashlib.sha256(f'{row.kind}:{row.id}:{target.isoformat()}:{value * unit}'.encode()).hexdigest()
            key = identity(lead)
            if key in state['sent']:
                return
            self.api._active()
            for older in crossed:
                state['sent'][identity(older)] = target.isoformat()
            # Claim before transient publication: a restart never repeats an alert.
            settings_store.save(self.path, state)
            detail = ' · '.join(str(v) for v in [row.subject, row.faculty, row.room, target.strftime('%a %d %b %H:%M')] if v)
            if row.kind == 'class':
                minutes = math.ceil(remaining / 60)
                payload = dict(subject=row.subject, faculty=row.faculty, room=row.room,
                    starts_at=target.isoformat(), minutes=minutes, lead_minutes=lead, text=detail)
                topic, title = 'schedule.class_soon', f'{row.subject} in {minutes} min'
            else:
                payload = dict(item_id=row.id, title=row.title, kind=row.kind, due_at=target.isoformat(),
                               hours=round(remaining / 3600, 2), lead_hours=lead * unit / 3600, text=detail)
                topic, title = 'schedule.due_soon', row.title + ' · due soon'
            self.api.publish(topic, payload)
            self.api.show_card(title[:120], detail[:1000], ttl_s=45)

    def tick(self):
        classes = self.leads('class_minutes', [15, 5])
        work = self.leads('assignment_hours', [24, 3])
        exams = self.leads('exam_days', [3, 1])
        for offset in range((max(classes) + 1439) // 1440 + 1):
            for row in self.adapter.classes_on(self.now().date() + timedelta(days=offset)):
                self._check(row, classes, 60)
        for row in self.adapter.due_items(max(7, max(exams), (max(work) + 23) // 24)):
            self._check(row, exams if row.kind == 'exam' else work, 86400 if row.kind == 'exam' else 3600)


def register(api):
    adapter = ScheduleAdapter(log=api.log)
    alerts = Alerts(api, adapter)
    api.provide('schedule', adapter)
    api.provide('schedule_alerts', alerts)
    api.every(30, alerts.tick)
