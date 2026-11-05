"""Dated class occurrences; the weekly timetable remains the source template."""

import uuid
import re
from datetime import date, datetime

from core.config import config
from services.automation.system_control import AutomationError
from services.proactive import deadline_store, deadlines


def path():
    return config.MEMORY_DIR / "class-sessions.json"


def edit():
    # All deadline/class link writers share this cross-process lock, so a reminder
    # cannot be claimed by two different commitments at once.
    return deadlines.edit()


def load():
    try:
        rows = deadline_store.read(path())
        seen = set()
        for row in rows:
            if not all(isinstance(row.get(field), list) for field in ("history", "linked_reminders", "reminder_updates")):
                raise ValueError("Missing class history or reminder metadata")
            day = date.fromisoformat(row["date"])
            base = row["template"]
            for field in ("day", "subject", "start", "end"):
                if not isinstance(base[field], str) or not base[field]:
                    raise ValueError("Invalid class template")
            for clock in (base["start"], base["end"], row["end"]):
                if not isinstance(clock, str) or not re.fullmatch(r"\d{2}:\d{2}", clock):
                    raise ValueError("Invalid class clock")
                datetime.strptime(clock, "%H:%M")
            if (datetime.fromisoformat(row["due"]).date() != day or row["kind"] != "class"
                    or not row.get("id") or not row.get("revision")
                    or base["day"] != day.strftime("%A").lower() or base["end"] <= base["start"]
                    or row["end"] <= datetime.fromisoformat(row["due"]).strftime("%H:%M")):
                raise ValueError("Invalid class occurrence")
            for change in row["history"]:
                for field in ("old_end", "new_end"):
                    datetime.strptime(change[field], "%H:%M")
            identity = (row["date"], base["subject"], base["start"])
            if identity in seen:
                raise ValueError("Duplicate class occurrence")
            seen.add(identity)
        return rows
    except (AutomationError, ValueError, KeyError, TypeError) as error:
        raise AutomationError("Saved class changes are unreadable. Repair class-sessions.json before changing classes.") from error


def save(rows):
    deadline_store.save(path(), rows)


def row_for(rows, day, template):
    return next((r for r in rows if r["date"] == day.isoformat() and r["template"] == template), None)


def create(day, template):
    return {"id": uuid.uuid4().hex, "revision": uuid.uuid4().hex, "kind": "class",
            "what": f"{day.isoformat()}'s {template['subject']}", "date": day.isoformat(),
            "template": dict(template), "due": f"{day.isoformat()}T{template['start']}", "end": template["end"],
            "history": [], "linked_reminders": [], "reminder_updates": []}


def effective(day, classes, rows=None):
    rows = load() if rows is None else rows
    result = []
    for template in classes:
        row = row_for(rows, day, template)
        result.append({**template, "start": datetime.fromisoformat(row["due"]).strftime("%H:%M"),
                       "end": row["end"], "session_revision": row["revision"]} if row and row["history"] else dict(template))
    return sorted(result, key=lambda c: (c["start"], c["subject"]))


def delivery_decision(reminder):
    from services.memory import schedule
    from services.proactive import timetable
    for row in load():
        if any(l["id"] == reminder.id for l in row["linked_reminders"]) and any(
                p["status"] == "pending" for p in row["reminder_updates"]):
            # A committed receipt can precede JSON finalization. Use the verified
            # due time for cancellation checks even before the owner's next retry.
            from services.proactive.deadline_reminders import reconcile
            reconcile(row)
        if not any((l["id"], l["text"], l["due_at"]) == (reminder.id, reminder.text, reminder.due_at)
                   for l in row.get("linked_reminders", [])):
            continue
        day = date.fromisoformat(row["date"])
        from services.proactive import attendance
        if not schedule.allowed(day, row["template"]["subject"]) or row["date"] in attendance.load()["holidays"]:
            return {"action": "suppress", "reason": "The owner cancelled the class explicitly linked to this reminder."}
        if row["template"] not in timetable.classes_on(timetable.DAYS[day.weekday()]):
            return {"action": "defer", "reason": "The linked class template changed; review its reminder before delivery."}
        if any(p["status"] == "pending" for p in row.get("reminder_updates", [])):
            return {"action": "defer", "reason": "A linked class moved; review its pending reminder update before delivery."}
    return None
