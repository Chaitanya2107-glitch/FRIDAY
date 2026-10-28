"""Shared situations, local action assessments and durable, proposal-only attention."""

import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition, redact
from services.mind.reasoning_store import fingerprint

REVIEW_GAP, HOURLY_LIMIT, LEASE_SECONDS = 300, 4, 45
SOURCE_KINDS = {"memory_summary", "question_review", "action_outcome", "outcome_lesson", "owner_fact", "owner_message", "owner_answer", "temporal_interpretation", "runtime", "observation", "learned_guess", "goal", "task", "reminder", "deadline", "execution", "weekly_template", "project", "reaction", "focus"}


def attention_state():
    from services.mind.cognition_context import live_state
    live = live_state()
    if live.get("state") == "partly unavailable":
        raise ValueError("Current attention is unavailable.")
    from services.mind.life_state import current
    return {**{k: live.get(k) for k in ("activity", "away", "mode_active", "mode_name", "waiting_for_answer", "speaking", "listening")},
            'life_state': current(live=live)}


def execution_evidence(store):
    """Local focus and historical receipts, without paths, notes or current-window claims."""
    from services.mind.workspace import Workspace
    with Workspace(store)._db() as conn:
        rows = conn.execute("SELECT e.id,e.state,e.cursor,e.payload,e.digest,e.evidence,e.updated,c.uncertain,c.expires "
                            "FROM workspace_executions e LEFT JOIN workspace_execution_claims c ON c.execution_id=e.id "
                            "ORDER BY e.id DESC LIMIT 5").fetchall()
        focus = {row["kind"]: row["target"] for row in conn.execute("SELECT kind,target FROM workspace_focus WHERE scope='local'")}
    result = {}
    for row in rows:
        payload, receipts = json.loads(row["payload"]), json.loads(row["evidence"])
        workflow = payload.get("workflow", "handoff")
        phases = {"handoff": 3, "project_session": 4, "project_execution": 5}.get(workflow, 0)
        verified = (row["state"] == "completed" and bool(row["digest"]) and phases > 0
                    and row["cursor"] == phases and len(receipts) == phases
                    and all(e.get("source") == "executor" and e.get("step") == i for i, e in enumerate(receipts)))
        if workflow == "project_execution":
            verified = verified and bool(payload.get("folder_window"))
        result[f"execution:{row['id']}"] = {"kind": "execution", "workflow": workflow,
            "project_name": str(payload.get("project", {}).get("name", ""))[:160],
            "state": row["state"], "checkpoints": row["cursor"], "updated": row["updated"],
            "effect_status": "uncertain" if row["state"] == "pending" and row["expires"] is not None
                and (row["uncertain"] or row["expires"] <= time.time()) else row["state"],
            "historically_verified": bool(verified), "source": "executor_receipt",
            "meaning": "Workflow result only; not source-task completion or current app state."}
    if focus:
        result["focus:local"] = {"kind": "focus", "scope": "local", "targets": focus, "source": "owner_selection"}
    return result


