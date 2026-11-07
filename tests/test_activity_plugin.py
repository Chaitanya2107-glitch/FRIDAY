from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from activity_support import make_activity, advance
from plugins.activity.policy import Sample
from plugins.activity.store import bounds


@pytest.fixture
def activity(tmp_path):
    value = make_activity(tmp_path)
    yield value
    value.api.stop()
    value.tracker.close()
    value.manager.bus.close()


def rows(activity):
    return activity.tracker.store.rows(0, 10**12)


def test_sessions_merge_and_discard_under_three_seconds(activity):
    activity.provider.choose('short.exe')
    activity.tracker.poll()
    advance(activity, 2)
    activity.provider.choose('code.exe')
    activity.tracker.poll()
    advance(activity, 6)
    activity.provider.choose('other.exe')
    activity.tracker.poll()
    data = rows(activity)
    assert len(data) == 1 and data[0]['process'] == 'code.exe'
    assert data[0]['end'] - data[0]['start'] == 6
    assert activity.tracker.summary()['active_seconds'] == 6
    assert len(activity.manager.bus.recent('activity.app_changed')) == 3


def test_idle_retracts_inactive_tail_and_resume_does_not_count_it(activity):
    activity.provider.choose()
    activity.tracker.poll()
    for idle in range(2, 132, 2):
        activity.clock.advance(2)
        activity.provider.choose(idle=idle)
        activity.tracker.poll()
    assert activity.tracker.summary()['active_seconds'] == 0
    assert len(activity.manager.bus.recent('activity.idle_started')) == 1
    activity.provider.choose()
    activity.tracker.poll()
    advance(activity, 4)
    assert activity.tracker.summary()['active_seconds'] == 4
    assert len(activity.manager.bus.recent('activity.idle_ended')) == 2


@pytest.mark.parametrize('process,title', [
    ('bitwarden.exe', 'a secret vault'), ('banking.exe', 'account balance'),
    ('chrome.exe', 'SECRET YouTube InPrivate'), ('firefox.exe', 'SECRET Private Browsing'),
    ('chrome.exe', 'SECRET Incognito Gmail'),
])
def test_private_windows_never_record_app_names(activity, process, title):
    activity.provider.choose(process, title, fullscreen=True)
    activity.tracker.poll()
    advance(activity, 4)
    data = rows(activity)
    assert len(data) == 1
    assert data[0]['category'] == 'private' and data[0]['process'] is data[0]['app_name'] is None
    assert activity.tracker.current()['state'] == 'private'
    assert activity.tracker.is_fullscreen()  # Geometry is safe ephemeral metadata, even for private windows.
    assert all(event['payload'].get('process') is None and event['payload'].get('app_name') is None
               for event in activity.manager.bus.recent('activity.app_changed'))


def test_site_labels_never_write_titles_or_put_them_on_bus_or_in_replies(activity, caplog):
    secret = 'UNIQUE SECRET TITLE 009-8624'
    activity.provider.choose('chrome.exe', secret + ' - YouTube - Google Chrome')
    activity.tracker.poll()
    advance(activity, 4)
    data = rows(activity)
    assert data[0]['app_name'] == 'YouTube' and data[0]['category'] == 'entertainment'
    assert activity.tracker.time_on('youtube')['seconds'] == 4
    assert activity.tracker.time_on('chrome')['seconds'] == 4
    assert activity.tracker.time_on('entertainment')['seconds'] == 4
    payload = json.dumps([activity.manager.bus.recent(), activity.tracker.current(), activity.tracker.summary(),
                          activity.tracker.handle_command('what am I doing')])
    dump = '\n'.join(activity.tracker.store.db.iterdump())
    assert secret not in payload + dump + caplog.text
    assert secret.encode() not in activity.tracker.store.path.read_bytes()
    activity.policy.update('site_labels', False)
    activity.provider.choose('chrome.exe', secret + ' - YouTube')
    activity.tracker.poll()
    assert activity.tracker.current()['app_name'] == 'Google Chrome'


def test_no_raw_titles_schema_and_private_constraint(activity):
    columns = {row[1] for row in activity.tracker.store.db.execute('PRAGMA table_info(sessions)')}
    assert columns == {'start', 'end', 'process', 'app_name', 'category'}
    assert not columns & {'title', 'window_title', 'url', 'text', 'payload', 'metadata', 'screenshot', 'clipboard', 'keys'}
    with pytest.raises(sqlite3.IntegrityError):
        activity.tracker.store.db.execute("INSERT INTO sessions VALUES (0,4,'secret.exe','Secret','private')")
    activity.tracker.store.db.rollback()


def test_retention_purges_and_clips_old_rows(activity):
    now = activity.clock.now().timestamp()
    cutoff = now - 90 * 86400
    activity.tracker.store.save(dict(start=cutoff-100, end=cutoff-90, process='old.exe', app_name='Old', category='other'))
    activity.tracker.store.save(dict(start=cutoff-50, end=cutoff+50, process='boundary.exe', app_name='Boundary', category='other'))
    activity.tracker.poll()
    data = rows(activity)
    assert len(data) == 1 and data[0]['start'] == cutoff
    assert data[0]['end'] == cutoff + 50


