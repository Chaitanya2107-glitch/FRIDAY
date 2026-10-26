"""Local handoff corrections and saved clarification choices; no model access."""

import json
import re
import sqlite3
import time

from core.logger import logger
from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.mind import execution, reference_context as context
from services.mind.workspace import AmbiguousReference


def read(engine):
    with engine.workspace._db() as conn:
        return context.read(conn, "handoff")


def correction(text):
    raw = strip_leading_filler(text).strip().rstrip(".!?")
    match = re.fullmatch(r"(?:actually|no)[, ]+(?:use|switch to) (.+?)(?: instead)?", raw, re.I)
    return match[1] if match else None


def match_turn(text, *, remote=False):
    from services.mind.execution_commands import match_command
    parsed = match_command(text)
    if parsed and parsed.get("workflow", "handoff") == "handoff":
        return parsed
    if remote:
        return None
    if parsed and parsed.get("change") != "project":
        return None
    saved = read(execution.executions)
    if not saved:
        return None
    if reference := correction(text):
        return {"action": "revise", "reference": reference, "context": saved}
    pending = saved["payload"].get("pending")
    if pending:
        choices = context.choices(text, [item["title"] for item in pending["candidates"]])
        ordinal = re.fullmatch(r"(?:the )?(?:\d+|first|second|third|fourth|fifth|last)(?: one| task)?",
                               strip_leading_filler(text).strip().rstrip(".!?"), re.I)
        if choices or ordinal:
            return {"action": pending["action"], "reference": None, "context": saved,
                    "choices": [pending["candidates"][i] for i in choices]}
    return None


def create(engine, selected, saved=None, *, revise=False):
    """Source identity, supersession and context replacement share the insert transaction."""
    with engine.workspace._db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if saved:
            context.require(conn, saved)
        task = engine.workspace._task(conn, selected["id"])
        if any(task[field] != selected[field] for field in ("title", "updated")):
            raise ValueError("That task changed. Prepare the handoff again with its saved name.")
        payload = {"task_version": task["updated"]}
        if revise:
            prior = engine._row(conn, saved["payload"]["target"])
            if prior["state"] == "cancelled":
                raise ValueError("That handoff was cancelled. Prepare a new handoff explicitly.")
            payload["supersedes"] = prior["id"]
            if prior["state"] in {"pending", "blocked"}:
                conn.execute("UPDATE workspace_executions SET state='cancelled',updated=? WHERE id=?", (time.time(), prior["id"]))
        stamp = time.time()
        ident = conn.execute("INSERT INTO workspace_executions(task_id,payload,created,updated) VALUES(?,?,?,?)",
                             (task["id"], json.dumps(payload), stamp, stamp)).lastrowid
        token = context.remember(conn, "handoff", {"target": ident})
    logger.debug("Created contextual handoff %s (revision=%s)", ident, revise)
    return ident, token


def run(parsed, *, remote=False):
    if remote:
        return ActionResult(False, "Task handoffs contain local notes. Ask me at the laptop.", repeatable=False)
    engine, action = execution.executions, parsed["action"]
    saved = parsed.get("context")
    try:
        kind = "task" if action in {"prepare", "revise"} else "execution"
        if action == "revise" and (not saved or not saved["payload"].get("target")):
            raise ValueError("No current handoff context. Check or prepare the handoff first.")
        if "choices" in parsed:
            if len(parsed["choices"]) != 1:
                return ActionResult(False, "Which task? Reply with an offered number or a unique saved name.", repeatable=False)
            selected = parsed["choices"][0]
            with engine.workspace._db() as conn:
                context.require(conn, saved)
                current = next((r for r in engine.workspace._references(conn, kind) if r["id"] == selected["id"]), None)
            if current is None or any(current[k] != selected[k] for k in ("title", "updated")):
                raise ValueError("That offered choice changed. Repeat the handoff request with its saved name.")
        else:
            selected = engine.workspace.resolve(kind, parsed.get("reference", parsed.get("id", "current")))
        ident = selected["id"]
        if action in {"prepare", "revise"}:
            ident, turn_token = create(engine, selected, saved, revise=action == "revise")
            row = engine.run(ident)
        else:
            with engine.workspace._db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if saved:
                    context.require(conn, saved)
                turn_token = context.remember(conn, "handoff", {"target": ident})
            if action == "resume":
                row = engine.run(ident, resume=True)
            elif action == "cancel":
                row = engine.cancel(ident)
            else:
                row = engine.get(ident)
        with engine.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = context.read(conn, "handoff")
            if current and current["token"] == turn_token:
                for kind, target in (("task", row["task_id"]), ("execution", ident)):
                    conn.execute("INSERT INTO workspace_focus VALUES('local',?,?) "
                                 "ON CONFLICT(scope,kind) DO UPDATE SET target=excluded.target", (kind, target))
                context.remember(conn, "handoff", {"target": ident})
        return describe(selected["title"], row, action)
    except AmbiguousReference as error:
        try:
            with engine.workspace._db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if saved:
                    context.require(conn, saved)
                payload = dict(saved["payload"]) if saved else {}
                payload["pending"] = {"action": action, "candidates": error.candidates}
                context.remember(conn, "handoff", payload)
        except (ValueError, OSError, sqlite3.Error):
            return ActionResult(False, "The handoff reference changed or is unavailable. Repeat the request with its name.", repeatable=False)
        shown = "; ".join(f'{i}. {r["title"]}' for i, r in enumerate(error.candidates, 1))
        return ActionResult(False, f"Which {kind}? {shown}. Reply with its full name or an offered number.",
                            memory_message="Local handoff needs a specific saved choice.", repeatable=False)
    except (ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Handoff reference unavailable: %s", type(error).__name__)
        message = str(error) if isinstance(error, ValueError) else "The local execution store is unavailable. Completion was not verified."
        return ActionResult(False, message, repeatable=False)


def describe(title, row, action):
    text = f'Handoff for "{title}": {row["state"]} ({row["cursor"]}/3 checkpoints).'
    if row["verified"]:
        text += f" Verified handoff: {row['artifact']}"
    elif row["state"] == "completed":
        text += " The output is missing or changed; it is not currently verified."
    if row["error"]:
        text += " " + row["error"]
    if row["state"] in {"pending", "blocked"}:
        text += " Say 'resume the handoff' to retry."
    success = row["verified"] or (action in {"status", "cancel"} and row["state"] in {"pending", "cancelled"})
    return ActionResult(success, text, memory_message=f'Local handoff for "{title}": {row["state"]}.', repeatable=False)
