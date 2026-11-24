"""Local daily phases from the effective timetable and P3 sleep observations."""

from datetime import datetime, timedelta

from core.config import config
from core.logger import logger

CLASS_LEAD = timedelta(hours=2)
WAKING_LENGTH = timedelta(hours=1)


def _first_class(now):
    from services.schedule_adapter import classes_on

    starts = [row.start.replace(tzinfo=now.tzinfo) for row in classes_on(now.date()) if row.start]
    return min(starts, default=None)


def _completed_sleep(now):
    from services.activity.timeline import phone_events
    from services.mind.phone_patterns import sleep_estimate

    events = phone_events((now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=6)).timestamp(),
                          now.timestamp())
    estimates = [sleep_estimate([row for row in events if row['device'] == device], now)
                 for device in {row['device'] for row in events}]
    return min((row for row in estimates if row), key=lambda row: row['first_unlock'], default=None)


def current(now=None, *, attention=None, laptop_idle=None, input_observed=False):
    now = now or datetime.now()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    default_wake = wake = day.replace(hour=7, minute=30)
    first = _first_class(now)
    if first:
        wake = max(day, min(wake, first - CLASS_LEAD))
    planned_wake = wake
    value = config.JOURNAL_HOUR.strip()
    nightly_enabled = value.isdigit() and 0 <= int(value) < 24
    wind = day.replace(hour=int(value) if nightly_enabled else 22)
    bed = max(day.replace(hour=23, minute=30), wind + timedelta(minutes=30))
    phase_source = 'timetable' if wake < default_wake else 'clock'
    minutes = None
    try:
        if attention is None:
            from services.activity.attention import where_is_attention
            attention = where_is_attention(now, laptop_idle=laptop_idle, publish=False)
        if attention.get('data_available'):
            if estimate := _completed_sleep(now):
                wake = datetime.fromtimestamp(estimate['first_unlock'], now.tzinfo)
                minutes = estimate['health_minutes'] or round(estimate['seconds'] / 60)
                if wake <= day.replace(hour=12) and now < wind:
                    phase_source = 'phone_wake_estimate'
                else:
                    wake = planned_wake
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        logger.debug('Rhythm phone estimate unavailable (%s)', type(error).__name__)
    attention = attention or {}
    phone_sleep = (not input_observed and attention.get('data_available') and attention.get('sleep_estimate')
                   and attention.get('attention') == 'away' and attention.get('confidence', 0) >= .6)
    recent_activity = input_observed or (attention.get('data_available') and attention.get('attention') in {'phone', 'both', 'laptop'}
                       and (attention.get('confidence', 0) >= .6 or laptop_idle is not None and laptop_idle < 180))

    wake_end = min(wake + WAKING_LENGTH, first) if first and first > wake else wake + WAKING_LENGTH
    if phone_sleep:
        phase, phase_source = 'asleep', 'phone_sleep_estimate'
    elif now >= bed or now < wake:
        phase = 'asleep'
        if now >= bed:
            phase_source = 'clock'
        if recent_activity:
            phase, phase_source = ('winding_down' if now >= bed else 'waking'), 'recent_activity'
    elif now >= wind:
        phase, phase_source = 'winding_down', 'clock'
    elif now < wake_end:
        phase = 'waking'
    else:
        phase = 'active'
    tiredness = {'waking': .17, 'active': 0., 'winding_down': .26, 'asleep': .4}[phase]
    if minutes is not None and minutes < 420:
        tiredness = max(tiredness, min(.5, (420 - minutes) / 480))
    return {'phase': phase, 'source': phase_source, 'planned_wake': planned_wake.isoformat(timespec='minutes'),
            'wake_at': wake.isoformat(timespec='minutes'), 'winding_down_at': wind.isoformat(timespec='minutes'),
            'bed_at': bed.isoformat(timespec='minutes'), 'sleep_minutes_estimate': minutes,
            'tiredness': round(tiredness, 3),
            'nightly_due': nightly_enabled and now >= wind and phase in {'winding_down', 'asleep'}}
