import asyncio
from datetime import datetime, timedelta
import pytest


def sample():
    return {
        'tracking_started': '2026-10-12T10:00:00', 'collected': 12,
        'appropriate': 8, 'excluded': 2, 'quarantined': 1, 'pending_screening': 1,
        'backfilled': 99, 'revisions': 3, 'removed': 1,
        'categories_active': 2, 'categories_created': 1,
        'categories': [{'name': 'activity/coding', 'collected': 10},
                       {'name': 'semantic_facts', 'collected': 2}],
        'reasons': {'unknown_origin': 4, 'private secret contents': 1},
        'eligible_examples': 0, 'used_training': 0, 'evaluated': 0,
        'latest_training': None, 'coverage': {'activity': 'unknown_origin'},
    }


@pytest.fixture
def report_stub(monkeypatch):
    from services.learning import reports
    calls = []
    data = sample()
    monkeypatch.setattr(reports, '_refresh', lambda now: calls.append(('refresh', now)))
    monkeypatch.setattr(reports, '_report', lambda start, end, freeze_key: calls.append((start, end, freeze_key)) or data)
    return reports, calls, data


def test_report_reconciles_record_and_example_units_without_private_content(report_stub):
    reports, calls, _ = report_stub
    now = datetime(2026, 10, 18, 21)
    text = reports.build(now, freeze_key='week-1')
    assert calls == [('refresh', now), (datetime(2026, 10, 11, 21), now + timedelta(microseconds=1), 'week-1')]
    for expected in ['Collected: 12', 'Appropriate: 8', 'Excluded: 2', 'Quarantined: 1',
                     'Pending screening: 1', 'Historical backfill: 99', 'Active: 2', 'Created: 1',
                     'Eligible: 0', 'Used for training: 0', 'Evaluated: 0', 'next-app-v1',
                     '2026-10-12 10:00', '2026-10-18 21:00', 'activity/coding: 10']:
        assert expected in text
    assert 'origin' in text.lower() and 'counting' in text.lower()
    assert 'private secret contents' not in text


def test_late_sunday_and_exact_cutoff_records_have_one_accounting_window(monkeypatch, tmp_path):
    from services.learning import reports
    from services.learning.catalog import LearningCatalog
    from services.learning.contracts import LearningRecord
    catalog = LearningCatalog(tmp_path / 'learning.db')
    start = datetime(2026, 10, 12, 10)
    cutoff = datetime(2026, 10, 18, 21)
    catalog.ingest([], start)
    def record(identity, at):
        return LearningRecord('facts', identity, 'v1', at, 'semantic_facts', 'accepted')
    catalog.ingest([record('on-boundary', cutoff)], cutoff)
    late = datetime(2026, 10, 18, 23)
    catalog.ingest([record('on-boundary', cutoff), record('late-sunday', late)], late)
    monkeypatch.setattr(reports, '_refresh', lambda now: None)
    monkeypatch.setattr(reports, '_report', catalog.report)
    first = reports.build(end=cutoff)
    second = reports.build(end=datetime(2026, 10, 25, 21))
    assert 'Collected: 0' in first
    assert 'Collected: 2' in second
    assert '2026-10-18 21:00' in second


def test_on_demand_includes_inventory_from_its_refresh(monkeypatch, tmp_path):
    from services.learning import reports
    from services.learning.catalog import LearningCatalog
    from services.learning.contracts import LearningRecord
    catalog = LearningCatalog(tmp_path / 'learning.db')
    now = datetime(2026, 10, 12, 10)
    def refresh(at):
        catalog.ingest([LearningRecord('facts', 'fresh', 'v1', at, 'semantic_facts', 'accepted')], at)
    monkeypatch.setattr(reports, '_refresh', refresh)
    monkeypatch.setattr(reports, '_report', catalog.report)
    assert 'Collected: 1' in reports.build(now=now)


def test_report_shows_measured_accuracy_and_skipped_training(report_stub):
    reports, _, data = report_stub
    data['latest_training'] = {'status': 'completed', 'model': {'top1': .4, 'top3': .7},
                               'counting': {'top1': .3, 'top3': .6}, 'in_charge': 'model',
                               'dataset_fingerprint': 'snapshot-id', 'policy_version': 'next-app-v1'}
    assert '40%' in reports.build(datetime(2026, 10, 18, 21))
    data['latest_training'] = {'status': 'skipped', 'reason': 'insufficient_examples'}
    text = reports.build(datetime(2026, 10, 18, 21))
    assert 'skipped' in text.lower() and '300' in text and '100' in text


def test_fitting_failure_and_latest_dataset_are_reported_honestly(report_stub):
    reports, _, data = report_stub
    data['dataset_version'] = 'abcd1234' * 8
    data['latest_training'] = {'status': 'skipped', 'reason': 'fitting_failed', 'model': None, 'counting': None}
    text = reports.build(datetime(2026, 10, 18, 21))
    assert 'fitting failed' in text.lower()
    assert 'abcd1234abcd1234' in text


def test_source_read_failure_does_not_claim_no_eligible_dataset(report_stub):
    reports, _, data = report_stub
    data['eligible_examples'] = 0
    data['eligible_examples_available'] = 20
    data['latest_training'] = {'status': 'skipped', 'reason': 'source_unavailable',
                               'in_charge': 'model', 'preserved_artifact': True,
                               'purged_crossing_examples': 2}
    text = reports.build(datetime(2026, 10, 18, 21))
    assert 'source data unavailable' in text and 'No eligible observed transitions yet' not in text
    assert 'previous evaluated model remains in charge' in text
    assert 'cutoff withheld: 2' in text


def test_untrusted_labels_and_source_diagnostics_do_not_leak(report_stub):
    reports, _, data = report_stub
    data['categories'] = [{'name': 'a private conversation', 'collected': 12}]
    data['coverage'] = {'private filename': 'private credentials'}
    data['latest_training'] = {'status': 'skipped', 'reason': 'private raw source text'}
    text = reports.build(datetime(2026, 10, 18, 21))
    for phrase in ('a private conversation', 'private filename', 'private credentials', 'private raw source text'):
        assert phrase not in text


@pytest.mark.parametrize('message', ['learning report', 'training data status', 'show my learning report'])
def test_local_requests_do_not_send_telegram(report_stub, message):
    reports, _, _ = report_stub
    result = asyncio.run(reports.try_handle(message))
    assert result.success and not result.repeatable
    assert asyncio.run(reports.try_handle('tell me about machine learning')) is None
