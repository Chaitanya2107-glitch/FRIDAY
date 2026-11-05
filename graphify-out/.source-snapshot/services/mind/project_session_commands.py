"""Replies for project briefs. Private source text stays in the local artifact."""

import sqlite3

from core.logger import logger
from services.automation.results import ActionResult
from services.mind import project_session
from services.mind import project_session_context as continuity


def run_session(parsed, *, remote=False):
    if remote:
        return ActionResult(False, "Project work sessions contain local context. Ask me at the laptop.", repeatable=False)
    try:
        engine, action = project_session.sessions, parsed["action"]
        if action == "prepare":
            ident = engine.create(parsed["reference"])
            continuity.activate(engine, ident)
            row = engine.run(ident)
        elif action == "revise":
            ident = continuity.revise(engine, parsed)
            if isinstance(ident, ActionResult):
                return ident
            row = engine.run(ident)
        else:
            selected = engine.workspace.resolve("project_session", parsed["reference"])
            ident = selected["id"]
            continuity.activate(engine, ident)
            if action == "resume":
                row = engine.run(ident, resume=True)
            elif action == "cancel":
                row = engine.cancel(ident)
            else:
                row = engine.get(ident)
        return describe(engine, row, action)
    except (ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Project-session command unavailable: %s", type(error).__name__)
        text = str(error) if isinstance(error, ValueError) else "The local work-session store is unavailable. Completion was not verified."
        return ActionResult(False, text, repeatable=False)


def describe(engine, row, action):
    text = (f"Project work session for \"{row['payload']['project']['name']}\": "
            f"{row['state']} ({row['cursor']}/{len(engine.phases)} checkpoints).")
    if row["verified"]:
        text += f" Verified brief: {row['artifact']}"
    elif row["state"] == "completed":
        text += " The brief is missing or changed; it is not currently verified."
    if row["error"]:
        text += " " + row["error"]
    if row["state"] in {"pending", "blocked"}:
        text += " Say 'resume my work session' to retry."
    success = row["verified"] or (action in {"status", "cancel"} and row["state"] in {"pending", "cancelled"})
    return ActionResult(success, text, memory_message=f"Local project work session: {row['state']}.", repeatable=False)
