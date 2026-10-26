"""Narrow service adapters. Language interpretation is in the model, execution is here."""

import json
import sqlite3
from datetime import datetime, date

from core.config import config
from services.mind.cognition import cognition
from services.mind.reasoning_store import reasoning_store, fingerprint


def automatic(claim, known):
    effect = claim["effect"]
    sources = [known[key] for key in claim["evidence"] if key in known]
    owner = [s for s in sources if s.get("kind") == "owner_fact"]
    return (claim["status"] == "proposed" and effect["type"] == "class_availability" and
            effect["basis"] == "explicit" and claim["confidence"] >= .9 and bool(owner) and
            all(s.get("certainty") == "confirmed" for s in owner) and
            not any(s.get("kind") == "learned_guess" for s in sources))


def apply(ident, now=None):
    now = now or datetime.now()
    claim = reasoning_store.get(ident, now)
    if not claim or claim["status"] != "proposed":
        raise ValueError("That proposal is expired, changed, already used or unavailable. Reconsider it first.")
    known = reasoning_store.evidence()
    if any(key not in known or fingerprint(known[key]) != stamp for key, stamp in claim["source_fingerprints"].items()):
        raise ValueError("The evidence changed; reconsider this proposal.")
    effect = claim["effect"]
    if effect["type"] == "guidance":
        raise ValueError("This conclusion is guidance, not an executable proposal.")
    if not reasoning_store.claim(ident):
        raise ValueError("This proposal was already consumed.")
    try:
        if effect["type"] == "class_availability":
            # The dated projection itself is the applied state. Weekly templates
            # and attendance rows are never destroyed by an inferred change.
            outcome = (f"{'Restored' if effect['available'] else 'Paused'} {effect['subject'] or 'regular'} classes "
                       f"from {claim['start']} through {claim['end']}.")
            reasoning_store.finish(ident, "applied", outcome)
            from services.memory import schedule
            if not any(f.key == f"reasoning:{ident}" for f in class_facts(now)):
                raise ValueError("Class projection could not be verified")
            # Confirm the shared schedule reader observes this projection.
            day = date.fromisoformat(claim["start"])
            if schedule.allowed(day, effect["subject"]) != effect["available"]:
                raise ValueError("A newer class constraint supersedes this proposal")
        elif effect["type"] == "task_plan":
            from services.mind.workspace import workspace
            original = known[f"task:{effect['task_id']}"]
            workspace.plan(effect["task_id"], effect["steps"], expected_updated=original["updated"])
            saved = next(t for t in workspace.tasks() if t["id"] == effect["task_id"])
            if saved["steps"] != [step.strip() for step in effect["steps"]]:
                raise ValueError("Saved task plan did not match")
            outcome = f"Saved {len(effect['steps'])} steps for task {effect['task_id']}; none are marked complete."
        elif effect["type"] == "reminder_move":
            due = datetime.fromisoformat(effect["due"])
            if due <= now:
                raise ValueError("The proposed reminder time has passed")
            original = known[f"reminder:{effect['reminder_id']}"]
            with sqlite3.connect(config.MEMORY_DB_PATH, timeout=2) as db:
                changed = db.execute("UPDATE reminders SET due_at = ? WHERE id = ? AND due_at = ? AND delivered_at IS NULL",
                                     (due.timestamp(), effect["reminder_id"], original["due_at"])).rowcount
                if changed != 1:
                    raise ValueError("The reminder changed or was already delivered")
                if db.execute("SELECT due_at FROM reminders WHERE id = ?", (effect["reminder_id"],)).fetchone()[0] != due.timestamp():
                    raise ValueError("Reminder time could not be verified")
            outcome = f"Moved reminder {effect['reminder_id']} to {due:%Y-%m-%d %H:%M}."
        else:
            raise ValueError("Unsupported service change")
        reasoning_store.finish(ident, "applied", outcome)
        cognition.record("reasoning_action", "brain", json.dumps({"proposal": ident, "outcome": outcome}),
                         status="verified", public=True)
        return outcome
    except BaseException:
        # A crash/failure never permits the same approval to replay a side effect.
        reasoning_store.finish(ident, "failed", "The change failed or its result could not be verified; inspect current state.")
        raise


def class_facts(now=None):
    from services.memory.schedule import Fact
    now = now or datetime.now()
    result = []
    for claim in reasoning_store.conclusions(now, include_future=True, include_expired=True):
        effect = claim["effect"]
        if claim["status"] == "applied" and effect["type"] == "class_availability":
            result.append(Fact(f"reasoning:{claim['id']}", claim["text"], datetime.fromisoformat(claim["noted"]),
                               date.fromisoformat(claim["start"]), date.fromisoformat(claim["end"]),
                               effect["available"], effect["subject"]))
    return result
