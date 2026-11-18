"""Deterministic quantified progress and free-slot arithmetic, without a model."""
from datetime import datetime, time, timedelta
import math


def window(definition, now, created):
    cadence = definition.get('cadence')
    if not cadence:
        return created, datetime.combine(datetime.fromisoformat(definition['deadline']).date() + timedelta(days=1), time.min)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if cadence['period'] == 'week':
        start -= timedelta(days=start.weekday())
    end = start + timedelta(days=7 if cadence['period'] == 'week' else 1)
    return max(start, created), end


def progress(definition, done, now=None, created=None):
    now = now or datetime.now(); created = created or now
    start, end = window(definition, now, created)
    cadence = definition.get('cadence')
    days = cadence['days'] if cadence else list(range(7))
    active = now.weekday() in days if cadence else now < end
    count = lambda a, b: sum((a.date() + timedelta(days=i)).weekday() in days for i in range(max(0, (b.date() - a.date()).days)))
    remaining_days = count(now.replace(hour=0, minute=0, second=0, microsecond=0), end)
    total_days = max(1, count(start.replace(hour=0, minute=0, second=0, microsecond=0), end))
    elapsed_days = max(1, min(total_days, count(start.replace(hour=0, minute=0, second=0, microsecond=0), now.replace(hour=0, minute=0, second=0, microsecond=0)) + int(active)))
    target = float(definition['target'])
    result = dict(target=target, unit=definition['unit'], start=start.isoformat(), end=end.isoformat(),
                  done=done, due_today=active, remaining_days=remaining_days, unavailable=done is None)
    if done is None:
        return dict(result, remaining=None, needed_per_day=None, pace_per_day=None, projected_finish=None, slack=None, shortfall=None)
    if type(done) not in (float, int) or not math.isfinite(done) or done < 0:
        raise ValueError('Invalid measured progress.')
    remaining = max(0, target - done)
    rate = done / elapsed_days
    finish = None
    if rate:
        finish = now.date()
        while finish.weekday() not in days:
            finish += timedelta(days=1)
        weeks, extra = divmod(max(1, math.ceil(remaining / rate)) - 1, len(days))
        finish += timedelta(weeks=weeks)
        for _ in range(extra):
            finish += timedelta(days=1)
            while finish.weekday() not in days:
                finish += timedelta(days=1)
    if remaining == 0:
        finish = now.date()
    completed_days = max(0, min(total_days, count(start.replace(hour=0, minute=0, second=0, microsecond=0), now.replace(hour=0, minute=0, second=0, microsecond=0))))
    expected = target * completed_days / total_days
    slack = done - expected
    return dict(result, remaining=remaining, needed_per_day=remaining / remaining_days if remaining_days else (0 if remaining == 0 else None),
                pace_per_day=rate, projected_finish=finish.isoformat() if finish else None,
                slack=slack, shortfall=max(0, -slack), overdue=now >= end and remaining > 0)


def free_slots(now, minutes=25, *, classes=None, blocks=(), sleep=('23:00', '07:00'), scene=None, days=7, limit=3):
    """Suggest only; classes may be an effective-date adapter or date->rows mapping."""
    if scene in {'exam', 'sleep'}:
        return []
    if type(minutes) is not int or not 5 <= minutes <= 240 or not 1 <= days <= 14:
        raise ValueError('Choose a block of 5 to 240 minutes within two weeks.')
    result = []
    for offset in range(days):
        day = now.date() + timedelta(days=offset)
        at = lambda value: datetime.combine(day, time.fromisoformat(value))
        day_start, day_end = at('00:00'), at('23:59') + timedelta(minutes=1)
        blocked = []
        rows = classes(day) if callable(classes) else (classes or {}).get(day.isoformat(), []) if isinstance(classes, dict) else classes or []
        for row in rows:
            if isinstance(row, dict):
                blocked.append((at(row['start']), at(row['end'])))
            else:
                blocked.append((row.start, row.end))
        sleep_start, sleep_end = map(at, sleep)
        blocked += [(sleep_start, sleep_end)] if sleep_start < sleep_end else [(day_start, sleep_end), (sleep_start, day_end)]
        for row in blocks:
            begin, end = datetime.fromisoformat(row['start']), datetime.fromisoformat(row['end'])
            if begin < day_end and end > day_start:
                blocked.append((max(begin, day_start), min(end, day_end)))
        current = max(at('07:00'), now)
        current = current.replace(second=0, microsecond=0) + timedelta(minutes=(5 - current.minute % 5) % 5)
        if current < now:
            current += timedelta(minutes=5)
        while current + timedelta(minutes=minutes) <= min(at('22:00'), day_end):
            end = current + timedelta(minutes=minutes)
            conflict = next(((a, b) for a, b in blocked if current < b and end > a), None)
            if conflict:
                current = max(current + timedelta(minutes=5), conflict[1])
                continue
            result.append(dict(start=current.isoformat(), end=end.isoformat(), minutes=minutes))
            if len(result) >= limit:
                return result
            current = end + timedelta(minutes=5)
    return result
