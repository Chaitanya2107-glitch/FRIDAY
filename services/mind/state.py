"""One read-only view of FRIDAY's present, assembled from local observations."""

from collections.abc import Mapping
from datetime import datetime
import sqlite3
import threading
import time
from types import MappingProxyType

from core.config import config
from core.logger import logger

CACHE_SECONDS = 3
_lock = threading.RLock()
_cached = None

_SOURCES = MappingProxyType({
    'as_of': 'Local clock supplied to snapshot',
    'mood': 'services.mind.life.mood and services.mind.brain.away_minutes',
    'mood_reason': 'services.mind.life.mood',
    'emotion': 'services.mind.emotion replay of local presentation events and life counters',
    'rhythm': 'services.mind.rhythm from the effective timetable and local P3 sleep estimate',
    'character': 'services.mind.character owner-shaped expression traits and values',
    'life_state': 'services.mind.life_state.current using the shared attention and presence readings',
    'posture': 'life_state.posture',
    'situation': 'services.mind.temporal_memory.situation',
    'due_next': 'Requested reminders, saved deadlines, effective timetable, focus timer, and dated commitments',
    'presence': 'services.presence.engine.current',
    'attention': 'services.activity.attention.where_is_attention, without publication',
    'strongest_thought': 'services.mind.thoughts.alive, ordered by current strength',
    'live_thoughts': 'services.mind.thoughts.alive',
    'quiet': 'services.quiet_mode.enabled, current mode, and conversation settings',
    'focus': 'Current focus timer, study or exam scene, or screen focus',
    'battery': 'services.briefing_context.battery',
    'idle': 'services.activity.log.idle_seconds',
    'live': 'services.mind.cognition_context.live_state',
})


def explain():
    """Return the source of each snapshot field."""
    return _SOURCES


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def as_json(value):
    """Copy the immutable view for an existing mutable or JSON API."""
    if isinstance(value, Mapping):
        return {key: as_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [as_json(item) for item in value]
    return value


def persona(now, *, legacy=False, tone=None):
    from services.mind import brain, life

    away = brain.away_minutes(now)
    if legacy:
        return life.legacy_mood(now, away)
    return life.mood(now, away, tone=tone)


def _read(source, fallback, reader, *args, **kwargs):
    try:
        return reader(*args, **kwargs)
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error) as error:
        logger.debug('Present state %s unavailable (%s)', source, type(error).__name__)
        return fallback


def _next_due(now, situation, timer):
    from services.automation.system_control import AutomationError
    from services.mind.cognition import redact
    from services.proactive import deadlines, timetable
    from services.reminders.service import reminders

    candidates = []

    def add(kind, label, due, *, date_only=False, pending=False):
        stamp = due.timestamp()
        if pending or stamp >= now.timestamp() or date_only and due.date() == now.date():
            value = due.date().isoformat() if date_only else due.isoformat(timespec='seconds')
            candidates.append((stamp, {'kind': kind, 'title': redact(label)[:160], 'due': value}))

    for reminder in _read('reminders', (), reminders.pending)[:1]:
        add('reminder', reminder.text, datetime.fromtimestamp(reminder.due_at, tz=now.tzinfo), pending=True)
    try:
        for row in deadlines.load():
            add('deadline', row['what'], datetime.fromisoformat(row['due']))
    except (AutomationError, ValueError, OSError, KeyError):
        pass
    try:
        if row := timetable.next_class_occurrence(now):
            add('class', row['subject'], datetime.fromisoformat(f"{row['date']}T{row['start']}"))
    except (AutomationError, ValueError, OSError, KeyError):
        pass
    for row in (*situation.get('current', ()), *situation.get('upcoming', ())):
        add('commitment', row['subject'], datetime.fromisoformat(row['start']), date_only=True)
    if timer.get('running') and timer.get('end_at') is not None:
        add('focus_timer', timer['label'], datetime.fromtimestamp(timer['end_at'], tz=now.tzinfo))
    return min(candidates, key=lambda item: item[0], default=(0, None))[1]