def clear_derived(conn):
    """Forget derived private context, invalidating active workers without resetting budgets."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("executive_reviews", "executive_situations", "executive_decisions", "executive_outcomes", "owner_episodes", "inquiry_jobs", "temporal_situations", "life_reactions", 'action_outcomes', 'memory_threads', 'consolidated_sources', 'dialogue_clarifications', 'screen_observations'):
        if table in tables:
            conn.execute(f"DELETE FROM {table}")
    if 'workspace_reference_context' in tables:
        conn.execute("DELETE FROM workspace_reference_context WHERE kind='commitment_topic'")
    if "executive_settings" in tables:
        conn.execute("UPDATE executive_settings SET epoch=epoch+1 WHERE id=1")
    if 'inquiry_meta' in tables:
        conn.execute('UPDATE inquiry_meta SET epoch=epoch+1 WHERE id=1')
    if 'outcome_settings' in tables:
        conn.execute('UPDATE outcome_settings SET epoch=epoch+1 WHERE id=1')
    if 'screen_settings' in tables:
        conn.execute('UPDATE screen_settings SET epoch=epoch+1 WHERE id=1')


class ExecutiveControl:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS executive_settings (id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, epoch INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS executive_situations (id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT UNIQUE NOT NULL, body TEXT NOT NULL, created REAL NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS executive_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT UNIQUE NOT NULL, situation_id INTEGER NOT NULL,
                state TEXT NOT NULL, token TEXT NOT NULL DEFAULT '', expires REAL NOT NULL DEFAULT 0,
                epoch INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                not_before REAL NOT NULL DEFAULT 0, updated REAL NOT NULL)""")
            conn.execute("CREATE TABLE IF NOT EXISTS executive_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS executive_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, execution_id INTEGER NOT NULL, situation_id INTEGER NOT NULL,
                decision TEXT NOT NULL, reason TEXT NOT NULL, expected TEXT NOT NULL, created REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS executive_outcomes (
                execution_id INTEGER PRIMARY KEY, state TEXT NOT NULL, verified INTEGER NOT NULL, updated REAL NOT NULL)""")
            conn.execute("INSERT OR IGNORE INTO executive_settings VALUES(1,1,0)")
            conn.commit()
            yield conn

    @staticmethod
    def _build(now, known, attention, intention):
        evidence, size = {}, 0
        selected = {f"{kind}:{ident}" for kind, ident in known.get("focus:local", {}).get("targets", {}).items()}
        from services.mind.temporal_memory import TemporalMemory
        pending = TemporalMemory.pending_corrections(known)
        priority = set(pending) | {ref for targets in pending.values() for ref in targets}
        ordered = sorted(known.items(), key=lambda item: (item[0] not in priority,
                         0 if item[0] in selected or item[1].get("kind") in {"focus", "project"} else
                         1 if item[1].get('historical_recall') or item[1].get("kind") in {"owner_fact", "goal", "action_outcome", "outcome_lesson", "memory_summary"} else 2))
        for ident, raw in ordered:
            if raw.get("kind") not in SOURCE_KINDS:
                continue
            encoded = redact(json.dumps(raw, default=str))
            if size + len(encoded) > 16000:
                continue
            evidence[ident], size = json.loads(encoded), size + len(encoded)
        temporal = {key: "due" if value["due_at"] <= now.timestamp() else
                    "soon" if value["due_at"] <= now.timestamp() + 3600 else "future"
                    for key, value in evidence.items() if value.get("kind") == "reminder"}
        data = {"day": now.date().isoformat(), "scope": "local", "intention": intention,
                "attention": attention, "evidence": evidence,
                "versions": {key: fingerprint(value) for key, value in evidence.items()}, "temporal": temporal}
        return {**data, "signature": fingerprint(data)}

    def _known(self):
        from services.mind.reasoning_store import ReasoningStore
        return ReasoningStore(self.store).evidence()

    def capture(self, now=None, *, known=None, attention=None, intention="background"):
        now = now or datetime.now()
        data = self._build(now, self._known() if known is None else known,
                           attention_state() if attention is None else attention, intention)
        with self._db() as conn:
            conn.execute("INSERT OR IGNORE INTO executive_situations(signature,body,created) VALUES(?,?,?)",
                         (data["signature"], json.dumps(data), now.timestamp()))
            ident = conn.execute("SELECT id FROM executive_situations WHERE signature=?", (data["signature"],)).fetchone()[0]
            conn.execute("DELETE FROM executive_situations WHERE id NOT IN (SELECT id FROM executive_situations "
                         "ORDER BY (id IN (SELECT situation_id FROM executive_reviews WHERE state='running')) DESC,id DESC LIMIT 200)")
        return {**data, "id": ident}

    def read(self, ident):
        with self._db() as conn:
            row = conn.execute("SELECT body FROM executive_situations WHERE id=?", (ident,)).fetchone()
        return {**json.loads(row[0]), "id": ident} if row else None

    def set_enabled(self, enabled):
        with self._db() as conn:
            conn.execute("UPDATE executive_settings SET enabled=?,epoch=epoch+1 WHERE id=1", (int(enabled),))
            conn.execute("UPDATE executive_reviews SET state='superseded' WHERE state IN ('pending','running','unavailable')")

    def context_version(self):
        """Fence dialogue snapshots against forgetting or a newer commitment revision."""
        with self._db() as conn:
            conn.execute('BEGIN')
            epoch = conn.execute('SELECT epoch FROM executive_settings WHERE id=1').fetchone()[0]
            temporal = conn.execute("SELECT 1 FROM sqlite_master WHERE name='temporal_situations'").fetchone()
            revision = conn.execute('SELECT COALESCE(MAX(id),0) FROM temporal_situations').fetchone()[0] if temporal else 0
        return epoch, revision

    def status(self, now=None):
        now = now or datetime.now()
        with self._db() as conn:
            settings = conn.execute("SELECT * FROM executive_settings WHERE id=1").fetchone()
            used = conn.execute("SELECT COUNT(*) FROM executive_attempts WHERE started>?", (now.timestamp() - 3600,)).fetchone()[0]
            last = conn.execute("SELECT state FROM executive_reviews ORDER BY id DESC LIMIT 1").fetchone()
        enabled = bool(config.COGNITION_ENABLED and config.COGNITIVE_REVIEW_ENABLED and config.REASONING_ENABLED and settings["enabled"])
        return {"enabled": enabled, "reviews_this_hour": used, "hourly_limit": HOURLY_LIMIT,
                "minimum_gap_seconds": REVIEW_GAP, "last_review": last[0] if last else "none"}

    def enqueue(self, situation, now, *, preserve_running=False):
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            states = ('pending', 'unavailable') if preserve_running else ('pending', 'running', 'unavailable')
            conn.execute("UPDATE executive_reviews SET state='superseded' WHERE signature<>? AND state IN (" +
                         ','.join('?' for _ in states) + ')', (situation["signature"], *states))
            conn.execute("INSERT OR IGNORE INTO executive_reviews(signature,situation_id,state,updated) VALUES(?,?,'pending',?)",
                         (situation["signature"], situation["id"], now.timestamp()))
            conn.execute("UPDATE executive_reviews SET state='pending',situation_id=?,token='',expires=0,updated=? "
                         "WHERE signature=? AND state='superseded'",
                         (situation["id"], now.timestamp(), situation["signature"]))
            conn.execute("UPDATE executive_reviews SET situation_id=? WHERE signature=? AND state IN ('pending','unavailable')",
                         (situation["id"], situation["signature"]))
            conn.execute("DELETE FROM executive_reviews WHERE id NOT IN (SELECT id FROM executive_reviews ORDER BY id DESC LIMIT 200) AND state<>'running'")

    def claim(self, now, *, signature=None):
        if not self.status(now)["enabled"]:
            return None
        stamp = now.timestamp()
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            settings = conn.execute("SELECT * FROM executive_settings WHERE id=1").fetchone()
            attempts = conn.execute("SELECT COUNT(*),MAX(started) FROM executive_attempts WHERE started>?", (stamp - 3600,)).fetchone()
            if (not settings["enabled"] or attempts[0] >= HOURLY_LIMIT or
                    (attempts[1] is not None and stamp - attempts[1] < REVIEW_GAP)):
                return None
            if conn.execute("SELECT 1 FROM executive_reviews WHERE state='running' AND expires>?", (stamp,)).fetchone():
                return None
            row = conn.execute("SELECT * FROM executive_reviews WHERE ((state IN ('pending','unavailable') AND not_before<=?) "
                               "OR (state='running' AND expires<=?)) AND (? IS NULL OR signature=?) ORDER BY id DESC LIMIT 1",
                               (stamp, stamp, signature, signature)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            conn.execute("UPDATE executive_reviews SET state='running',token=?,expires=?,epoch=?,attempts=attempts+1,updated=? WHERE id=?",
                         (token, stamp + LEASE_SECONDS, settings["epoch"], stamp, row["id"]))
            conn.execute("INSERT INTO executive_attempts(started) VALUES(?)", (stamp,))
            conn.execute("DELETE FROM executive_attempts WHERE started<?", (stamp - 86400,))
            claimed = dict(conn.execute("SELECT * FROM executive_reviews WHERE id=?", (row["id"],)).fetchone())
        logger.debug("Executive review %s claimed; attempt=%s", claimed["id"], claimed["attempts"])
        return claimed

    @staticmethod
    def _valid(conn, job, stamp):
        return bool(conn.execute("SELECT 1 FROM executive_reviews r JOIN executive_settings s ON s.id=1 "
            "WHERE r.id=? AND r.token=? AND r.state='running' AND r.expires>? AND r.epoch=s.epoch AND s.enabled=1",
            (job["id"], job["token"], stamp)).fetchone())

    def finish(self, job, state, now):
        if state not in {"completed", "unavailable"}:
            raise ValueError("Invalid review result.")
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._valid(conn, job, now.timestamp()):
                if state == "completed":
                    return bool(conn.execute("SELECT 1 FROM executive_reviews r JOIN executive_settings s ON s.id=1 "
                        "WHERE r.id=? AND r.token=? AND r.state='completed' AND r.epoch=s.epoch AND s.enabled=1",
                        (job["id"], job["token"])).fetchone())
                return False
            delay = min(3600, REVIEW_GAP * 2 ** min(job["attempts"] - 1, 4))
            conn.execute("UPDATE executive_reviews SET state=?,not_before=?,updated=? WHERE id=?",
                         (state, now.timestamp() + delay, now.timestamp(), job["id"]))
            return True

    async def review(self, now=None, *, busy=False):
        from services.mind import reasoning
        from services.mind.reasoning_store import ReasoningStore
        now = now or datetime.now()
        try:
            if not self.status(now)["enabled"]:
                return {"status": "disabled"}
            attention = await asyncio.to_thread(attention_state)
            if (busy or not attention.get('life_state', {}).get('can_review', True)
                    or any(attention.get(k) for k in ("speaking", "listening", "waiting_for_answer"))):
                return {"status": "deferred"}
            situation = await asyncio.to_thread(self.capture, now, attention=attention)
            if not any(v.get("kind") != "weekly_template" for v in situation["evidence"].values()):
                return {"status": "idle"}
            await asyncio.to_thread(self.enqueue, situation, now)
            job = await asyncio.to_thread(self.claim, now)
            if not job:
                return {"status": "idle"}
            started = time.monotonic()

            def guard(conn):
                if (not config.COGNITIVE_REVIEW_ENABLED or not config.REASONING_ENABLED or not config.COGNITION_ENABLED
                        or not self._valid(conn, job, now.timestamp() + time.monotonic() - started)):
                    raise ValueError("The executive review was disabled, cleared, replaced or expired.")

            def ready():
                current = self._build(now, self._known(), attention_state(), "background")
                if current["signature"] != situation["signature"]:
                    raise ValueError("The reviewed situation changed.")
                with self._db() as conn:
                    guard(conn)

            def save(report, noted, bounded):
                # Re-read ALL reviewed sources, not just the model's chosen citations.
                ready()
                def finalize(conn):
                    guard(conn)
                    conn.execute("UPDATE executive_reviews SET state='completed',updated=? WHERE id=? AND token=?",
                                 (now.timestamp() + time.monotonic() - started, job["id"], job["token"]))
                return ReasoningStore(self.store).save(report, noted, bounded, guard=guard, finalize=finalize)

            result = await reasoning.analyze("", now=now, cognitive=True, evidence=situation["evidence"], save=save,
                                             deadline=started + LEASE_SECONDS - 1, ready=ready)
            state = "completed" if result["status"] == "completed" else "unavailable"
            finished = datetime.fromtimestamp(now.timestamp() + time.monotonic() - started)
            accepted = await asyncio.to_thread(self.finish, job, state, finished)
            return result if accepted else {"status": "superseded"}
        except (ValueError, OSError, sqlite3.Error) as error:
            logger.warning("Executive review unavailable: %s", type(error).__name__)
            return {"status": "unavailable"}

    def assess_project(self, engine, row, *, active, remote=False):
        decision, reason = "proceed", "Explicit local project request; current sources and brief verified."
        try:
            if remote or not active():
                raise ValueError("The project action is not owned by an active local request.")
            with engine.workspace._db() as conn:
                engine._validate_source(conn, row)
        except (ValueError, OSError) as error:
            decision, reason = "refuse", str(error)
        if not config.COGNITION_ENABLED:
            if decision != "proceed":
                raise ValueError(reason)
            return
        payload = row["payload"]
        sources = {"project": {"kind": "project", "name": payload["project"]["name"],
                               "identity": fingerprint(payload["project"])}}
        sources.update({f"task:{t['id']}": {"kind": "task", **t} for t in payload.get("tasks", [])})
        sources.update({f"deadline:{i}": {"kind": "deadline", **d} for i, d in enumerate(payload.get("deadlines", []))})
        situation = self.capture(intention="open_registered_project_folder", known=sources,
                                 attention={**attention_state(), "channel": "local"})
        expected = "Verified brief plus an independently observed Explorer folder; source task progress unchanged."
        with self._db() as conn:
            conn.execute("INSERT INTO executive_decisions(execution_id,situation_id,decision,reason,expected,created) VALUES(?,?,?,?,?,?)",
                         (row["id"], situation["id"], decision, reason, expected, time.time()))
            conn.execute("DELETE FROM executive_decisions WHERE id NOT IN (SELECT id FROM executive_decisions ORDER BY id DESC LIMIT 200)")
        if decision != "proceed":
            raise ValueError(reason)
        logger.debug("Executive assessment: execution=%s decision=%s", row["id"], decision)

    def outcome(self, row):
        if not config.COGNITION_ENABLED:
            return
        receipt = execution_evidence(self.store).get(f"execution:{row['id']}", {})
        state = receipt.get("effect_status", row["state"])
        with self._db() as conn:
            conn.execute("INSERT INTO executive_outcomes VALUES(?,?,?,?) ON CONFLICT(execution_id) DO UPDATE SET "
                         "state=excluded.state,verified=excluded.verified,updated=excluded.updated",
                         (row["id"], state, int(bool(row.get("verified"))), time.time()))
            conn.execute("DELETE FROM executive_outcomes WHERE execution_id NOT IN (SELECT execution_id FROM executive_outcomes ORDER BY updated DESC LIMIT 200)")

    def describe(self, *, why=False):
        status = self.status()
        text = (f"Executive background review: {'on' if status['enabled'] else 'off'}. "
                f"Reviews this hour: {status['reviews_this_hour']}/{HOURLY_LIMIT}; minimum gap: 5 minutes. "
                f"Last review: {status['last_review']}. Project pre-action checks remain local.")
        with self._db() as conn:
            row = conn.execute("SELECT * FROM executive_decisions ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                outcome = conn.execute("SELECT * FROM executive_outcomes WHERE execution_id=?", (row["execution_id"],)).fetchone()
                text += f" Last assessment: {row['decision']}. {row['reason']} Expected: {row['expected']}"
                if outcome:
                    text += f" Recorded outcome: {outcome['state']}; verified: {bool(outcome['verified'])}."
                if why:
                    source = conn.execute("SELECT body FROM executive_situations WHERE id=?", (row["situation_id"],)).fetchone()
                    if source:
                        text += " Source versions: " + ", ".join(f"{k}={v[:12]}" for k, v in json.loads(source[0])["versions"].items())
            elif why:
                text += " No project action assessment has been recorded yet."
        return text


executive = ExecutiveControl(cognition)
