"""
services/reminders/service.py

Local reminders for F.R.I.D.A.Y.

Stored in the same SQLite file as chat memory, so they survive restarts.
A background loop inside the API process (started in interfaces/api/app.py)
checks every few seconds and delivers due reminders as a Windows notification
plus FRIDAY speaking them aloud. Reminders that came due while FRIDAY was off
are delivered on the next start, marked as late.
"""

import asyncio
import base64
import contextvars
import functools
import os
import sqlite3
import subprocess
import time
import winreg
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from xml.sax.saxutils import quoteattr

from core.config import config
from core.errors import FridayError
from core.logger import logger
from services.reminders.parser import ReminderParseError, describe_due, parse_reminder
from services.reminders.delivery_state import DeliveryState
from services.voice.tts import tts

POLL_SECONDS = 5
LATE_AFTER_SECONDS = 120
NOTIFICATION_TITLE = "F.R.I.D.A.Y reminder"
TOAST_APP_ID = "FRIDAY.Assistant"
TOAST_ICON = Path(__file__).resolve().parents[2] / "assets" / "friday.png"
POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# Shown under FRIDAY's own app ID (name + icon registered in HKCU by
# _toast_app_id, so it says F.R.I.D.A.Y, not Windows PowerShell); PowerShell
# only delivers it. Text arrives via environment variables and is
# XML-escaped, so reminder text can never inject into the script or the XML.
# Extra buttons (friday:// links, services/proactive/buttons.py) arrive as XML
# built and escaped by show_toast.
_TOAST_SCRIPT = r"""
$ProgressPreference = 'SilentlyContinue'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$title = [System.Security.SecurityElement]::Escape($env:FRIDAY_TOAST_TITLE)
$body = [System.Security.SecurityElement]::Escape($env:FRIDAY_TOAST_BODY)
$actions = $env:FRIDAY_TOAST_ACTIONS
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$expire = [int]$env:FRIDAY_TOAST_EXPIRE
if ($expire -gt 0) { $open = "<toast>"; $dismiss = "" } else { $open = "<toast scenario='reminder'>"; $dismiss = "<action content='Dismiss' arguments='dismiss' activationType='system'/>" }
$xml.LoadXml("$open<visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual><actions>$actions$dismiss</actions></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
if ($expire -gt 0) { $toast.ExpirationTime = [DateTimeOffset]::Now.AddSeconds($expire) }
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:FRIDAY_TOAST_APPID).Show($toast)
"""


TRANSIENT_SECONDS = 8  # a command's confirmation disappears after this
_transport_result = contextvars.ContextVar("reminder_transport_result", default=None)


class ReminderError(FridayError):
    """A user-facing problem with a reminder request (bad time, unknown number)."""
    def __init__(self, message: str):
        super().__init__(message, status_code=400)


class Reminder(NamedTuple):
    id: int
    text: str
    due_at: float  # Unix timestamp


class ReminderService(DeliveryState):
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.MEMORY_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    text         TEXT NOT NULL,
                    due_at       REAL NOT NULL,
                    created_at   REAL NOT NULL,
                    delivered_at REAL
                )
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_from_message(self, message: str, now: datetime | None = None) -> str:
        now = now or datetime.now()
        try:
            task, due = parse_reminder(message, now)
        except ReminderParseError as e:
            raise ReminderError(str(e))

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reminders (text, due_at, created_at) VALUES (?, ?, ?)",
                (task, due.timestamp(), now.timestamp()),
            )
        logger.info(f"Reminder set for {due:%Y-%m-%d %H:%M}")
        return f"Okay, I'll remind you at {describe_due(due, now)}: {task}."

    def snooze(self, text: str, minutes: int) -> str:
        """The same reminder again in `minutes` (the notification's Snooze button)."""
        due = time.time() + minutes * 60
        with self._connect() as conn:
            conn.execute("INSERT INTO reminders (text, due_at, created_at) VALUES (?, ?, ?)", (text, due, time.time()))
        return f"Okay, I'll remind you again in {minutes} minutes: {text}."

    def pending(self) -> list[Reminder]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, text, due_at FROM reminders WHERE delivered_at IS NULL ORDER BY due_at, id"
            ).fetchall()
        return [Reminder(*row) for row in rows]

    def list_message(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        upcoming = self.pending()
        if not upcoming:
            return "You don't have any reminders."
        lines = [
            f"{i}. {r.text} — {describe_due(datetime.fromtimestamp(r.due_at), now)}"
            for i, r in enumerate(upcoming, start=1)
        ]
        return "Your reminders:\n" + "\n".join(lines)

    def cancel(self, number: int) -> str:
        """Cancel by the number shown in list_message (1 = soonest)."""
        upcoming = self.pending()
        if not upcoming:
            raise ReminderError("You don't have any reminders.")
        if not 1 <= number <= len(upcoming):
            raise ReminderError(f'There\'s no reminder {number}. Say "list reminders" to see them.')

        reminder = upcoming[number - 1]
        with self._connect() as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder.id,))
        return f"Cancelled reminder {number}: {reminder.text}."

    def cancel_all(self) -> str:
        with self._connect() as conn:
            count = conn.execute("DELETE FROM reminders WHERE delivered_at IS NULL").rowcount
        if count == 0:
            return "You don't have any reminders."
        return f"Cancelled {count} reminder{'s' if count != 1 else ''}."

    def take_due(self, now_ts: float) -> list[Reminder]:
        """Claim due reminders for a bounded lease; this does not acknowledge delivery."""
        return [claim.reminder for claim in self._claim_due(now_ts)]


