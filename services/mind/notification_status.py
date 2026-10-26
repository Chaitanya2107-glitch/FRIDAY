"""Local introspection of notification decisions and actual reminder outcomes."""

import json
from datetime import datetime
from pathlib import Path

from core.config import config
from services.mind.cognition import cognition
from services.reminders.service import reminders


def snapshot(limit=20):
    limit = max(1, min(100, int(limit)))
    decisions = []
    for event in reversed(cognition.recent(config.COGNITION_MAX_EVENTS)):
        if event["kind"] != "notification_decision":
            continue
        try:
            detail = json.loads(event["text"])
        except (ValueError, TypeError):
            detail = {"reason": event["text"]}
        decisions.append({"id": event["id"], "at": event["at"], "channel": event["channel"],
                          "status": event["status"], "detail": detail})
        if len(decisions) >= limit:
            break
    deliveries = reminders.delivery_status(limit) if Path(reminders.db_path).exists() else []
    return {"review_enabled": config.NOTIFICATION_REVIEW_ENABLED,
            "decisions": decisions, "reminders": deliveries}


def describe(*, latest_only=False):
    state = snapshot(1 if latest_only else 10)
    lines = [f"Notification brain review is {'enabled' if state['review_enabled'] else 'disabled'}. "
             "Submission confirms a transport accepted the notification, not that you read it."]
    if not state["decisions"]:
        lines.append("No notification decisions are recorded yet.")
    for decision in state["decisions"]:
        detail = decision["detail"]
        when = datetime.fromtimestamp(decision["at"]).strftime("%I:%M %p")
        lines.append(f"Decision {decision['id']} at {when} ({decision['channel']}, {decision['status']}): "
                     f"{detail.get('reason', 'No reason was recorded.')}")
        if evidence := detail.get("evidence"):
            lines.append("Evidence: " + ", ".join(map(str, evidence)))
    if not latest_only:
        for row in state["reminders"]:
            retry = (f"; review/retry at {datetime.fromtimestamp(row['next_retry']):%I:%M %p}"
                     if row.get("next_retry") else "")
            lines.append(f"Reminder {row['id']}: {row['status']}; desktop {row['desktop_status']}, "
                         f"Telegram {row['telegram_status']}; attempts {row['attempts']}{retry}. "
                         f"{row['reason']}")
        if any(row["status"] in {"failed", "uncertain"} for row in state["reminders"]):
            lines.append("Say 'retry failed reminders' for a fresh brain review. "
                         "An uncertain submission may already have reached its destination.")
    return "\n".join(lines)
