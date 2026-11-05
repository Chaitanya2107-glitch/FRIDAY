"""Explicit single-date class corrections and scoped clarification."""

import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta

from core.logger import logger
from services.automation.command_words import strip_leading_filler
from services.automation.results import ActionResult
from services.automation.system_control import AutomationError
from services.mind import reference_context as context
from services.proactive import class_sessions, timetable

DAY = r"(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})"
REF = rf"(?P<day>{DAY})(?:'s|s)?\s+(?P<subject>.+?)"
CLOCK = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"


def clock(text):
    if re.search(r"[ap]", text, re.I) and not 1 <= int(re.match(r"\d+", text)[0]) <= 12:
        raise ValueError("Use an hour from 1 to 12 with AM or PM.")
    return timetable.parse_time(text)


def match_command(text):
    raw = strip_leading_filler(text).strip().rstrip(".!?").replace("\u2019", "'")
    moved = re.fullmatch(rf"(?:my |the )?{REF} class (?:has |was )?(?:moved|rescheduled|changed)"
                        rf"(?: from (?P<old>{CLOCK}))? to (?P<start>{CLOCK})", raw, re.I)
    command = re.fullmatch(rf"(?:move|reschedule|change) (?:my |the )?{REF} class"
                          rf"(?: from (?P<old>{CLOCK}))? to (?P<start>{CLOCK})", raw, re.I)
    if m := moved or command:
        return {"action": "move_class_session", "day": m["day"].lower(), "subject": m["subject"],
                "old": m["old"], "start": m["start"], "quote": text}
    if m := re.fullmatch(rf"(?:when is|what time is) (?:my |the )?{REF} class", raw, re.I):
        return {"action": "recall_class_session", "day": m["day"].lower(), "subject": m["subject"]}
    if m := re.fullmatch(rf"(?:show |list )?class history for (?:my |the )?{REF}(?: class)?", raw, re.I):
        return {"action": "class_session_history", "day": m["day"].lower(), "subject": m["subject"]}
    if m := re.fullmatch(rf"link reminder (?P<number>\d+) to (?:my |the )?{REF} class", raw, re.I):
        return {"action": "link_class_reminder", "day": m["day"].lower(), "subject": m["subject"], "number": int(m["number"])}
    if m := re.fullmatch(rf"(?P<verb>review|apply|reject) class reminder updates for (?:my |the )?{REF}(?: class)?", raw, re.I):
        return {"action": "class_reminder_updates", "day": m["day"].lower(), "subject": m["subject"], "verb": m["verb"].lower()}
    return None


def target_day(text, now):
    if text in ("today", "tomorrow"):
        return now.date() + timedelta(days=text == "tomorrow")
    if text in timetable.DAYS:
        return now.date() + timedelta(days=(timetable.DAYS.index(text) - now.weekday()) % 7)
    return date.fromisoformat(text)


def candidates(parsed, now):
    day = date.fromisoformat(parsed["date"]) if "date" in parsed else target_day(parsed["day"], now)
    query = re.sub(r"\s+at\s+(.+)$", "", parsed["subject"], flags=re.I).strip()
    at = re.search(r"\s+at\s+(.+)$", parsed["subject"], re.I)
    matches = []
    rows = class_sessions.load()
    for template in timetable.classes_on(timetable.DAYS[day.weekday()]):
        # Exact subject/alias or an acronym; no loose substring guessing.
        if not any(query.casefold() == alias.casefold() or timetable.abbreviates(query, alias)
                   or timetable.abbreviates(alias, query) for alias in timetable.aliases(template["subject"])):
            continue
        row = class_sessions.row_for(rows, day, template)
        if not row and any(r["date"] == day.isoformat() and r["template"]["subject"] == template["subject"]
                           and r["template"]["start"] == template["start"] for r in rows):
            raise ValueError("The weekly class template changed after a dated correction. Review its saved occurrence before changing it again.")
        start = datetime.fromisoformat(row["due"]).strftime("%H:%M") if row else template["start"]
        if at and clock(at[1]) != start:
            continue
        matches.append({"date": day.isoformat(), "template": template, "revision": row["revision"] if row else None,
                        "start": start, "end": row["end"] if row else template["end"]})
    return matches


def match_turn(text, *, remote=False):
    scope = "telegram" if remote else "local"
    if parsed := match_command(text):
        try:
            parsed["date"] = target_day(parsed["day"], datetime.now()).isoformat()
            found = candidates(parsed, datetime.now())
            if len(found) == 1:
                parsed["expected"] = found[0]
                if parsed["action"] == "class_reminder_updates":
                    from services.proactive.deadline_reminders import digest
                    row = class_sessions.row_for(class_sessions.load(), date.fromisoformat(parsed["date"]), found[0]["template"])
                    pending = [p for p in (row or {}).get("reminder_updates", []) if p["status"] == "pending" and p["scope"] == scope]
                    parsed["proposal"] = digest(pending[-1]) if pending else None
        except (AutomationError, ValueError):
            pass  # Explicit requests still route to the deterministic error path.
        return parsed
    from services.mind.workspace import workspace
    with workspace._db() as db:
        saved = context.read(db, "class_session", scope)
    if saved:
        found = saved["payload"]["candidates"]
        indices = context.choices(text, [f'{c["template"]["subject"]} at {c["start"]}' for c in found])
        if indices or re.fullmatch(r"(?:the )?(?:\d+|first|second|third|fourth|fifth|last)(?: one)?", text.strip(), re.I):
            return {**saved["payload"]["request"], "context": saved, "choices": [found[i] for i in indices]}
    return None


