from datetime import datetime, timedelta

from services.activity.log import ActivityLog
from services.learning import origin


def test_historical_rows_remain_unknown_after_schema_upgrade(tmp_path):
    import sqlite3
    path = tmp_path / "activity.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE activity (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, app TEXT, action TEXT, target TEXT, success INTEGER, title TEXT, duration_s REAL, category TEXT, project TEXT, subject TEXT)")
        conn.execute("INSERT INTO activity(at,kind,app,duration_s) VALUES ('2026-10-01T09:00:00','app','code',30)")
    log = ActivityLog(str(path))
    with log._connect() as conn:
        assert conn.execute("SELECT origin,runtime FROM activity").fetchone() == ("unknown", None)


def test_new_observations_distinguish_runtime_start_and_user_switch(tmp_path):
    now = datetime.now()
    log = ActivityLog(str(tmp_path / "activity.db"))
    log.observe("code", now)
    log.observe("chrome", now + timedelta(seconds=20))
    log.flush(now + timedelta(seconds=40))
    with log._connect() as conn:
        rows = conn.execute("SELECT app,origin,runtime FROM activity WHERE kind='app' ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("code", "unknown"), ("chrome", "user")]
    assert rows[0][2] and rows[0][2] == rows[1][2]


def test_automatic_open_is_not_labeled_a_user_choice(tmp_path):
    now = datetime.now()
    log = ActivityLog(str(tmp_path / "activity.db"))
    log.observe("code", now)
    with origin.action_scope("automatic"):
        origin.note_open(now + timedelta(seconds=10))
    log.observe("spotify", now + timedelta(seconds=11))
    log.observe("spotify", now + timedelta(seconds=15), title="a song")
    log.flush(now + timedelta(seconds=35))
    with log._connect() as conn:
        assert conn.execute("SELECT DISTINCT origin FROM activity WHERE app='spotify'").fetchall() == [("automatic",)]


def test_user_requested_open_has_requested_origin(tmp_path):
    now = datetime.now()
    log = ActivityLog(str(tmp_path / "activity.db"))
    origin.note_open(now)
    log.observe("code", now + timedelta(seconds=1))
    log.flush(now + timedelta(seconds=21))
    with log._connect() as conn:
        assert conn.execute("SELECT origin FROM activity WHERE kind='app'").fetchone()[0] == "requested"


def test_idle_boundary_is_persisted_without_inventing_an_app(tmp_path):
    now = datetime.now()
    log = ActivityLog(str(tmp_path / "activity.db"))
    log.observe("code", now)
    log.observe(None, now + timedelta(seconds=20))
    with log._connect() as conn:
        assert conn.execute("SELECT reason FROM activity_boundaries WHERE reason='idle'").fetchall() == [("idle",)]
        assert conn.execute("SELECT app FROM activity WHERE kind='app'").fetchall() == [("code",)]


def test_discarded_brief_foreground_app_breaks_real_dataset(tmp_path):
    from services.learning.sources import scan_sources
    from services.learning.dataset import build_examples
    now = datetime.now()
    log = ActivityLog(str(tmp_path / "activity.db"))
    origin.note_open(now, app="code")
    log.observe("code", now)
    log.observe("brief", now + timedelta(seconds=10))
    log.observe("chrome", now + timedelta(seconds=12))
    log.observe("spotify", now + timedelta(seconds=22))
    log.flush(now + timedelta(seconds=32))
    scan = scan_sources(log=log, now=now + timedelta(seconds=33))
    dataset = build_examples(scan.sessions, scan.feedback, now + timedelta(seconds=33))
    assert [(e.app, e.nxt) for e in dataset.examples] == [("chrome", "spotify")]
    with log._connect() as conn:
        assert conn.execute("SELECT reason FROM activity_boundaries WHERE reason='short_session'").fetchall() == [("short_session",)]


def test_delayed_automatic_open_keeps_origin_after_unrelated_request():
    now = datetime.now()
    with origin.action_scope("automatic"):
        origin.note_open(now, app="spotify")
    origin.note_open(now + timedelta(seconds=1), app="chrome")
    assert origin.observed_actor(now + timedelta(seconds=2), "spotify") == "automatic"
    assert origin.observed_actor(now + timedelta(seconds=2), "chrome") == "requested"
    assert origin.observed_actor(now + timedelta(seconds=1000), "spotify") is None
