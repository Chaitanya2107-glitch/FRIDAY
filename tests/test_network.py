import asyncio

import pytest

from core.config import config
from providers import failover
from providers.base_provider import ProviderResponse
from services.automation import intent
from services.network import status
from services.network.status import NetworkStatus


def fake_net(monkeypatch, reachable, wifi="connected"):
    monkeypatch.setattr(status, "internet_reachable", lambda: reachable)
    monkeypatch.setattr(status, "wifi_state", lambda: wifi)


def test_starting_online_says_nothing_then_each_change_notifies(monkeypatch):
    net = NetworkStatus()
    fake_net(monkeypatch, True)
    assert net.check() is None and net.online

    fake_net(monkeypatch, False, wifi="off")  # Wi-Fi switched off: offline at once
    note = net.check()
    assert not net.online and note == "FRIDAY OFFLINE"
    assert net.check() is None  # still offline: no repeat

    fake_net(monkeypatch, True)
    assert net.check() == "FRIDAY ONLINE"
    assert net.online


def test_one_failed_check_on_connected_wifi_waits_for_a_second(monkeypatch):
    net = NetworkStatus()
    fake_net(monkeypatch, True)
    net.check()
    fake_net(monkeypatch, False, wifi="connected")
    assert net.check() is None and net.online  # maybe just slow
    assert net.check() == "FRIDAY OFFLINE" and net.reason == "connected"
    assert not net.online


def test_starting_offline_notifies(monkeypatch):
    net = NetworkStatus()
    fake_net(monkeypatch, False, wifi="disconnected")
    assert net.check() == "FRIDAY OFFLINE"


def test_offline_goes_straight_to_the_local_model(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "ollama")
    assert failover.provider_chain("openrouter") == ["openrouter", "ollama"]
    monkeypatch.setattr(status.network, "online", False)
    assert failover.provider_chain("openrouter") == ["ollama"]

    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "none")  # no fallback set: still the local model offline
    assert failover.provider_chain("openrouter") == ["ollama"]


def test_offline_chat_never_calls_the_api(monkeypatch):
    called = []

    class Fake:
        def __init__(self, name):
            self.name = name

        async def complete(self, **kwargs):
            called.append(self.name)
            return ProviderResponse(content="hi", provider=self.name, model="m")

        def get_model_name(self):
            return "m"

    monkeypatch.setattr(failover, "get_provider", lambda name, model=None: Fake(name))
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "ollama")
    monkeypatch.setattr(status.network, "online", False)
    reply = asyncio.run(failover.complete_with_failover("openrouter", [], "system", 100))
    assert called == ["ollama"] and reply.provider == "ollama"


def test_offline_command_classifier_uses_only_the_local_model(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "ollama")
    monkeypatch.setattr(config, "INTENT_PROVIDER", "openrouter")
    assert {name for name, _ in intent._classifier_attempts("openrouter")} == {"openrouter", "ollama"}
    monkeypatch.setattr(status.network, "online", False)
    assert {name for name, _ in intent._classifier_attempts("openrouter")} == {"ollama"}



def test_each_change_is_notified_silently(monkeypatch):
    from services.reminders import service
    from services.voice.tts import tts

    net = NetworkStatus()
    results = iter([(False, "off"), (True, None)])
    spoken, shown = [], []

    def check():
        online, reason = next(results)
        return net._set(online, reason)

    async def speak(text, cache=False):
        spoken.append(text)

    async def stop_after_two(_):
        if len(shown) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(net, "check", check)
    monkeypatch.setattr(service, "show_toast", lambda title, text: shown.append(text))
    monkeypatch.setattr(tts, "speak", speak)
    monkeypatch.setattr(status, "warm_local_model", lambda: None)
    monkeypatch.setattr(status.asyncio, "sleep", stop_after_two)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(status.watch_network(net))
    assert shown == ["FRIDAY OFFLINE", "FRIDAY ONLINE"] and spoken == []


def test_back_online_says_how_long_it_was_offline(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(status.time, "monotonic", lambda: clock[0])
    net = NetworkStatus()
    fake_net(monkeypatch, False, wifi="off")
    assert net.check() == "FRIDAY OFFLINE"
    clock[0] += 25 * 60
    fake_net(monkeypatch, True)
    assert net.check() == "FRIDAY ONLINE (offline 25 min)"