def move(row, parsed, now, scope):
    from services.memory import schedule
    from services.proactive import attendance, deadline_reminders
    day = date.fromisoformat(row["date"])
    if not schedule.allowed(day, row["template"]["subject"]) or row["date"] in attendance.load()["holidays"]:
        raise ValueError("That class is cancelled. A time correction cannot resume a cancelled class.")
    old = datetime.fromisoformat(row["due"])
    if parsed.get("old") and clock(parsed["old"]) != old.strftime("%H:%M"):
        raise ValueError(f'The saved class starts at {old:%H:%M}; check its current time before changing it.')
    start = clock(parsed["start"])
    new = datetime.fromisoformat(f'{row["date"]}T{start}')
    end = new + (datetime.fromisoformat(f'{row["date"]}T{row["end"]}') - old)
    if old <= now or new <= now or end.date() != day or end <= new:
        raise ValueError("Use a future class and a future time whose duration stays within that date.")
    evidence = {row["template"]["start"], old.strftime("%H:%M")}
    for h in row["history"]:
        evidence.update(datetime.fromisoformat(h[k]).strftime("%H:%M") for k in ("old_due", "new_due"))
    if any(r["date"] == row["date"] and r["subject"] == row["template"]["subject"] and r["start"] in evidence
           for r in attendance.load()["records"]):
        raise ValueError("Attendance is already recorded for that occurrence. Review it before changing the class time.")
    if new == old:
        return f'{row["what"]} already starts at {start}; no change was made.'
    deadline_reminders.reconcile(row)
    row["history"].append({"old_due": row["due"], "new_due": new.isoformat(timespec="minutes"),
                           "old_end": row["end"], "new_end": end.strftime("%H:%M"), "quote": parsed["quote"],
                           "source": "owner_report", "noted": now.isoformat()})
    row["due"], row["end"], row["revision"] = new.isoformat(timespec="minutes"), end.strftime("%H:%M"), uuid.uuid4().hex
    return f'{row["what"]} now runs {start}–{row["end"]}. Weekly timetable unchanged; original time retained in history.' + deadline_reminders.propose(row, scope)


def run(parsed, *, remote=False):
    from services.mind.workspace import workspace
    from services.proactive import deadline_reminders
    scope = "telegram" if remote else "local"
    try:
        with class_sessions.edit():
            now = datetime.now()
            found = candidates(parsed, now)
            with workspace._db() as db:
                if "context" in parsed:
                    context.require(db, parsed["context"])
                    found = [c for c in found if len(parsed["choices"]) == 1 and c == parsed["choices"][0]]
                else:
                    context.clear(db, "class_session", scope)
            if "expected" in parsed and found != [parsed["expected"]]:
                raise ValueError("The class changed after this request. Review the current class before retrying.")
            if len(found) > 1:
                offered = found[:5]
                with workspace._db() as db:
                    context.remember(db, "class_session", {"request": parsed, "candidates": offered}, scope)
                labels = "; ".join(f'{i}. {c["template"]["subject"]} at {c["start"]}' for i, c in enumerate(offered, 1))
                return ActionResult(False, f"Which class? {labels}. Reply with an offered number or subject and time.", repeatable=False)
            if not found:
                raise ValueError("That class is missing, changed or the choice is ambiguous. Give its date, saved subject and time.")
            selected, rows = found[0], class_sessions.load()
            day = date.fromisoformat(selected["date"])
            row = class_sessions.row_for(rows, day, selected["template"])
            if row is None:
                row = class_sessions.create(day, selected["template"])
                rows.append(row)
            action = parsed["action"]
            if action == "move_class_session":
                message = move(row, parsed, now, scope)
            elif action in {"recall_class_session", "class_session_history"}:
                from services.memory import schedule
                state = "cancelled" if not schedule.allowed(day, row["template"]["subject"]) else f'{row["due"]}–{row["end"]}'
                message = f'{row["what"]}: {state}.'
                if action == "class_session_history":
                    message += "\n" + ("\n".join(f'{h["noted"]}: {h["old_due"]}–{h["old_end"]} -> {h["new_due"]}–{h["new_end"]} (owner report)' for h in row["history"]) or "No time changes recorded.")
            else:
                pending = [p for p in row["reminder_updates"] if p["status"] == "pending" and p["scope"] == scope]
                if "proposal" in parsed and (deadline_reminders.digest(pending[-1]) if pending else None) != parsed["proposal"]:
                    raise ValueError("The reminder proposal changed. Review it again before applying it.")
                if action == "class_reminder_updates" and parsed["verb"] == "apply":
                    from services.memory import schedule
                    from services.proactive import attendance
                    if not schedule.allowed(day, row["template"]["subject"]) or row["date"] in attendance.load()["holidays"]:
                        raise ValueError("That class is cancelled; its linked reminders cannot be shifted.")
                adapter = {**parsed, "action": "link_deadline_reminder" if action == "link_class_reminder" else "deadline_reminder_updates"}
                message = deadline_reminders.run(row, adapter, now, scope)
            if action not in {"recall_class_session", "class_session_history"}:
                class_sessions.save(rows)
            with workspace._db() as db:
                context.clear(db, "class_session", scope)
            return ActionResult(True, message, memory_message=message, repeatable=False)
    except (AutomationError, ValueError, OSError, sqlite3.Error) as error:
        logger.warning("Class correction unavailable: %s", type(error).__name__)
        message = str(error) if isinstance(error, (AutomationError, ValueError)) else "The class change could not be verified. Check its current time before retrying."
        return ActionResult(False, message, repeatable=False)
