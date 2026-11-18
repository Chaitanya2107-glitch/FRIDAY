from datetime import datetime, timedelta
import json
import sqlite3

import pytest

from services.presence.engine import PresenceEngine, infer
from services.presence.inputs import observation

START = datetime(2026, 11, 16, 8)


def sample(**changes):
    return dict(fresh=True, laptop_idle=600, place='home', motion='still', screen='off', charging=False, **changes)


def test_simulated_day_hysteresis_and_explicit_edges():
    events = []
    engine = PresenceEngine(publish=events.append)
    assert engine.observe(sample(), START)['state'] == 'at_home'
    moving = dict(sample(), place=None, motion='in_vehicle', transition={'event': 'leave', 'place': 'home', 'id': 'exit'})
    assert engine.observe(moving, START + timedelta(seconds=1))['state'] == 'at_home'
    assert engine.observe(sample(), START + timedelta(seconds=20))['state'] == 'at_home'
    engine.observe(moving, START + timedelta(seconds=30))
    assert engine.observe(moving, START + timedelta(seconds=91))['state'] == 'commuting'
    college = dict(sample(), place='college', class_window=True)
    engine.observe(college, START + timedelta(minutes=30))
    assert engine.observe(college, START + timedelta(minutes=31))['state'] == 'in_class'
    free = dict(college, class_window=False)
    engine.observe(free, START + timedelta(hours=2))
    assert engine.observe(free, START + timedelta(hours=2, minutes=1))['state'] == 'at_college_free'
    assert [e['state'] for e in events] == ['at_home', 'commuting', 'in_class', 'at_college_free']


def test_sleep_needs_dwell_and_wake_does_not_become_a_sleep_fact():
    night = START.replace(hour=23)
    engine = PresenceEngine()
    sleeping = dict(sample(), charging=True)
    assert engine.observe(sleeping, night)['state'] == 'winding_down'
    assert engine.observe(sleeping, night + timedelta(minutes=4))['state'] == 'winding_down'
    value = engine.observe(sleeping, night + timedelta(minutes=5))
    assert value['state'] == 'asleep' and 'suggest' in value['reason']
    awake = dict(sleeping, screen='unlocked')
    engine.observe(awake, night + timedelta(hours=8))
    assert engine.observe(awake, night + timedelta(hours=8, minutes=1))['state'] == 'on_phone'


def test_stale_signals_cannot_keep_automations_authoritative():
    engine = PresenceEngine()
    engine.observe(sample(), START)
    value = engine.observe(dict(fresh=False, laptop_idle=600), START + timedelta(minutes=1))
    assert value['confidence'] < .6 and value['place'] is None and value['transition'] is None
    assert engine.observe(dict(fresh=False, laptop_idle=600), START + timedelta(minutes=3))['state'] == 'away'
    old = engine.observe(dict(sample(), place='college'), START)
    assert old['state'] == 'away'


def test_place_edges_are_debounced_and_first_sync_is_not_arrival():
    engine = PresenceEngine()
    home = dict(sample(), device='one', transition=dict(event='arrive', place='home', id='initial', at=START.timestamp()))
    assert engine.observe(home, START)['transition'] is None
    outside = dict(home, place=None, transition=dict(event='leave', place='home', id='exit', at=START.timestamp() + 10))
    assert engine.observe(outside, START + timedelta(seconds=10))['transition'] is None
    engine.observe(home, START + timedelta(seconds=20))
    assert engine.observe(home, START + timedelta(seconds=60))['place'] == 'home'
    engine.observe(outside, START + timedelta(seconds=70))
    left = engine.observe(outside, START + timedelta(seconds=116))
    assert left['place'] is None and left['transition']['id'] == 'exit'
    engine.reset('one')
    assert engine.value is None and engine.source_device is None


@pytest.mark.parametrize('change,state', [({'laptop_idle': 0}, 'at_desk'), ({'screen': 'unlocked'}, 'on_phone'),
    ({'place': 'college', 'class_window': True}, 'in_class'), ({'place': 'college'}, 'at_college_free'),
    ({'place': None, 'motion': 'walking'}, 'commuting'), ({'place': 'library'}, 'away')])
def test_rule_priority(change, state):
    assert infer(dict(sample(), **change), START)[0] == state


def test_one_handset_permissions_and_heartbeat_freshness(tmp_path, monkeypatch):
    import services.remote
    monkeypatch.setattr(services.remote, '_service', None)
    path = tmp_path / 'phone.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE phones(device TEXT,heartbeat REAL,metadata TEXT)')
        db.execute('CREATE TABLE phone_events(device TEXT,id TEXT,timestamp REAL,type TEXT,payload TEXT)')
        for device, signal, payload in [('one', 'places', {'place': 'college', 'transition': 'entered'}),
                                         ('two', 'screen', {'state': 'unlocked', 'unlock_count': 2})]:
            db.execute('INSERT INTO phones VALUES(?,?,?)', (device, START.timestamp() - (10 if device == 'one' else 20), json.dumps({'signals': [signal]})))
            db.execute('INSERT INTO phone_events VALUES(?,?,?,?,?)', (device, device, START.timestamp() - 30, signal, json.dumps(payload)))
    value = observation(START, path=path, laptop_idle=600, classes=[])
    assert value['device'] == 'one' and value['place'] == 'college' and 'screen' not in value
    stale = observation(START + timedelta(minutes=20), path=path, laptop_idle=600, classes=[])
    assert not stale['fresh']
    with sqlite3.connect(path) as db:
        db.execute('UPDATE phones SET metadata=?', (json.dumps({'signals': []}),))
    assert not observation(START, path=path, laptop_idle=600, classes=[])['fresh']
