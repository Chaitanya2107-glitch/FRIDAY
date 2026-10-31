"""Owner goals and explicit task progress, shared across processes and restarts.

Plans are data, never executable tool calls or permission grants. Completion
evidence here is an owner report; independent tool verification stays with
the executor. No raw requests, screenshots or computer-task text are captured.
"""

import json
import re
import sqlite3
import time
from contextlib import contextmanager

from core.logger import logger
from services.mind.cognition import cognition, redact

PRIORITIES = {"low": 1, "normal": 2, "high": 3}


class AmbiguousReference(ValueError):
    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = candidates[:5]


def _text(value, limit=300):
    value = redact(value.strip())
    if not value or len(value) > limit:
        raise ValueError(f"Use between 1 and {limit} characters.")
    return value


class Workspace:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        # Reuse cognition's path, redaction, transactions and test isolation.
        with self.store._lock, self.store._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                priority INTEGER NOT NULL, status TEXT NOT NULL, updated REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, goal_id INTEGER,
                status TEXT NOT NULL, steps TEXT NOT NULL DEFAULT '[]', cursor INTEGER NOT NULL DEFAULT 0,
                blocker TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', cursor INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '[]',
                artifact TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_execution_claims (
                execution_id INTEGER PRIMARY KEY, token TEXT NOT NULL,
                expires REAL NOT NULL, uncertain INTEGER NOT NULL DEFAULT 0)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_focus (
                scope TEXT NOT NULL, kind TEXT NOT NULL, target INTEGER NOT NULL,
                PRIMARY KEY(scope,kind))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_brief_context (
                scope TEXT PRIMARY KEY, target INTEGER NOT NULL, expires REAL NOT NULL,
                token TEXT NOT NULL, pending TEXT NOT NULL DEFAULT '{}')""")
            conn.execute("""CREATE TABLE IF NOT EXISTS workspace_reference_context (
                scope TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                expires REAL NOT NULL, token TEXT NOT NULL, PRIMARY KEY(scope,kind))""")
            yield conn

    @staticmethod
    def _references(conn, kind):
        if kind == "execution":
            return [dict(row) for row in conn.execute(
                "SELECT e.id,e.task_id,e.task_id AS subject,e.state AS status,e.updated,t.title FROM workspace_executions e "
                "JOIN workspace_tasks t ON t.id=e.task_id ORDER BY e.id DESC")]
        if kind in {"project_session", "project_execution"}:
            result = []
            for row in conn.execute("SELECT id,state,payload FROM workspace_executions WHERE task_id=0 ORDER BY id DESC"):
                payload = json.loads(row["payload"])
                if payload.get("workflow") == kind:
                    project = payload["project"]
                    result.append({"id": row["id"], "status": row["state"], "title": project["name"],
                                   "subject": (project["name"], project["path"])})
            return result
        tables = {"task": "workspace_tasks", "goal": "workspace_goals"}
        if kind not in tables:
            raise ValueError("Unknown reference type.")
        return [dict(row) for row in conn.execute(f"SELECT id,title,status,updated FROM {tables[kind]} ORDER BY id DESC")]

    def focus(self, kind, ident, *, scope="local"):
        with self._db() as conn:
            if not any(row["id"] == ident for row in self._references(conn, kind)):
                raise ValueError("That item is no longer available.")
            conn.execute("INSERT INTO workspace_focus(scope,kind,target) VALUES(?,?,?) "
                         "ON CONFLICT(scope,kind) DO UPDATE SET target=excluded.target", (scope, kind, ident))

    def resolve(self, kind, reference="current", *, scope="local"):
        """Resolve explicit IDs/names, remembered focus, or an explicitly requested latest item."""
        from services.mind.lessons import key

        noun = {"execution": "handoff", "project_session": "work session", "project_execution": "project session"}.get(kind, kind)
        workflow = kind in {"execution", "project_session", "project_execution"}
        raw = str("current" if reference is None or reference == "" else reference).strip()
        literal = len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]
        query = key(raw.strip("\"'"))
        with self._db() as conn:
            rows = self._references(conn, kind)
            focused = conn.execute("SELECT target FROM workspace_focus WHERE scope=? AND kind=?", (scope, kind)).fetchone()
        if not rows:
            raise ValueError(f"No saved {noun}s yet." + (" Start with: start task: <name>." if kind == "task" else ""))
        if raw.isdigit():
            found = next((row for row in rows if row["id"] == int(raw)), None)
            if found:
                return found
            raise ValueError(f"No {noun} with that ID.")
        exact = [row for row in rows if key(row["title"]) == query]
        # A handoff name identifies the latest version for that one task.
        if workflow and exact and len({row["subject"] for row in exact}) == 1:
            return exact[0]
        if len(exact) == 1:
            return exact[0]
        if not literal and not exact:
            query = re.sub(r"^(?:my|the) ", "", query)
            latest = query in {"latest", "last", f"latest {noun}", f"last {noun}"}
            if latest:
                return rows[0]
            latest_named = bool(re.match(r"^(?:latest|last) ", query))
            if latest_named:
                query = query.split(" ", 1)[1]
            if query in {"current", "this", "that", "it", noun, f"current {noun}", f"this {noun}", f"that {noun}"}:
                eligible = rows if workflow else [r for r in rows if r["status"] not in {"completed", "cancelled"}]
                if focused:
                    selected = next((r for r in rows if r["id"] == focused["target"]), None)
                    if selected:
                        return selected
                    raise ValueError(f"Your selected {noun} is no longer available. Say another name.")
                exact = eligible
            else:
                terms = set(query.split())
                exact = [r for r in rows if terms and terms <= set(key(r["title"]).split())]
            if latest_named and exact:
                return exact[0]
            if workflow and exact and len({r["subject"] for r in exact}) == 1:
                # Multiple versions need an explicit project name or latest request; a bare pronoun cannot guess.
                if query not in {"current", "this", "that", "it", noun, f"current {noun}", f"this {noun}", f"that {noun}"}:
                    return exact[0]
            if len(exact) == 1:
                return exact[0]
        if not exact:
            raise ValueError(f"I couldn't find that {noun}. Say its saved name, or ask to show your tasks/goals.")
        names = list(dict.fromkeys(f'"{row["title"]}"' for row in exact))
        raise AmbiguousReference(f"Which {noun} do you mean? " + ", ".join(names[:5]) +
                         (f" and {len(names) - 5} more" if len(names) > 5 else "") +
                         f". Try the request again with the full name, or explicitly request the latest {noun}.", exact)

    def add_goal(self, title, priority="normal"):
        title = _text(title, 160)
        if priority not in PRIORITIES:
            raise ValueError("Priority must be low, normal or high.")
        with self._db() as conn:
            ident = conn.execute("INSERT INTO workspace_goals (title, priority, status, updated) VALUES (?, ?, 'active', ?)",
                                 (title, PRIORITIES[priority], time.time())).lastrowid
        self.store.record("goal", "workspace", f"Owner added goal {ident}")
        return ident

    def goals(self, include_finished=False):
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM workspace_goals " + ("" if include_finished else "WHERE status = 'active' ") +
                                "ORDER BY priority DESC, updated DESC, id DESC LIMIT 100").fetchall()
        return [dict(row) for row in rows]

    def goal_state(self, ident, status=None, priority=None):
        if status is not None and status not in {"active", "paused", "completed", "cancelled"}:
            raise ValueError("Unknown goal status.")
        if priority is not None and priority not in PRIORITIES:
            raise ValueError("Priority must be low, normal or high.")
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM workspace_goals WHERE id = ?", (ident,)).fetchone()
            if row is None:
                raise ValueError("No goal with that ID.")
            conn.execute("UPDATE workspace_goals SET status = ?, priority = ?, updated = ? WHERE id = ?",
                         (status or row["status"], PRIORITIES[priority] if priority else row["priority"], time.time(), ident))
        self.store.record("goal", "workspace", f"Owner updated goal {ident}")

    def start_task(self, title, goal_id=None):
        title = _text(title, 160)
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if goal_id is not None and not conn.execute(
                    "SELECT 1 FROM workspace_goals WHERE id = ? AND status = 'active'", (goal_id,)).fetchone():
                raise ValueError("Choose an active goal ID.")
            ident = conn.execute("INSERT INTO workspace_tasks (title, goal_id, status, updated) VALUES (?, ?, 'active', ?)",
                                 (title, goal_id, time.time())).lastrowid
        self.store.record("task", "workspace", f"Owner started task {ident}")
        return ident

    @staticmethod
    def _task(conn, ident):
        row = conn.execute("SELECT * FROM workspace_tasks WHERE id = ?", (ident,)).fetchone()
        if row is None:
            raise ValueError("No task with that ID.")
        task = dict(row)
        task["steps"], task["evidence"] = json.loads(task["steps"]), json.loads(task["evidence"])
        return task

    def tasks(self, include_finished=False):
        with self._db() as conn:
            rows = conn.execute("SELECT id FROM workspace_tasks " +
                                ("" if include_finished else "WHERE status IN ('active', 'blocked', 'paused') ") +
                                "ORDER BY updated DESC, id DESC LIMIT 100").fetchall()
            return [self._task(conn, row["id"]) for row in rows]

    def plan(self, ident, steps, expected_updated=None):
        if not 1 <= len(steps) <= 20:
            raise ValueError("A plan needs 1 to 20 steps.")
        steps = [_text(step, 200) for step in steps]
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = self._task(conn, ident)
            if expected_updated is not None and task["updated"] != expected_updated:
                raise ValueError("Task changed since this plan was proposed.")
            if task["status"] != "active" or task["cursor"]:
                raise ValueError("Set the plan on an active task before completing steps.")
            conn.execute("UPDATE workspace_tasks SET steps = ?, updated = ? WHERE id = ?",
                         (json.dumps(steps), time.time(), ident))
        self.store.record("task", "workspace", f"Owner planned task {ident}")

    def advance(self, ident, evidence, expected_updated=None):
        evidence = _text(evidence)
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = self._task(conn, ident)
            if expected_updated is not None and task['updated'] != expected_updated:
                raise ValueError('This task changed elsewhere. Refresh before reporting progress.')
            if task["status"] != "active" or task["cursor"] >= len(task["steps"]):
                raise ValueError("No active planned step to finish.")
            task["evidence"].append({"step": task["cursor"], "text": evidence, "source": "owner_report"})
            cursor = task["cursor"] + 1
            status = "completed" if cursor == len(task["steps"]) else "active"
            conn.execute("UPDATE workspace_tasks SET cursor = ?, status = ?, evidence = ?, updated = ? WHERE id = ?",
                         (cursor, status, json.dumps(task["evidence"]), time.time(), ident))
        self.store.record("task", "workspace", f"Owner reported step completion for task {ident}", status="reported")

    def task_state(self, ident, status, note="", expected_updated=None):
        if status not in {"active", "paused", "blocked", "completed", "cancelled"}:
            raise ValueError("Unknown task status.")
        note = _text(note) if note or status in {"blocked", "completed"} else ""
        with self._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = self._task(conn, ident)
            if expected_updated is not None and task['updated'] != expected_updated:
                raise ValueError('This task changed elsewhere. Refresh before updating it.')
            if task["status"] in {"completed", "cancelled"}:
                raise ValueError("That task is finished; start a new task.")
            if status == "completed":
                if task["cursor"] < len(task["steps"]):
                    raise ValueError("Finish each planned step with evidence first, or cancel the task.")
                task["evidence"].append({"text": note, "source": "owner_report"})
            conn.execute("UPDATE workspace_tasks SET status = ?, blocker = ?, evidence = ?, updated = ? WHERE id = ?",
                         (status, note if status == "blocked" else "", json.dumps(task["evidence"]), time.time(), ident))
        self.store.record("task", "workspace", f"Owner set task {ident} to {status}",
                          status="reported" if status == "completed" else "completed")

    def context(self):
        """Small shared attention inputs; full plans/evidence stay in the store."""
        try:
            goals = self.goals()[:5]
            tasks = self.tasks()[:5]
            from services.proactive.deadline_changes import current
            return {"deadlines": current(), "goals": [{"id": g["id"], "title": redact(g["title"]), "priority": g["priority"]} for g in goals],
                    "tasks": [{"id": t["id"], "title": redact(t["title"]), "goal_id": t["goal_id"],
                               "status": t["status"], "done": t["cursor"], "total": len(t["steps"]),
                               "next_step": redact(t["steps"][t["cursor"]]) if t["cursor"] < len(t["steps"]) else "",
                               "blocker": redact(t["blocker"])} for t in tasks]}
        except (OSError, sqlite3.Error, ValueError) as error:
            logger.warning("Task workspace unavailable: %s", type(error).__name__)
            return {"status": "unavailable", "goals": [], "tasks": []}

    def clear(self):
        """Explicit workspace reset; clearing conversation/events preserves goals."""
        with self._db() as conn:
            from services.mind.task_followups import schema
            schema(conn)
            conn.execute("DELETE FROM workspace_followups")
            conn.execute("DELETE FROM workspace_followup_preferences")
            conn.execute("DELETE FROM workspace_reference_context")
            conn.execute("DELETE FROM workspace_brief_context")
            conn.execute("DELETE FROM workspace_focus")
            conn.execute("DELETE FROM workspace_execution_claims")
            conn.execute("DELETE FROM workspace_executions")
            conn.execute("DELETE FROM workspace_tasks")
            conn.execute("DELETE FROM workspace_goals")
            from services.mind.executive import clear_derived
            clear_derived(conn)
        self.store.record("workspace", "workspace", "Owner cleared goals and tasks")


workspace = Workspace(cognition)
