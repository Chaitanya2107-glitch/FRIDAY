"""Owner controls and channel-scoped replies to proactive task suggestions."""

import re
import sqlite3
from datetime import datetime

from core.logger import logger
from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.mind import reference_context, task_followups
from services.mind.workspace import workspace

SHORT_REPLIES = {"not now": "pause", "later": "pause", "stop asking about this": "stop",
                 "stop asking about that": "stop", "show that task": "review", "review it": "review",
                 "why this followup": "why", "why did you suggest that": "why"}


def match_command(text):
    raw = strip_leading_filler(text).strip().rstrip(".!?")
    if re.fullmatch(r"show (?:task followups|proactive task help)|proactive task help", raw, re.I):
        return {"action": "task_followup_status"}
    if m := re.fullmatch(r"(?P<verb>pause|stop|resume) task followups(?: for (?P<reference>.+))?", raw, re.I):
        return {"action": "task_followup_control", "verb": m["verb"].lower(), "reference": m["reference"]}
    if m := re.fullmatch(r"(?P<verb>review|explain|snooze|dismiss) (?:(?:this|that|the) )?task followup", raw, re.I):
        return {"action": "task_followup_response", "verb": {"review": "review", "explain": "why", "snooze": "pause", "dismiss": "stop"}[m["verb"].lower()]}
    return None


def match_turn(text, *, remote=False):
    parsed = match_command(text)
    if parsed and parsed["action"] != "task_followup_response":
        return parsed
    with workspace._db() as db:
        saved = reference_context.read(db, "task_followup", "telegram" if remote else "local")
    if not parsed and saved:
        raw = strip_leading_filler(text).strip().rstrip(".!?").lower()
        if raw in SHORT_REPLIES:
            parsed = {"action": "task_followup_response", "verb": SHORT_REPLIES[raw]}
    if parsed:
        parsed["context"] = saved
    return parsed


def run(parsed, *, remote=False):
    try:
        now = datetime.now()
        if parsed["action"] == "task_followup_status":
            message = task_followups.status(now)
        elif parsed["action"] == "task_followup_control":
            reference = parsed["reference"]
            selected = workspace.resolve("task", reference, scope="remote" if remote else "local") if reference else None
            message = task_followups.control(parsed["verb"], selected["id"] if selected else 0, now)
            if selected:
                message = f'{selected["title"]}: {message}'
        else:
            saved = parsed.get("context")
            scope = "telegram" if remote else "local"
            if not saved or saved["scope"] != scope:
                raise ValueError("No current task followup in this conversation. Ask to show task followups or use a saved task name.")
            message = task_followups.respond(saved["payload"]["token"], parsed["verb"], now, context=saved)
        return ActionResult(True, message, memory_message=message, repeatable=False)
    except (ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Task followup control unavailable: %s", type(error).__name__)
        return ActionResult(False, str(error) if isinstance(error, ValueError) else
                            "Task followups could not be checked. Try again when the workspace is available.", repeatable=False)
