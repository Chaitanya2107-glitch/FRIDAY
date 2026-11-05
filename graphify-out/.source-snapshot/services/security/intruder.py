"""
services/security/intruder.py

Wrong-password alert: when someone fails to sign in to this laptop (wrong password or PIN at the
lock screen), take one webcam photo and send it to the owner on Telegram:
"Wrong password on your laptop at 14:32" + the photo. Photos are also kept in memory/intruder/.

How it's triggered: FRIDAY itself runs as the user and can't read the Security log, so a Windows
scheduled task does it. The task runs on Security event 4625 ("an account failed to log on") as
SYSTEM — that also covers the sign-in screen right after boot, before anyone has logged in —
and starts `pythonw -m services.security.intruder`. Setting it up needs admin rights once:
    python -m services.security.intruder --install     (a UAC prompt appears; press Yes)
    python -m services.security.intruder --uninstall
    python -m services.security.intruder --test        (photo + Telegram now, to check it works)
--install also switches on auditing of failed logons, without which Windows doesn't log 4625.
"""

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from core.config import config
from core.logger import logger

TASK_NAME = "FRIDAY Wrong Password Alert"
PHOTO_DIR = config.MEMORY_DIR / "intruder"
MIN_GAP_SECONDS = 20       # several wrong tries in a row: one photo per 20 s is plenty
WARMUP_FRAMES = 10         # the first frames are dark while the camera adjusts its exposure
PHOTO_WIDTH = 1280
LOGON_AUDIT_GUID = "{0CCE9215-69AE-11D9-BED3-505054503030}"  # the "Logon" audit subcategory, in any Windows language
ROOT = config.ROOT_DIR
PYTHONW = ROOT / "venv" / "Scripts" / "pythonw.exe"


# ── Photo ─────────────────────────────────────────────────────────────────────

def camera_name() -> str:
    """The first webcam's name, as DirectShow knows it."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-PnpDevice -Class Camera,Image -Status OK | Select-Object -First 1).FriendlyName"],
        capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    name = result.stdout.strip()
    if not name:
        raise RuntimeError("no webcam found")
    return name


def take_photo(path: Path) -> Path:
    import av

    container = av.open(f"video={camera_name()}", format="dshow", options={"rtbufsize": "64M"})
    try:
        frame = None
        for i, frame in enumerate(container.decode(video=0)):
            if i >= WARMUP_FRAMES:
                break
    finally:
        container.close()
    if frame is None:
        raise RuntimeError("the webcam gave no picture")
    image = frame.to_image()
    if image.width > PHOTO_WIDTH:
        image = image.resize((PHOTO_WIDTH, round(image.height * PHOTO_WIDTH / image.width)))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=85)
    return path


# ── The alert ─────────────────────────────────────────────────────────────────

def _too_soon(now: float) -> bool:
    last = PHOTO_DIR / ".last"
    try:
        if now - float(last.read_text()) < MIN_GAP_SECONDS:
            return True
    except (OSError, ValueError):
        pass
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    last.write_text(str(now))
    return False


def alert(test: bool = False, now: datetime | None = None, photo=take_photo, telegram=None) -> str:
    """Take the photo and send it. Never raises: whatever works is done, the rest is logged."""
    from services.telegram import client

    telegram = telegram or client
    now = now or datetime.now()
    if not test and _too_soon(now.timestamp()):
        return "skipped: another alert just went out"
    text = ("Test: this is what a wrong-password alert looks like" if test
            else f"Wrong password on your laptop at {now:%H:%M} ({now:%a %d %b})")
    path = PHOTO_DIR / f"{now:%Y-%m-%d %H-%M-%S}.jpg"
    try:
        photo(path)
    except Exception as e:  # no camera, camera busy, blocked by privacy settings
        logger.warning(f"Wrong-password alert: no photo ({e})")
        path, text = None, text + " — couldn't take a photo."
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_USER_ID):
        logger.warning("Wrong-password alert: Telegram isn't set up, photo kept locally only")
        return "no Telegram"
    try:
        if path:
            telegram.send_file(config.TELEGRAM_USER_ID, path, photo=True, caption=text)
        else:
            telegram.send(config.TELEGRAM_USER_ID, text)
    except Exception as e:  # offline at the lock screen: the photo stays in memory/intruder/
        logger.warning(f"Wrong-password alert: couldn't send it to Telegram ({e})")
        return "not sent"
    logger.info("Wrong-password alert sent")
    return "sent"


# ── Setup (admin, once) ───────────────────────────────────────────────────────

def task_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>F.R.I.D.A.Y: photo + Telegram message when someone types a wrong password.</Description></RegistrationInfo>
  <Triggers>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="Security"&gt;&lt;Select Path="Security"&gt;*[System[(EventID=4625)]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2M</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHONW}</Command>
      <Arguments>-m services.security.intruder</Arguments>
      <WorkingDirectory>{ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _run_elevated(commands: list[str]) -> None:
    """Run PowerShell lines as admin: Windows shows a UAC prompt. Waits for it to finish."""
    script = Path(tempfile.gettempdir()) / "friday_intruder_setup.ps1"
    script.write_text("\n".join(["$ErrorActionPreference = 'Stop'", *commands]), encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
                    f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"{script}\"'"], check=True)


def install() -> None:
    xml = Path(tempfile.gettempdir()) / "friday_intruder_task.xml"
    xml.write_text(task_xml(), encoding="utf-16")
    _run_elevated([
        f"auditpol /set /subcategory:'{LOGON_AUDIT_GUID}' /failure:enable | Out-Null",
        f"schtasks /Create /TN '{TASK_NAME}' /XML '{xml}' /F | Out-Null",
    ])


def uninstall() -> None:
    _run_elevated([f"schtasks /Delete /TN '{TASK_NAME}' /F | Out-Null"])


def installed() -> bool:
    """A SYSTEM task can't be read by a normal user: "Access is denied" means it's there."""
    result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode == 0 or "access is denied" in (result.stderr or "").lower()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--install":
        install()
        print("Installed." if installed() else "Not installed (was the UAC prompt declined?).")
    elif arg == "--uninstall":
        uninstall()
        print("Removed." if not installed() else "Still installed.")
    else:
        print(alert(test=arg == "--test"))
