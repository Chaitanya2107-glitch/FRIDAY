"""Explicit deadline corrections, current recall and channel-scoped clarification."""

import re
import sqlite3
import uuid
from datetime import datetime, timedelta

from core.logger import logger
from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.automation.system_control import AutomationError
from services.mind import reference_context as context
from services.mind.lessons import key, keywords
from services.proactive import deadlines

ACTIONS = {"move_deadline", "recall_deadline", "deadline_history", "link_deadline_reminder", "deadline_reminder_updates"}


def complete(row):
    """Retain optional done status, with the same history/link removal as completion."""
    row.update(done=True, revision=uuid.uuid4().hex)
    for field in ('history', 'linked_reminders', 'reminder_updates'):
        row.pop(field, None)


def identity(row):
    return {k: row.get(k) for k in ("id", "what", "due", "revision")}


def match_turn(text, *, remote=False):
    parsed = deadlines.match_deadline_change(strip_leading_filler(text).strip().rstrip(".!?"))
    if parsed and parsed["action"] in ACTIONS:
        try:
            matches = resolve(deadlines.load(), parsed["reference"])
        except AutomationError:
            return parsed
        if len(matches) == 1:
            parsed["expected"] = identity(matches[0])
            if parsed["action"] == "deadline_reminder_updates":
                pending = [p for p in matches[0].get("reminder_updates", [])
                           if p["status"] == "pending" and p["scope"] == ("telegram" if remote else "local")]
                parsed["proposal_id"] = pending[-1]["id"] if pending else None
                if pending:
                    from services.proactive.deadline_reminders import digest
                    parsed["proposal_digest"] = digest(pending[-1])
        return parsed
    from services.mind.workspace import workspace
    scope = "telegram" if remote else "local"
    with workspace._db() as db:
        saved = context.read(db, "deadline", scope)
    if not saved:
        return None
    candidates = saved["payload"]["candidates"]
    indices = context.choices(text, [r["what"] for r in candidates])
    ordinal = re.fullmatch(r"(?:the )?(?:\d+|first|second|third|fourth|fifth|last)(?: one| deadline)?",
                           strip_leading_filler(text).strip().rstrip(".!?"), re.I)
    if indices or ordinal:
        return {**saved["payload"]["request"], "context": saved, "choices": [candidates[i] for i in indices]}
    return None


def resolve(rows, reference):
    query = key(re.sub(r"^(?:the|my) ", "", reference.strip(), flags=re.I).strip("\"'"))
    exact = [r for r in rows if key(r["what"]) == query]
    terms = set(query.split())
    return exact or [r for r in rows if terms and terms <= set(key(r["what"]).split())]


def changed_due(text, old, now):
    iso = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?: at (.+))?", text.strip())
    explicit_clock = bool(re.search(r"\bat\b|\d:\d|\d\s*(?:am|pm)\b|noon|midnight", text, re.I))
    if iso:
        result = datetime.fromisoformat(iso[1])
        clock = deadlines._time(iso[2].lower()) if iso[2] else (old.hour, old.minute)
        if clock is None:
            raise ValueError("Give a valid deadline time.")
        result = result.replace(hour=clock[0], minute=clock[1])
    else:
        result = deadlines.parse_due(text, now)
        if not explicit_clock:
            result = result.replace(hour=old.hour, minute=old.minute)
    return result


def move(row, parsed, now, scope):
    old = datetime.fromisoformat(row["due"])
    if parsed.get("old"):
        expected = changed_due(parsed["old"], old, old.replace(hour=0, minute=0) - timedelta(days=1))
        if expected != old:
            raise ValueError(f'The saved deadline is {row["due"]}, not that old date. Check it before changing it.')
    due = changed_due(parsed["when"], old, now)
    if due <= now:
        raise ValueError("The new deadline is in the past. Give a future date.")
    if due == old:
        return f'{row["what"]} is already due {row["due"]}; no change was made.'
    from services.proactive import deadline_reminders
    deadline_reminders.reconcile(row)
    row.setdefault("history", []).append({"old_due": row["due"], "new_due": due.isoformat(timespec="minutes"),
        "quote": parsed["quote"], "source": "owner_report", "noted": now.isoformat()})
    row["due"], row["revision"] = due.isoformat(timespec="minutes"), uuid.uuid4().hex
    row["alerted"] = [name for name, before in deadlines.STAGES if due - before <= now]
    preview = deadline_reminders.propose(row, scope)
    return f'{row["what"]} is now due {row["due"]}. Previous date retained in deadline history.' + preview


