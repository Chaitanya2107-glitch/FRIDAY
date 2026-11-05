"""Explicit laptop-only entry points for checkpointed local workflows."""

import re

from services.automation.command_words import normalize_command, strip_leading_filler

PATTERNS = {
    "prepare": r"prepare (?:a )?task handoff (?P<id>\d+)",
    "status": r"execution status (?P<id>\d+)|show execution (?P<other>\d+)",
    "resume": r"resume execution (?P<id>\d+)",
    "cancel": r"cancel execution (?P<id>\d+)",
}
NATURAL = {
    "prepare": r"(?:prepare|create|make) (?:a |the |my )?(?:task )?handoff(?: for (?P<reference>.+))?",
    "prepare_named": r"prepare (?:a )?task handoff (?P<reference>.+)",
    "status": r"(?:check|show)(?: me)? (?P<handoff>(?:(?:my|the|this|that|current|latest|last) )*handoff)(?: for (?P<reference>.+))?",
    "status_named": r"handoff status(?: for (?P<reference>.+))?",
    "resume": r"resume (?P<handoff>(?:(?:my|the|this|that|current|latest|last) )*handoff)(?: for (?P<reference>.+))?",
    "cancel": r"cancel (?P<handoff>(?:(?:my|the|this|that|current|latest|last) )*handoff)(?: for (?P<reference>.+))?",
}
SESSION = {
    "prepare": r"(?:prepare|create|make) (?:(?:a|the|my) )?(?:project )?work session(?: for (?P<reference>.+))?",
    "status": r"(?:check|show)(?: me)? (?P<session>(?:(?:my|the|this|that|current|latest|last) )*(?:project )?work session)(?: for (?P<reference>.+))?",
    "resume": r"resume (?P<session>(?:(?:my|the|this|that|current|latest|last) )*(?:project )?work session)(?: for (?P<reference>.+))?",
    "cancel": r"cancel (?P<session>(?:(?:my|the|this|that|current|latest|last) )*(?:project )?work session)(?: for (?P<reference>.+))?",
}
BRIEF = r"(?:(?:my|the|this|that|current|latest|last) )*(?:project )?(?:brief|work session)"
PROJECT_EXECUTION = {
    "start": r"(?:start|launch) (?:(?:a|my|the) )?project session for (?P<reference>.+)",
    "status": r"(?:(?:check|show) (?:(?:my|the|current) )?project session|project session status)(?: for (?P<reference>.+))?",
    "resume": r"resume (?:(?:my|the|current) )?project session(?: for (?P<reference>.+))?",
    "cancel": r"cancel (?:(?:my|the|current) )?project session(?: for (?P<reference>.+))?",
}


def _match_followup(text):
    if re.fullmatch(rf"(?:refresh|update|regenerate) {BRIEF}", text, re.I):
        return {"action": "revise", "workflow": "project_session", "change": "refresh"}
    if (re.fullmatch(rf"(?:leave out|exclude|omit) (?:the |my |saved )?notes(?: from {BRIEF})?", text, re.I)
            or re.fullmatch(rf"remove (?:the |my |saved )?notes from {BRIEF}", text, re.I)):
        return {"action": "revise", "workflow": "project_session", "change": "notes", "include_notes": False}
    if re.fullmatch(rf"(?:include|add|restore) (?:the |my |saved )?notes(?: again| back| in {BRIEF})?", text, re.I):
        return {"action": "revise", "workflow": "project_session", "change": "notes", "include_notes": True}
    if match := re.fullmatch(r"(?:actually[, ]+)?(?:use|switch to) (?P<reference>.+? project)(?: instead)?", text, re.I):
        return {"action": "revise", "workflow": "project_session", "change": "project", "reference": match["reference"]}
    return None


def match_command(text):
    original = strip_leading_filler(text).strip().rstrip(".!?")
    for action, pattern in PROJECT_EXECUTION.items():
        if match := re.fullmatch(pattern, original, re.I):
            return {"action": action, "workflow": "project_execution", "reference": match["reference"] or "current"}
    if followup := _match_followup(original):
        return followup
    for action, pattern in SESSION.items():
        if match := re.fullmatch(pattern, original, re.I):
            fields = match.groupdict()
            reference = fields.get("reference")
            if reference is None:
                reference = re.sub(r"\bproject work session\b", "work session",
                                   fields.get("session") or "current project", flags=re.I)
            return {"action": action, "workflow": "project_session", "reference": reference}
    # Names are literal user data; preserve a final "Friday" instead of dropping it as a wake-name suffix.
    for action, pattern in NATURAL.items():
        if match := re.fullmatch(pattern, original, re.I):
            fields = match.groupdict()
            return {"action": action.split("_")[0],
                    "reference": fields.get("reference") or fields.get("handoff") or "current"}
    text = normalize_command(text)
    for action, pattern in PATTERNS.items():
        if match := re.fullmatch(pattern, text, re.I):
            fields = match.groupdict()
            return {"action": action, "id": int(fields.get("id") or fields["other"])}
    return None


def run(parsed, *, remote=False):
    if parsed.get("workflow") == "project_execution":
        from services.mind.project_execution import run_command
        return run_command(parsed, remote=remote)
    if parsed.get("workflow") == "project_session":
        from services.mind.project_session_commands import run_session
        return run_session(parsed, remote=remote)
    from services.mind.handoff_context import run as run_handoff
    return run_handoff(parsed, remote=remote)