def test_summary_and_time_on_clip_at_midnight_and_merge_focus(activity):
    today = activity.clock.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    for start, end, name, category in [(today-600, today+600, 'Code', 'coding'),
                                      (today+600, today+1200, 'PyCharm', 'coding'),
                                      (today+1200, today+1500, 'YouTube', 'entertainment')]:
        activity.tracker.store.save(dict(start=start, end=end, process=name.lower()+'.exe', app_name=name, category=category))
    assert activity.tracker.time_on('coding', 'yesterday')['seconds'] == 600
    assert activity.tracker.time_on('coding', 'today')['seconds'] == 1200
    summary = activity.tracker.summary()
    assert summary['active_seconds'] == 1500
    assert summary['categories'] == {'coding': 1200, 'entertainment': 300}
    assert summary['longest_focus_seconds'] == 1200
    assert len(summary['top_apps']) == 3
    assert activity.tracker.time_on('code.exe', 'last 7 days')['seconds'] == 1200
    start, _ = bounds('this week', activity.clock.now())
    assert datetime.fromtimestamp(start, activity.clock.now().tzinfo).weekday() == 0


def test_pause_and_resume_persist_but_do_not_count_paused_time(activity):
    activity.provider.choose()
    activity.tracker.poll()
    advance(activity, 4)
    assert activity.tracker.handle_command('pause tracking')['ok']
    reads = activity.provider.reads
    advance(activity, 20)
    assert activity.provider.reads == reads
    assert activity.tracker.summary()['active_seconds'] == 4
    assert activity.api.settings.get('activity')['paused']
    activity.tracker.handle_command('resume tracking')
    activity.tracker.poll()
    advance(activity, 4)
    assert activity.tracker.summary()['active_seconds'] == 8


def test_private_scene_pause_and_game_scene_nudges(activity):
    activity.policy.update('nudge_rules', {'entertainment': .1})
    activity.provider.choose('spotify.exe')
    activity.tracker.poll()
    activity.tracker.scene({'topic': 'scene.started', 'payload': {'scene_id': 'game-1', 'name': 'game'}})
    advance(activity, 8)
    assert not activity.manager.bus.recent('activity.nudge')
    activity.tracker.scene({'topic': 'scene.ended', 'payload': {'scene_id': 'game-1', 'name': 'game'}})
    advance(activity, 2)
    assert len(activity.manager.bus.recent('activity.nudge')) == 1
    for job in activity.api._test_jobs:
        job()
    assert len(activity.manager.notifications) == 1
    assert 'entertainment' not in activity.manager.notifications[0][1]
    activity.tracker.scene({'topic': 'scene.started', 'payload': {'scene_id': 'private-1', 'name': 'private'}})
    assert activity.tracker.current()['state'] == 'paused'
    old = activity.tracker.summary()['active_seconds']
    advance(activity, 10)
    assert activity.tracker.summary()['active_seconds'] == old
    activity.tracker.pause(True)
    activity.tracker.scene({'topic': 'scene.ended', 'payload': {'scene_id': 'private-1', 'name': 'private'}})
    assert activity.tracker.paused()  # Ending a scene never overrides a manual pause.


@pytest.mark.parametrize('state', ['idle', 'private'])
def test_queued_nudge_is_suppressed_when_foreground_becomes_ineligible(activity, state):
    activity.policy.update('nudge_rules', {'entertainment': .1})
    activity.provider.choose('spotify.exe')
    activity.tracker.poll()
    advance(activity, 8)
    assert activity.api._test_jobs
    if state == 'idle':
        activity.provider.choose(process=None)
    else:
        activity.provider.choose('chrome.exe', 'Incognito')
    activity.tracker.poll()
    for job in activity.api._test_jobs:
        job()
    assert not activity.manager.notifications


def test_nudge_threshold_cooldown_and_strictest_scene_override(activity):
    nudges = activity.tracker.nudges
    assert nudges.check('games', 0) is None
    assert nudges.check('games', 7199) is None
    assert nudges.check('games', 7200)['minutes'] == 120
    assert nudges.check('games', 10799) is None
    assert nudges.check('games', 10800)['minutes'] == 180
    nudges.reset()
    nudges.last = -float('inf')
    activity.tracker.set_threshold_override('entertainment', 10, 'study')
    activity.tracker.set_threshold_override('entertainment', 20, 'work')
    assert nudges.check('entertainment', 20000) is None
    assert nudges.check('entertainment', 20599) is None
    assert nudges.check('entertainment', 20600)['minutes'] == 10
    activity.tracker.clear_overrides('study')
    assert nudges.overrides == {'work': {'entertainment': 20.0}}
    activity.tracker.scene({'topic': 'scene.ended', 'payload': {'name': 'work', 'scene_id': 'work'}})
    assert nudges.overrides == {}


