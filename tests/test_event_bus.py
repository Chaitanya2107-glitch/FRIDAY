import threading

from services.event_bus import EventBus


def test_wildcard_delivery_is_off_publisher_thread_and_isolated():
    bus = EventBus()
    publisher = threading.get_ident()
    seen, done = [], threading.Event()
    def callback(event):
        seen.append((event, threading.get_ident()))
        done.set()
    bus.subscribe('activity.*', callback, plugin_id='observer')
    try:
        bus.publish('todo.changed', {})
        bus.publish('activity.app_changed', {'app': 'editor'})
        assert done.wait(1)
        assert len(seen) == 1 and seen[0][1] != publisher
        seen[0][0]['payload']['app'] = 'mutated'
        assert bus.recent()[-1]['payload']['app'] == 'editor'
    finally:
        bus.close()


def test_slow_and_crashing_subscribers_do_not_block_others(caplog):
    bus = EventBus()
    entered, release, fast, crashed = threading.Event(), threading.Event(), threading.Event(), threading.Event()
    def slow(event):
        entered.set()
        release.wait(2)
    def crash(event):
        crashed.set()
        raise RuntimeError('intentional')
    bus.subscribe('*', slow, plugin_id='slow')
    bus.subscribe('*', crash, plugin_id='broken')
    bus.subscribe('*', lambda event: fast.set(), plugin_id='fast')
    try:
        bus.publish('activity.nudge', {})
        assert entered.wait(1)
        assert fast.wait(.5)
        assert crashed.wait(.5)
        assert not release.is_set()
    finally:
        release.set()
        bus.close()
    assert 'plugin=broken' in caplog.text


def test_debug_history_keeps_last_200_events():
    bus = EventBus()
    for value in range(210):
        bus.publish('index.progress', {'value': value})
    history = bus.recent()
    assert len(history) == 200
    assert history[0]['payload']['value'] == 10
    assert history[-1]['payload']['value'] == 209
