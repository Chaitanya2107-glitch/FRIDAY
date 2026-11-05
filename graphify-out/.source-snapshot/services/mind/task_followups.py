"""Goal-aware task suggestions with durable feedback and bounded interruptions."""

import asyncio
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

from core.logger import logger
from services.mind.workspace import workspace

HOUR = 3600
DAY = 24 * HOUR
ATTEMPT_GAP = 30 * 60
SENT_GAP = 4 * HOUR
DAILY_LIMIT = 2
DAILY_REVIEWS = 4


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS workspace_followup_preferences (
        task_id INTEGER PRIMARY KEY, snoozed_until REAL NOT NULL DEFAULT 0,
        muted INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS workspace_followups (
        token TEXT PRIMARY KEY, task_id INTEGER NOT NULL, snapshot TEXT NOT NULL,
        text TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
        state TEXT NOT NULL, sent_at REAL NOT NULL DEFAULT 0, decision_id INTEGER)""")


@contextmanager
def _db():
    with workspace._db() as db:
        schema(db)
        yield db


def _snapshot(db, task_id):
    if not db.execute("SELECT 1 FROM workspace_tasks WHERE id=?", (task_id,)).fetchone():
        return None
    task = workspace._task(db, task_id)
    if task["status"] not in {"active", "blocked"}:
        return None
    goal = db.execute("SELECT * FROM workspace_goals WHERE id=?", (task["goal_id"],)).fetchone()
    if task["goal_id"] is not None and (goal is None or goal["status"] != "active"):
        return None
    return {"task": {k: task[k] for k in ("id", "title", "goal_id", "status", "steps", "cursor", "blocker", "updated")},
            "goal": dict(goal) if goal else None}


def _allowed(db, task_id, now):
    return not db.execute("SELECT 1 FROM workspace_followup_preferences WHERE task_id IN (0,?) "
                          "AND (muted=1 OR snoozed_until>?)", (task_id, now.timestamp())).fetchone()


def _ranked(db, now):
    ranked = []
    for row in db.execute("SELECT t.id FROM workspace_tasks t LEFT JOIN workspace_goals g ON g.id=t.goal_id "
                          "WHERE t.status IN ('active','blocked') ORDER BY COALESCE(g.priority,2) DESC,t.updated,t.id LIMIT 100"):
        snapshot = _snapshot(db, row["id"])
        if not snapshot or not _allowed(db, row["id"], now):
            continue
        task, goal = snapshot["task"], snapshot["goal"]
        age = now.timestamp() - task["updated"]
        if age < (DAY if task["status"] == "blocked" else 2 * DAY):
            continue
        previous = db.execute("SELECT MAX(sent_at) FROM workspace_followups WHERE task_id=?", (task["id"],)).fetchone()[0] or 0
        prefs = db.execute("SELECT streak FROM workspace_followup_preferences WHERE task_id=?", (task["id"],)).fetchone()
        delay = DAY * min(7, 2 ** min(3, max(0, (prefs[0] if prefs else 0) - 1)))
        if previous and now.timestamp() - previous < delay:
            continue
        priority = goal["priority"] if goal else 2
        ranked.append(((priority, task["status"] == "blocked", age, -task["id"]), snapshot))
    return [snapshot for _, snapshot in sorted(ranked, key=lambda item: item[0], reverse=True)]


def _describe(snapshot):
    task, goal = snapshot["task"], snapshot["goal"]
    since = datetime.fromtimestamp(task["updated"]).strftime("%Y-%m-%d %H:%M")
    reason = f'Your saved task has not been updated since {since}.'
    if goal:
        reason += f' It supports your goal "{goal["title"]}" (owner priority {goal["priority"]}/3).'
    if task["status"] == "blocked":
        text = f'You marked "{task["title"]}" blocked by: {task["blocker"]}. Want to review the blocker?'
        reason += " You explicitly recorded this blocker; I have no evidence it is resolved."
    else:
        step = task["steps"][task["cursor"]] if task["cursor"] < len(task["steps"]) else ""
        text = f'Your task "{task["title"]}" is still saved as active.'
        text += f' Next saved step: {step}. Want to review it?' if step else " Want to review what comes next?"
    return text, reason


def offer(now):
    """Reserve at most one candidate; selection is not a notification or a task action."""
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = db.execute("SELECT MAX(created),MAX(sent_at) FROM workspace_followups").fetchone()
        if latest[0] and now.timestamp() - latest[0] < ATTEMPT_GAP:
            return None
        if latest[1] and now.timestamp() - latest[1] < SENT_GAP:
            return None
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        if db.execute("SELECT COUNT(*) FROM workspace_followups WHERE created>=?", (midnight,)).fetchone()[0] >= DAILY_REVIEWS:
            return None
        if db.execute("SELECT COUNT(*) FROM workspace_followups WHERE sent_at>=? AND sent_at>0", (midnight,)).fetchone()[0] >= DAILY_LIMIT:
            return None
        ranked = _ranked(db, now)
        if not ranked:
            return None
        snapshot = ranked[0]
        text, reason = _describe(snapshot)
        token = uuid.uuid4().hex
        db.execute("INSERT INTO workspace_followups(token,task_id,snapshot,text,reason,created,expires,state) "
                   "VALUES(?,?,?,?,?,?,?,'candidate')", (token, snapshot["task"]["id"], json.dumps(snapshot),
                                                        text, reason, now.timestamp(), now.timestamp() + 600))
        logger.debug("Reserved task follow-up for task %s", snapshot["task"]["id"])
        return {"token": token, "task_id": snapshot["task"]["id"], "text": text, "reason": reason,
                "basis": {"source": "owner_saved_workspace", **snapshot, "reason": reason}}


def _current(db, token, now, states):
    row = db.execute("SELECT * FROM workspace_followups WHERE token=?", (token,)).fetchone()
    return (dict(row) if row and row["state"] in states and row["expires"] > now.timestamp()
            and _allowed(db, row["task_id"], now)
            and _snapshot(db, row["task_id"]) == json.loads(row["snapshot"]) else None)


def current(token, now):
    with _db() as db:
        return bool(_current(db, token, now, {"candidate"}))


def control(verb, task_id, now):
    if verb not in {"pause", "stop", "resume"}:
        raise ValueError("Choose pause, stop or resume task followups.")
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        if task_id and not _snapshot(db, task_id):
            raise ValueError("Choose an active task with an active goal, or control all task followups.")
        _control(db, verb, task_id, now)
        db.execute("UPDATE workspace_followups SET state='retired' WHERE state='candidate' AND (?=0 OR task_id=?)", (task_id, task_id))
        from services.mind import reference_context
        saved = reference_context.read(db, "task_followup")
        if saved:
            selected = db.execute("SELECT task_id FROM workspace_followups WHERE token=?", (saved["payload"]["token"],)).fetchone()
            if task_id == 0 or (selected and selected[0] == task_id):
                reference_context.clear(db, "task_followup")
    return {"pause": "Task followups paused for 24 hours.", "stop": "Task followups stopped until you resume them.",
            "resume": "Task followups resumed; normal attention checks and cooldowns still apply."}[verb]


def _control(db, verb, task_id, now):
    db.execute("INSERT INTO workspace_followup_preferences(task_id,snoozed_until,muted) VALUES(?,?,?) "
               "ON CONFLICT(task_id) DO UPDATE SET snoozed_until=excluded.snoozed_until,muted=excluded.muted,streak=0",
               (task_id, now.timestamp() + DAY if verb == "pause" else 0, int(verb == "stop")))


def claim(token, now):
    try:
        return _claim(token, now)
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Task followup claim unavailable: %s", type(error).__name__)
        return False


def _claim(token, now):
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = _current(db, token, now, {"candidate"})
        if not row:
            return False
        latest = db.execute("SELECT MAX(sent_at) FROM workspace_followups").fetchone()[0] or 0
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        count = db.execute("SELECT COUNT(*) FROM workspace_followups WHERE sent_at>=? AND sent_at>0", (midnight,)).fetchone()[0]
        if (latest and now.timestamp() - latest < SENT_GAP) or count >= DAILY_LIMIT:
            return False
        db.execute("UPDATE workspace_followups SET state='submitting',sent_at=?,expires=? WHERE token=?",
                   (now.timestamp(), now.timestamp() + 12 * HOUR, token))
        db.execute("INSERT INTO workspace_followup_preferences(task_id,streak) VALUES(?,1) "
                   "ON CONFLICT(task_id) DO UPDATE SET streak=MIN(4,streak+1)", (row["task_id"],))
        return True


def settle(token, state, decision_id, now):
    if state not in {"withheld", "submitted", "failed", "uncertain"}:
        raise ValueError("Unknown followup delivery state.")
    from services.mind import reference_context
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("UPDATE workspace_followups SET state=?,decision_id=? WHERE token=? AND state=?",
                             (state, decision_id, token, "candidate" if state == "withheld" else "submitting")).rowcount
        if changed and state == "submitted" and _current(db, token, now, {"submitted"}):
            reference_context.remember(db, "task_followup", {"token": token})


def respond(token, verb, now, *, context=None):
    if verb not in {"review", "why", "pause", "stop"}:
        raise ValueError("Choose review, explain, not now or stop asking.")
    from services.mind import reference_context
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        if context:
            reference_context.require(db, context)
        row = _current(db, token, now, {"submitted", "uncertain", "reviewed"})
        if not row:
            raise ValueError("That task followup changed, expired or was stopped. Ask to show task followups or use the saved task name.")
        if verb == "why":
            return row["reason"] + " This is a suggestion to review saved work; no task step was executed."
        if verb in {"pause", "stop"}:
            _control(db, verb, row["task_id"], now)
        else:
            db.execute("UPDATE workspace_followup_preferences SET streak=0 WHERE task_id=?", (row["task_id"],))
        db.execute("UPDATE workspace_followups SET state=? WHERE token=?",
                   ({"review": "reviewed", "pause": "snoozed", "stop": "muted"}[verb], token))
        if verb in {"pause", "stop"}:
            saved = reference_context.read(db, "task_followup")
            if saved and saved["payload"]["token"] == token:
                reference_context.clear(db, "task_followup")
        task = json.loads(row["snapshot"])["task"]
        if verb == "pause":
            return f'I will leave "{task["title"]}" alone for 24 hours.'
        if verb == "stop":
            return f'I will stop followups for "{task["title"]}" until you resume them.'
        step = task["steps"][task["cursor"]] if task["cursor"] < len(task["steps"]) else "No next step is saved."
        return f'{task["title"]}: {task["status"]}. Next step: {step}' + (f' Blocker: {task["blocker"]}' if task["blocker"] else "")


def status(now):
    from core.config import config
    from services.mind import talk
    from services.proactive import watcher
    with _db() as db:
        prefs = [dict(r) for r in db.execute("SELECT p.*,t.title FROM workspace_followup_preferences p "
                                           "LEFT JOIN workspace_tasks t ON t.id=p.task_id WHERE muted=1 OR snoozed_until>?",
                                           (now.timestamp(),))]
        rows = [dict(r) for r in db.execute("SELECT * FROM workspace_followups ORDER BY created DESC LIMIT 3")]
    lines = ["Task help follows saved goals and progress. At most two attempts to notify per day, four hours apart."]
    talking = talk.load()
    lines.append(f'Availability: nudges {"on" if watcher.nudges_active(now.timestamp()) else "off/paused"}; '
                 f'free will {"on" if talking.get("on", True) and now.timestamp() >= talking.get("paused_until", 0) else "off/paused"}; '
                 f'notification review {"on" if config.NOTIFICATION_REVIEW_ENABLED else "off"}.')
    for pref in prefs:
        label = pref["title"] or "All task followups"
        lines.append(f'{label}: stopped.' if pref["muted"] else f'{label}: paused until {datetime.fromtimestamp(pref["snoozed_until"]):%Y-%m-%d %H:%M}.')
    for row in rows:
        state = "uncertain (interrupted submission; not replayed)" if row["state"] == "submitting" else row["state"]
        lines.append(f'{row["text"]}\nState: {state}. Why: {row["reason"]}')
    if not rows:
        lines.append("No task followups yet. Save tasks and goals; recent progress and paused work are left alone.")
    return "\n".join(lines)


def attention(now, busy, idle):
    from services.mind import talk
    from services.proactive import watcher
    return watcher.nudges_active(now.timestamp()) and talk.may_talk(talk.load(), now.timestamp(), busy, idle)


def deliverable(token, now):
    from services.proactive import watcher
    try:
        return attention(now, watcher.is_busy(), watcher.idle_seconds()) and current(token, now)
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Task followup recheck unavailable: %s", type(error).__name__)
        return False


async def tick(now, busy, idle):
    from core.config import config
    from services.mind import talk, notifications
    from services.proactive import watcher, buttons
    try:
        if not config.NOTIFICATION_REVIEW_ENABLED or not await asyncio.to_thread(attention, now, busy, idle):
            return False
        if await asyncio.to_thread(talk.mic_in_use):
            return False
        if not (item := await asyncio.to_thread(offer, now)):
            return False
        await notifications.notify(item["text"], buttons.offer("task_followup", followup=item["token"]),
                                   kind="task_followup", subject=item["token"], transport=watcher.show_toast, now=now,
                                   basis=item["basis"])
        return True  # queued for review, not a claim of delivery
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Task followup unavailable: %s", type(error).__name__)
        return False


def pending_conversation():
    from services.mind import reference_context
    try:
        with _db() as db:
            return reference_context.read(db, "task_followup") is not None
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Task followup context unavailable: %s", type(error).__name__)
        return False
