"""Remove only the synthetic lecture app's test metadata, never real activity."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP = "fridayscreenfixture"
KEYS = ("app:" + APP, "topic:graph lecture fixture - friday screen test")
TABLES = {"app_explanations": "key", "things": "key", "thing_revisions": "key", "thoughts": "subject"}


def cleanup(apply=False):
    from services.activity.log import activity_log
    from services.mind import knowledge, talk
    from services.mind.cognition import cognition
    from tasks.verify_screen_awareness import identity
    def connect(path, stack):
        path = Path(path).resolve()
        assert ROOT in path.parents and path.is_file()
        conn = sqlite3.connect(path.as_uri() + "?mode=" + ("rw" if apply else "ro"), uri=True)
        stack.callback(conn.close)
        stack.enter_context(conn)
        return conn
    def exists(conn, table):
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    with ExitStack() as stack:
        activity, brain, state = [connect(path, stack) for path in (activity_log.db_path, knowledge.db_path, cognition.path)]
        tokens = [r[0] for r in brain.execute("SELECT token FROM app_explanations WHERE key IN (?,?)", KEYS)] if exists(brain, "app_explanations") else []
        thoughts = [r[0] for r in brain.execute("SELECT id FROM thoughts WHERE subject IN (?,?)", KEYS)]
        refs = ["app-explanation:" + token for token in tokens] + ["thought:" + str(item) for item in thoughts]
        jobs = set()
        if exists(state, "inquiry_jobs"):
            for ref in refs:
                jobs.update(r[0] for r in state.execute(
                    "SELECT j.id FROM inquiry_jobs j WHERE EXISTS (SELECT 1 FROM "
                    "json_each(CASE WHEN json_valid(j.basis) THEN j.basis ELSE '{}' END) b WHERE b.key=?)", (ref,)))
        counts = {"activity": activity.execute("SELECT COUNT(*) FROM activity WHERE app=?", (APP,)).fetchone()[0]}
        for table, column in TABLES.items():
            counts[table] = brain.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IN (?,?)", KEYS).fetchone()[0] if exists(brain, table) else 0
        counts["inquiry_jobs"] = len(jobs)
        pending = talk.load().get("pending") or {}
        matched_pending = ((pending.get("app_verification") or {}).get("key") in KEYS
                           or pending.get("thought") in thoughts or pending.get("inquiry_id") in jobs)
        if apply:
            if matched_pending:
                from tasks.screen_native_probe import api_client, command
                with api_client() as client:
                    command(client, "pause screen awareness")  # normal backend retirement, no direct file edit
            if counts["activity"] and exists(activity, "activity_boundaries"):
                activity.execute("INSERT INTO activity_boundaries(at,reason,runtime) "
                                 "SELECT at,?,COALESCE(runtime,'') FROM activity WHERE app=? AND kind='app'",
                                 ("synthetic_fixture_removed", APP))
            activity.execute("DELETE FROM activity WHERE app=?", (APP,))
            for job in jobs:
                if exists(state, "inquiry_interruptions"):
                    state.execute("DELETE FROM inquiry_interruptions WHERE job_id=?", (job,))
                state.execute("DELETE FROM inquiry_jobs WHERE id=?", (job,))
            for table, column in TABLES.items():
                if exists(brain, table):
                    brain.execute(f"DELETE FROM {table} WHERE {column} IN (?,?)", KEYS)
            assert not activity.execute("SELECT 1 FROM activity WHERE app=?", (APP,)).fetchone()
            assert not brain.execute("SELECT 1 FROM things WHERE key IN (?,?)", KEYS).fetchone()
    result = {"applied": apply, "source_identity": identity(), "fixture_app": APP,
              "selected_counts": counts, "matched_pending_question": bool(matched_pending),
              "scope": "Exact synthetic app and topic keys only; real apps and personal facts are outside the selectors.",
              "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if apply:
        (ROOT / "tasks/screen-fixture-cleanup.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cleanup(apply="--apply" in sys.argv)
