import sys
from types import ModuleType

from services.friday_island_server.runtime import presence_summary


def install_engine(monkeypatch, current):
    package = ModuleType('services.presence')
    engine = ModuleType('services.presence.engine')
    engine.current = current
    monkeypatch.setitem(sys.modules, 'services.presence', package)
    monkeypatch.setitem(sys.modules, 'services.presence.engine', engine)


def test_island_presence_is_a_small_display_projection(monkeypatch):
    install_engine(monkeypatch, lambda: dict(state='on_phone', reason='Phone use is recent.', confidence=.8,
        since=1800000000, data_available=True, place='Private place', device='device-key', raw_events=['private']))
    assert presence_summary() == dict(state='on_phone', reason='Phone use is recent.', confidence=.8,
        since=1800000000, data_available=True)


def test_unavailable_presence_does_not_claim_the_owner_is_away(monkeypatch):
    def unavailable():
        raise OSError('No source')
    install_engine(monkeypatch, unavailable)
    assert presence_summary()['data_available'] is False
    assert presence_summary()['confidence'] == 0
