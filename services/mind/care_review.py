"""Private weekly arithmetic and one owner-confirmed experiment, without models."""
from datetime import datetime, timedelta

from . import coaching_metrics as metrics


def numbers(start, end, *, data=None, entries=None):
    data = data if data is not None else metrics.snapshot(start, end)
    if entries is None:
        from .care import store
        entries = store().entries(start, end)
    categories = {}
    for row in data['segments']:
        categories.setdefault(row['category'], []).append((row['start'], row['end']))
    nights = metrics.sleep_days(data, start, end)
    return dict(start=start.isoformat(), end=end.isoformat(),
                screen_minutes=metrics.seconds((r['start'], r['end']) for r in data['segments']) / 60,
                categories={key: metrics.seconds(value) / 60 for key, value in categories.items()},
                focus_minutes=metrics.seconds((r['start'], r['end']) for r in data['focus']) / 60,
                breaks_taken=sum(row['kind'] == 'breaks' for row in entries),
                sleep_minutes=sum(row['minutes'] for row in nights) / len(nights) if nights else None,
                sleep_days=len(nights), sleep_sources=sorted({r['source'] for r in nights}),
                observed_days=len({datetime.fromtimestamp(r['start']).date() for r in data['segments']}))


def weekly(now=None, *, current=None, previous=None):
    now = now or datetime.now()
    start = now - timedelta(days=7)
    current = current if current is not None else numbers(start, now)
    previous = previous if previous is not None else numbers(start - timedelta(days=7), start)
    def line(row):
        sleep = f"{row['sleep_minutes']:.0f} recorded/estimated minutes over {row['sleep_days']} nights" if row['sleep_minutes'] is not None else 'unavailable'
        categories = ', '.join(f'{key} {value:.0f} min' for key, value in sorted(row['categories'].items())) or 'unavailable'
        return (f"Sleep average {sleep}. Screen {row['screen_minutes']:.0f} min across {row['observed_days']} observed days; "
                f"categories: {categories}. Focus {row['focus_minutes']:.0f} min. Breaks you logged: {row['breaks_taken']}.")
    return dict(current=current, previous=previous, text='Your last seven days: ' + line(current) + '\nYour previous seven days: ' + line(previous)
                + '\nOnly your own records are compared. Missing sleep is not zero; screen/charging is an uncertain sleep estimate. Category intervals may overlap when two devices are used together.')


def phone_study(start, end, data=None):
    data = data if data is not None else metrics.snapshot(start, end)
    phone = [(r['start'], r['end']) for r in data['segments'] if r['device'] == 'phone']
    study = [(r['start'], r['end']) for r in data['focus']]
    study += [(r['start'], r['end']) for r in data.get('contexts', []) if r['situation'] == 'study']
    return metrics.seconds(metrics.intersect(phone, study)) / 60 if phone and study else None


def propose_experiment(now=None):
    from .phone_patterns import lock
    # Serialize source reads and derived writes with the existing phone-forget boundary.
    with lock:
        return _propose_experiment(now)


def _propose_experiment(now=None):
    from .outcome_learning import OutcomeLearning
    from .cognition import cognition
    now = now or datetime.now()
    finish_experiments(now)
    for row in OutcomeLearning(cognition).private_experiments():
        if row['state'] in {'proposed', 'confirmed'}:
            if row['state'] == 'confirmed':
                raise ValueError('One experiment is already running. Review its result after the displayed end date.')
            return dict(id=row['id'], text=f"One optional experiment: {row['definition']['name']}. Baseline {row['baseline']} recorded minutes. Measurement window {datetime.fromtimestamp(row['start']).isoformat()} to {datetime.fromtimestamp(row['end']).isoformat()}. Confirm yes or leave it.")
    start = now - timedelta(days=7)
    data = metrics.snapshot(start, now)
    baseline = phone_study(start, now, data)
    if baseline is None:
        raise ValueError('There is not enough recorded phone and study time to measure this experiment yet.')
    definition = dict(name='Put the phone in another room for the first study block', metric='phone_study_minutes', direction='decrease')
    sources = [{'device': device} for device in sorted({r.get('device_id') for r in data['segments'] if r.get('device_id')})]
    identity = OutcomeLearning(cognition).propose_private_experiment(definition, baseline, now, now + timedelta(days=7), sources, now=now)
    return dict(id=identity, text=f"One optional experiment: {definition['name']}. Baseline: {baseline:.0f} recorded phone minutes overlapping study in the previous seven days. "
                'Compare the same metric over the next seven days. Missing coverage will stay unknown; no app is blocked. Confirm with yes or leave it.')


def finish_experiments(now=None):
    from .outcome_learning import OutcomeLearning
    from .cognition import cognition
    now = now or datetime.now()
    outcomes = OutcomeLearning(cognition)
    results = []
    for row in outcomes.private_experiments():
        if row.get('state') not in {'confirmed', 'active'}:
            continue
        start = datetime.fromtimestamp(row['start']) if isinstance(row['start'], (int, float)) else datetime.fromisoformat(row['start'])
        end = datetime.fromtimestamp(row['end']) if isinstance(row['end'], (int, float)) else datetime.fromisoformat(row['end'])
        if end > now:
            continue
        data = metrics.snapshot(start, end)
        value = phone_study(start, end, data)
        sources = [{'device': device} for device in sorted({r.get('device_id') for r in data['segments'] if r.get('device_id')})]
        result = outcomes.finish_private_experiment(row['id'], value, sources, now)
        if result is not None:
            results.append(result)
    return results
