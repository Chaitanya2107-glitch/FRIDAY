"""Lead thresholds and durable at-most-once claims, with a fake civil clock."""
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from briefing_fakes import API, Clock
from plugins.schedule_alerts.main import Alerts, register
from services.schedule_adapter import ScheduleItem


def setup_alerts(tmp_path, kind='class', **settings):
    api, clock = API(tmp_path / 'alerts'), Clock()
    target = clock.now() + timedelta(days=4)
    row = ScheduleItem('stable', 'Physics lab', 'Physics', 'Prof. Ray', 'B-4',
                       start=target if kind == 'class' else None, due_at=target if kind != 'class' else None, kind=kind)
    adapter = SimpleNamespace(classes_on=lambda day: [row] if kind == 'class' and row.start.date() == day else [],
                              due_items=lambda n: [] if kind == 'class' else [row])
    api.settings.update(settings)
    return Alerts(api, adapter, clock.now), clock, row


@pytest.mark.parametrize('kind,unit,leads,topic', [
    ('class', 60, [15, 5], 'schedule.class_soon'),
    ('assignment', 3600, [24, 3], 'schedule.due_soon'),
    ('exam', 86400, [3, 1], 'schedule.due_soon'),
])
def test_each_threshold_once_even_after_restart(tmp_path, kind, unit, leads, topic):
    alerts, clock, row = setup_alerts(tmp_path, kind)
    target = row.start or row.due_at
    for lead in leads:
        clock.value = target-timedelta(seconds=lead*unit+1)
        alerts.tick()
        before = len(alerts.api.payloads(topic))
        clock.advance(seconds=1)
        alerts.tick()
        assert len(alerts.api.payloads(topic)) == before+1
        event = alerts.api.payloads(topic)[-1]
        assert event.get('minutes', event.get('hours')) == lead if kind != 'exam' else event['hours'] == lead*24
        if kind == 'class':
            assert (event['subject'], event['faculty'], event['room'], event['starts_at']) == ('Physics', 'Prof. Ray', 'B-4', target.isoformat())
        else:
            assert (event['title'], event['kind'], event['due_at']) == ('Physics lab', kind, target.isoformat())
        assert all(value in alerts.api.cards[-1][0][1] for value in ('Physics', 'Prof. Ray', 'B-4', target.strftime('%H:%M')))
        alerts = Alerts(alerts.api, alerts.adapter, clock.now)
        alerts.tick()
        assert len(alerts.api.payloads(topic)) == before+1
    assert len(alerts.api.payloads(topic)) == 2
    assert len(json.loads(alerts.path.read_text())['sent']) == 2


def test_starting_late_only_emits_nearest_crossed_lead(tmp_path):
    alerts, clock, row = setup_alerts(tmp_path)
    clock.value = row.start-timedelta(minutes=4)
    alerts.tick()
    assert [p['minutes'] for p in alerts.api.payloads('schedule.class_soon')] == [4]
    assert alerts.api.payloads('schedule.class_soon')[0]['lead_minutes'] == 5
    alerts.tick()
    clock.value = row.start+timedelta(seconds=1)
    alerts.tick()
    assert len(alerts.api.cards) == 1


def test_configurable_leads_and_empty_adapter(tmp_path):
    alerts, clock, row = setup_alerts(tmp_path, **{'schedule_alerts.class_minutes': [12, 2]})
    clock.value = row.start-timedelta(minutes=12)
    alerts.tick()
    assert alerts.api.payloads('schedule.class_soon')[0]['minutes'] == 12
    alerts.adapter.classes_on = lambda day: []
    alerts.tick()
    assert len(alerts.api.cards) == 1


def test_claim_is_saved_before_publication(tmp_path):
    alerts, clock, row = setup_alerts(tmp_path)
    clock.value = row.start-timedelta(minutes=15)
    def stopped(topic, payload):
        raise RuntimeError('Crash after durable claim')
    alerts.api.publish = stopped
    with pytest.raises(RuntimeError):
        alerts.tick()
    Alerts(alerts.api, alerts.adapter, clock.now).tick()  # Never replays the claimed event.


def test_corrupt_state_is_preserved(tmp_path):
    alerts, _, _ = setup_alerts(tmp_path)
    alerts.path.write_text('{broken')
    with pytest.raises(ValueError):
        Alerts(alerts.api, alerts.adapter)
    assert alerts.path.read_text() == '{broken'


def test_provides_service_and_checks_every_30_seconds(tmp_path):
    api = API(tmp_path / 'registration')
    register(api)
    assert set(api.services) == {'schedule', 'schedule_alerts'}
    assert api.timers[0][0] == 30


def test_configured_week_horizon_is_not_limited_to_next_thirty_classes(tmp_path):
    alerts, clock, row = setup_alerts(tmp_path, **{'schedule_alerts.class_minutes': [7*1440]})
    rows = [ScheduleItem(str(n), 'Physics', 'Physics', start=clock.now()+timedelta(days=4, minutes=n)) for n in range(40)]
    alerts.adapter.classes_on = lambda day: [r for r in rows if r.start.date() == day]
    alerts.tick()
    assert len(alerts.api.payloads('schedule.class_soon')) == 40
