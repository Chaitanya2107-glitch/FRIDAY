"""Recover exact pre-test SQLite rows; require catalog hashes before any restore."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "tasks/passive-data-recovery"
REMOVED_AT = "2026-10-29T22:04:21.683841"


def recover():
    catalog = sqlite3.connect((ROOT / "memory/learning.db").as_uri() + "?mode=ro", uri=True)
    rows = catalog.execute("SELECT source_id,revision,event_at FROM records WHERE source=? AND removed_at=?",
                           ("conversations", REMOVED_AT)).fetchall()
    catalog.close()
    assert len(rows) == 46, "Recovery selector changed; do not guess."
    by_time = {}
    for ident, digest, when in rows:
        by_time.setdefault(when, []).append((int(ident), digest))
    raw = (RECOVERY / "friday-after-interrupted-tests.db").read_bytes()
    matched = {}
    zone = timezone(timedelta(hours=5, minutes=30))
    for stamp in re.finditer(rb"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?\+00:00", raw):
        at = stamp.group().decode("ascii")
        when = datetime.fromisoformat(at).astimezone(zone).replace(tzinfo=None).isoformat(timespec="microseconds")
        targets = by_time.get(when, [])
        if not targets:
            continue
        region = raw[max(0, stamp.start() - 30000):stamp.start()]
        for role in re.finditer(rb"user|assistant", region):
            try:
                content = region[role.end():].decode("utf-8")
            except UnicodeDecodeError:
                continue
            for ident, digest in targets:
                record = {"_rowid": ident, "id": ident, "role": role.group().decode("ascii"),
                          "content": content, "timestamp": at}
                revision = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
                if revision == digest:
                    matched[ident] = record
    assert set(matched) == {int(row[0]) for row in rows}, "Some exact records could not be reconstructed."
    assert min(matched) == 4028 and max(matched) == 4073
    return matched, {int(row[0]): row[1] for row in rows}


def main():
    recovered, revisions = recover()
    path = ROOT / "memory/friday.db"
    assert path.is_file() and path.resolve().is_relative_to(ROOT / "memory")
    conn = sqlite3.connect(path)
    backup = sqlite3.connect(RECOVERY / "friday-before-exact-restore.db")
    conn.backup(backup)
    backup.close()
    with conn:
        for ident, item in sorted(recovered.items()):
            values = (item["id"], item["role"], item["content"], item["timestamp"])
            existing = conn.execute("SELECT id,role,content,timestamp FROM conversations WHERE id=?", (ident,)).fetchone()
            assert existing is None or tuple(existing) == values, "An ID was reused; do not overwrite."
            conn.execute("INSERT OR IGNORE INTO conversations(id,role,content,timestamp) VALUES(?,?,?,?)", values)
        for ident, expected in revisions.items():
            row = conn.execute("SELECT id,role,content,timestamp FROM conversations WHERE id=?", (ident,)).fetchone()
            record = dict(zip(("id", "role", "content", "timestamp"), row))
            record["_rowid"] = record["id"]
            assert hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest() == expected
    conn.close()
    receipt = {"restored": len(recovered), "all_catalog_hashes_match": True, "original_ids_and_timestamps": True,
               "selector": {"source": "conversations", "removed_at": REMOVED_AT},
               "revisions": revisions, "scope": "Only the exact 46 pre-test rows; no invented text, timestamp changes or owner-fact edits.",
               "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (RECOVERY / "exact-restoration.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("restored", "all_catalog_hashes_match", "original_ids_and_timestamps")}))


if __name__ == "__main__":
    main()
