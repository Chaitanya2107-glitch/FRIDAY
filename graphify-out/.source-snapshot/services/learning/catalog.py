"""Durable metadata audit; original source stores remain authoritative."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.config import config
from .contracts import POLICY_VERSION


def stamp(value: datetime) -> str:
    # Source timestamps use local wall time. Normalize aware inputs to that same clock.
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


class LearningCatalog:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    @contextmanager
    def db(self):
        with self._lock:
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS records (
                        source TEXT, source_id TEXT, revision TEXT, event_at TEXT, first_at TEXT,
                        backfill INTEGER, category TEXT, status TEXT, reason TEXT, metadata TEXT,
                        policy TEXT, removed_at TEXT, PRIMARY KEY(source, source_id));
                    CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, created_at TEXT, backfill INTEGER);
                    CREATE TABLE IF NOT EXISTS changes (source TEXT, source_id TEXT, at TEXT, kind TEXT);
                    CREATE TABLE IF NOT EXISTS examples (
                        id TEXT PRIMARY KEY, first_at TEXT, label_at TEXT, fingerprint TEXT, active INTEGER);
                    CREATE TABLE IF NOT EXISTS links (example_id TEXT, source TEXT, source_id TEXT,
                        PRIMARY KEY(example_id, source, source_id));
                    CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, at TEXT, payload TEXT);
                    CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, payload TEXT);
                    CREATE TABLE IF NOT EXISTS record_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source TEXT, source_id TEXT, at TEXT, payload TEXT);
                    CREATE TABLE IF NOT EXISTS example_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        example_id TEXT, at TEXT, payload TEXT);
                    CREATE TABLE IF NOT EXISTS meta_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT, at TEXT, value TEXT);
                    CREATE INDEX IF NOT EXISTS records_first_at ON records(first_at);
                    CREATE INDEX IF NOT EXISTS record_history_at ON record_history(at, source, source_id);
                    CREATE INDEX IF NOT EXISTS example_history_at ON example_history(at, example_id);
                """)
                yield conn
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _meta(conn, key, value, instant):
        old = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if old is None or old[0] != value:
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
            conn.execute("INSERT INTO meta_history(key,at,value) VALUES (?, ?, ?)", (key, instant, value))

    @staticmethod
    def _record_history(conn, source, source_id, instant):
        row = dict(conn.execute("SELECT * FROM records WHERE source=? AND source_id=?", (source, source_id)).fetchone())
        conn.execute("INSERT INTO record_history(source,source_id,at,payload) VALUES (?, ?, ?, ?)",
                     (source, source_id, instant, json.dumps(row, sort_keys=True)))

    @staticmethod
    def _example_history(conn, example_id, instant):
        row = dict(conn.execute("SELECT * FROM examples WHERE id=?", (example_id,)).fetchone())
        conn.execute("INSERT INTO example_history(example_id,at,payload) VALUES (?, ?, ?)",
                     (example_id, instant, json.dumps(row, sort_keys=True)))

    def ingest(self, records, now, complete_sources=None, coverage=None):
        instant = stamp(now)
        records = list(records)
        with self.db() as conn:
            initial = conn.execute("SELECT 1 FROM meta WHERE key='tracking_started'").fetchone() is None
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('tracking_started', ?)", (instant,))
            started = conn.execute("SELECT value FROM meta WHERE key='tracking_started'").fetchone()[0]
            seen = set()
            for record in records:
                key = (record.source, str(record.source_id))
                if not all(key) or key in seen:
                    continue
                seen.add(key)
                event = stamp(record.event_at) if record.event_at else None
                old = conn.execute("SELECT * FROM records WHERE source=? AND source_id=?", key).fetchone()
                backfill = old["backfill"] if old else int(event is not None and event < started or initial and event is None)
                category = record.category or "unknown"
                conn.execute("INSERT OR IGNORE INTO categories VALUES (?, ?, ?)", (category, instant, backfill))
                if initial and backfill:
                    conn.execute("UPDATE categories SET backfill=1 WHERE name=? AND created_at=?", (category, instant))
                # Only validated, small audit fields may cross the source boundary.
                metadata = {k: v for k, v in record.metadata.items() if k in {
                    "origin", "runtime", "inferred", "exportable", "approval", "has_outcome", "feedback_available"}
                    and isinstance(v, (bool, int, float, str, type(None)))}
                status = record.status if record.status in {"accepted", "excluded", "quarantined", "pending"} else "pending"
                fields = (record.revision, event, category, status, record.reason,
                          json.dumps(metadata, sort_keys=True), POLICY_VERSION)
                if old is None:
                    conn.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                                 (*key, record.revision, event, instant, backfill, category, status, record.reason,
                                  fields[5], POLICY_VERSION))
                    self._record_history(conn, *key, instant)
                else:
                    changed = old["revision"] != record.revision or old["status"] != status or old["category"] != category
                    if changed:
                        conn.execute("INSERT INTO changes VALUES (?, ?, ?, 'revision')", (*key, instant))
                    conn.execute("UPDATE records SET revision=?,event_at=?,category=?,status=?,reason=?,metadata=?,policy=?,removed_at=NULL WHERE source=? AND source_id=?", (*fields, *key))
                    if changed or old["removed_at"] or old["reason"] != record.reason or old["metadata"] != fields[5]:
                        self._record_history(conn, *key, instant)
            for source in complete_sources or ():
                rows = conn.execute("SELECT source_id FROM records WHERE source=? AND removed_at IS NULL", (source,)).fetchall()
                for row in rows:
                    if (source, row["source_id"]) not in seen:
                        conn.execute("UPDATE records SET removed_at=? WHERE source=? AND source_id=?", (instant, source, row["source_id"]))
                        conn.execute("INSERT INTO changes VALUES (?, ?, ?, 'removed')", (source, row["source_id"], instant))
                        self._record_history(conn, source, row["source_id"], instant)
            invalid = [r[0] for r in conn.execute("SELECT DISTINCT e.id FROM examples e JOIN links l ON e.id=l.example_id JOIN records r ON r.source=l.source AND r.source_id=l.source_id WHERE e.active=1 AND (r.removed_at IS NOT NULL OR r.status!='accepted')")]
            conn.execute("UPDATE examples SET active=0 WHERE id IN (SELECT l.example_id FROM links l JOIN records r ON r.source=l.source AND r.source_id=l.source_id WHERE r.removed_at IS NOT NULL OR r.status != 'accepted')")
            for identity in invalid:
                self._example_history(conn, identity, instant)
            if coverage is not None:
                self._meta(conn, "coverage", json.dumps(coverage, sort_keys=True), instant)

    def replace_examples(self, examples, now, fingerprint):
        instant = stamp(now)
        with self.db() as conn:
            old_examples = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM examples")}
            conn.execute("UPDATE examples SET active=0")
            active = set()
            for example in examples:
                ids = tuple(dict.fromkeys(example.source_ids))
                if not ids or any(conn.execute("SELECT 1 FROM records WHERE source='activity' AND source_id=? AND status='accepted' AND removed_at IS NULL", (str(i),)).fetchone() is None for i in ids):
                    continue
                conn.execute("INSERT INTO examples VALUES (?, ?, ?, ?, 1) ON CONFLICT(id) DO UPDATE SET label_at=excluded.label_at,fingerprint=excluded.fingerprint,active=1",
                             (example.source_id, instant, stamp(example.label_at), fingerprint))
                conn.execute("DELETE FROM links WHERE example_id=?", (example.source_id,))
                conn.executemany("INSERT INTO links VALUES (?, 'activity', ?)", ((example.source_id, str(i)) for i in ids))
                active.add(example.source_id)
                old = old_examples.get(example.source_id)
                if old is None or not old["active"] or old["fingerprint"] != fingerprint or old["label_at"] != stamp(example.label_at):
                    self._example_history(conn, example.source_id, instant)
            for identity, old in old_examples.items():
                if old["active"] and identity not in active:
                    self._example_history(conn, identity, instant)
            self._meta(conn, "dataset_version", fingerprint, instant)

    def record_training_run(self, run):
        allowed = {"id", "at", "status", "reason", "dataset_version", "policy_version", "training_ids", "evaluation_ids", "model", "counting", "metrics", "in_charge", "promoted", "train_count", "test_count", "cutoff", "weights", "source_ids", "feedback_ids", "purged_crossing_examples", "preserved_artifact"}
        payload = {k: v for k, v in run.items() if k in allowed}
        for key in ("training_ids", "evaluation_ids"):
            payload[key] = sorted(set(payload.get(key, [])))
        at = run["at"]
        at = stamp(at if isinstance(at, datetime) else datetime.fromisoformat(at))
        payload["at"] = at
        with self.db() as conn:
            conn.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?)", (run["id"], at, json.dumps(payload, sort_keys=True)))

    def record_dataset_diagnostics(self, reasons, now):
        with self.db() as conn:
            self._meta(conn, "eligibility_reasons", json.dumps(reasons, sort_keys=True), stamp(now))

    def report(self, start, end, freeze_key=None):
        lower, upper = stamp(start), stamp(end)
        with self.db() as conn:
            if freeze_key:
                # Serialize the first snapshot writer across backend/CLI processes.
                conn.execute("BEGIN IMMEDIATE")
                frozen = conn.execute("SELECT payload FROM snapshots WHERE key=?", (freeze_key,)).fetchone()
                if frozen:
                    return json.loads(frozen[0])
            meta = {r["key"]: r["value"] for r in conn.execute("SELECT h.key,h.value FROM meta_history h WHERE h.id IN (SELECT MAX(id) FROM meta_history WHERE at<? GROUP BY key)", (upper,))}
            tracked = conn.execute("SELECT value FROM meta WHERE key='tracking_started'").fetchone()
            meta["tracking_started"] = tracked[0] if tracked else None
            rows = [json.loads(r[0]) for r in conn.execute("SELECT h.payload FROM record_history h WHERE h.id IN (SELECT MAX(id) FROM record_history WHERE at<? GROUP BY source,source_id)", (upper,))]
            rows = [r for r in rows if lower <= r["first_at"] < upper]
            fresh = [row for row in rows if not row["backfill"]]
            statuses = Counter(row["status"] for row in fresh)
            result = {"tracking_started": meta.get("tracking_started"), "window_start": lower, "window_end": upper,
                      "collected": len(fresh), "appropriate": statuses["accepted"], "excluded": statuses["excluded"],
                      "quarantined": statuses["quarantined"], "pending_screening": statuses["pending"],
                      "backfilled": sum(row["backfill"] for row in rows), "coverage": json.loads(meta.get("coverage", "{}")),
                      "dataset_version": meta.get("dataset_version"), "policy_version": POLICY_VERSION}
            result["eligibility_reasons"] = json.loads(meta.get("eligibility_reasons", "{}"))
            result["categories"] = []
            for name in sorted({r["category"] for r in fresh}):
                members = [r for r in fresh if r["category"] == name]
                counts = Counter(r["status"] for r in members)
                result["categories"].append({"name": name, "collected": len(members), "appropriate": counts["accepted"], "excluded": counts["excluded"], "quarantined": counts["quarantined"], "pending_screening": counts["pending"]})
            result["categories_active"] = len(result["categories"])
            result["categories_created"] = conn.execute("SELECT COUNT(*) FROM categories WHERE created_at>=? AND created_at<? AND backfill=0", (lower, upper)).fetchone()[0]
            result["reasons"] = dict(Counter(r["reason"] for r in fresh if r["reason"] and r["status"] in {"excluded", "quarantined"}))
            for kind, key in (("revision", "revisions"), ("removed", "removed")):
                result[key] = conn.execute("SELECT COUNT(*) FROM changes WHERE kind=? AND at>=? AND at<?", (kind, lower, upper)).fetchone()[0]
            historical_examples = [json.loads(r[0]) for r in conn.execute("SELECT h.payload FROM example_history h WHERE h.id IN (SELECT MAX(id) FROM example_history WHERE at<? GROUP BY example_id)", (upper,))]
            result["eligible_examples"] = sum(1 for r in historical_examples if r["active"] and lower <= r["first_at"] < upper and r["label_at"] < upper)
            result["eligible_examples_available"] = sum(1 for r in historical_examples if r["active"] and r["label_at"] < upper)
            runs = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM runs WHERE at>=? AND at<? ORDER BY at", (lower, upper))]
            result["used_training"] = len({i for run in runs for i in run.get("training_ids", [])})
            result["evaluated"] = len({i for run in runs for i in run.get("evaluation_ids", [])})
            latest = conn.execute("SELECT payload FROM runs WHERE at<? ORDER BY at DESC LIMIT 1", (upper,)).fetchone()
            result["latest_training"] = json.loads(latest[0]) if latest else None
            measured = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM runs WHERE at<? ORDER BY at DESC", (upper,))]
            result["latest_measured_training"] = next((r for r in measured if r.get("status") == "completed"), None)
            if freeze_key:
                conn.execute("INSERT INTO snapshots VALUES (?, ?)", (freeze_key, json.dumps(result, sort_keys=True)))
            return result


catalog = LearningCatalog(config.MEMORY_DIR / "learning.db")
