from datetime import datetime, timedelta
from dataclasses import replace
import sqlite3

from services.learning.catalog import LearningCatalog
from services.learning.contracts import LearningRecord, TrainingExample

NOW = datetime(2026, 10, 12, 12)


def record(key="1", **changes):
    return replace(LearningRecord("activity", key, "v1", NOW, "activity/coding", "accepted"), **changes)


def test_unique_funnel_backfill_revisions_and_removed(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    rows = [record(), record("2", status="excluded", reason="short_session"),
            record("3", status="quarantined", reason="invalid_time"),
            record("4", status="pending"), record("old", event_at=NOW-timedelta(days=1))]
    catalog.ingest(rows, NOW, complete_sources={"activity"})
    catalog.ingest(rows, NOW+timedelta(seconds=1), complete_sources={"activity"})
    report = catalog.report(NOW, NOW+timedelta(minutes=1))
    assert [report[k] for k in ("collected", "appropriate", "excluded", "quarantined", "pending_screening", "backfilled")] == [4, 1, 1, 1, 1, 1]
    assert report["categories_active"] == 1
    catalog.ingest([replace(rows[0], revision="v2", category="activity/study")], NOW+timedelta(seconds=2), complete_sources={"activity"})
    report = catalog.report(NOW, NOW+timedelta(minutes=1))
    assert report["collected"] == 4
    assert report["revisions"] == 1
    assert report["removed"] == 4


def test_freeze_is_immutable_and_missing_scan_does_not_remove(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    catalog.ingest([record()], NOW)
    frozen = catalog.report(NOW, NOW+timedelta(hours=1), freeze_key="week")
    catalog.ingest([record("2")], NOW+timedelta(minutes=1), coverage={"activity": "busy"})
    assert catalog.report(NOW, NOW+timedelta(hours=1), freeze_key="week") == frozen
    assert catalog.report(NOW, NOW+timedelta(hours=1))["removed"] == 0


def test_examples_and_fitting_counts_are_unique_and_revocable(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    catalog.ingest([record(), record("2")], NOW)
    example = TrainingExample("e1", NOW, NOW+timedelta(seconds=20), "code", "chrome", None, ("1", "2"), 3)
    catalog.replace_examples([example], NOW+timedelta(minutes=1), "f1")
    run = {"id": "run1", "at": (NOW+timedelta(minutes=2)).isoformat(), "status": "trained", "training_ids": ["e1", "e1"], "evaluation_ids": ["e1"], "dataset_version": "f1"}
    catalog.record_training_run(run)
    catalog.record_training_run(run)
    result = catalog.report(NOW, NOW+timedelta(hours=1))
    assert [result[k] for k in ("eligible_examples", "used_training", "evaluated")] == [1, 1, 1]
    catalog.ingest([record()], NOW+timedelta(minutes=3), complete_sources={"activity"})
    assert catalog.report(NOW, NOW+timedelta(hours=1))["eligible_examples"] == 0


def test_private_payload_is_never_duplicated(tmp_path):
    path = tmp_path / "audit.db"
    catalog = LearningCatalog(path)
    catalog.ingest([record(metadata={"text": "private diary secret", "origin": "user", "category": "secret"})], NOW)
    with sqlite3.connect(path) as conn:
        dump = "\n".join(conn.iterdump())
    assert "private diary secret" not in dump
    assert '"category": "secret"' not in dump


def test_catchup_reports_use_original_cutoff_and_half_open_windows(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    catalog.ingest([record()], NOW)
    cutoff = NOW + timedelta(hours=1)
    catalog.ingest([record(status="excluded", reason="sensitive_record", revision="v2"), record("2", event_at=cutoff)], cutoff)
    old = catalog.report(NOW, cutoff)
    current = catalog.report(cutoff, cutoff+timedelta(hours=1))
    assert old["collected"] == 1
    assert old["appropriate"] == 1
    assert old["excluded"] == 0
    assert old["revisions"] == 0
    assert current["collected"] == 1
    assert current["revisions"] == 1


def test_removed_example_and_coverage_preserve_historical_state(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    catalog.ingest([record(), record("2")], NOW, coverage={"activity": "complete"})
    example = TrainingExample("e1", NOW, NOW+timedelta(seconds=20), "code", "chrome", None, ("1", "2"))
    catalog.replace_examples([example], NOW+timedelta(minutes=1), "f1")
    cutoff = NOW+timedelta(hours=1)
    catalog.ingest([record()], cutoff, complete_sources={"activity"}, coverage={"activity": "complete_with_unknown_origin"})
    old = catalog.report(NOW, cutoff)
    assert old["eligible_examples"] == 1
    assert old["removed"] == 0
    assert old["coverage"] == {"activity": "complete"}
    assert catalog.report(NOW, cutoff+timedelta(minutes=1))["eligible_examples"] == 0


def test_initial_category_registry_is_not_created_growth(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    catalog.ingest([record(), record("old", event_at=NOW-timedelta(days=2))], NOW)
    report = catalog.report(NOW, NOW+timedelta(minutes=1))
    assert report["categories_active"] == 1
    assert report["categories_created"] == 0


def test_invalid_historical_timestamp_is_backfilled_on_initial_inventory(tmp_path):
    catalog = LearningCatalog(tmp_path / "audit.db")
    catalog.ingest([record(event_at=None, status="quarantined", reason="invalid_time")], NOW)
    report = catalog.report(NOW, NOW+timedelta(minutes=1))
    assert report["backfilled"] == 1
    assert report["collected"] == 0
