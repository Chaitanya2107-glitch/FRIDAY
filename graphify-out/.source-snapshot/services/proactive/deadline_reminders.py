"""Explicit reminder links and approved shifts, with durable replay receipts."""

import hashlib
import json
import time
import uuid
from datetime import datetime

from services.proactive import deadlines
from services.reminders.service import ReminderService


def digest(proposal):
    return hashlib.sha256(json.dumps({k: proposal[k] for k in ("id", "revision", "scope", "items")}, sort_keys=True).encode()).hexdigest()


def schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS deadline_reminder_receipts (id TEXT PRIMARY KEY,digest TEXT NOT NULL,applied REAL NOT NULL)")


def _finish(row, proposal):
    for link in row.get("linked_reminders", []):
        item = next((i for i in proposal["items"] if i["id"] == link["id"]), None)
        if item:
            link["due_at"] = item["new_due"]
    proposal["status"] = "applied"


def reconcile(row):
    pending = [p for p in row.get("reminder_updates", []) if p["status"] == "pending"]
    if not pending:
        return 0
    recovered = 0
    with ReminderService()._connect() as db:
        schema(db)
        for proposal in pending:
            receipt = db.execute("SELECT digest FROM deadline_reminder_receipts WHERE id=?", (proposal["id"],)).fetchone()
            if receipt:
                if receipt[0] != digest(proposal):
                    raise ValueError("The saved reminder proposal conflicts with its receipt. Check reminders before retrying.")
                _finish(row, proposal)
                recovered += 1
    return recovered


def propose(row, scope):
    for previous in row.get("reminder_updates", []):
        if previous["status"] == "pending":
            previous["status"] = "superseded"
    if not row.get("linked_reminders"):
        return " No explicitly linked reminders were changed."
    due = datetime.fromisoformat(row["due"]).timestamp()
    items = [{**link, "new_due": due + link["offset"]} for link in row["linked_reminders"]]
    proposal = {"id": uuid.uuid4().hex, "revision": row["revision"], "scope": scope, "status": "pending", "items": items}
    row.setdefault("reminder_updates", []).append(proposal)
    return "\n" + preview(row, proposal)


def preview(row, proposal):
    lines = ["Proposed linked reminder updates (not applied; saved link snapshots):"]
    lines += [f'{item["text"]}: {datetime.fromtimestamp(item["due_at"]):%Y-%m-%d %H:%M} -> '
              f'{datetime.fromtimestamp(item["new_due"]):%Y-%m-%d %H:%M}' for item in proposal["items"]]
    kind = "class " if row.get("kind") == "class" else ""
    lines.append(f'Say "apply {kind}reminder updates for {row["what"]}" or "reject {kind}reminder updates for {row["what"]}".')
    return "\n".join(lines)


