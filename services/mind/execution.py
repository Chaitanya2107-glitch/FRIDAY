"""Checkpointed local workflows, including task handoffs. Task plans are data.

Local phases use short SQLite transactions. External phases use token/lease
claims with execution and observation outside the transaction.
"""

import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.config import config
from core.logger import logger
from services.memory import notes
from services.mind.lessons import keywords
from services.mind.workspace import workspace

PHASES = ("Capture task", "Collect related notes", "Publish and verify handoff")


class ExecutionEngine:
    workflow = "handoff"
    phases = PHASES
    external_phases = frozenset()
    claim_seconds = 60

    def __init__(self, task_workspace, output_dir):
        self.workspace = task_workspace
        self.output_dir = Path(output_dir)

    def _row(self, conn, ident):
        row = conn.execute("SELECT * FROM workspace_executions WHERE id = ?", (ident,)).fetchone()
        if row is None:
            raise ValueError("No execution with that ID.")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["evidence"] = json.loads(result["evidence"])
        if result["payload"].get("workflow", "handoff") != self.workflow:
            raise ValueError("That execution belongs to a different workflow. Use its own status/resume controls.")
        return result

    def create(self, task_id):
        with self.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = self.workspace._task(conn, task_id)
            stamp = time.time()
            ident = conn.execute("INSERT INTO workspace_executions(task_id,payload,created,updated) VALUES(?,?,?,?)",
                                 (task_id, json.dumps({"task_version": task["updated"]}), stamp, stamp)).lastrowid
        logger.debug("Created handoff execution %s for task %s", ident, task_id)
        return ident

    def _target(self, ident):
        root = self.output_dir.resolve()
        target = root / f"execution-{ident}.md"
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("The output path is not a managed local file.")
        return target

    def _verified(self, row):
        if row["state"] != "completed" or not row["digest"]:
            return False
        try:
            target = self._target(row["id"])
            if str(target) != row["artifact"]:
                return False
            with target.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest() == row["digest"]
        except (OSError, ValueError):
            return False

    def get(self, ident):
        with self.workspace._db() as conn:
            row = self._row(conn, ident)
        row["verified"] = self._verified(row)
        return row

    def _snapshot(self, conn, row):
        from services.proactive.deadline_changes import related
        task = self.workspace._task(conn, row["task_id"])
        goal = conn.execute("SELECT title FROM workspace_goals WHERE id = ?", (task["goal_id"],)).fetchone()
        return {"task": task, "goal": goal["title"] if goal else "", "deadlines": related([task["title"]])}

    @staticmethod
    def _read_notes():
        # notes.load() intentionally treats bad JSON as empty; an executor must expose source failure.
        if not notes.path.exists():
            return []
        try:
            rows = json.loads(notes.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ValueError("Saved notes could not be read. Repair the notes file, then resume this execution.") from error
        if not isinstance(rows, list):
            raise ValueError("Saved notes are unreadable; repair them before resuming.")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not isinstance(row.get("at"), str):
                raise ValueError("A saved note has invalid fields; repair it before resuming.")
            try:
                datetime.fromisoformat(row["at"])
            except ValueError as error:
                raise ValueError("A saved note has an invalid date. Repair it before resuming.") from error
        return rows

    @staticmethod
    def _render(row):
        payload = row["payload"]
        task = payload["task"]
        lines = [f"# Task handoff: {task['title']}", "",
                 f"Snapshot created: {datetime.fromtimestamp(row['created'], timezone.utc).isoformat()}",
                 f"Task: {task['id']} | State: {task['status']}",
                 f"Goal: {payload['goal'] or 'No linked goal'}", "", "## Progress", ""]
        lines += [f"- [{'x' if index < task['cursor'] else ' '}] {step}"
                  for index, step in enumerate(task["steps"])] or ["No saved plan."]
        if task["blocker"]:
            lines += ["", f"Blocker: {task['blocker']}"]
        lines += ["", "## Saved completion evidence", ""]
        lines += [f"- {item.get('text', '')} (source: {item.get('source', 'owner_report')})"
                  for item in task["evidence"]] or ["No reported completion evidence."]
        lines += ["", "## Current matching deadlines (owner reported)", ""]
        lines += [f"- {d['what']} — {d['due']}" for d in payload.get("deadlines", [])] or ["No matching deadlines."]
        lines += ["", "## Related saved notes (keyword matches)", ""]
        lines += [f"- {note['at']}: {note['text']}" for note in payload["notes"]] or ["No matching saved notes."]
        lines += ["", "This handoff records a snapshot. Generating it does not complete the source task.", ""]
        return "\n".join(lines).encode("utf-8")

    def _publish(self, row):
        target = self._target(row["id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self._render(row)
        if not target.exists():
            # Same-directory hard link publishes a complete file without overwriting a conflicting path.
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".handoff-", delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                except BaseException:
                    stream.close()
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    pass  # another completed publication is accepted only if its bytes agree
            finally:
                temporary.unlink(missing_ok=True)
        with target.open("rb") as stream:
            matches = stream.read(len(content) + 1) == content
        if not matches:
            raise ValueError("A different file already occupies the output path. It was not overwritten; start again to create a new output.")
        return str(target), hashlib.sha256(content).hexdigest()

    def _validate_source(self, conn, row):
        from services.proactive.deadline_changes import related
        task = self.workspace._task(conn, row["task_id"])
        if task["updated"] != row["payload"]["task_version"]:
            raise ValueError("The task changed after this execution was created. Prepare a new handoff.")
        if "deadlines" in row["payload"] and related([task["title"]]) != row["payload"]["deadlines"]:
            raise ValueError("A matching deadline changed. Prepare a new handoff with current dates.")

    def _checkpoint(self, conn, row):
        phase = row["cursor"]
        if phase == 0:
            row["payload"].update(self._snapshot(conn, row))
        elif phase == 1:
            terms = keywords(row["payload"]["task"]["title"])
            row["payload"]["notes"] = [note for note in self._read_notes() if terms & keywords(note["text"])]
        elif phase == 2:
            row["artifact"], row["digest"] = self._publish(row)
        else:
            raise ValueError("This execution checkpoint is invalid.")

    def step(self, ident):
        if self.get(ident)["cursor"] in self.external_phases:
            return self._external_step(ident)
        with self.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, ident)
            if row["state"] != "pending":
                return {**row, "verified": self._verified(row)}
            self._validate_source(conn, row)
            phase = row["cursor"]
            self._checkpoint(conn, row)
            final = phase == len(self.phases) - 1
            row["evidence"].append({"step": phase, "name": self.phases[phase], "source": "executor", "at": time.time(),
                                    "digest": row["digest"] if final else ""})
            conn.execute("UPDATE workspace_executions SET cursor=?,state=?,payload=?,evidence=?,artifact=?,digest=?,"
                         "error='',updated=? WHERE id=?",
                         (phase + 1, "completed" if final else "pending", json.dumps(row["payload"]),
                          json.dumps(row["evidence"]), row["artifact"], row["digest"], time.time(), ident))
        logger.debug("Execution %s checkpoint %s verified", ident, phase + 1)
        self.workspace.store.record("execution", "executor", f"Execution {ident}: {self.phases[phase]}", status="completed")
        return self.get(ident)

    def _external_step(self, ident):
        """Claim briefly, perform outside SQLite, then accept evidence only for this claim.

        Expired/uncertain claims can observe outcomes but cannot submit another action.
        Cancellation may race an already submitted OS operation; its result cannot revive a job.
        """
        token = uuid.uuid4().hex
        with self.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, ident)
            if row["state"] != "pending" or row["cursor"] not in self.external_phases:
                return {**row, "verified": self._verified(row)}
            self._validate_source(conn, row)
            old = conn.execute("SELECT * FROM workspace_execution_claims WHERE execution_id=?", (ident,)).fetchone()
            if old and not old["uncertain"] and old["expires"] > time.time():
                return {**row, "verified": False}
            recovering = old is not None
            conn.execute("INSERT INTO workspace_execution_claims(execution_id,token,expires,uncertain) VALUES(?,?,?,0) "
                         "ON CONFLICT(execution_id) DO UPDATE SET token=excluded.token,expires=excluded.expires,uncertain=0",
                         (ident, token, time.time() + self.claim_seconds))

        def active():
            with self.workspace._db() as conn:
                return bool(conn.execute(
                    "SELECT 1 FROM workspace_execution_claims c JOIN workspace_executions e ON e.id=c.execution_id "
                    "WHERE e.id=? AND e.state='pending' AND e.cursor=? AND c.token=? AND c.expires>?",
                    (ident, row["cursor"], token, time.time())).fetchone())

        try:
            changes = self._perform_external(row, recovering=recovering, active=active)
            with self.workspace._db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = self._row(conn, ident)
                claim = conn.execute("SELECT * FROM workspace_execution_claims WHERE execution_id=?", (ident,)).fetchone()
                if (current["state"] != "pending" or current["cursor"] != row["cursor"]
                        or not claim or claim["token"] != token or claim["expires"] <= time.time()):
                    return {**current, "verified": self._verified(current)}
                self._validate_source(conn, current)
                current["payload"].update(changes)
                phase = row["cursor"]
                current["evidence"].append({"step": phase, "name": self.phases[phase], "source": "executor",
                                            "at": time.time(), "reconciled": recovering})
                conn.execute("UPDATE workspace_executions SET cursor=?,state=?,payload=?,evidence=?,error='',updated=? WHERE id=?",
                             (phase + 1, "completed" if phase == len(self.phases) - 1 else "pending",
                              json.dumps(current["payload"]), json.dumps(current["evidence"]), time.time(), ident))
                conn.execute("DELETE FROM workspace_execution_claims WHERE execution_id=? AND token=?", (ident, token))
            logger.debug("Execution %s external checkpoint %s verified; reconciled=%s", ident, phase + 1, recovering)
            self.workspace.store.record("execution", "executor", f"Execution {ident}: {self.phases[phase]}", status="completed")
            return self.get(ident)
        except BaseException:
            # Even process interruptions handled by Python leave a reconcilable receipt.
            # A hard process exit leaves the finite lease to expire instead.
            with self.workspace._db() as conn:
                conn.execute("UPDATE workspace_execution_claims SET uncertain=1,expires=0 WHERE execution_id=? AND token=?",
                             (ident, token))
            raise

    def cancel(self, ident):
        with self.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._row(conn, ident)
            if row["state"] == "completed":
                raise ValueError("This execution already completed. Its output is retained.")
            conn.execute("UPDATE workspace_executions SET state='cancelled',updated=? WHERE id=?", (time.time(), ident))
        return self.get(ident)

    def run(self, ident, *, resume=False):
        if resume:
            with self.workspace._db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = self._row(conn, ident)
                if row["state"] == "blocked" or (row["state"] == "completed" and not self._verified(row)):
                    conn.execute("UPDATE workspace_executions SET state='pending',cursor=?,error='',updated=? WHERE id=?",
                    (min(row["cursor"], len(self.phases) - 1), time.time(), ident))
        for _ in self.phases:
            row = self.get(ident)
            if row["state"] != "pending":
                return row
            try:
                cursor = row["cursor"]
                row = self.step(ident)
            except (OSError, ValueError) as error:
                message = str(error) if isinstance(error, ValueError) else f"Local file operation failed ({type(error).__name__})."
                with self.workspace._db() as conn:
                    conn.execute("UPDATE workspace_executions SET state='blocked',error=?,updated=? "
                                 "WHERE id=? AND state='pending'", (message, time.time(), ident))
                logger.warning("Execution %s blocked: %s", ident, type(error).__name__)
                return self.get(ident)
            if row["cursor"] == cursor:
                return row  # another worker owns an external checkpoint; do not spin
        return row


executions = ExecutionEngine(workspace, config.MEMORY_DIR / "handoffs")
