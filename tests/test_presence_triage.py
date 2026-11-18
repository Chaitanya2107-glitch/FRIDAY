from datetime import datetime, timedelta
import hashlib

import pytest

from services.presence.triage import TriageStore, score
from services.phone_signals import schema
from services.remote.security import Denied

NOW = datetime(2026, 11, 16, 10)


def record(name='one', *, event='posted', reason=None, category='msg', package='org.example.chat', importance=3, at=None):
    value = dict(package=package, time=(at or NOW).timestamp(), category=category,
                 notification_id=hashlib.sha256(name.encode()).hexdigest(), event=event, importance=importance)
    if reason is not None:
        value['reason'] = reason
    return dict(device='phone-one', id='event-' + name + '-' + event, type='notifications', timestamp=value['time'], payload=value)


def test_beta_updates_original_posting_context_once(tmp_path):
    store = TriageStore(tmp_path / 'triage.db')
    store.context('study', NOW - timedelta(minutes=1))
    store.ingest([record()], NOW)
    store.context('free', NOW + timedelta(minutes=1))
    opened = record(event='opened', reason=1, at=NOW + timedelta(minutes=2))
    store.ingest([opened, opened], NOW + timedelta(minutes=2))
    assert store.belief('phone-one', 'org.example.chat', 'study', NOW) == (3, 3)
    assert store.belief('phone-one', 'org.example.chat', 'free', NOW) == (2, 3)
    store.ingest([record('two'), record('two', event='dismissed', reason=2)], NOW + timedelta(minutes=3))
    assert store.belief('phone-one', 'org.example.chat', 'study', NOW) == (3, 4)


@pytest.mark.parametrize('reason', [4, 8, 10, 12, 18, 19, 22])
def test_non_owner_removal_never_teaches_rejection(tmp_path, reason):
    store = TriageStore(tmp_path / 'triage.db')
    store.context('study', NOW - timedelta(seconds=1))
    store.ingest([record(), record(event='removed', reason=reason)], NOW)
    assert store.belief('phone-one', 'org.example.chat', 'study', NOW) == (2, 3)


def test_digest_counts_distinct_cards_and_protected_apps(tmp_path):
    store = TriageStore(tmp_path / 'triage.db')
    store.context('study', NOW - timedelta(seconds=1))
    rows = [record(str(i), category='msg' if i < 3 else 'promo' if i < 8 else 'unknown') for i in range(12)]
    store.ingest(rows + rows, NOW)
    store.ingest([record('call', category='call'), record('vip', package='org.vip')], NOW, vip=['org.vip'])
    assert len(store.alerts(NOW)) == 2
    store.context('free', NOW + timedelta(minutes=25))
    digest = store.digests(NOW + timedelta(minutes=25))[0]
    assert digest['total'] == 12 and digest['counts'] == {'chat': 3, 'shopping': 5, 'other': 4}
    store.delivered(digest['id'])
    assert store.digests(NOW + timedelta(minutes=26)) == []


def test_decay_and_forget_are_private_per_device(tmp_path):
    store = TriageStore(tmp_path / 'triage.db')
    store.context('study', NOW - timedelta(seconds=1))
    store.ingest([record(), record(event='opened', reason=1)], NOW)
    store.decay(NOW + timedelta(days=1))
    assert store.belief('phone-one', 'org.example.chat', 'study', NOW + timedelta(days=1)) == pytest.approx((2.97, 3))
    store.forget('phone-one')
    with store.db() as db:
        assert not db.execute('SELECT 1 FROM triage_notifications').fetchone()
        assert not db.execute('SELECT 1 FROM triage_beliefs').fetchone()


def test_app_importance_and_learning_affect_scores():
    assert score('app', 'promo', 1, 'study')['score'] < score('app', 'promo', 5, 'study')['score']
    assert score('app', 'msg', 5, 'study', (30, 3))['allow']
    assert not score('app', 'msg', 5, 'study', (2, 30))['allow']
    assert score('app', 'alarm', 0, 'sleep')['urgent']
    assert score('app', 'promo', 0, 'study', vip=['app'])['allow']


def test_notification_schema_backwards_compatible_and_content_forbidden():
    schema.payload('notifications', {'package': 'org.example', 'time': NOW.timestamp(), 'category': 'msg'})
    schema.payload('notifications', record(event='opened', reason=1)['payload'])
    for key in ['text', 'title', 'extras', 'content', 'notification_text']:
        with pytest.raises(Denied):
            schema.payload('notifications', dict(record()['payload'], **{key: 'private'}))
    with pytest.raises(Denied):
        schema.payload('notifications', record(event='opened', reason=18)['payload'])
