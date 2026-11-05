"""Short, laptop-only reference context; no text is learned as a reusable command."""

import json
import re
import sqlite3
import time
import uuid

from core.logger import logger
from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.mind.lessons import key

TTL_SECONDS = 15 * 60


def read(conn):
    row = conn.execute("SELECT * FROM workspace_brief_context WHERE scope='local'").fetchone()
    if row is None or row["expires"] <= time.time():
        return None
    return {**dict(row), "pending": json.loads(row["pending"])}


def require(conn, expected):
    current = read(conn)
    if not current or current["token"] != expected["token"]:
        raise ValueError("The current brief context changed or expired. Check your work session before changing it.")


def remember(conn, ident, pending=None):
    conn.execute("INSERT INTO workspace_brief_context(scope,target,expires,token,pending) VALUES('local',?,?,?,?) "
                 "ON CONFLICT(scope) DO UPDATE SET target=excluded.target,expires=excluded.expires,"
                 "token=excluded.token,pending=excluded.pending",
                 (ident, time.time() + TTL_SECONDS, uuid.uuid4().hex, json.dumps(pending or {})))
    conn.execute("INSERT INTO workspace_focus(scope,kind,target) VALUES('local','project_session',?) "
                 "ON CONFLICT(scope,kind) DO UPDATE SET target=excluded.target", (ident,))


def activate(engine, ident):
    with engine.workspace._db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        engine._row(conn, ident)
        remember(conn, ident)


def clear():
    from services.mind.project_session import sessions
    with sessions.workspace._db() as conn:
        conn.execute("DELETE FROM workspace_brief_context WHERE scope='local'")


def answer_candidates(text, pending):
    candidates = pending.get("candidates", [])
    if not candidates:
        return []
    raw = strip_leading_filler(text).strip().rstrip(".!?")
    literal = len(raw) > 1 and raw[0] in "\"'" and raw[-1] == raw[0]
    query = key(raw.strip("\"'"))
    exact = [item for item in candidates if key(item["name"]) == query]
    if exact or literal:
        return exact
    index = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
    ordinal = re.fullmatch(r"(?:the )?(first|second|third|fourth|fifth)(?: one| project)?", query)
    if ordinal and index[ordinal[1]] < min(len(candidates), 5):
        return [candidates[index[ordinal[1]]]]
    terms = set(re.sub(r"^(?:the|my) ", "", query).split()) - {"one", "project"}
    return [item for item in candidates if terms and terms <= set(key(item["name"]).split())]


def observe(text, *, remote=False):
    """Classify before search/learning; unrelated local turns retire short references."""
    from services.mind.execution_commands import match_command
    parsed = match_command(text)
    if parsed and parsed.get("workflow") == "project_session":
        return True
    if remote:
        return False
    from services.mind.project_session import sessions
    try:
        with sessions.workspace._db() as conn:
            context = read(conn)
            if context and answer_candidates(text, context["pending"]):
                return True
            if context:
                conn.execute("DELETE FROM workspace_brief_context WHERE scope='local' AND token=?", (context["token"],))
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Brief reference context unavailable: %s", type(error).__name__)
    return False


def current(engine):
    with engine.workspace._db() as conn:
        context = read(conn)
    if context is None:
        raise ValueError("No current brief context. Say 'check my work session' or prepare a project work session first.")
    return context


def revise(engine, parsed):
    from services.mind.project_session import AmbiguousProject
    context = current(engine)
    try:
        return engine.revise(context, reference=parsed.get("reference"), include_notes=parsed.get("include_notes"))
    except AmbiguousProject as error:
        with engine.workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require(conn, context)
            remember(conn, context["target"], {"candidates": error.candidates})
        message = str(error).replace("Repeat the request with its full name.", "Reply with its full name or an offered ordinal.")
        return ActionResult(False, message, memory_message="Local brief change needs a specific project.", repeatable=False)


def try_answer(text, *, remote=False):
    if remote:
        return None
    from services.mind.project_session import sessions
    from services.mind.project_session_commands import describe
    try:
        with sessions.workspace._db() as conn:
            context = read(conn)
        if not context:
            return None
        matches = answer_candidates(text, context["pending"])
        if not matches:
            return None
        if len(matches) != 1:
            return ActionResult(False, "Which project? Reply with its full saved name.",
                                memory_message="Local brief project choice is still ambiguous.", repeatable=False)
        chosen = matches[0]
        # Re-check the choice's identity; a saved name moved to another folder needs a fresh request.
        ident = sessions.revise(context, reference='"' + chosen["name"] + '"', expected_project=chosen)
        return describe(sessions, sessions.run(ident), "revise")
    except (ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Brief clarification unavailable: %s", type(error).__name__)
        message = str(error) if isinstance(error, ValueError) else "Local brief context is unavailable. Completion was not verified."
        return ActionResult(False, message, memory_message="Local brief clarification could not be applied.", repeatable=False)