def run(parsed, *, remote=False):
    from services.mind.workspace import workspace
    scope = "telegram" if remote else "local"
    try:
        with deadlines.edit():
            if "context" not in parsed:
                with workspace._db() as db:
                    context.clear(db, "deadline", scope)
            rows = deadlines.load()
            if parsed.get("expected") and not any(identity(r) == parsed["expected"] for r in rows):
                raise ValueError("The deadline changed after this request. Review the current deadline and reminder proposal first.")
            if any("id" not in r for r in rows):
                deadlines._save(rows)
            if "context" in parsed:
                with workspace._db() as db:
                    context.require(db, parsed["context"])
                matches = [r for r in rows if len(parsed["choices"]) == 1 and identity(r) == parsed["choices"][0]]
                if not matches:
                    raise ValueError("That offered deadline changed or is still ambiguous. Repeat the request with its name.")
            else:
                matches = resolve(rows, parsed["reference"])
            if len(matches) > 1:
                offered = [identity(r) for r in matches[:5]]
                with workspace._db() as db:
                    context.remember(db, "deadline", {"request": parsed, "candidates": offered}, scope)
                text = "; ".join(f'{i}. {r["what"]} ({r["due"]})' for i, r in enumerate(offered, 1))
                return ActionResult(False, f"Which deadline? {text}. Reply with its saved name or an offered number.", repeatable=False)
            if not matches:
                raise ValueError("I couldn't find that saved deadline. Ask to list deadlines first.")
            row, action, now = matches[0], parsed["action"], deadlines.datetime.now()
            if "proposal_id" in parsed:
                pending = [p for p in row.get("reminder_updates", []) if p["status"] == "pending" and p["scope"] == scope]
                if (pending[-1]["id"] if pending else None) != parsed["proposal_id"]:
                    raise ValueError("The reminder proposal changed. Review the current proposal before applying it.")
                if pending and parsed.get("proposal_digest"):
                    from services.proactive.deadline_reminders import digest
                    if digest(pending[-1]) != parsed["proposal_digest"]:
                        raise ValueError("The proposed reminder times changed. Review the proposal again.")
            if action == "move_deadline":
                message = move(row, parsed, now, scope)
            elif action == "recall_deadline":
                message = f'{row["what"]} is due {row["due"]} (owner reported).'
            elif action == "deadline_history":
                message = f'Current: {row["what"]} — {row["due"]}.'
                message += "\n" + "\n".join(f'{h["noted"]}: {h["old_due"]} -> {h["new_due"]} (owner report)' for h in row.get("history", []))
            else:
                from services.proactive import deadline_reminders
                message = deadline_reminders.run(row, parsed, now, scope)
            if action not in {"recall_deadline", "deadline_history"}:
                deadlines._save(rows)
            with workspace._db() as db:
                context.clear(db, "deadline", scope)
            return ActionResult(True, message, memory_message=f'Deadline "{row["what"]}": current due {row["due"]}.', repeatable=False)
    except (AutomationError, ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Deadline change unavailable: %s", type(error).__name__)
        message = str(error) if isinstance(error, (AutomationError, ValueError)) else "The deadline change could not be verified. Check current state before retrying."
        return ActionResult(False, message, repeatable=False)


def related(names):
    terms = [keywords(name) - {"project", "work", "task"} for name in names]
    try:
        return [identity(r) for r in deadlines.load() if any(t and t <= keywords(r["what"]) for t in terms)][:100]
    except AutomationError as error:
        raise ValueError(str(error)) from error


def current():
    try:
        from services.mind.cognition import redact
        return [{**identity(r), "what": redact(r["what"])[:160]} for r in deadlines.load()[:10]]
    except AutomationError:
        return [{"status": "deadline store unavailable"}]
