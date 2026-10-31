"""Compact evidence of observed activity, not personal facts or training labels."""
from collections import defaultdict
from datetime import datetime, timedelta
import json

KINDS = {"reading", "watching", "writing", "browsing", "messaging", "playing", "unknown"}


def tables(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(screen_observations)")}
    for name, declaration in (("subject", "TEXT NOT NULL DEFAULT ''"),
                              ("kind", "TEXT NOT NULL DEFAULT 'unknown'"),
                              ("generation", "INTEGER NOT NULL DEFAULT 0")):
        if name not in columns:
            conn.execute(f"ALTER TABLE screen_observations ADD COLUMN {name} {declaration}")
    conn.execute("""CREATE TABLE IF NOT EXISTS screen_activity_days (
        day TEXT NOT NULL, app TEXT NOT NULL, subject TEXT NOT NULL, kind TEXT NOT NULL,
        first_at TEXT NOT NULL, last_at TEXT NOT NULL, checks INTEGER NOT NULL,
        exposures INTEGER NOT NULL, seconds REAL NOT NULL, hours TEXT NOT NULL,
        summary TEXT NOT NULL, activity TEXT NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY(day,app,subject,kind))""")


def _window(scope):
    return {key: value for key, value in json.loads(scope).items() if key != "content_hash"}


def observe(conn, previous, item):
    subject = " ".join(item["subject"].casefold().split())
    if not subject or item["kind"] == "unknown":
        return
    at = datetime.fromisoformat(item["at"])
    day = at.date().isoformat()
    key = (day, item["app"], subject, item["kind"])
    row = conn.execute("SELECT * FROM screen_activity_days WHERE day=? AND app=? AND subject=? AND kind=?", key).fetchone()
    gap = (at - datetime.fromisoformat(previous["at"])).total_seconds() if previous else -1
    continuous = bool(previous and 0 <= gap <= 75 and all(
        previous[k] == item[k] for k in ("app", "session", "epoch", "generation", "kind"))
        and " ".join(previous["subject"].casefold().split()) == subject
        and previous["at"][:10] == day and _window(previous["scope"]) == _window(item["scope"]))
    hours = sorted(set(json.loads(row["hours"]) if row else []) | {at.hour})
    conn.execute("INSERT OR REPLACE INTO screen_activity_days VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        *key, row["first_at"] if row else item["at"], item["at"], (row["checks"] if row else 0) + 1,
        (row["exposures"] if row else 0) + int(not continuous),
        (row["seconds"] if row else 0) + (gap if continuous else 0), json.dumps(hours),
        item["summary"], item["activity"], item["source"]))


def prune(conn, now):
    conn.execute("DELETE FROM screen_activity_days WHERE first_at<? OR rowid NOT IN "
                 "(SELECT rowid FROM screen_activity_days ORDER BY last_at DESC LIMIT 512)",
                 ((now - timedelta(days=7)).isoformat(timespec="seconds"),))


def context(conn, now):
    """Derived on read, so deleting evidence immediately removes its patterns."""
    cutoff = (now - timedelta(days=7)).isoformat(timespec="seconds")
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM screen_activity_days WHERE last_at>=? AND last_at<=? ORDER BY last_at DESC",
        (cutoff, now.isoformat(timespec="seconds")))]
    recent = [{key: r[key] for key in ("app", "subject", "kind", "first_at", "last_at", "exposures", "source")}
              for r in rows[:6]]
    grouped = defaultdict(list)
    for row in rows:
        if row["seconds"] >= 60:
            grouped[(row["app"], row["subject"], row["kind"])].append(row)
    patterns = []
    for (app, subject, kind), days in grouped.items():
        if len(days) < 3:
            continue
        periods = defaultdict(set)
        for row in days:
            for hour in json.loads(row["hours"]):
                period = "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 and hour >= 12 else "evening" if 17 <= hour < 22 else "night"
                periods[period].add(row["day"])
        usual = max(periods, key=lambda p: len(periods[p]))
        patterns.append({"app": app, "subject": subject, "kind": kind, "days": len(days),
                         "exposures": sum(r["exposures"] for r in days),
                         "observed_minutes": round(sum(r["seconds"] for r in days) / 60, 1),
                         "observed_period": usual if len(periods[usual]) >= 3 else None,
                         "status": "observed recurrence; not a confirmed preference or completed task"})
    return {"recent_activities": recent, "observed_patterns": sorted(patterns, key=lambda p: -p["days"])[:4]}