@functools.cache
def _toast_app_id() -> str:
    """Register FRIDAY's notification name and icon (per user, no admin). Falls back to PowerShell's ID."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{TOAST_APP_ID}") as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "F.R.I.D.A.Y")
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(TOAST_ICON))
        return TOAST_APP_ID
    except OSError as e:
        logger.warning(f"Couldn't register FRIDAY's notification name/icon, using PowerShell's: {e}")
        return POWERSHELL_APP_ID


def show_toast(title: str, body: str, buttons: list[tuple[str, str]] | None = None, transient: bool = False,
               *, cognition_public: bool = False, mirror_telegram: bool = True) -> bool:
    """Record the exact local notification and whether Windows accepted it."""
    from services.mind.cognition import cognition

    with cognition.operation("notification", "desktop", f"{title}\n{body}", public=cognition_public) as event:
        accepted = _show_toast(title, body, buttons, transient, mirror_telegram=mirror_telegram)
        event.finish("submitted" if accepted else "failed")
        return accepted


def _show_toast(title: str, body: str, buttons: list[tuple[str, str]] | None = None, transient: bool = False,
                *, mirror_telegram: bool = True) -> bool:
    """
    Show a Windows notification, with optional (label, link) buttons before Dismiss — and on Telegram too
    while the user is away (services/telegram/client.py). Failures are logged, never raised.
    transient=True (a command's "Opening Chrome."): shown briefly, then gone — from the notification centre
    too. Otherwise it stays on screen until dismissed (answers, reminders, FRIDAY's own questions).
    """
    from services.telegram import client as telegram  # avoid an import cycle at startup

    if not transient and mirror_telegram:  # a command's confirmation isn't worth a phone buzz
        telegram.mirror(title, body, buttons)
    encoded = base64.b64encode(_TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")
    actions = "".join(
        f"<action content={quoteattr(label)} arguments={quoteattr(link)} activationType='protocol'/>"
        for label, link in buttons or []
    )
    env = {**os.environ, "FRIDAY_TOAST_APPID": _toast_app_id(), "FRIDAY_TOAST_TITLE": title, "FRIDAY_TOAST_BODY": body,
           "FRIDAY_TOAST_ACTIONS": actions, "FRIDAY_TOAST_EXPIRE": str(TRANSIENT_SECONDS if transient else 0)}
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        # A timeout can occur after Windows accepted the toast. The scheduler must
        # retain this uncertainty instead of automatically repeating an external effect.
        if isinstance(e, subprocess.TimeoutExpired) and (outcome := _transport_result.get()) is not None:
            outcome["uncertain"] = True
        logger.warning(f"Couldn't show reminder notification: {e}")
        return False
    if result.returncode != 0 or result.stderr.strip():
        logger.warning("Reminder notification failed (exit=%s, stderr=%s)", result.returncode, bool(result.stderr.strip()))
        return False
    return True


def _submit_desktop(body, offers):
    outcome = {"uncertain": False}
    token = _transport_result.set(outcome)
    try:
        return show_toast(NOTIFICATION_TITLE, body, offers, mirror_telegram=False), outcome
    finally:
        _transport_result.reset(token)


def _reminder_body(reminder: Reminder) -> str:
    body = reminder.text
    if time.time() - reminder.due_at > LATE_AFTER_SECONDS:
        body += f" (was due {describe_due(datetime.fromtimestamp(reminder.due_at), datetime.now())})"

    return body


async def _deliver_claim(service, claim):
    from services.mind import reminder_review
    from services.proactive import buttons, watcher
    from services.telegram import client as telegram
    from services import body_state

    reminder = claim.reminder
    review = await reminder_review.review(reminder, datetime.now())
    if not service._active(claim):
        return
    service._decision(claim, review)
    if review.action != "send":
        service._hold(claim, review)
        return
    review = await reminder_review.recheck(reminder, review, datetime.now())
    if not service._active(claim):
        return
    service._decision(claim, review)
    if review.action != "send":
        service._hold(claim, review)
        return
    body = _reminder_body(reminder)
    offers = buttons.offer("reminder", text=reminder.text)
    failed = False
    uncertain = False
    if claim.desktop_status != "submitted":
        if not service._state(claim, status="submitting") or not service._active(claim):
            return
        accepted, outcome = await asyncio.to_thread(_submit_desktop, body, offers)
        uncertain = outcome["uncertain"]
        if accepted is not True:
            failed = True
        service._state(claim, desktop_status="uncertain" if uncertain else "submitted" if accepted is True else "failed",
                       status="reviewing")
    if not service._active(claim):
        return
    if claim.telegram_status != "submitted":
        if review.allow_telegram:
            review = await reminder_review.recheck(reminder, review, datetime.now())
            if not service._active(claim):
                return
            service._decision(claim, review)
            if review.action != "send":
                service._hold(claim, review)
                return
        if review.allow_telegram:
            if not service._state(claim, status="submitting") or not service._active(claim):
                return
            phone_outcome = {}
            accepted = await asyncio.to_thread(telegram.mirror, NOTIFICATION_TITLE, body, offers, outcome=phone_outcome)
            phone_uncertain = phone_outcome.get("uncertain", False)
            uncertain = uncertain or phone_uncertain
            if accepted is False:
                failed = True
            service._state(claim, telegram_status="uncertain" if phone_uncertain else
                           {True: "submitted", False: "failed", None: "skipped"}[accepted],
                           status="reviewing")
        else:
            service._state(claim, telegram_status="skipped")
    if uncertain:
        service._finish_decision(claim, "uncertain")
        service._state(claim, status="uncertain", token=None, next_retry=None,
                       reason="Notification submission was interrupted; delivery may have occurred. Explicit retry required.")
        return
    if failed:
        service._failed(claim, "One or more notification destinations did not acknowledge submission")
        return
    if not service._complete(claim):
        return
    logger.info("Reminder %s notification submission acknowledged", reminder.id)
    try:
        speech_review = await reminder_review.recheck(reminder, review, datetime.now()) if review.allow_speech else review
        can_speak = speech_review.action == "send" and speech_review.allow_speech
        body_state.push("alert", f"Reminder: {body}")
        if can_speak and not await asyncio.to_thread(watcher.is_busy):
            await tts.speak(f"Reminder: {body}")
            service._state(claim, speech_status="completed")
        else:
            service._state(claim, speech_status="skipped")
    except Exception:
        service._state(claim, speech_status="failed")
        logger.warning("Reminder %s feedback failed after notification submission", reminder.id)


async def deliver_due(service: ReminderService) -> None:
    # Claim just before reviewing each item, so a long queue cannot outlive its leases.
    for _ in range(20):
        claims = service._claim_due(time.time(), limit=1)
        if not claims:
            break
        claim = claims[0]
        try:
            await _deliver_claim(service, claim)
        except Exception:
            service._interrupted(claim)
            logger.error("Problem delivering reminder %s", claim.reminder.id)


async def run_scheduler(service: ReminderService) -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan."""
    logger.info("Reminder scheduler started")
    while True:
        try:
            await deliver_due(service)
        except Exception as e:
            # A bad tick (e.g. database locked) must not kill the loop.
            logger.error(f"Reminder scheduler error: {e}", exc_info=True)
        await asyncio.sleep(POLL_SECONDS)


# ── Singleton ─────────────────────────────────────────────────────────────────
reminders = ReminderService()
