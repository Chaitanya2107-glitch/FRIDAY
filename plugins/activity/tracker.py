"""Sanitized app sessions, local queries and cooperative tracking lifecycle."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import sys
import threading
import time
from uuid import uuid4

from .nudges import Nudges
from .store import Store, bounds


class Clock:
    def now(self) -> datetime:
        return datetime.now().astimezone()

    def monotonic(self) -> float:
        return time.monotonic()


class Activity:
    def __init__(self, api, policy, provider, clock=None):
        self.api, self.policy, self.provider = api, policy, provider
        self.clock = clock or Clock()
        self.lock = threading.RLock()
        self.store = Store(api.data_dir / 'activity.sqlite3')
        self.nudges = Nudges(policy)
        self.session = None
        self.rowid = None
        self.sample = None
        self.idle = True
        self.closed = False
        self.generation = 0
        self.last_wall = self.clock.now().timestamp()
        self.last_mono = self.clock.monotonic()
        self.started = self.last_wall
        self.next_purge = 0
        self.scenes = {}
        self.confirm_until = 0
        self.commands = None
        # Keep active scene policy across hot reload, but never across process restarts.
        self.epoch = sys.__dict__.setdefault('_friday_activity_epoch', uuid4().hex)
        runtime = api.settings.get('activity.runtime', {})
        if runtime.get('epoch') == self.epoch:
            self.scenes = dict(runtime.get('scenes', {}))
            self.nudges.overrides = dict(runtime.get('overrides', {}))
            self.nudges.last = runtime.get('last_nudge', -float('inf'))
        self.store.purge(self.last_wall - policy.number('retention_days', 1) * 86400)

    def _runtime(self):
        value = {'epoch': self.epoch, 'scenes': self.scenes, 'overrides': self.nudges.overrides}
        if self.nudges.last != -float('inf'):
            value['last_nudge'] = self.nudges.last
        self.api.settings.set('activity.runtime', value)

    def paused(self):
        return bool(self.policy.values.get('paused') or (self.policy.values.get('pause_in_private_scene')
                    and 'private' in self.scenes.values()))

    def _finish(self, end):
        if self.session:
            self.session['end'] = max(self.session['start'], end)
            self.rowid = self.store.save(self.session, self.rowid)
        self.session, self.rowid = None, None

    def poll(self):
        notification = None
        with self.lock:
            if self.closed or self.api.stop_event.is_set():
                return
            self.policy.reload()
            now, mono = self.clock.now().timestamp(), self.clock.monotonic()
            if mono >= self.next_purge:
                cutoff = now - self.policy.number('retention_days', 1) * 86400
                self.store.purge(cutoff)
                if self.session:
                    self.session['start'] = max(self.session['start'], cutoff)
                    if self.session['end'] - self.session['start'] < 3:
                        self.rowid = None
                self.next_purge = mono + 3600
            if self.paused():
                self._finish(now)
                self.sample = None
                self.nudges.reset()
                self.last_wall, self.last_mono = now, mono
                return
            wall_delta, mono_delta = now - self.last_wall, mono - self.last_mono
            if mono_delta > max(10, self.policy.number('poll_seconds') * 3) or abs(wall_delta - mono_delta) > 5:
                self._finish(self.last_wall)
                self.nudges.reset()  # Sleep/suspend gaps are unknown, not active time.
                self.sample = None
                if now < self.last_wall:
                    self.store.trim_since(now)  # Do not retain overlapping intervals after a backward clock change.
                if abs(wall_delta - mono_delta) > 5:
                    self.started = now
            sample = self.provider.sample()
            idle = sample.idle_seconds >= self.policy.number('idle_seconds') or (sample.process is None and not sample.private)
            if idle:
                cutoff = max(self.started, now - sample.idle_seconds) if sample.idle_seconds >= self.policy.number('idle_seconds') else now
                self._finish(cutoff)
                if sample.idle_seconds >= self.policy.number('idle_seconds'):
                    self.store.trim_since(cutoff)
                if not self.idle:
                    self.api.publish('activity.idle_started', {'since': cutoff})
                self.idle, self.sample = True, None
                self.nudges.reset()
            else:
                if self.idle:
                    self.api.publish('activity.idle_ended', {'at': now})
                self.idle = False
                key = (sample.process, sample.app_name, sample.category)
                previous = (self.sample.process, self.sample.app_name, self.sample.category) if self.sample else None
                if key != previous or self.session is None:
                    self._finish(now)
                    self.session = dict(start=now, end=now, process=sample.process, app_name=sample.app_name, category=sample.category)
                    self.api.publish('activity.app_changed', dict(process=sample.process, app_name=sample.app_name, category=sample.category))
                else:
                    self.session['end'] = max(self.session['start'], now)
                    self.rowid = self.store.save(self.session, self.rowid)
                self.sample = sample
                notification = self.nudges.check(sample.category, mono, 'game' in self.scenes.values())
                if notification:
                    self._runtime()
                    generation = self.generation
                    self.api.publish('activity.nudge', notification)
            self.last_wall, self.last_mono = now, mono
        if notification:
            def notify():
                with self.lock:
                    if (self.closed or self.idle or (self.sample and self.sample.private) or self.paused()
                            or 'game' in self.scenes.values() or generation != self.generation):
                        return
                    self.api.notify('A small break?',
                        'You have been at this for a while. A short break might feel good.', 'normal')
            self.api.run_background(notify)

    def current(self):
        with self.lock:
            state = 'paused' if self.paused() else 'idle' if self.idle else 'private' if self.sample and self.sample.private else 'active'
            row = self.session or {}
            return dict(state=state, process=row.get('process'), app_name=row.get('app_name'),
                        category=row.get('category'), since=row.get('start'),
                        seconds=max(0, min(self.clock.now().timestamp(), self.last_wall + self.policy.number('poll_seconds')) - row['start']) if row else 0)

    def time_on(self, name: str, range: str = 'today'):
        with self.lock:
            start, end = bounds(range, self.clock.now())
            key = name.strip().casefold()
            seconds = sum(row['end'] - row['start'] for row in self.store.rows(start, end)
                          if key in {str(row['process'] or '').casefold(), str(row['process'] or '').removesuffix('.exe').casefold(),
                                     str(row['app_name'] or '').casefold(), row['category'].casefold()})
            return dict(name=name, range=range, seconds=seconds)

    def summary(self, range: str = 'today'):
        with self.lock:
            start, end = bounds(range, self.clock.now())
            rows = self.store.rows(start, end)
            apps, categories = defaultdict(float), defaultdict(float)
            longest = 0
            stretch_start = stretch_end = None
            for row in rows:
                seconds = row['end'] - row['start']
                categories[row['category']] += seconds
                if row['app_name']:
                    apps[row['app_name']] += seconds
                if row['category'] in {'study', 'coding'}:
                    if stretch_end is None or row['start'] > stretch_end + .001:
                        stretch_start = row['start']
                    stretch_end = row['end']
                    longest = max(longest, stretch_end - stretch_start)
                else:
                    stretch_start = stretch_end = None
            return dict(range=range, active_seconds=sum(categories.values()), private_seconds=categories.get('private', 0),
                        top_apps=[dict(app_name=name, seconds=seconds) for name, seconds in sorted(apps.items(), key=lambda row: (-row[1], row[0]))[:5]],
                        categories=dict(categories), longest_focus_seconds=longest)

    def is_fullscreen(self):
        with self.lock:
            return bool(not self.paused() and not self.idle and self.sample and self.sample.fullscreen)

    def set_threshold_override(self, category, minutes, owner):
        with self.lock:
            self.nudges.set_override(category, minutes, owner)
            self._runtime()

    def clear_overrides(self, owner):
        with self.lock:
            self.nudges.clear(owner)
            self._runtime()

    def scene(self, event):
        with self.lock:
            if event['topic'] == 'scene.state':
                # The official scene manager periodically reconciles events missed
                # during plugin reload. Other plugins' owners are left alone.
                payload = event['payload']
                if event.get('plugin_id') != 'scenes':
                    return
                owner, name = payload.get('scene_id'), payload.get('name')
                name = name.casefold() if isinstance(name, str) else None
                changed = False
                for previous in list(self.scenes):
                    if previous.startswith('scenes:') and previous != owner:
                        self.scenes.pop(previous)
                        changed = True
                for previous in list(self.nudges.overrides):
                    if previous.startswith('scenes:') and previous != owner:
                        self.nudges.clear(previous)
                        changed = True
                if isinstance(owner, str) and owner.startswith('scenes:') and name in {'private', 'game'} and self.scenes.get(owner) != name:
                    self.scenes[owner] = name
                    changed = True
                if changed:
                    self.generation += 1
                    if self.paused():
                        self._finish(self.clock.now().timestamp())
                        self.sample = None
                        self.idle = True
                        self.nudges.reset()
                    self._runtime()
                return
            if event['topic'] not in {'scene.started', 'scene.ended'}:
                return
            self.generation += 1
            payload = event['payload']
            name = str(payload.get('name', '')).casefold()
            owner = str(payload.get('scene_id', name))[:128]
            if event['topic'] == 'scene.started':
                if name in {'private', 'game'}:
                    self.scenes[owner] = name
            else:
                self.scenes.pop(owner, None)
                self.nudges.clear(owner)
            if self.paused():
                self._finish(self.clock.now().timestamp())
                self.sample = None
                self.idle = True
                self.nudges.reset()
            self._runtime()

    def pause(self, value):
        with self.lock:
            self.generation += 1
            self._finish(self.clock.now().timestamp())
            self.policy.update('paused', value)
            self.sample = None
            self.idle = True
            self.started = self.clock.now().timestamp()
            self.nudges.reset()

    def handles(self, text):
        return self.commands is not None and self.commands.matches(text)

    def handle_command(self, text):
        return self.commands.run(text)

    def close(self):
        with self.lock:
            if not self.closed:
                self._finish(self.last_wall)
                self.store.close()
                self.sample = None
                self.idle = True
                self.generation += 1
                self.closed = True
