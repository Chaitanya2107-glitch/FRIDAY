"""
services/network/campus.py

Campus Wi-Fi auto-login. When the network watcher sees Wi-Fi connected but no internet, and
Windows' connection test is being redirected to a login page (a captive portal), then:
  - the campus portal (CAMPUS_WIFI_PORTAL, default REVA's captiveportal.reva.edu.in): FRIDAY
    opens it. REVA signs in with Microsoft, which often finishes by itself when the browser is
    already signed in; if it asks, FRIDAY fills in the saved "wifi" login ("save my wifi login":
    username and password on separate pages) with logins.py's careful typing — only on a page
    that looks like a sign-in page, with the browser in front
  - any other Wi-Fi's login page: only a notification. Your college password is never typed on
    a network FRIDAY doesn't know.
Tried at most every RETRY_MINUTES. "log me in to wifi" does it by hand.
"""

import re
import time
from urllib.parse import urlparse

import httpx

from core.config import config
from core.logger import logger
from services.network.status import CHECK_TEXT, CHECK_TIMEOUT, CHECK_URL

WIFI_LOGIN = "wifi"   # the saved login's name in logins.py
RETRY_MINUTES = 5

_last_try = 0.0
_REDIRECT = re.compile(r"""(?:location(?:\.href)?\s*=\s*|url=|href=)["']?(https?://[^"'\s>]+)""", re.I)


def portal_url() -> str | None:
    """The Wi-Fi's login page, if the connection test is being redirected to one (else None)."""
    try:
        response = httpx.get(CHECK_URL, timeout=CHECK_TIMEOUT, follow_redirects=False)
    except httpx.HTTPError:
        return None
    if response.status_code == 200 and response.text.strip() == CHECK_TEXT:
        return None  # not redirected: the internet works (or the problem is elsewhere)
    if location := response.headers.get("location"):
        return location
    found = _REDIRECT.search(response.text)
    return found.group(1) if found else None


def _host(url: str) -> str:
    return (urlparse(url if "//" in url else "//" + url).hostname or "").lower()


def on_no_internet(now_ts: float | None = None) -> str | None:
    """Wi-Fi is connected without internet (the watcher's call, blocking). Returns a notification, or None."""
    global _last_try
    now_ts = now_ts or time.time()
    if now_ts - _last_try < RETRY_MINUTES * 60:
        return None
    url = portal_url()
    if not url:
        return None
    _last_try = now_ts
    host = _host(url)
    campus = _host(config.CAMPUS_WIFI_PORTAL) if config.CAMPUS_WIFI_PORTAL else ""
    if not campus or host != campus:
        logger.info(f"Wi-Fi login page at {host}: not the campus portal, only telling the user")
        return f"This Wi-Fi wants you to sign in ({host}). Open a browser to continue."
    return sign_in(url)


def sign_in(url: str) -> str:
    """Open the campus portal (the one just detected — it carries a one-time token) and sign in if asked."""
    from services.automation import logins
    from services.automation.system_control import system

    if WIFI_LOGIN not in logins.load():
        system.open_url(url)
        return ('Campus Wi-Fi wants a sign-in — I opened it. Say "save my wifi login" (username and password on '
                "separate pages) and I'll sign in for you next time.")
    try:
        return "Campus Wi-Fi: " + logins.log_in(WIFI_LOGIN, lambda _saved_page: system.open_url(url))
    except Exception as e:  # never let a sign-in problem break the network watcher
        logger.warning(f"Campus Wi-Fi sign-in failed: {e}")
        return f"Campus Wi-Fi: I couldn't sign in ({e})."