def apply(row, proposal, now):
    links = {i["id"]: i for i in row.get("linked_reminders", [])}
    if len(links) != len(proposal["items"]) or any(
            any(item.get(k) != links.get(item["id"], {}).get(k) for k in ("id", "text", "due_at", "offset"))
            or item["new_due"] != datetime.fromisoformat(row["due"]).timestamp() + item["offset"]
            for item in proposal["items"]):
        raise ValueError("The linked reminders or proposed times changed. Review the current reminder proposal first.")
    service = ReminderService()
    with service._connect() as db:
        service._delivery_schema(db)
        schema(db)
        db.execute("BEGIN IMMEDIATE")
        receipt = db.execute("SELECT digest FROM deadline_reminder_receipts WHERE id=?", (proposal["id"],)).fetchone()
        if receipt:
            if receipt[0] != digest(proposal):
                raise ValueError("The proposal changed after its approval was recorded.")
        else:
            for item in proposal["items"]:
                reminder = db.execute("SELECT text,due_at,delivered_at FROM reminders WHERE id=?", (item["id"],)).fetchone()
                if not reminder or reminder != (item["text"], item["due_at"], None):
                    raise ValueError("A linked reminder changed, was cancelled or was already delivered. No reminders were moved.")
                if item["new_due"] <= now.timestamp():
                    raise ValueError("A proposed reminder time is already past. No reminders were moved; relink a suitable reminder.")
                state = db.execute("SELECT status,lease_until,desktop_status,telegram_status FROM reminder_delivery WHERE reminder_id=?",
                                   (item["id"],)).fetchone()
                if state and (state[0] in {"submitting", "uncertain", "delivered"} or
                              any(s in {"submitted", "uncertain"} for s in state[2:]) or (state[1] or 0) > time.time()):
                    raise ValueError("A linked reminder has active or uncertain delivery. Resolve its delivery before moving it.")
            for item in proposal["items"]:
                db.execute("UPDATE reminders SET due_at=? WHERE id=?", (item["new_due"], item["id"]))
                db.execute("DELETE FROM reminder_delivery WHERE reminder_id=?", (item["id"],))
                if db.execute("SELECT due_at FROM reminders WHERE id=?", (item["id"],)).fetchone()[0] != item["new_due"]:
                    raise ValueError("The reminder change could not be verified.")
            db.execute("INSERT INTO deadline_reminder_receipts VALUES(?,?,?)", (proposal["id"], digest(proposal), time.time()))
    _finish(row, proposal)
    return f'Updated and verified {len(proposal["items"])} linked reminder(s) for {row["what"]}.'


def run(row, parsed, now, scope):
    kind = "class" if row.get("kind") == "class" else "deadline"
    recovered = reconcile(row)
    if parsed["action"] == "link_deadline_reminder":
        if any(p["status"] == "pending" for p in row.get("reminder_updates", [])):
            raise ValueError("Review, apply or reject the pending reminder updates before changing links.")
        reminders = ReminderService().pending()
        number = parsed["number"]
        if not 1 <= number <= len(reminders):
            raise ValueError("Choose a reminder number from 'list reminders'.")
        reminder = reminders[number - 1]
        from services.proactive import class_sessions
        if any(d["id"] != row["id"] and any(l["id"] == reminder.id for l in d.get("linked_reminders", []))
               for d in deadlines.load() + class_sessions.load()):
            raise ValueError("That reminder is linked to another deadline or class. Create a separate reminder for this one.")
        links = [l for l in row.get("linked_reminders", []) if l["id"] != reminder.id]
        links.append({"id": reminder.id, "text": reminder.text, "due_at": reminder.due_at,
                      "offset": reminder.due_at - datetime.fromisoformat(row["due"]).timestamp()})
        row["linked_reminders"] = links
        return f'Linked reminder {number} ({reminder.text}) to {row["what"]}. Its time was not changed.'
    pending = [p for p in row.get("reminder_updates", []) if p["status"] == "pending" and p["scope"] == scope]
    if not pending:
        if recovered and parsed["verb"] == "apply":
            return "The earlier reminder update was already committed; its receipt was verified without replaying it."
        raise ValueError(f"No pending reminder update for this {kind} in this conversation. Check its current time or create a new change.")
    proposal = pending[-1]
    if proposal["revision"] != row["revision"]:
        raise ValueError(f"The {kind} changed after this proposal. Review the current reminder proposal first.")
    if parsed["verb"] == "review":
        return preview(row, proposal)
    if parsed["verb"] == "reject":
        proposal["status"] = "rejected"
        for link in row.get("linked_reminders", []):
            link["offset"] = link["due_at"] - datetime.fromisoformat(row["due"]).timestamp()
        return f"Kept the linked reminder times as requested. The corrected {kind} remains saved."
    return apply(row, proposal, now)


def hold_reason(reminder):
    for row in deadlines.load():
        for proposal in row.get("reminder_updates", []):
            if proposal["status"] == "pending" and any(
                    (i["id"], i["text"], i["due_at"]) == (reminder.id, reminder.text, reminder.due_at) for i in proposal["items"]):
                return "A linked deadline changed; review its pending reminder update before delivery."
    return ""
