"""Serialized source refresh used by runtime, reporting and the actual learner."""
from datetime import datetime
import threading

from core.config import config
from .catalog import catalog
from .contracts import Dataset
from .dataset import build_examples
from .sources import scan_sources

_lock = threading.RLock()


def refresh(log=None, now=None):
    now = now or datetime.now()
    with _lock:
        if not getattr(config, "LEARNING_DATA_ENABLED", True):
            return Dataset((), "disabled", {"tracking_disabled": 1})
        scan = scan_sources(log=log, now=now)
        catalog.ingest(scan.records, now, complete_sources=scan.complete_sources, coverage=scan.coverage)
        unavailable = not scan.coverage.get("activity", "").startswith("complete")
        unavailable |= scan.coverage.get("activity_boundary") in {"busy_or_unreadable", "partial", "malformed"}
        unavailable |= any(session.source_id.startswith("boundary:") and session.at is None for session in scan.sessions)
        if unavailable:
            # Preserve the last valid catalog inventory. Never return stale rows for fitting.
            return Dataset((), "source-unavailable", {"source_unavailable": 1})
        dataset = build_examples(scan.sessions, scan.feedback, now,
                                 min_seconds=getattr(config, "LEARNING_MIN_SESSION_SECONDS", 5),
                                 max_gap_seconds=getattr(config, "LEARNING_MAX_GAP_SECONDS", 60))
        catalog.replace_examples(dataset.examples, now, dataset.fingerprint)
        catalog.record_dataset_diagnostics(dataset.reasons, now)
        return dataset
