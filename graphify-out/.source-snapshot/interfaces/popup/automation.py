"""Poll only an explicitly started task; a newer command invalidates old UI replies."""

import time

from interfaces.tray import backend
from services.browser.commands import match_command


def follow(text, publish, is_current, job_id):
    command = match_command(text)
    if not command or command.kind not in {"browser", "desktop", "research", "yes", "stop"}:
        return
    for _ in range(610):
        if not is_current():
            return
        try:
            result = backend.automation_status()
        except backend.BackendError:
            return
        current = result.get("job_id")
        if current != job_id:
            return
        if not is_current():
            return
        publish(result["response"], result["awaiting_reply"])
        if not result["active"] or result["awaiting_reply"]:
            return
        time.sleep(1)