def focus_state():
    from services.scene_runtime import services as scene_services
    from services.screen_watch.service import watch

    manager, scenes, focus = scene_services()
    scene = _read('scene', {}, manager.invoke, scenes.api, scenes.status) if scenes else {}
    timer = _read('timer', {}, manager.invoke, focus.api, focus.snapshot) if focus else {}
    name = scene.get('active')
    if isinstance(name, Mapping):
        name = name.get('name')
    return name, timer, bool(watch.focused() or name in {'study', 'exam'}
                             or (timer.get('running') and timer.get('phase') == 'focus'))


def _collect(now):
    from services.activity.attention import where_is_attention
    from services.activity.log import idle_seconds
    from services.automation import modes
    from services.briefing_context import battery
    from services.mind import character, cognition_context, emotion, life_state, rhythm, talk, temporal_memory, thoughts
    from services.presence import engine
    from services.proactive.watcher import is_busy
    from services.quiet_mode import enabled as quiet_enabled

    idle = idle_seconds()
    mode = modes.active() or {}
    preferences = talk.load()
    presence = engine.current(now, laptop_idle=idle)
    attention = _read('attention', {'data_available': False}, where_is_attention, now, laptop_idle=idle, publish=False)
    daily_rhythm = rhythm.current(now, attention=attention, laptop_idle=idle)
    tone = emotion.snapshot(now, daily_rhythm=daily_rhythm)
    mood, why = persona(now, tone=tone)
    moment = {'idle': idle, 'mode': mode, 'preferences': preferences, 'mood': persona(now, legacy=True)[0]}
    token = cognition_context._present_inputs.set((now, moment))
    try:
        live = cognition_context.live_state()
    finally:
        cognition_context._present_inputs.reset(token)
    behavior = life_state.current(now, live=live, preferences=preferences, busy=is_busy(),
                                  attention=attention, presence=presence)
    situation = temporal_memory.situation(now)
    live_thoughts = _read('thoughts', (), thoughts.alive, now)[:4]
    strongest = live_thoughts[0] if live_thoughts else None
    _, timer, focused = focus_state()
    quiet = (quiet_enabled() or mode.get('quiet', False) or not preferences.get('on', True)
             or preferences.get('paused_until', 0) > now.timestamp())

    return _freeze({
        'as_of': now.isoformat(),
        'mood': mood,
        'mood_reason': why,
        'emotion': tone,
        'rhythm': daily_rhythm,
        'character': character.snapshot(now),
        'life_state': behavior,
        'posture': behavior.get('posture'),
        'situation': situation,
        'due_next': _next_due(now, situation, timer),
        'presence': presence,
        'attention': attention,
        'strongest_thought': vars(strongest) | {'at': strongest.at.isoformat()} if strongest else None,
        'live_thoughts': [{'kind': thought.kind, 'data': thought.data} for thought in live_thoughts],
        'quiet': bool(quiet),
        'focus': focused,
        'battery': battery(),
        'idle': idle,
        'live': live,
    })


def _source_stamp():
    """A committed change or forget invalidates any cached private situation."""
    from services.mind import character, emotion, life
    from services.mind.cognition import cognition
    from services.mind.temporal_memory import temporal_memory

    signatures = []
    for path in (cognition.path, temporal_memory.store.path, life.path, emotion.storage_path(), character.storage_path()):
        try:
            signatures.append((path, path.stat().st_mtime_ns))
        except OSError:
            signatures.append((path, None))
    return config.MEMORY_DIR, config.COGNITION_ENABLED, tuple(signatures)


def snapshot(now=None, *, fresh=False):
    """Read one deeply immutable local snapshot. Safety rechecks may read afresh."""
    global _cached
    now = now or datetime.now()
    if fresh:
        return _collect(now)
    with _lock:
        key = _source_stamp()
        monotonic = time.monotonic()
        if _cached:
            stamp, at, saved_key, value = _cached
            age = now.timestamp() - at.timestamp()
            if saved_key == key and at.date() == now.date() and 0 <= age < CACHE_SECONDS and monotonic - stamp < CACHE_SECONDS:
                return value
        value = _collect(now)
        current = _source_stamp()
        # A new database can be initialized during the first read. A committed
        # intervening edit to an existing database must instead force another read.
        if (all(old[1] is None or old == new for old, new in zip(key[2][:2], current[2][:2]))
                and key[2][2:] == current[2][2:]):
            _cached = monotonic, now, current, value
        else:
            _cached = None
        return value
