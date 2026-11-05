"""
services/network/status.py

Knows whether the laptop is on the internet, so FRIDAY picks the AI to use:
online → the API providers (Ollama only if they fail); offline → straight to
the local Ollama model, without waiting for API calls to time out.

Every POLL_SECONDS it fetches Windows' own connectivity-test page (the same
check behind the taskbar's "No internet" icon), which also catches Wi-Fi
login pages that answer with something else. If that fails, `netsh wlan`
says why: Wi-Fi switched off, not connected, or connected without internet.
Wi-Fi off/disconnected counts at once; a failed check with Wi-Fi connected
has to fail twice in a row, so one slow answer doesn't switch models.
Each change shows a silent notification: "FRIDAY ONLINE" / "FRIDAY OFFLINE"; coming back after
a minute or more offline says how long: "FRIDAY ONLINE (offline 25 min)".
"""

import asyncio
import re
import subprocess
import time

import httpx

from core.config import config
from core.logger import logger

POLL_SECONDS = 10
CHECK_URL = "http://www.msftconnecttest.com/connecttest.txt"
CHECK_TEXT = "Microsoft Connect Test"
CHECK_TIMEOUT = 4
LOCAL_PROVIDERS = {"ollama"}  # everything else (OmniRoute included) needs the internet

def internet_reachable() -> bool:
    try:
        response = httpx.get(CHECK_URL, timeout=CHECK_TIMEOUT, follow_redirects=False)
        return response.status_code == 200 and response.text.strip() == CHECK_TEXT
    except httpx.HTTPError:
        return False


def wifi_state() -> str | None:
    """'off' (radio switched off), 'connected', 'disconnected', or None (no Wi-Fi adapter / netsh failed)."""
    try:
        out = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if re.search(r"(software|hardware) off", out, re.I):
        return "off"
    state = re.search(r"^\s*State\s*:\s*(\w+)", out, re.I | re.M)
    return state.group(1).lower() if state else None


class NetworkStatus:
    def __init__(self):
        self.online: bool = True       # until the first check says otherwise, APIs are tried as usual
        self.reason: str | None = None  # why it's offline: wifi_state() ('off', 'disconnected', 'connected') or None
        self._checked = False
        self._misses = 0
        self._offline_since: float | None = None
        self._was_offline = 0.0  # seconds, for the ONLINE message

    def check(self) -> str | None:
        """One check (blocking). Returns the notification text if online/offline changed, else None."""
        if internet_reachable():
            self._misses = 0
            return self._set(True, None)
        wifi = wifi_state()
        self._misses += 1
        if wifi == "connected" and self._misses < 2 and self.online:
            return None  # maybe just one slow answer: wait for the next check
        return self._set(False, wifi)

    def _set(self, online: bool, reason: str | None) -> str | None:
        """Notify when online/offline flips (starting up online is normal: no notification)."""
        first, self._checked = not self._checked, True
        changed = online != self.online
        if changed and not online:
            self._offline_since = time.monotonic()
        elif changed and self._offline_since is not None:
            self._was_offline, self._offline_since = time.monotonic() - self._offline_since, None
        self.online, self.reason = online, reason
        if not (changed or (first and not online)):
            return None
        logger.info(f"Network: {'online' if online else f'offline ({reason})'}")
        return self.message()

    def message(self) -> str:
        if not self.online:
            return "FRIDAY OFFLINE"
        minutes = round(self._was_offline / 60)
        if minutes < 1:
            return "FRIDAY ONLINE"
        return f"FRIDAY ONLINE (offline {minutes} min)" if minutes < 60 else f"FRIDAY ONLINE (offline {minutes // 60} h {minutes % 60} min)"

    def usable(self, providers: list[str]) -> list[str]:
        """The providers worth trying right now: offline, only local ones (Ollama)."""
        if self.online:
            return providers
        local = [name for name in providers if name in LOCAL_PROVIDERS]
        if not local and config.provider_is_configured("ollama"):
            local = ["ollama"]  # offline, and no local model in the chain: use it anyway rather than fail
        return local or providers


network = NetworkStatus()


def warm_local_model() -> None:
    """Load the Ollama model into memory now, so the first offline reply isn't slowed by loading it (~4 s)."""
    try:
        httpx.post(f"{config.OLLAMA_BASE_URL}/api/generate",
                   json={"model": config.OLLAMA_MODEL, "keep_alive": "30m"}, timeout=60)
    except httpx.HTTPError as e:
        logger.warning(f"Couldn't load the local model ({config.OLLAMA_MODEL}) — is Ollama running? {e}")


async def watch_network(status: NetworkStatus = network) -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan."""
    from services.reminders.service import show_toast  # toast helper shared with reminders

    logger.info("Network watcher started")
    while True:
        try:
            note = await asyncio.to_thread(status.check)
            if note:
                await asyncio.to_thread(show_toast, "F.R.I.D.A.Y", note)
                if not status.online:
                    await asyncio.to_thread(warm_local_model)
            if not status.online and status.reason == "connected":  # on Wi-Fi without internet: a login page?
                from services.network import campus
                if login_note := await asyncio.to_thread(campus.on_no_internet):
                    await asyncio.to_thread(show_toast, "F.R.I.D.A.Y", login_note)
        except Exception as e:
            logger.error(f"Network watcher error: {e}", exc_info=True)
        await asyncio.sleep(POLL_SECONDS)
