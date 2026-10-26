"""
services/watch/auto.py

The "it's done" alerts FRIDAY gives without being asked, plus the loop that runs every watch
(started from interfaces/api/app.py's lifespan):
  - Downloads: a browser's partial file (.crdownload / .part / .partial) in Downloads becomes
    the real file → "Downloaded setup.exe (1.2 GB)." Only downloads that took a minute or more.
    A new document that looks like a subject's or project's also gets "Move it to College\\DBMS?"
    buttons, however fast it came (services/files/filing.py).
  - Screenshots: one taken during a class or a subject's study session is moved to
    College\\<Subject>\\Screenshots (services/files/filing.py) — told once per subject a day.
  - Heavy work: CPU or GPU ≥ 80% for HEAVY_WORK_MINUTES, then calm → "Heavy work finished —
    GPU busy for 42 min." Not while gaming or fullscreen (a game ending isn't news).
The asked-for watches are in asked.py; Claude Code and terminal alerts arrive through the API (done.py).
"""

import asyncio
import os
import time
from pathlib import Path

import psutil

from core.config import config
from core.logger import logger
from services.network.status import network
from services.watch import asked, done

CHECK_SECONDS = 10
LOAD_EVERY_SECONDS = 30
DOWNLOADS = Path.home() / "Downloads"
PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".opdownload")
DOWNLOAD_MIN_SECONDS = 60
HIGH_LOAD, LOW_LOAD = 80, 30  # %
CALM_SECONDS = 120            # below LOW_LOAD this long: the work is over
UNSETTLED_SECONDS = 300       # or below HIGH_LOAD this long (normal use afterwards)


def _size(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB" if n >= 1024 ** 2 else f"{max(n // 1024, 1)} KB"


class Downloads:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or DOWNLOADS
        self._partial: dict[str, float] = {}  # partial file name → when first seen
        self._known: set[str] | None = None   # finished files already there (None: not looked yet)

    def check(self, now: float | None = None) -> list[tuple[Path, bool]]:
        """
        Blocking. Files that just appeared in the folder, finished, with whether each took
        DOWNLOAD_MIN_SECONDS or more. Files already there when FRIDAY starts don't count.
        Lists the top of the folder only (Downloads: ~76 entries, well under a millisecond).
        """
        now = time.time() if now is None else now
        try:
            names = {e.name for e in os.scandir(self.folder) if e.is_file()}
        except OSError:
            return []
        partials = {n for n in names if n.lower().endswith(PARTIAL_SUFFIXES)}
        busy = {p[:p.rfind(".")] for p in partials}  # Firefox's empty placeholder while the .part fills
        ready = names - partials - busy
        slow = {name[:name.rfind(".")] for name, seen in self._partial.items()  # Chrome's "Unconfirmed 1.crdownload"
                if name not in partials and now - seen >= DOWNLOAD_MIN_SECONDS}  # has no real name: never matches
        self._partial = {name: self._partial.get(name, now) for name in partials}
        new = [] if self._known is None else sorted(ready - self._known)
        self._known = ready
        return [(self.folder / name, name in slow) for name in new]


class HeavyWork:
    def __init__(self):
        self._since = self._last_high = self._low_since = None
        self._what: set[str] = set()
        self._gaming = False

    def check(self, cpu: float, gpu: float | None, gaming: bool, now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        load = max(cpu, gpu or 0)
        if load >= HIGH_LOAD:
            if self._since is None:
                self._since, self._what, self._gaming = now, set(), False
            self._what |= {part for part, value in (("CPU", cpu), ("GPU", gpu or 0)) if value >= HIGH_LOAD}
            self._last_high, self._low_since = now, None
            self._gaming |= gaming
            return None
        if self._since is None:
            return None
        self._gaming |= gaming
        if load < LOW_LOAD:
            self._low_since = self._low_since or now
        else:
            self._low_since = None
        if not ((self._low_since and now - self._low_since >= CALM_SECONDS) or now - self._last_high >= UNSETTLED_SECONDS):
            return None
        busy, what, gaming_ = self._last_high - self._since, self._what, self._gaming
        self._since = self._last_high = self._low_since = None
        if gaming_ or busy < config.HEAVY_WORK_MINUTES * 60:
            return None
        return f"Heavy work finished — {' and '.join(sorted(what))} busy for {done.duration(busy)}."


def read_load() -> tuple[float, float | None, bool]:
    """Blocking (nvidia-smi). CPU % since the last call, the busiest GPU's %, gaming/fullscreen."""
    from services.automation.system_stats import _gpus
    from services.proactive.watcher import fullscreen_or_gaming  # avoid an import cycle at startup

    loads = [gpu.load for gpu in _gpus()]
    return psutil.cpu_percent(None), max(loads, default=None), fullscreen_or_gaming()


def announce(path: Path, slow: bool) -> str | None:
    """A new download (blocking: filing reads its first page). Shows a filing question, or returns the
    plain "Downloaded …" alert for a slow download; None for a quick one nobody needs to hear about."""
    from services.files import filing
    from services.proactive import buttons
    from services.reminders.service import show_toast  # avoid an import cycle at startup
    from services.mind import notifications

    try:
        size = _size(path.stat().st_size)
    except OSError:
        return None  # already moved or deleted
    folder = filing.suggest(path)
    if folder is None:
        return f"Downloaded {path.name} ({size})." if slow else None
    lead = f"Downloaded {path.name} ({size})." if slow else f"New download: {path.name}."
    asyncio.run(notifications.notify(f"{lead} Move it to {filing.describe(folder)}?",
                buttons.offer("file_move", path=str(path), folder=str(folder)),
                kind="filing", transport=show_toast, public=False))
    return None


_told_screenshots: set[tuple[str, str]] = set()  # (subject, day) already told about


def file_screenshot(path: Path) -> None:
    """A new screenshot (blocking): file it with its subject; the first one each day gets a toast."""
    from datetime import date
    from services.files import filing
    from services.reminders.service import show_toast  # avoid an import cycle at startup

    folder = filing.file_screenshot(path)
    if folder is None:
        return
    subject = folder.parent.name
    if (subject, date.today().isoformat()) not in _told_screenshots:
        _told_screenshots.add((subject, date.today().isoformat()))
        show_toast(done.TITLE, f"Screenshots during {subject} go to {filing.describe(folder)}.")


async def run_watches() -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan."""
    logger.info("Done alerts started")
    from services.automation.system_control import SCREENSHOT_DIR

    downloads, screenshots, heavy = Downloads(), Downloads(SCREENSHOT_DIR), HeavyWork()
    last_load = 0.0
    while True:
        try:
            now = time.time()
            alerts = []
            for path, slow in await asyncio.to_thread(downloads.check, now):
                if alert := await asyncio.to_thread(announce, path, slow):
                    alerts.append(alert)
            for path, _ in await asyncio.to_thread(screenshots.check, now):
                await asyncio.to_thread(file_screenshot, path)
            alerts += await asyncio.to_thread(asked.check, now, network.online)
            if now - last_load >= LOAD_EVERY_SECONDS:
                last_load = now
                cpu, gpu, gaming = await asyncio.to_thread(read_load)
                if alert := heavy.check(cpu, gpu, gaming, now):
                    alerts.append(alert)
            for text in alerts:
                await asyncio.to_thread(done.notify, text)
        except Exception as e:
            logger.error(f"Done alerts check failed: {e}", exc_info=True)
        await asyncio.sleep(CHECK_SECONDS)
