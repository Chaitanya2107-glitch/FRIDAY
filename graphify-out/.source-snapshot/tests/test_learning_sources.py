from datetime import datetime
import json
import sqlite3
from pathlib import Path

from services.activity.log import ActivityLog
from services.learning.sources import scan_sources
from services.memory.semantic import semantic_memory
from services.mind import knowledge, corrections
from services.mind.reviews import reviews

NOW = datetime(2026, 10, 12, 12)


def test_sessions_feedback_and_inference_are_separate(tmp_path, monkeypatch):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE activity(id INTEGER, at TEXT, kind TEXT, app TEXT, duration_s REAL, category TEXT, origin TEXT, runtime TEXT, title TEXT); CREATE TABLE memories(id INTEGER, text TEXT, source TEXT, created_at TEXT);")
        conn.execute("INSERT INTO activity VALUES (1, ?, 'app', 'code', 20, 'coding', 'user', 'r1', 'Private window title')", (NOW.isoformat(),))
        conn.execute("INSERT INTO activity VALUES (2, 'bad', 'app', 'chrome', -1, NULL, 'unknown', NULL, 'secret title')")
        conn.execute("INSERT INTO memories VALUES (1, 'User is vegetarian', 'learned', ?)", (NOW.isoformat(),))
    monkeypatch.setattr(semantic_memory, "db_path", str(path))
    Path(knowledge.db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(knowledge.db_path) as conn:
        conn.execute("CREATE TABLE foresight_labels(at TEXT, frm TEXT, nxt TEXT, before TEXT, right INTEGER, recorded_at TEXT)")
        conn.execute("INSERT INTO foresight_labels VALUES (?, 'code', 'chrome', NULL, 1, ?)", (NOW.isoformat(), NOW.isoformat()))
    scan = scan_sources(ActivityLog(str(path)), now=NOW.replace(minute=1))
    assert len(scan.sessions) == 2
    assert scan.sessions[0].origin == "user"
    assert scan.sessions[1].status == "quarantined"
    assert len(scan.feedback) == 1
    assert scan.feedback[0].available_at == NOW
    memory = next(r for r in scan.records if r.source == "semantic")
    assert memory.reason == "inferred_fact"
    assert memory.status == "quarantined"
    assert not any("Private window title" in repr(r) or "User is vegetarian" in repr(r) for r in scan.records)
    assert "activity" in scan.complete_sources


def test_missing_and_corrupt_sources_are_not_complete(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(semantic_memory, "db_path", str(missing))
    corrections.path.parent.mkdir(parents=True, exist_ok=True)
    corrections.path.write_text("not JSON")
    scan = scan_sources(ActivityLog(str(missing)), now=NOW)
    assert scan.coverage["activity"] == "missing"
    assert scan.coverage["semantic"] == "missing"
    assert scan.coverage["command_corrections"] == "malformed"
    assert "activity" not in scan.complete_sources
    assert "command_corrections" not in scan.complete_sources
    assert not missing.exists()


def test_review_revocation_and_sensitive_records(tmp_path):
    item = reviews.capture("example", "secret private example", {}, at=NOW.timestamp())
    reviews.review(item, teaching="Owner-approved lesson", approve=True, exportable=False)
    scan = scan_sources(now=NOW)
    row = next(r for r in scan.records if r.source == "reviews")
    assert row.status == "accepted"
    assert row.metadata["exportable"] is False
    reviews.reject(item)
    row2 = next(r for r in scan_sources(now=NOW).records if r.source == "reviews")
    assert row2.status == "excluded"
    assert row2.revision != row.revision


def test_json_corrections_are_hashed_and_cumulative_counters_disclosed():
    corrections.path.parent.mkdir(parents=True, exist_ok=True)
    corrections.path.write_text(json.dumps({"open my confidential project": {"actions": [{"action": "open_app", "app_name": "code"}], "day": "2026-10-12", "meant": "private sentence"}}))
    scan = scan_sources(now=NOW)
    row = next(r for r in scan.records if r.source == "command_corrections")
    assert row.status == "accepted"
    assert "confidential" not in repr(row)
    assert "private sentence" not in repr(row)
    assert scan.coverage["habit_counters"] in {"missing", "cumulative_baseline_only"}


def test_sensitive_user_commands_and_invalid_duration_are_screened(tmp_path, monkeypatch):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE activity(id INTEGER, at TEXT, kind TEXT, app TEXT, duration_s REAL, category TEXT); CREATE TABLE conversations(id INTEGER, role TEXT, content TEXT, timestamp TEXT);")
        conn.execute("INSERT INTO activity VALUES (1, ?, 'app', 'code', 1e300, 'coding')", (NOW.isoformat(),))
        conn.execute("INSERT INTO conversations VALUES (1, 'user', 'type my confidential sentence', ?)", (NOW.isoformat(),))
    monkeypatch.setattr("services.learning.sources.config.MEMORY_DB_PATH", str(path))
    scan = scan_sources(ActivityLog(str(path)), now=NOW)
    row = next(r for r in scan.records if r.source == "activity")
    assert row.status == "quarantined"
    assert row.reason == "invalid_duration"
    row = next(r for r in scan.records if r.source == "conversations")
    assert row.status == "excluded"
    assert row.reason == "sensitive_record"


def test_malformed_intermediate_timestamp_preserves_observation_order(tmp_path):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE activity(id INTEGER, at TEXT, kind TEXT, app TEXT, duration_s REAL, category TEXT, origin TEXT, runtime TEXT)")
        for ident, at, app in ((1, "2026-10-12T11:59:00", "code"), (2, "malformed", "spotify"), (3, "2026-10-12T11:59:40", "chrome")):
            conn.execute("INSERT INTO activity VALUES (?, ?, 'app', ?, 20, 'coding', 'user', 'r1')", (ident, at, app))
    scan = scan_sources(ActivityLog(str(path)), now=NOW)
    assert [s.source_id for s in scan.sessions] == ["1", "2", "3"]
