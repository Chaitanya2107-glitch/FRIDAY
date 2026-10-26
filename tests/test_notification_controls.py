"""Notification review permissions and transport acknowledgements."""

import asyncio

import pytest
import httpx

from core.config import config
from core.errors import ProviderError
from providers import failover, policy
from providers.base_provider import ProviderResponse
from services.telegram import client

REAL_CALL = client.call


def test_notification_review_is_an_explicit_scoped_permission(monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", True, raising=False)
    policy.check_allowed("notification_review")
    with pytest.raises(ProviderError):
        policy.check_allowed("reasoning")
    with pytest.raises(ProviderError):
        policy.check_allowed()
    monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", False)
    with pytest.raises(ProviderError):
        policy.check_allowed("notification_review")


def test_review_permission_does_not_leak_after_completion(monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", True, raising=False)

    async def complete(*args, **kwargs):
        assert policy.purpose.get() == "notification_review"
        policy.check_allowed()
        return ProviderResponse(content="synthetic", provider="ollama", model="synthetic")

    monkeypatch.setattr(failover, "_complete_with_failover", complete)
    asyncio.run(failover.complete_with_failover(purpose="notification_review"))
    assert policy.purpose.get() is None
    with pytest.raises(ProviderError):
        policy.check_allowed()


@pytest.fixture
def mirror(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    monkeypatch.setattr(config, "TELEGRAM_AWAY_MINUTES", 5)
    monkeypatch.setattr("services.activity.log.idle_seconds", lambda: 600)
    sent = []
    monkeypatch.setattr(client, "send", lambda *args: sent.append(args))
    return sent


def test_phone_submission_reports_acknowledgement(mirror):
    assert client.mirror("Reminder", "Synthetic") is True
    assert mirror == [(42, "Reminder\nSynthetic", [])]


def test_phone_failure_reports_failure_without_private_error(mirror, monkeypatch, caplog):
    def fail(*args):
        raise client.TelegramError("SENTINEL_PRIVATE_TRANSPORT_ERROR")

    monkeypatch.setattr(client, "send", fail)
    assert client.mirror("Reminder", "Synthetic") is False
    assert "SENTINEL_PRIVATE_TRANSPORT_ERROR" not in caplog.text


def test_phone_ineligible_is_distinct_from_failed(mirror, monkeypatch):
    monkeypatch.setattr("services.activity.log.idle_seconds", lambda: 1)
    assert client.mirror_eligible() is False
    assert client.mirror("Reminder", "Synthetic") is None
    assert not mirror


def test_review_routing_check_never_changes_away_state(mirror, monkeypatch):
    monkeypatch.setattr("services.activity.log.idle_seconds", lambda: 1)
    monkeypatch.setattr(client, "away", lambda: True)
    monkeypatch.setattr(client, "set_away", lambda value: pytest.fail("Read-only review changed away state"))
    assert client.mirror_eligible() is False


def test_unacknowledged_phone_submission_reports_uncertainty(mirror, monkeypatch):
    def fail(*args):
        raise client.TelegramSubmissionUncertain("Synthetic lost response")

    monkeypatch.setattr(client, "send", fail)
    outcome = {}
    assert client.mirror("Reminder", "Synthetic", outcome=outcome) is False
    assert outcome["uncertain"] is True


def test_send_timeout_is_distinct_from_a_known_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout("SENTINEL_PRIVATE_TRANSPORT_ERROR")

    monkeypatch.setattr(client.httpx, "post", fail)
    with pytest.raises(client.TelegramSubmissionUncertain):
        REAL_CALL("sendMessage", chat_id=42, text="Synthetic")
