"""One background observation at a time, fenced by controls, indicator and window."""
import asyncio
from datetime import datetime
import re
import threading
import time
import uuid

from core.logger import logger
from services.activity.log import idle_seconds
from services.browser.worker import ProcessRuntime
from services.screen_watch import capture, create_reader, inference
from services.screen_watch.store import ScreenStore


class ScreenWatch:
    def __init__(self, store=None):
        self.store = store or ScreenStore()
        self.session = uuid.uuid4().hex
        self._indicator, self._lease = None, 0
        self._generation, self._scope, self._epoch = 0, None, None
        self._state, self._job = "off", None
        self._next, self._settled = 0.0, 0.0
        self._prune_at = 0.0
        self._query_lock = asyncio.Lock()
        self._stopped = threading.Event()
        self._attention, self._focus_key, self._focus_since = None, None, 0.0
        self.dialogue, self.dialogue_epoch, self.dialogue_at = [], None, 0.0

    def control(self, action):
        self.store.control(action)
        self._generation += 1
        self._attention, self._focus_key = None, None
        self.dialogue.clear()
        self._next = 0
        self._state = "waiting_for_indicator" if action in {"start", "resume"} else "paused" if action == "pause" else "off"
        if self._job:
            self._job.get_loop().call_soon_threadsafe(self._job.cancel)

    def heartbeat(self, hwnd):
        badge = capture.indicator(hwnd)
        self._indicator = badge
        self._lease = time.monotonic() + 6 if badge else 0
        return bool(badge)

    def rules_changed(self):
        self.store.invalidate()
        self._generation += 1
        self._attention, self._focus_key = None, None
        self.dialogue.clear()
        self._next = 0
        if self._job:
            self._job.get_loop().call_soon_threadsafe(self._job.cancel)

    def visible(self):
        return bool(time.monotonic() < self._lease and capture.indicator_valid(self._indicator))

    def status(self):
        cfg = self.store.settings()
        state = ("off" if not cfg["enabled"] else "paused" if cfg["paused"] else
                 "waiting_for_indicator" if not self.visible() else self._state)
        return {"enabled": bool(cfg["enabled"]), "paused": bool(cfg["paused"]), "state": state,
                "epoch": cfg["epoch"], "local_only": True}

    def _allowed(self, window, epoch, generation):
        cfg = self.store.settings()
        current = capture.foreground()
        return bool(not self._stopped.is_set() and cfg["enabled"] and not cfg["paused"]
                    and cfg["epoch"] == epoch and generation == self._generation and self.visible()
                    and not capture.blocked(current) and current["scope"] == window["scope"])

    async def observe(self, window, epoch, generation):
        stopped = threading.Event()
        reader = ProcessRuntime(create_reader, (), stopped, timeout=8)
        frame = {}
        saved = False
        try:
            if not self._allowed(window, epoch, generation):
                return
            self._state = "reading_text"
            frame = await reader.call("read", window, self._indicator)
            if frame.get("blocked"):
                self._state = frame["blocked"]
                return
            captured = datetime.now()
            if not self._allowed(window, epoch, generation):
                return
            text = frame.get("text", "")
            result = None
            if len(text.strip()) >= 80:
                self._state = "interpreting_text"
                result = await inference.analyze(window["app"], text)
            if result and result.sensitive:
                self._state = "private_window"
                return
            source = "accessible_text"
            if not result or result.needs_vision:
                if not self._allowed(window, epoch, generation):
                    return
                self._state = "checking_vision"
                frame = await reader.call("image", window, self._indicator)
                if frame.get("blocked"):
                    self._state = frame["blocked"]
                    return
                if not self._allowed(window, epoch, generation):
                    return
                captured = datetime.now()
                result = await inference.analyze(window["app"], frame.get("text", ""), frame["image"])
                source = "vision"
            if result.sensitive:
                self._state = "private_window"
                return
            if result.needs_vision and source == "vision":
                self._state = "unreadable"
                return
            if not self._allowed(window, epoch, generation):
                return
            # Recheck accessibility privacy and URL identity after the model wait.
            after = await reader.call("read", window, self._indicator)
            if (after.get("blocked") or after.get("url_hash") != frame.get("url_hash")
                    or after.get("content_hash") != frame.get("content_hash")):
                self._state = after.get("blocked", "screen_changed")
                return
            if not self._allowed(window, epoch, generation):
                return
            evidence_scope = {**window["scope"], "url_hash": frame.get("url_hash"), "content_hash": frame.get("content_hash")}
            saved = self.store.save(epoch=epoch, session=self.session, scope=evidence_scope, app=window["app"],
                                    summary=result.summary, activity=result.activity, source=source, at=captured,
                                    subject=result.subject, kind=result.kind, generation=generation)
            if saved:
                focus = (str(window["scope"]), frame.get("url_hash"), result.subject.casefold(), result.kind, epoch)
                gap = (captured - self._attention["at"]).total_seconds() if self._attention else -1
                if focus != self._focus_key or not 0 <= gap <= 75:
                    self._focus_key, self._focus_since = focus, time.monotonic()
                self._attention = {"window": window, "at": captured, "epoch": epoch,
                                   "generation": generation, "kind": result.kind}
                self._state = "watching"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._state = "unavailable"
            self._next = time.monotonic() + 60
            text = str(error)
            known = {"Local screen model is unavailable", "A local vision-capable model is required",
                     "Incomplete screen interpretation", "Screen awareness requires a local Ollama endpoint",
                     "Screen awareness requires a local model", "Screen observation is too large",
                     "Private content is excluded from screen analysis"}
            safe = type(error) is ValueError and (text in known or re.fullmatch(
                r"Automation operation unavailable: [A-Za-z_][A-Za-z_0-9]{0,79}|Automation worker exited", text))
            logger.debug("Local screen observation unavailable (%s)", text if safe else type(error).__name__)
        finally:
            if not saved:
                self._attention, self._focus_key = None, None
            frame.clear()  # no raw image or extracted text retained by the service
            stopped.set()
            try:
                await reader.aclose()
            except Exception as error:
                logger.debug("Screen capture worker cleanup (%s)", type(error).__name__)

    async def tick(self):
        if time.monotonic() >= self._prune_at:
            self.store.prune()
            self._prune_at = time.monotonic() + 60
        cfg = self.store.settings()
        window = capture.foreground() if cfg["enabled"] and not cfg["paused"] and self.visible() else None
        safe = not capture.blocked(window)
        away = idle_seconds() >= 300 if safe else False
        scope = window["scope"] if safe and not away else None
        now = time.monotonic()
        if scope != self._scope or cfg["epoch"] != self._epoch:
            self._scope, self._epoch = scope, cfg["epoch"]
            self._generation += 1
            self._attention, self._focus_key = None, None
            self._settled, self._next = now + 2, 0
            if self._job:
                self._job.cancel()
        if self._job and self._job.done():
            await asyncio.gather(self._job, return_exceptions=True)
            self._job = None
        if not scope:
            self._state = "away" if away else "private_window" if window else "waiting_for_indicator"
            return
        if self._job is None and now >= max(self._settled, self._next):
            self._next = now + 30
            self._job = asyncio.create_task(self.observe(window, cfg["epoch"], self._generation))

    async def run(self):
        self._stopped.clear()
        try:
            while not self._stopped.is_set():
                try:
                    await self.tick()
                except Exception as error:
                    self._state = "unavailable"
                    logger.debug("Screen awareness tick unavailable (%s)", type(error).__name__)
                await asyncio.sleep(1)
        finally:
            self._stopped.set()
            self._lease = 0
            if self._job:
                self._job.cancel()
                await asyncio.gather(self._job, return_exceptions=True)
            self._job = None

    async def current(self):
        cfg = self.store.settings()
        window = capture.foreground()
        if not cfg["enabled"] or cfg["paused"] or not self.visible() or capture.blocked(window):
            return None
        if self._query_lock.locked():
            return None
        async with self._query_lock:
            stopped = threading.Event()
            reader = ProcessRuntime(create_reader, (), stopped, timeout=8)
            generation = self._generation
            try:
                frame = await reader.call("read", window, self._indicator)
                if frame.get("blocked") or not self._allowed(window, cfg["epoch"], generation):
                    return None
                scope = {**window["scope"], "url_hash": frame.get("url_hash"), "content_hash": frame.get("content_hash")}
                return self.store.latest(scope, self.session, cfg["epoch"])
            except Exception:
                return None
            finally:
                stopped.set()
                try:
                    await reader.aclose()
                except Exception as error:
                    logger.debug("Screen query worker cleanup (%s)", type(error).__name__)

    def local_context(self):
        """Private background learning, already available before an owner asks anything."""
        cfg = self.store.settings()
        if not cfg["enabled"] or cfg["paused"] or not self.visible():
            return None
        context = self.store.learned_context()
        # Read policy after the database lock is released (settings writes take the opposite order).
        from services.screen_watch.app_rules import rules
        context = {key: [row for row in rows if rules.allowed(row['app'])] for key, rows in context.items()}
        if not any(context.values()) or self.store.settings()["epoch"] != cfg["epoch"] or not self.visible():
            return None
        return {"epoch": cfg["epoch"], "as_of": datetime.now().isoformat(timespec="seconds"), **context}

    def focused(self):
        """Only a timing flag leaves private context; no subject text enters public prompts."""
        attention = self._attention
        return bool(attention and attention["kind"] in {"reading", "watching", "writing"}
                    and time.monotonic() - self._focus_since >= 120
                    and 0 <= (datetime.now() - attention["at"]).total_seconds() <= 75
                    and self._allowed(attention["window"], attention["epoch"], attention["generation"]))


watch = ScreenWatch()
