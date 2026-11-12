"""Restart-safe focus/Pomodoro state; pause intervals never count as focused time."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
import math
import threading
from uuid import uuid4

from services import settings_store

from .commands import handle, parse, result

DEFAULTS = {'focus_minutes': 25, 'short_break_minutes': 5, 'long_break_minutes': 15, 'rounds': 4}
PHASES = {'focus', 'short_break', 'long_break'}


class Clock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


def positive(value, maximum=1440):
    return type(value) in {int, float} and math.isfinite(value) and 0 < value <= maximum


def options(value):
    if (not isinstance(value, dict) or any(not positive(value.get(key)) for key in DEFAULTS if key != 'rounds')
            or type(value.get('rounds')) is not int or not 1 <= value['rounds'] <= 24):
        raise ValueError('Focus settings need positive minutes up to 1440 and 1 to 24 rounds.')
    return {key: value[key] for key in DEFAULTS}


class Focus:
    def __init__(self, api, clock=None):
        self.api, self.clock = api, clock or Clock()
        self.path = api.data_dir / 'focus.json'
        self.lock, self.closed = threading.RLock(), False
        self._read_options()
        self.data = self._read()

    def _read_options(self):
        raw = self.api.settings.get('focus', {})
        if not isinstance(raw, dict):
            raise ValueError('Focus settings must be a JSON object.')
        value = options(DEFAULTS | raw)
        if value != raw:
            self.api.settings.set('focus', value)
        return value

    @staticmethod
    def _segments_valid(segments):
        return (isinstance(segments, list) and all(isinstance(row, list) and len(row) == 2
                and all(type(v) in {int, float} and math.isfinite(v) for v in row) and row[1] >= row[0]
                for row in segments))

    def _read(self):
        if not self.path.exists():
            return {'version': 1, 'active': None, 'history': []}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(data, dict) or data.get('version') != 1 or 'active' not in data
                    or not isinstance(data.get('history'), list)):
                raise ValueError()
            ids = set()
            for row in data['history']:
                if (not isinstance(row, dict) or not isinstance(row.get('session_id'), str) or not row['session_id']
                        or row['session_id'] in ids or type(row.get('completed')) is not bool
                        or not isinstance(row.get('date'), str) or not positive(row.get('planned_minutes'))
                        or not isinstance(row.get('label'), str) or not 1 <= len(row['label']) <= 120
                        or type(row.get('minutes')) not in {int, float} or not math.isfinite(row['minutes'])
                        or not 0 <= row['minutes'] <= row['planned_minutes']
                        or not self._segments_valid(row.get('segments'))):
                    raise ValueError()
                if datetime.fromisoformat(row['date']).date().isoformat() != row['date']:
                    raise ValueError()
                ids.add(row['session_id'])
            state = data.get('active')
            if state is not None:
                if (not isinstance(state, dict) or not isinstance(state.get('session_id'), str)
                        or state['session_id'] in ids or state.get('phase') not in PHASES
                        or type(state.get('paused')) is not bool or type(state.get('pomodoro')) is not bool
                        or type(state.get('round')) is not int or not 1 <= state['round'] <= 24
                        or not positive(state.get('duration_s'), 86400)
                        or not positive(state.get('remaining_s'), 86400)
                        or state['remaining_s'] > state['duration_s']
                        or not isinstance(state.get('label'), str) or not 1 <= len(state['label']) <= 120
                        or not isinstance(state.get('owner'), str) or len(state['owner']) > 128
                        or not self._segments_valid(state.get('segments'))):
                    raise ValueError()
                options(state.get('schedule'))
                if state['round'] > state['schedule']['rounds']:
                    raise ValueError()
                times = [state.get('started_at')]
                if state['paused']:
                    if state.get('end_at') is not None or state.get('segment_start') is not None:
                        raise ValueError()
                else:
                    times.extend([state.get('end_at'), state.get('segment_start')])
                if any(type(v) not in {int, float} or not math.isfinite(v) for v in times):
                    raise ValueError()
                if not state['paused'] and state['end_at'] < state['segment_start']:
                    raise ValueError()
            return data
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError('Focus state is damaged. Restore focus.json before changing it; the original was preserved.') from error

    def _save(self, data):
        self.api._active()
        settings_store.save(self.path, data)
        self.data = data

    def _new(self, minutes, label, owner, schedule, now, *, pomodoro=False, phase='focus', round=1):
        from services.remote.context import remote_origin
        seconds = float(minutes) * 60
        state = dict(session_id=uuid4().hex, owner=owner, label=label, phase=phase, round=round,
                    pomodoro=pomodoro, schedule=schedule, started_at=now, segment_start=now,
                    end_at=now + seconds, duration_s=seconds, remaining_s=seconds, paused=False, segments=[])
        if remote_origin.get() or owner == 'remote':
            state['remote_origin'] = True
        return state

    def _segments(self, state, now):
        segments = deepcopy(state['segments'])
        if not state['paused']:
            budget = max(0, state['duration_s'] - sum(end-start for start, end in segments))
            end = state['segment_start'] + min(budget, max(0, min(now, state['end_at']) - state['segment_start']))
            if end > state['segment_start']:
                segments.append([state['segment_start'], end])
        return segments

    def _payload(self, state, **extra):
        if state.get('remote_origin'):
            extra['remote_origin'] = True
        return dict(session_id=state['session_id'], owner=state['owner'], minutes=state['duration_s']/60,
                    label=state['label'], task=state['label'], phase=state['phase'], round=state['round'],
                    duration_s=state['duration_s'], **extra)

    def _record(self, data, state, now, completed):
        if state['phase'] == 'focus':
            segments = self._segments(state, now)
            seconds = sum(end-start for start, end in segments)
            finished = datetime.fromtimestamp(now, self.clock.now().tzinfo).date().isoformat()
            data['history'].append(dict(session_id=state['session_id'], date=finished,
                minutes=min(seconds, state['duration_s'])/60, planned_minutes=state['duration_s']/60, completed=completed,
                label=state['label'], segments=segments))

    def start(self, minutes=None, label='Focus', owner='', *, pomodoro=False):
        try:
            schedule = self._read_options()
            minutes = schedule['focus_minutes'] if minutes is None else minutes
            if (not positive(minutes) or not isinstance(label, str) or not 1 <= len(label) <= 120
                    or not isinstance(owner, str) or len(owner) > 128
                    or any(ord(c) < 32 for c in label + owner) or type(pomodoro) is not bool):
                raise ValueError('Use positive focus minutes up to 1440 and a short label/owner.')
        except ValueError as error:
            return result(str(error), ok=False, error='invalid_focus')
        self.tick()
        with self.lock:
            if self.closed:
                return result('Focus has been unloaded.', ok=False, error='unloaded')
            if self.data['active']:
                return result('A focus timer is already running or paused. Stop it before starting another.',
                              ok=False, error='already_running', data=self._status())
            now = self.clock.now().timestamp()
            state = self._new(minutes, label, owner, schedule, now, pomodoro=pomodoro)
            self._save(dict(self.data, active=state))
            self.api.publish('focus.started', self._payload(state))
            return result(f'{label} started for {minutes:g} minutes.', data=self._status())

    def tick(self):
        with self.lock:
            if self.closed or self.api.stop_event.is_set():
                return
            state, now = self.data['active'], self.clock.now().timestamp()
            if state is None or state['paused'] or now < state['end_at']:
                return
            data = deepcopy(self.data)
            self._record(data, state, state['end_at'], True)
            next_state = None
            if state['pomodoro']:
                schedule = state['schedule']
                if state['phase'] == 'focus':
                    phase = 'long_break' if state['round'] == schedule['rounds'] else 'short_break'
                    minutes = schedule[phase + '_minutes']
                    label, round = ('Long break' if phase == 'long_break' else 'Short break'), state['round']
                else:
                    phase, minutes = 'focus', schedule['focus_minutes']
                    round = 1 if state['round'] == schedule['rounds'] else state['round'] + 1
                    label = 'Pomodoro'
                # Never synthesize completed work while FRIDAY was not running.
                next_state = self._new(minutes, label, state['owner'], schedule, now,
                                       pomodoro=True, phase=phase, round=round)
                if state.get('remote_origin'):
                    next_state['remote_origin'] = True
            data['active'] = next_state
            self._save(data)  # Completion/history/next phase share one durable transaction.
        from services.remote.context import origin_scope
        with origin_scope(state.get('remote_origin', False)):
            self.api.publish('focus.done', self._payload(state, completed=True, elapsed_s=state['duration_s'], reason='completed'))
            if next_state:
                self.api.publish('focus.started', self._payload(next_state))
            self.api.notify('Focus complete' if state['phase'] == 'focus' else 'Break complete',
                            f"{state['label']} finished." + (f" {next_state['label']} has started." if next_state else ''), 'critical')
            self.api.set_mood('celebrating', 6, priority=3)

    def pause(self):
        self.tick()
        with self.lock:
            state = self.data['active']
            if not state:
                return result('No focus timer is running.', ok=False, error='not_running')
            if state['paused']:
                return result('Focus is already paused.', data=self._status())
            now = self.clock.now().timestamp()
            segments = self._segments(state, now)
            # A backward clock correction must not replenish previously completed work.
            budget = max(0, state['duration_s'] - sum(end-start for start, end in segments))
            remaining = min(budget, max(0, state['end_at']-now))
            if remaining > 0:
                state = dict(state, segments=segments, remaining_s=remaining,
                             end_at=None, segment_start=None, paused=True)
                self._save(dict(self.data, active=state))
                self.api.publish('focus.paused', self._payload(state, remaining_s=remaining))
                return result('Focus paused.', data=self._status())
        # The deadline can pass between the first tick and acquiring the lock.
        self.tick()
        return result('The focus phase just finished.', data=self.status())

    def resume(self):
        self.tick()
        with self.lock:
            state = self.data['active']
            if not state:
                return result('No focus timer is paused.', ok=False, error='not_running')
            if not state['paused']:
                return result('Focus is already running.', data=self._status())
            now = self.clock.now().timestamp()
            state = dict(state, segment_start=now, end_at=now + state['remaining_s'], paused=False)
            self._save(dict(self.data, active=state))
            self.api.publish('focus.started', self._payload(state, resumed=True))
            return result('Focus resumed.', data=self._status())

    def stop(self, owner=None):
        with self.lock:
            state = self.data['active']
            if owner is not None and (not state or state['owner'] != owner):
                return result('The scene no longer owns this focus timer; it was left alone.', data=self._status())
        self.tick()
        with self.lock:
            state = self.data['active']
            if not state:
                return result('No focus timer is running.', data=self._status())
            if owner is not None and state['owner'] != owner:
                return result('The scene no longer owns this focus timer; it was left alone.', data=self._status())
            now = self.clock.now().timestamp()
            data = deepcopy(self.data)
            self._record(data, state, now, False)
            data['active'] = None
            self._save(data)
            elapsed = sum(end-start for start, end in self._segments(state, now))
            self.api.publish('focus.done', self._payload(state, completed=False, elapsed_s=elapsed, reason='stopped'))
            return result('Focus stopped.', data=self._status())

    def _status(self):
        state = self.data['active']
        if not state:
            return dict(state='idle', active=False, running=False, remaining_s=0, session_id=None, owner=None)
        remaining = state['remaining_s'] if state['paused'] else max(0, state['end_at']-self.clock.now().timestamp())
        return dict(state='paused' if state['paused'] else 'running', active=True, running=not state['paused'],
                    remaining_s=remaining, session_id=state['session_id'], owner=state['owner'],
                    label=state['label'], phase=state['phase'], round=state['round'], pomodoro=state['pomodoro'],
                    minutes=state['duration_s']/60, end_at=state['end_at'])

    def status(self):
        self.tick()
        with self.lock:
            return self._status()

    def stats(self, period='today'):
        if period not in {'today', 'yesterday', 'this week'}:
            raise ValueError('Use today, yesterday or this week.')
        self.tick()
        with self.lock:
            now = self.clock.now()
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if period == 'this week':
                start -= timedelta(days=start.weekday())
            end = start if period == 'yesterday' else now
            if period == 'yesterday':
                start -= timedelta(days=1)
            low, high = start.timestamp(), end.timestamp()
            rows = self.data['history']
            segments = [segment for row in rows for segment in row['segments']]
            state = self.data['active']
            if state and state['phase'] == 'focus':
                segments.extend(self._segments(state, high))
            seconds = sum(max(0, min(end, high)-max(begin, low)) for begin, end in segments)
            last_date = (end - timedelta(microseconds=1)).date() if period == 'yesterday' else now.date()
            current_rows = [row for row in rows if start.date().isoformat() <= row['date'] <= last_date.isoformat()]
            return dict(range=period, minutes=seconds/60, completed=sum(row['completed'] for row in current_rows),
                        stopped=sum(not row['completed'] for row in current_rows))

    def today_minutes(self):
        return self.stats('today')['minutes']

    def matches(self, text):
        return parse(text)[0] is not None

    def handle_command(self, text):
        return handle(self, text)

    def close(self):
        with self.lock:
            self.closed = True
