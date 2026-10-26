"""Explicit owner controls for goals and task progress, with no model writes."""

import re
import sqlite3

from core.logger import logger
from services.automation.results import ActionResult
from services.automation.command_words import normalize_command, strip_leading_filler
from services.mind.cognition import redact
from services.mind.workspace import workspace

PATTERNS = {
    "clear": r"clear my goals and tasks",
    "goals": r"(?:show|list) my goals",
    "tasks": r"(?:show|list) my tasks|task progress",
    "add_goal": r"add goal(?: (?P<priority>low|normal|high))?\s*:\s*(?P<title>.+)",
    "goal_state": r"(?P<state>pause|resume|complete|cancel) goal (?P<reference>.+)",
    "priority": r"set goal (?P<reference>.+?) priority (?P<priority>low|normal|high)",
    "start_task": r"start task(?: for goal (?P<goal>.+?))?\s*:\s*(?P<title>.+)",
    "plan": r"plan task (?P<reference>.+?)\s*:\s*(?P<steps>.+)",
    "step": r"finish task step (?P<reference>.+?)\s*:\s*(?P<evidence>.+)",
    "task_state": r"(?P<state>pause|resume|cancel|block|complete) (?:task (?P<reference>[^:]+?)|(?P<alias>(?:my |the )?(?:current|this|that) task))(?:\s*:\s*(?P<note>.+))?",
}
STATES = {"pause": "paused", "resume": "active", "cancel": "cancelled", "block": "blocked", "complete": "completed"}


def match_command(text):
    # Anchor explicit commands; quoted examples, hypothetical statements and
    # typing/clipboard payloads are not goal declarations.
    stem, separator, payload = text.strip().partition(":")
    # Preserve a task/goal name ending in Friday; ordinary normalization treats it as a wake-name suffix.
    for normalized in (strip_leading_filler(stem).strip().rstrip(".!?"), normalize_command(stem)):
        for action, pattern in PATTERNS.items():
            if match := re.fullmatch(pattern, (normalized + separator + payload).strip(), re.I):
                return {"action": action, **match.groupdict()}
    return None


def run(parsed, *, remote=False):
    try:
        action = parsed["action"]
        ident, selected = None, None
        scope = "remote" if remote else "local"
        kind = "goal" if action in {"goal_state", "priority", "add_goal"} else "task"
        if action in {"goal_state", "priority", "plan", "step", "task_state"}:
            reference = parsed.get("reference") or parsed.get("alias") or parsed.get("id") or "current"
            if "id" in parsed:
                reference = parsed["id"]
            selected = workspace.resolve(kind, reference, scope=scope)
            ident = selected["id"]
        if action == "clear":
            workspace.clear()
            text = "Cleared saved goals and tasks."
        elif action == "goals":
            rows = workspace.goals(include_finished=True)
            text = "\n".join(f"{g['title']} (priority {g['priority']}/3, {g['status']})" for g in rows) or "No saved goals. Use add goal high: <objective>."
        elif action == "tasks":
            rows = workspace.tasks(include_finished=True)
            lines = []
            for task in rows:
                step = task["steps"][task["cursor"]] if task["cursor"] < len(task["steps"]) else "none"
                lines.append(f"{task['title']} ({task['status']}, {task['cursor']}/{len(task['steps'])} steps)\n"
                             f"Next: {step}." + (f" Blocked: {task['blocker']}." if task["blocker"] else ""))
            text = "\n".join(lines) or "No saved tasks. Use start task: <work>."
        elif action == "add_goal":
            ident = workspace.add_goal(parsed["title"], (parsed.get("priority") or "normal").lower())
            text = f"Saved goal \"{parsed['title']}\". You can refer to it by name."
        elif action == "goal_state":
            workspace.goal_state(ident, STATES[parsed["state"].lower()])
            text = f"Updated goal \"{selected['title']}\". Linked task states are tracked separately."
        elif action == "priority":
            workspace.goal_state(ident, priority=parsed["priority"].lower())
            text = f"Updated priority for \"{selected['title']}\"."
        elif action == "start_task":
            goal = workspace.resolve("goal", parsed["goal"], scope=scope) if parsed.get("goal") else None
            ident = workspace.start_task(parsed["title"], goal["id"] if goal else None)
            if goal:
                workspace.focus("goal", goal["id"], scope=scope)
            text = f"Tracking \"{parsed['title']}\" as your current task. Set its steps with plan task current: step one; step two."
        elif action == "plan":
            workspace.plan(ident, parsed["steps"].split(";"))
            text = f"Saved plan for \"{selected['title']}\". Steps stay pending until completion is reported."
        elif action == "step":
            workspace.advance(ident, parsed["evidence"])
            text = f"Saved your completion evidence for \"{selected['title']}\" (owner report)."
        else:
            workspace.task_state(ident, STATES[parsed["state"].lower()], parsed.get("note") or "")
            text = f"Updated task \"{selected['title']}\"." + (" Completion recorded as your report." if parsed["state"].lower() == "complete" else "")
        if ident is not None:
            workspace.focus(kind, ident, scope=scope)
        return ActionResult(True, redact(text), repeatable=False)
    except ValueError as error:
        return ActionResult(False, str(error), repeatable=False)
    except (OSError, sqlite3.Error) as error:
        logger.warning("Workspace command unavailable: %s", type(error).__name__)
        return ActionResult(False, "The goal/task store is unavailable. Nothing was confirmed saved.", repeatable=False)
