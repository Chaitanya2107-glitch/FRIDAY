import asyncio
from types import SimpleNamespace

from services import quiet_mode
from services.event_bus import EventBus


def test_quiet_state_is_shared_persistent_and_critical_toasts_bypass(tmp_path, monkeypatch):
    from services.reminders import service
    calls = []
    monkeypatch.setattr(service, '_show_toast', lambda *a, **kw: calls.append((a, kw)) or True)
    quiet_mode.set_owner('one', True)
    assert quiet_mode.path().is_relative_to(tmp_path)
    assert service.show_toast('ordinary', 'synthetic', mirror_telegram=False) is False
    assert not calls
    assert service.show_toast('critical', 'synthetic', urgency='critical', mirror_telegram=False)
    assert len(calls) == 1
    quiet_mode.set_owner('two', True); quiet_mode.set_owner('one', False)
    assert quiet_mode.enabled()
    quiet_mode.set_owner('two', False)
    assert not quiet_mode.enabled()


def test_quiet_gate_covers_direct_card_publication_and_retains_debug_receipt():
    bus = EventBus()
    try:
        quiet_mode.set_owner('scene', True)
        event = bus.publish('ui.card', dict(title='normal', body='synthetic'), plugin_id='synthetic')
        assert event['suppressed'] and bus.recent('ui.card')[-1]['suppressed']
        critical = bus.publish('ui.card', dict(title='restore', body='synthetic', urgency='critical'))
        assert not critical.get('suppressed')
    finally:
        bus.close()


def test_due_reminders_defer_before_windows_phone_or_model_review(monkeypatch):
    from services.reminders import service
    from services.mind import reminder_review
    from services.telegram import client as telegram
    def forbidden(*a, **kw): raise AssertionError('Quiet reminder reached a destination/model')
    monkeypatch.setattr(reminder_review, 'review', forbidden)
    monkeypatch.setattr(telegram, 'mirror', forbidden)
    monkeypatch.setattr(service, '_submit_desktop', forbidden)
    quiet_mode.set_owner('scene', True)
    decisions = []
    fake = SimpleNamespace(_decision=lambda claim, review: decisions.append(review),
                           _hold=lambda claim, review: decisions.append(review))
    asyncio.run(service._deliver_claim(fake, SimpleNamespace(reminder=SimpleNamespace(id=1))))
    assert len(decisions) == 2 and decisions[0].action == 'defer'


def test_proactive_urgent_context_bypasses_quiet(monkeypatch):
    from services.reminders import service
    from services.mind.training import urgent_delivery
    quiet_mode.set_owner('scene', True)
    monkeypatch.setattr(service, '_show_toast', lambda *a, **kw: True)
    token = urgent_delivery.set(True)
    try:
        assert service.show_toast('Critical battery', 'synthetic', mirror_telegram=False)
    finally:
        urgent_delivery.reset(token)