def test_category_maps_reload_and_override_is_persisted(activity):
    assert activity.policy.sanitize('unknown.exe', '').category == 'other'
    assert activity.tracker.handle_command('categorise unknown as study')['ok']
    assert activity.policy.sanitize('unknown.exe', '').category == 'study'
    path = activity.policy.folder / 'categories.json'
    data = json.loads(path.read_text())
    data['processes']['new.exe'] = 'coding'
    path.write_text(json.dumps(data), encoding='utf-8')
    activity.policy.reload()
    assert activity.policy.sanitize('new.exe', '').category == 'coding'
    path.write_text('{partial', encoding='utf-8')
    activity.policy.reload()
    assert activity.policy.sanitize('new.exe', '').category == 'coding'


def test_delete_requires_fresh_confirmation_and_does_not_resurrect_open_session(activity):
    activity.provider.choose()
    activity.tracker.poll()
    advance(activity, 4)
    assert not activity.tracker.handle_command('confirm delete my activity data')['ok']
    assert activity.tracker.handle_command('delete my activity data')['ok']
    assert rows(activity)
    activity.clock.advance(31)
    assert not activity.tracker.handle_command('confirm delete my activity data')['ok']
    activity.tracker.handle_command('delete my activity data')
    assert activity.tracker.handle_command('confirm delete my activity data')['ok']
    assert rows(activity) == []
    activity.tracker.close()
    assert 'Visual Studio Code'.encode() not in activity.tracker.store.path.read_bytes()


def test_delete_also_forgets_own_recent_events_but_preserves_other_plugins(activity):
    activity.provider.choose()
    activity.tracker.poll()
    advance(activity, 4)
    activity.manager.bus.publish('todo.changed', {'items': []}, plugin_id='todo')
    assert activity.manager.bus.recent('activity.*')
    activity.tracker.handle_command('delete my activity data')
    activity.tracker.handle_command('confirm delete my activity data')
    assert not activity.manager.bus.recent('activity.*')
    assert activity.manager.bus.recent('todo.changed')


def test_private_scene_end_waits_for_a_new_sample(activity):
    activity.provider.choose()
    activity.tracker.poll()
    for kind in ['scene.started', 'scene.ended']:
        activity.tracker.scene({'topic': kind, 'payload': {'name': 'private', 'scene_id': 'private'}})
    assert activity.tracker.current()['state'] == 'idle'
    assert 'None' not in activity.tracker.handle_command('what am I doing')['text']


def test_clock_adjustment_does_not_invent_hours_or_overlapping_sessions(activity):
    activity.provider.choose()
    activity.tracker.poll()
    advance(activity, 4)
    activity.clock.value += timedelta(hours=1)
    advance(activity, 2)
    assert activity.tracker.summary()['active_seconds'] == 4
    advance(activity, 4)
    assert activity.tracker.summary()['active_seconds'] == 8
    activity.clock.value -= timedelta(hours=1)
    advance(activity, 2)
    data = rows(activity)
    assert all(first['end'] <= second['start'] for first, second in zip(data, data[1:]))


def test_retention_cannot_be_undone_by_a_live_session(activity):
    now = activity.clock.now().timestamp()
    cutoff = now - 90 * 86400
    row = dict(start=cutoff-100, end=now, process='code.exe', app_name='Code', category='coding')
    activity.tracker.rowid = activity.tracker.store.save(row)
    activity.tracker.session = row
    activity.provider.choose()
    activity.tracker.sample = activity.provider.value
    activity.tracker.idle = False
    activity.tracker.poll()
    advance(activity, 4)
    assert min(row['start'] for row in rows(activity)) >= cutoff


def test_existing_schema_with_title_column_fails_closed(tmp_path):
    from plugins.activity.store import Store
    path = tmp_path / 'bad.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sessions(start REAL,end REAL,process TEXT,app_name TEXT,category TEXT,title TEXT)')
    with pytest.raises(ValueError, match='schema'):
        Store(path)


def test_native_store_rejects_repository_paths():
    from plugins.activity.store import Store
    from pathlib import Path
    with pytest.raises(ValueError, match='outside'):
        Store(Path(__file__).resolve().parents[1] / 'tasks/activity-plugin/forbidden.sqlite3')


@pytest.mark.parametrize('phrase', [
    'what am I doing', 'what am I doing right now', 'show my current activity',
    'activity summary', 'what did I do today', 'what did I do yesterday', 'summarize my activity',
    'how much time did I spend on YouTube today', 'how much time did I spend in coding yesterday',
    'how long was I on chrome this week', 'how long did I spend on games last 7 days',
    'how much time have I spent on YouTube today', 'how long have I been in games today',
    'how long was I in study the last seven days', 'pause tracking', 'resume tracking',
    'categorize Spotify as entertainment', 'categorise Chrome as study',
])
def test_query_phrasings_are_whole_string_and_have_speech(activity, phrase):
    value = activity.tracker.handle_command(phrase)
    assert value['ok'] and value['text'] and value['speech']
    assert not activity.tracker.handles('a sentence containing ' + phrase + ' but more words')
