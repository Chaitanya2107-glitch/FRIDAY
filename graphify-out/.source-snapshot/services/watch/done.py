"""
services/watch/done.py

"It's done" alerts from Claude Code and the terminal. Both report to FRIDAY's local API
(interfaces/api/routes/done.py) through small hooks outside this repo:
  - Claude Code: UserPromptSubmit / Stop / PermissionRequest hooks in ~/.claude/settings.json
    run `curl.exe … /api/v1/done/claude` with the hook's JSON
  - PowerShell: the prompt function in the user's profile posts commands that ran ≥ 1 min
    to /api/v1/done/terminal

Completion candidates pass through FRIDAY's notification judgment before delivery;
outstanding Claude permission requests remain direct alerts. Approved notices also reach
Telegram once the user has been away TELEGRAM_AWAY_MINUTES. A terminal notice is skipped while the user
is at the laptop with a terminal in front: they can see it already.
"""

import asyncio
import time
from pathlib import Path

from core.config import config
from core.logger import logger

TITLE = "F.R.I.D.A.Y"
AT_LAPTOP_SECONDS = 60
TERMINAL_APPS = {"windowsterminal", "powershell", "pwsh", "cmd", "conhost", "code"}
COMMAND_PREVIEW = 60

_started: dict[str, float] = {}  # Claude Code session id → when its current prompt was sent


def duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return f"{int(seconds)} s"
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def notify(text: str, about_terminal: bool = False, links=None) -> None:
    """Review a completion in its worker thread; permission requests remain direct. Never raises."""
    from services.activity.log import foreground_app, idle_seconds
    from services.reminders.service import show_toast  # avoid an import cycle at startup
    from services.mind import notifications

    try:
        if about_terminal and idle_seconds() < AT_LAPTOP_SECONDS and foreground_app() in TERMINAL_APPS:
            logger.info(f"Done alert skipped (terminal in front): {text}")
            return
        logger.info(f"Done alert: {text}")
        if text.startswith("Claude needs your permission in "):
            show_toast(TITLE, text, links)
        else:
            asyncio.run(notifications.notify(text, links, kind="work_completion", transport=show_toast, public=False))
    except Exception as e:
        logger.warning(f"Couldn't show the done alert: {e}")


def _project(cwd) -> str:
    return Path(str(cwd)).name if cwd else "Claude Code"


def claude_event(payload: dict, now: float | None = None) -> str | None:
    """One Claude Code hook call → the alert to show, if any."""
    now = time.time() if now is None else now
    event, session = payload.get("hook_event_name"), str(payload.get("session_id", ""))
    if event == "UserPromptSubmit":
        _started[session] = now
    elif event == "Stop":
        started = _started.pop(session, None)  # unknown (FRIDAY started mid-reply): not reported
        if started is not None and now - started >= config.DONE_MIN_MINUTES * 60:
            return f"Claude finished in {_project(payload.get('cwd'))} after {duration(now - started)}."
    elif event == "PermissionRequest":
        tool = payload.get("tool_name")
        return f"Claude needs your permission in {_project(payload.get('cwd'))}" + (f" ({tool})." if tool else ".")
    return None


def terminal_event(command: str, seconds: float, ok: bool) -> str | None:
    """A PowerShell command finished → the alert, if it ran long enough."""
    if seconds < config.DONE_MIN_MINUTES * 60:
        return None
    command = " ".join(command.split())
    if len(command) > COMMAND_PREVIEW:
        command = command[:COMMAND_PREVIEW - 1] + "…"
    return f"{command} finished after {duration(seconds)}" + ("." if ok else " — it failed.")
