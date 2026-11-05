"""Read-only inventory and deterministic screening of retained learning stores.

Raw text is read only to hash revisions and check sensitivity; it is never returned.
Missing stores and cumulative counters are disclosed rather than invented as events.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
from services.activity import categories, habits, predict
from services.activity.log import activity_log, IGNORED_PROCESSES, PASSWORD_MANAGERS
from services.memory.semantic import semantic_memory
from services.mind import corrections, knowledge
from services.mind.reviews import reviews
from .contracts import LearningRecord, PredictionFeedback, Session, SourceScan

PURPOSES = {*categories.APPS, *categories.SITES, "project", "browsing", "other", "unknown"}
_SENSITIVE = re.compile(r"\b(?:password|api[_ -]?key|access[_ -]?token|bearer|private[_ -]?key|clipboard|diary|journal)\b", re.I)
_APP = re.compile(r"^[\w .+-]{1,100}$")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _time(value):
    try:
        parsed = datetime.fromtimestamp(value) if isinstance(value, (int, float)) else datetime.fromisoformat(str(value))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _timing(at, now):
    if at is None or at.year < 2000:
        return "quarantined", "invalid_time"
    if at > now + timedelta(seconds=5):
        return "quarantined", "future_time"
    return "accepted", ""


def _purpose(value):
    return value if value in PURPOSES else "unknown"


def _sensitive(*values):
    return any(_SENSITIVE.search(str(v or "")) for v in values)


def _session_duration(at, seconds, now):
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds <= 0:
        return "quarantined", "invalid_duration"
    try:
        end = at + timedelta(seconds=seconds)
    except (ValueError, OverflowError):
        return "quarantined", "invalid_duration"
    if end > now + timedelta(seconds=5):
        return "quarantined", "future_time"
    if seconds < getattr(config, "LEARNING_MIN_SESSION_SECONDS", 5):
        return "excluded", "short_session"
    return "accepted", ""


def _record(source, key, row, at, category, now, *, status=None, reason="", metadata=None):
    timed_status, timed_reason = _timing(at, now)
    if timed_status != "accepted":
        status, reason = timed_status, timed_reason
    return LearningRecord(source, str(key), _hash(row), at, category, status or "accepted", reason, metadata or {})


def _table(scan, path, table, source):
    """Return all rows, or no rows with an explicit incomplete-source diagnostic."""
    path = Path(path)
    if not path.exists():
        scan.coverage[source] = "missing"
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)) as conn:
            conn.row_factory = sqlite3.Row
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            if not columns:
                scan.coverage[source] = "missing_table"
                return None
            # Embedding vectors are neither needed nor copied into revision metadata.
            names = [f'"{c}"' for c in columns if c != "vector"]
            rows = [dict(row) for row in conn.execute(f'SELECT rowid AS _rowid, {", ".join(names)} FROM "{table}" ORDER BY rowid')]
        scan.complete_sources.add(source)
        scan.coverage[source] = "complete"
        return rows
    except (sqlite3.Error, OSError):
        scan.coverage[source] = "busy_or_unreadable"
        return None


def _activity(scan, log, now):
    rows = _table(scan, log.db_path, "activity", "activity")
    if rows is not None:
        unknown = False
        for row in rows:
            key, at = str(row.get("id", row["_rowid"])), _time(row.get("at"))
            kind, app = row.get("kind"), row.get("app")
            status, reason = _timing(at, now)
            purpose = _purpose(row.get("category"))
            seconds = row.get("duration_s")
            if status == "accepted" and kind == "app":
                if not isinstance(app, str) or not _APP.fullmatch(app.strip()):
                    status, reason = "quarantined", "invalid_app"
                elif app.lower() in PASSWORD_MANAGERS:
                    status, reason = "excluded", "sensitive_record"
                elif app.lower() in IGNORED_PROCESSES or purpose == "system":
                    status, reason = "excluded", "system_window"
                else:
                    status, reason = _session_duration(at, seconds, now)
            elif status == "accepted" and kind not in {"command", "launch", "web", "file", "feedback"}:
                status, reason = "quarantined", "unsupported_kind"
            if _sensitive(row.get("title"), row.get("target")) or purpose in {"notes", "diary"}:
                status, reason = "excluded", "sensitive_record"
            origin = row.get("origin") if row.get("origin") in {"user", "requested", "automatic"} else "unknown"
            category = "command_outcomes" if kind == "command" else "prediction_feedback" if kind == "feedback" else "activity/" + purpose
            scan.records.append(_record("activity", key, row, at, category, now, status=status, reason=reason,
                                        metadata={"origin": origin} if kind == "app" else {}))
            if kind == "app":
                unknown |= origin == "unknown"
                scan.sessions.append(Session(key, at, app, seconds, purpose, origin, status, row.get("runtime")))
        if unknown:
            scan.coverage["activity"] = "complete_with_unknown_origin"
    boundaries = _table(scan, log.db_path, "activity_boundaries", "activity_boundary")
    boundary_sessions = []
    for row in boundaries or ():
        at = _time(row.get("at"))
        key = str(row.get("id", row["_rowid"]))
        reason = "idle_boundary" if row.get("reason") == "idle" else "runtime_boundary"
        scan.records.append(_record("activity_boundary", key, row, at, "activity/system", now, status="excluded", reason=reason))
        boundary_sessions.append(Session("boundary:" + key, at, None, 0, "system", "unknown", "excluded", row.get("runtime")))
    # Preserve row order, especially malformed/reversed intermediate timestamps.
    # Sorting malformed B before A would permit a fabricated A-to-C transition.
    boundary_sessions.sort(key=lambda s: s.at or datetime.min)
    merged, index = [], 0
    for session in scan.sessions:
        while index < len(boundary_sessions) and (boundary_sessions[index].at is None or session.at is not None and boundary_sessions[index].at <= session.at):
            merged.append(boundary_sessions[index])
            index += 1
        merged.append(session)
    scan.sessions = merged + boundary_sessions[index:]


def _memories(scan, now):
    for row in _table(scan, semantic_memory.db_path, "memories", "semantic") or ():
        kind = row.get("source")
        category = "conversation_summaries" if kind == "episode" else "semantic_plans" if row.get("happens_on") else "semantic_facts"
        inferred = kind != "told"
        status, reason = ("quarantined", "inferred_fact") if inferred else ("accepted", "")
        if not row.get("text"):
            status, reason = "quarantined", "missing_fields"
        if _sensitive(row.get("text")):
            status, reason = "excluded", "sensitive_record"
        scan.records.append(_record("semantic", row.get("id", row["_rowid"]), row, _time(row.get("created_at")), category, now,
                                    status=status, reason=reason, metadata={"inferred": inferred}))
    for table, source, category, text_key, time_key in (
        ("conversations", "conversations", "conversation_records", "content", "timestamp"),
        ("user_facts", "user_facts", "semantic_facts", "value", "updated_at"),
    ):
        for row in _table(scan, config.MEMORY_DB_PATH, table, source) or ():
            status, reason = "accepted", ""
            if not row.get(text_key):
                status, reason = "quarantined", "missing_fields"
            if _sensitive(row.get(text_key), row.get("key")):
                status, reason = "excluded", "sensitive_record"
            if table == "conversations" and row.get("role") == "user":
                from services.mind.reflection import _private
                if _private(str(row.get(text_key) or "")):
                    status, reason = "excluded", "sensitive_record"
            scan.records.append(_record(source, row.get("id", row["_rowid"]), row, _time(row.get(time_key)), category, now, status=status, reason=reason))


def _brain(scan, now):
    for row in _table(scan, knowledge.db_path, "things", "knowledge") or ():
        provenance = row.get("source")
        inferred = provenance == "lookup"
        status, reason = ("quarantined", "inferred_fact") if inferred else ("accepted", "")
        if _sensitive(row.get("name"), row.get("about")):
            status, reason = "excluded", "sensitive_record"
        scan.records.append(_record("knowledge", _hash(row.get("key", row["_rowid"])), row, _time(row.get("first_seen")), "learned_knowledge", now,
                                    status=status, reason=reason, metadata={"inferred": inferred}))
    for table, source, category in (("thoughts", "thoughts", "thought_patterns"), ("reasons", "reasons", "learned_knowledge")):
        for row in _table(scan, knowledge.db_path, table, source) or ():
            status, reason = ("accepted", "") if row.get("answer") or table == "reasons" else ("quarantined", "inferred_fact")
            if _sensitive(row.get("answer"), row.get("reason"), row.get("data"), row.get("subject")):
                status, reason = "excluded", "sensitive_record"
            key = str(row["id"]) if "id" in row else _hash(row.get("pattern", row["_rowid"]))
            scan.records.append(_record(source, key, row, _time(row.get("at")), category, now, status=status, reason=reason))
    for row in _table(scan, knowledge.db_path, "foresight_labels", "prediction_feedback") or ():
        at, available = _time(row.get("at")), _time(row.get("recorded_at"))
        key = str(row["_rowid"])
        valid = all(isinstance(row.get(k), str) and _APP.fullmatch(row[k]) for k in ("frm", "nxt")) and row.get("right") in {0, 1}
        record = _record("prediction_feedback", key, row, at, "prediction_feedback", now,
                         status="accepted" if valid else "quarantined", reason="" if valid else "missing_fields",
                         metadata={"feedback_available": available is not None, "has_outcome": False})
        scan.records.append(record)
        if valid and record.status == "accepted":
            scan.feedback.append(PredictionFeedback(key, at, row["frm"], row["nxt"], bool(row["right"]), row.get("before"), available))
    for table, name in (("foresight_tally", "prediction_counters"), ("foresight_patterns", "prediction_pattern_counters")):
        if _table(scan, knowledge.db_path, table, name) is not None:
            scan.complete_sources.discard(name)
            scan.coverage[name] = "cumulative_baseline_only"
    # Learned category mappings are derived from things, not independent observations.
    scan.coverage["category_mappings"] = "derived_from_knowledge"


def _reviews(scan, now):
    for row in _table(scan, reviews.path, "reviews", "reviews") or ():
        state = row.get("state")
        if state in {"approved", "trained"} and (row.get("teaching") or row.get("preferred")):
            status, reason = "accepted", ""
        elif state == "rejected":
            status, reason = "excluded", "rejected_review"
        else:
            status, reason = "quarantined", "unreviewed"
        scan.records.append(_record("reviews", row.get("id", row["_rowid"]), row, _time(row.get("at")), "owner_reviewed_lessons", now,
                                    status=status, reason=reason,
                                    metadata={"approval": state in {"approved", "trained"}, "exportable": bool(row.get("exportable"))}))


def _json_sources(scan, now):
    path = Path(corrections.path)
    if not path.exists():
        scan.coverage["command_corrections"] = "missing"
    else:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(entries, dict):
                raise ValueError("Expected mapping")
            for key, entry in entries.items():
                valid = isinstance(entry, dict) and isinstance(entry.get("actions"), list) and bool(entry["actions"])
                private = _sensitive(key, entry)
                status, reason = ("excluded", "sensitive_record") if private else ("accepted", "") if valid else ("quarantined", "malformed_record")
                scan.records.append(_record("command_corrections", _hash(key), entry,
                                            _time(entry.get("day")) if isinstance(entry, dict) else None,
                                            "command_corrections", now, status=status, reason=reason))
            scan.complete_sources.add("command_corrections")
            scan.coverage["command_corrections"] = "complete"
        except (OSError, ValueError, TypeError):
            scan.coverage["command_corrections"] = "malformed"
    for path, source, category in ((habits.examples_path, "habit_feedback", "habit_feedback"),
                                   (predict.bar_log_path, "bar_predictions", "prediction_feedback")):
        path = Path(path)
        if not path.exists():
            scan.coverage[source] = "missing"
            continue
        try:
            counts, malformed = Counter(), False
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if not isinstance(entry, dict):
                        raise ValueError("Expected object")
                except (ValueError, TypeError):
                    malformed = True
                    continue
                identity = _hash(entry)
                counts[identity] += 1
                key = f"{identity}:{counts[identity]}"
                status, reason = ("excluded", "sensitive_record") if _sensitive(entry) else ("accepted", "")
                scan.records.append(_record(source, key, entry, _time(entry.get("at")), category, now, status=status, reason=reason))
            scan.coverage[source] = "partial" if malformed else "complete"
            if not malformed:
                scan.complete_sources.add(source)
        except OSError:
            scan.coverage[source] = "busy_or_unreadable"
    path = Path(habits.state_path)
    if not path.exists():
        scan.coverage["habit_counters"] = "missing"
    else:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            scan.coverage["habit_counters"] = "cumulative_baseline_only" if isinstance(state, dict) else "malformed"
        except (OSError, ValueError):
            scan.coverage["habit_counters"] = "malformed"


def scan_sources(log=None, now=None):
    now = _time(now or datetime.now())
    scan = SourceScan()
    _activity(scan, log or activity_log, now)
    _memories(scan, now)
    _brain(scan, now)
    _reviews(scan, now)
    _json_sources(scan, now)
    return scan
