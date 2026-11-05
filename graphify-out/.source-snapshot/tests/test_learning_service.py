from datetime import datetime, timedelta
import pytest
from core.config import config

from services.learning import service
from services.learning.catalog import LearningCatalog
from services.learning.contracts import LearningRecord, Session, SourceScan

NOW = datetime(2026, 10, 12, 12)


@pytest.fixture(autouse=True)
def tracking_enabled(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_DATA_ENABLED", True)


def complete_scan():
    records = [LearningRecord("activity", str(i), "v1", NOW+timedelta(seconds=10*i), "activity/coding", "accepted") for i in (1, 2)]
    sessions = [Session(str(i), NOW+timedelta(seconds=10*i), app, 10, "coding", "user", "accepted", "r1") for i, app in ((1, "code"), (2, "chrome"))]
    return SourceScan(records, sessions, [], {"activity"}, {"activity": "complete"})


def test_refresh_rescans_and_governs_real_examples(tmp_path, monkeypatch):
    catalog = LearningCatalog(tmp_path / "audit.db")
    monkeypatch.setattr(service, "catalog", catalog)
    scan = complete_scan()
    monkeypatch.setattr(service, "scan_sources", lambda **kwargs: scan)
    dataset = service.refresh(now=NOW+timedelta(minutes=1))
    assert len(dataset.examples) == 1
    # Source removal invalidates eligibility instead of returning cached samples.
    scan.records.pop()
    scan.sessions.pop()
    assert service.refresh(now=NOW+timedelta(minutes=2)).examples == ()
    assert catalog.report(NOW, NOW+timedelta(hours=1))["eligible_examples"] == 0


def test_failed_scan_retains_catalog_but_cannot_train_stale_samples(tmp_path, monkeypatch):
    catalog = LearningCatalog(tmp_path / "audit.db")
    monkeypatch.setattr(service, "catalog", catalog)
    monkeypatch.setattr(service, "scan_sources", lambda **kwargs: complete_scan())
    service.refresh(now=NOW+timedelta(minutes=1))
    monkeypatch.setattr(service, "scan_sources", lambda **kwargs: SourceScan(coverage={"activity": "busy_or_unreadable"}))
    result = service.refresh(now=NOW+timedelta(minutes=2))
    assert result.examples == ()
    assert result.reasons["source_unavailable"] == 1
    assert catalog.report(NOW, NOW+timedelta(hours=1))["eligible_examples"] == 1


def test_unreadable_boundary_table_cannot_create_bridge(tmp_path, monkeypatch):
    catalog = LearningCatalog(tmp_path / "audit.db")
    monkeypatch.setattr(service, "catalog", catalog)
    scan = complete_scan()
    scan.coverage["activity_boundary"] = "busy_or_unreadable"
    monkeypatch.setattr(service, "scan_sources", lambda **kwargs: scan)
    assert service.refresh(now=NOW+timedelta(minutes=1)).examples == ()
