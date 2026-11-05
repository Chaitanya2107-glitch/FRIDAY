"""Local project briefs: bounded file metadata, saved context and verified publication."""

import json
import os
import re
import stat
import time
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

from core.config import config
from core.logger import logger
from services.activity import projects
from services.mind.execution import ExecutionEngine
from services.mind.lessons import key, keywords
from services.mind.workspace import workspace

SKIP_DIRS = {"node_modules", "venv", ".venv", "__pycache__", "dist", "build", "logs", "memory", "vendor"}
MAX_ENTRIES, MAX_FILES, MAX_DEPTH = 500, 100, 2


class AmbiguousProject(ValueError):
    def __init__(self, names, saved):
        self.candidates = [{"name": name, "path": str(Path(saved[name]["path"]).resolve())} for name in names]
        super().__init__("Which project do you mean? " + ", ".join(f'"{name}"' for name in names[:5]) +
                         ". Repeat the request with its full name.")


def saved_projects():
    if not projects.path.exists():
        return {}
    if projects.path.stat().st_size > 1_000_000:
        raise ValueError("The saved project catalog is too large to read for a work session.")
    try:
        data = json.loads(projects.path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError("The saved project catalog is unreadable. Repair it before preparing a session.") from error
    if not isinstance(data, dict) or any(not isinstance(info, dict) or not isinstance(info.get("path"), str)
                                         for info in data.values()):
        raise ValueError("The saved project catalog is invalid. Repair it before preparing a session.")
    return data


def select_project(reference, *, current=None):
    saved = saved_projects()
    if not saved:
        raise ValueError('No saved projects yet. Open its folder and say "this is a project" first.')
    raw = str(reference).strip()
    literal = len(raw) > 1 and raw[0] in "\"'" and raw[-1] == raw[0]
    query = key(raw.strip("\"'"))
    matches = [name for name in saved if key(name) == query]
    if not matches and not literal:
        query = key(re.sub(r"^(?:my|the) ", "", raw, flags=re.I))
        if query in {"other project", "other"} and current:
            matches = [name for name in saved if name != current["name"]]
        elif query in {"current", "current project", "project", "this project", "my project"}:
            matches = list(saved)
        else:
            terms = set(query.split())
            matches = [name for name in saved if terms and terms <= set(key(name).split())]
            if not matches and query.endswith(" project"):
                terms.discard("project")
                matches = [name for name in saved if terms and terms <= set(key(name).split())]
    if len(matches) != 1:
        if not matches:
            raise ValueError("I couldn't find that saved project. Say its saved name.")
        raise AmbiguousProject(matches, saved)
    name = matches[0]
    folder = Path(saved[name]["path"])
    if not folder.is_absolute() or folder.is_symlink() or folder.is_junction() or not folder.is_dir():
        raise ValueError("The saved project folder is missing or is a link. Save its actual folder again.")
    return {"name": name, "path": str(folder.resolve())}


def linked_tasks(conn, name):
    # Match the complete project name, excluding generic labels, against task or linked goal titles.
    terms = keywords(name) - {"project", "work"}
    rows = conn.execute("SELECT t.*,g.title AS goal FROM workspace_tasks t LEFT JOIN workspace_goals g "
                        "ON g.id=t.goal_id WHERE t.status IN ('active','blocked','paused') ORDER BY t.id").fetchall()
    result = []
    for row in rows:
        if terms and terms <= keywords(row["title"] + " " + (row["goal"] or "")):
            task = dict(row)
            task["steps"], task["evidence"] = json.loads(task["steps"]), json.loads(task["evidence"])
            result.append(task)
    if len(result) > 100:
        raise ValueError("This project has more than 100 matching tasks. Narrow its saved project name first.")
    return result


def file_stamp(root, relative):
    target = root / relative
    if not target.resolve().is_relative_to(root) or any(
            p.is_symlink() or p.is_junction() for p in (target, *target.parents) if p != root and p.is_relative_to(root)):
        raise ValueError("A captured project file became a link. Prepare a new work session.")
    info = target.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("A captured project file is no longer a regular file. Prepare a new work session.")
    return {"path": relative, "size": info.st_size, "mtime_ns": info.st_mtime_ns}


class ProjectSessionEngine(ExecutionEngine):
    workflow = "project_session"
    phases = ("Capture project and tasks", "Inventory project files", "Collect related notes", "Publish and verify brief")

    def _insert(self, conn, project, *, include_notes=True, supersedes=None):
        stamp = time.time()
        payload = {"workflow": self.workflow, "project": project, "include_notes": include_notes}
        if supersedes is not None:
            payload["supersedes"] = supersedes
        # Project executions have no source task; 0 is outside the workspace's task IDs.
        return conn.execute("INSERT INTO workspace_executions(task_id,payload,created,updated) VALUES(0,?,?,?)",
                            (json.dumps(payload), stamp, stamp)).lastrowid

    def create(self, reference):
        project = select_project(reference)
        with self.workspace._db() as conn:
            ident = self._insert(conn, project)
        logger.debug("Created project-session execution %s", ident)
        return ident

    def revise(self, context, *, reference=None, include_notes=None, expected_project=None):
        from services.mind import project_session_context as continuity
        with self.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            continuity.require(conn, context)
            previous = self._row(conn, context["target"])
            if previous["state"] == "cancelled":
                raise ValueError("That work session was cancelled. Prepare a new work session explicitly.")
            old = previous["payload"]
            project = select_project(reference if reference is not None else '"' + old["project"]["name"] + '"',
                                     current=old["project"])
            if (reference is None and project != old["project"]) or (expected_project and project != expected_project):
                raise ValueError("The registered project changed. Prepare a work session with its explicit saved name.")
            preference = old.get("include_notes", True) if include_notes is None else include_notes
            ident = self._insert(conn, project, include_notes=preference, supersedes=previous["id"])
            if previous["state"] in {"pending", "blocked"}:
                conn.execute("UPDATE workspace_executions SET state='cancelled',error=?,updated=? WHERE id=?",
                             ("Superseded by revised instructions.", time.time(), previous["id"]))
            continuity.remember(conn, ident)
        logger.debug("Project-session execution %s supersedes %s", ident, previous["id"])
        return ident

    def _snapshot(self, conn, row):
        from services.proactive.deadline_changes import related
        name = row["payload"]["project"]["name"]
        tasks = linked_tasks(conn, name)
        return {"tasks": tasks, "deadlines": related([name, *[t["title"] for t in tasks]])}

    def _validate_source(self, conn, row):
        payload = row["payload"]
        project = payload["project"]
        if select_project('"' + project["name"] + '"') != project:
            raise ValueError("The saved project changed. Prepare a new work session.")
        if "tasks" in payload and linked_tasks(conn, project["name"]) != payload["tasks"]:
            raise ValueError("The project tasks changed. Prepare a new work session for the current context.")
        if "deadlines" in payload:
            from services.proactive.deadline_changes import related
            if related([project["name"], *[t["title"] for t in payload["tasks"]]]) != payload["deadlines"]:
                raise ValueError("A matching deadline changed. Prepare a new work session with current dates.")
        root = Path(project["path"])
        for item in payload.get("files", []):
            if file_stamp(root, item["path"]) != item:
                raise ValueError("A captured project file changed. Prepare a new work session.")

    def _inventory(self, root):
        pending, files, inspected, limited = [(root, 0)], [], 0, False
        # ponytail: shallow metadata inventory, 500 entries/100 files; use the file index for broader discovery.
        while pending and inspected < MAX_ENTRIES and len(files) < MAX_FILES:
            folder, depth = pending.pop(0)
            if folder.is_symlink() or folder.is_junction() or not folder.resolve().is_relative_to(root):
                raise ValueError("A project directory became a link. Prepare a new work session.")
            with os.scandir(folder) as scan:
                entries = list(islice(scan, MAX_ENTRIES - inspected + 1))
            for entry in sorted(entries, key=lambda item: item.name.lower()):
                inspected += 1
                if inspected > MAX_ENTRIES or len(files) >= MAX_FILES:
                    limited = True
                    break
                path = Path(entry.path)
                if entry.name.startswith(".") or entry.is_symlink() or path.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in SKIP_DIRS and path.resolve() != self.output_dir.resolve():
                        if depth < MAX_DEPTH:
                            pending.append((path, depth + 1))
                        else:
                            limited = True
                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() not in {".pem", ".key", ".pfx"}:
                    files.append(file_stamp(root, path.relative_to(root).as_posix()))
        return {"files": files, "inventory_limited": limited or bool(pending)}

    def _checkpoint(self, conn, row):
        payload, phase = row["payload"], row["cursor"]
        if phase == 0:
            payload.update(self._snapshot(conn, row))
        elif phase == 1:
            payload.update(self._inventory(Path(payload["project"]["path"])))
        elif phase == 2:
            terms = keywords(payload["project"]["name"]) - {"project", "work"}
            payload["notes"] = ([note for note in self._read_notes() if terms and terms <= keywords(note["text"])]
                                if payload.get("include_notes", True) else [])
        elif phase == 3:
            row["artifact"], row["digest"] = self._publish(row)
        else:
            raise ValueError("This work-session checkpoint is invalid.")

    @staticmethod
    def _render(row):
        p = row["payload"]
        lines = [f"# Project work session: {p['project']['name']}", "",
                 f"Snapshot: {datetime.fromtimestamp(row['created'], timezone.utc).isoformat()}",
                 f"Project folder: {p['project']['path']}", "", "## Saved tasks and blockers", "",
                 "Matches use project-name words in task/goal titles; relevance is not inferred."]
        for task in p["tasks"]:
            lines += ["", f"### {task['title']} ({task['status']})"]
            if task["goal"]:
                lines.append(f"Linked goal: {task['goal']}")
            if task["blocker"]:
                lines.append(f"Owner-reported blocker: {task['blocker']}")
            lines += [f"- [{'x' if i < task['cursor'] else ' '}] {step}" for i, step in enumerate(task["steps"])]
            lines += [f"- Reported evidence ({e.get('source', 'owner_report')}): {e.get('text', '')}"
                      for e in task["evidence"]]
        if not p["tasks"]:
            lines += ["", "No matching active, paused or blocked saved tasks."]
        lines += ["", "## Current matching deadlines (owner reported)", ""]
        lines += [f"- {d['what']} — {d['due']}" for d in p.get("deadlines", [])] or ["No matching deadlines."]
        lines += ["", "## Project file inventory", "",
                  f"Metadata only; depth <= {MAX_DEPTH}, <= {MAX_FILES} files, <= {MAX_ENTRIES} inspected entries.",
                  "Hidden files, credential key files, links and generated/storage folders are excluded.",
                  "Inventory truncated: " + ("yes" if p["inventory_limited"] else "no")]
        lines += [f"- {item['path']} ({item['size']} bytes; mtime_ns={item['mtime_ns']})" for item in p["files"]]
        lines += ["", "## Related saved notes (project-name keyword matches)", ""]
        if not p.get("include_notes", True):
            lines += ["Saved notes excluded by owner instruction."]
        else:
            lines += [f"- {note['at']}: {note['text']}" for note in p["notes"]] or ["No matching saved notes."]
        lines += ["", "This brief is a dated snapshot. File contents were not read; task progress was not changed.",
                  "Publication is verified by readback. File metadata is rechecked, not file-content integrity.", ""]
        return "\n".join(lines).encode("utf-8")


sessions = ProjectSessionEngine(workspace, config.MEMORY_DIR / "project-sessions")
