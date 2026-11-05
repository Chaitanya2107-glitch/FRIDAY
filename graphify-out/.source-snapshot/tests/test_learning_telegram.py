import asyncio
from datetime import datetime

import pytest

from core.config import config
from services.telegram import client, commands, summaries


@pytest.fixture
def audit(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'LEARNING_DATA_ENABLED', True, raising=False)
    monkeypatch.setattr(config, 'TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setattr(config, 'TELEGRAM_USER_ID', 42)
    monkeypatch.setattr(config, 'TELEGRAM_BRIEFING_HOUR', '')
    monkeypatch.setattr(config, 'TELEGRAM_NIGHTLY_HOUR', '')
    monkeypatch.setattr(config, 'TELEGRAM_WEEKLY_HOUR', '21')
    monkeypatch.setattr(config, 'TELEGRAM_WEEKLY_DAY', 6)
    monkeypatch.setattr(summaries, 'state_path', tmp_path / 'summaries.json')
    monkeypatch.setattr(summaries, '_tracking_started', lambda now: datetime(2026, 10, 12, 10))
    sent = []
    monkeypatch.setattr(client, 'send', lambda recipient, text: sent.append((recipient, text)))
    return sent


def test_explicit_telegram_request_routes_learning_summary(audit, monkeypatch):
    assert commands.match_command('send me my learning report through telegram') == {
        'action': 'telegram_summary', 'kind': 'learning'}
    monkeypatch.setattr(summaries, 'build', lambda kind, now: 'learning audit')
    assert commands.run({'action': 'telegram_summary', 'kind': 'learning'}).success
    assert audit == [(42, 'learning audit')]
    assert summaries._load().get('weekly') is None


def test_weekly_report_catches_up_only_since_tracking_with_original_cutoff(audit, monkeypatch):
    calls = []
    monkeypatch.setattr(summaries, 'build', lambda kind, now: calls.append(now) or str(now))
    monday = datetime(2026, 10, 26, 7)
    asyncio.run(summaries.tick(monday))
    assert calls == [datetime(2026, 10, 18, 21), datetime(2026, 10, 25, 21)]
    assert len(audit) == 2
    summaries._delivered.clear()
    asyncio.run(summaries.tick(monday))
    assert len(audit) == 2


def test_weekly_failed_delivery_reuses_entire_frozen_body_after_restart(audit, monkeypatch):
    built = []
    monkeypatch.setattr(summaries, 'build', lambda kind, now: built.append(now) or 'frozen original counts')
    def fail(*args):
        raise client.TelegramError('uncertain network result')
    monkeypatch.setattr(client, 'send', fail)
    now = datetime(2026, 10, 18, 21)
    asyncio.run(summaries.tick(now))
    monkeypatch.setattr(summaries, 'build', lambda *args: pytest.fail('retry recalculated frozen data'))
    summaries._delivered.clear()
    monkeypatch.setattr(client, 'send', lambda recipient, text: audit.append((recipient, text)))
    asyncio.run(summaries.tick(now.replace(minute=5)))
    assert audit == [(42, 'frozen original counts')]
    assert len(built) == 1


def test_weekly_partial_chunks_are_not_repeated_after_acknowledgement(audit, monkeypatch):
    body = 'x' * client.TEXT_LIMIT + 'tail'
    monkeypatch.setattr(summaries, 'build', lambda *args: body)
    def partly_fail(recipient, text):
        if text == 'tail':
            raise client.TelegramError('uncertain')
        audit.append((recipient, text))
    monkeypatch.setattr(client, 'send', partly_fail)
    now = datetime(2026, 10, 18, 21)
    asyncio.run(summaries.tick(now))
    summaries._delivered.clear()
    monkeypatch.setattr(client, 'send', lambda recipient, text: audit.append((recipient, text)))
    asyncio.run(summaries.tick(now.replace(minute=5)))
    assert [text for _, text in audit] == ['x' * client.TEXT_LIMIT, 'tail']


def test_tracking_begins_after_past_cutoff_does_not_fabricate_report(audit, monkeypatch):
    monkeypatch.setattr(summaries, '_tracking_started', lambda now: datetime(2026, 10, 19, 8))
    assert summaries.due(datetime(2026, 10, 19, 10)) == []


def test_learning_storage_failure_is_reported_without_private_details(audit, monkeypatch):
    import sqlite3
    def fail(*args):
        raise sqlite3.OperationalError('private database path')
    monkeypatch.setattr(summaries, 'build', fail)
    result = commands.run({'action': 'telegram_summary', 'kind': 'learning'})
    assert not result.success and not audit
    assert 'private database path' not in result.message


def test_missing_learning_catalog_does_not_block_other_due_summaries(audit, monkeypatch):
    import sqlite3
    monkeypatch.setattr(config, 'TELEGRAM_BRIEFING_HOUR', '7')
    def fail(*args):
        raise sqlite3.OperationalError('locked')
    monkeypatch.setattr(summaries, '_tracking_started', fail)
    assert summaries.due(datetime(2026, 10, 19, 8)) == [('morning', '2026-10-19')]


def test_delivery_marker_is_per_recipient(audit, monkeypatch):
    monkeypatch.setattr(summaries, 'build', lambda *args: 'weekly aggregate')
    now = datetime(2026, 10, 18, 21)
    asyncio.run(summaries.tick(now))
    monkeypatch.setattr(config, 'TELEGRAM_USER_ID', 43)
    asyncio.run(summaries.tick(now))
    assert audit == [(42, 'weekly aggregate'), (43, 'weekly aggregate')]


def test_no_weekly_snapshot_is_sent_before_it_can_be_persisted(audit, monkeypatch):
    monkeypatch.setattr(summaries, 'build', lambda *args: 'weekly aggregate')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(summaries, '_save_snapshots', fail)
    asyncio.run(summaries.tick(datetime(2026, 10, 18, 21)))
    assert not audit and 'weekly' not in summaries._delivered
