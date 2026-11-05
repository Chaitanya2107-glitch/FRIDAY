"""
services/automation/logins.py

Login shortcuts: "log me in to github" opens the site's login page and signs in.

  "save my github login" / "add a login for reva"  → a small private window asks for the
        login page, username and password (never said out loud or typed into FRIDAY's chat)
  "log me in to github" / "sign in to reva"         → open the page, fill in, press Enter
  "list my logins", "remove my github login", "update my github login"
  "open lms", "lms", "lms login" → signs in to the college LMS if a login is saved as lms / rulms /
        moodle ("save my lms login"), else just opens rulms.reva.edu.in
  Campus Wi-Fi uses the login saved as "wifi" (services/network/campus.py)

Passwords live only in Windows Credential Manager (encrypted by Windows, tied to your
Windows login) as "FRIDAY login: <name>". memory/logins.json keeps just the login page
and whether it's a two-page login (username, Next, then password — like Google).
Passwords never go into FRIDAY's files, logs, chat history or any AI.

Typing is careful: the password is typed key by key (never via the clipboard) and only
while the browser is the window in front showing a page whose title looks like a login
page — so if you're already signed in, FRIDAY doesn't type your password into whatever
is on the page.
"""

import ctypes
import json
import re
import time
from ctypes import wintypes

from core.config import config
from core.logger import logger
from services.automation import keyboard
from services.automation.system_control import AutomationError

path = config.MEMORY_DIR / "logins.json"  # tests point this elsewhere
TARGET = "FRIDAY login: {name}"
PAGE_WAIT_SECONDS = 20
SETTLE_SECONDS = 1.5          # a title unchanged this long = the page has loaded
NEXT_PAGE_SECONDS = 3         # two-page logins: wait after the username page
LOGIN_TITLE = re.compile(r"sign[\s-]?in|log[\s-]?in|login|signin|authenticat|account|password|verify", re.I)
BROWSERS = ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi")
LOGIN_ACTIONS = {"list_logins", "remove_login"}  # saving (a window) and logging in (waits, types) run in threads

_SAVE = re.compile(r"^(?:save|add|store|set up|update|change)\s+(?:a |my |the )?(?:login|password|sign[\s-]?in)"
                   r"(?:\s+(?:for|to))?\s+(?P<a>.+)$|^(?:save|add|store|set up|update|change)\s+(?:my |the )?(?P<b>.+?)"
                   r"\s+(?:login|password|sign[\s-]?in|credentials)$", re.I)
_LOGIN = re.compile(r"^(?:log|sign)\s*(?:me\s+)?(?:in|into|on)(?:\s+(?:to|into|on))?\s+(?P<name>.+)$|^login\s+(?:to\s+)?(?P<n2>.+)$", re.I)
LMS_NAMES = ("lms", "rulms", "moodle")  # a saved login under one of these is the college LMS
LMS_URL = "https://rulms.reva.edu.in"
_LMS = re.compile(r"^(?:(?:open|go to|launch|log (?:me )?in(?:to)?(?: to)?|sign (?:me )?in(?:to)?(?: to)?)\s+)?"
                  r"(?:my\s+|the\s+|college\s+)*(?:lms|rulms|moodle)(?:\s+login)?$", re.I)
_LIST = re.compile(r"^(?:(?:list|show)(?: me)?(?: all)?(?: my| the)? (?:logins|saved logins|passwords)|what logins do i have)$", re.I)
_REMOVE = re.compile(r"^(?:remove|delete|forget)\s+(?:my |the )?(?:login (?:for )?(?P<a>.+)|(?P<b>.+?) (?:login|password))$", re.I)


# ── Windows Credential Manager ────────────────────────────────────────────────

class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2


def save_secret(name: str, username: str, password: str) -> None:
    blob = password.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob, len(blob))
    credential = _Credential(
        Type=CRED_TYPE_GENERIC, TargetName=TARGET.format(name=name), CredentialBlobSize=len(blob),
        CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)), Persist=CRED_PERSIST_LOCAL_MACHINE,
        UserName=username,
    )
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential), 0):
        raise AutomationError("Windows Credential Manager didn't save it.")


def read_secret(name: str) -> tuple[str, str] | None:
    """(username, password), or None if nothing is saved under that name."""
    pointer = ctypes.POINTER(_Credential)()
    if not ctypes.windll.advapi32.CredReadW(TARGET.format(name=name), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return None
    try:
        c = pointer.contents
        return c.UserName or "", ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(pointer)


def delete_secret(name: str) -> None:
    ctypes.windll.advapi32.CredDeleteW(TARGET.format(name=name), CRED_TYPE_GENERIC, 0)


# ── The list of logins (no secrets) ───────────────────────────────────────────

def load() -> dict[str, dict]:
    try:
        return {k.lower(): v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if isinstance(v, dict)}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e


def _save(logins: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(logins, indent=2, ensure_ascii=False), encoding="utf-8")


def _name(text: str) -> str:
    return re.sub(r"^(?:my |the )|(?:'s)?(?: account| website| site| page| portal)$", "", text.strip(" .'\"").lower()).strip()


# ── Matching ──────────────────────────────────────────────────────────────────

def match_login_command(text: str) -> dict | None:
    """Login commands. `text` has been through normalize_command()."""
    text = text.strip()
    if _LMS.match(text):  # "open lms": sign in if a login is saved for it, else just open the site
        try:
            saved = next((name for name in LMS_NAMES if name in load()), None)
        except AutomationError:
            saved = None
        return {"type": "system", "action": "log_in", "name": saved} if saved else \
            {"type": "system", "action": "open_url", "url": LMS_URL}
    if _LIST.match(text):
        return {"type": "system", "action": "list_logins"}
    if m := _REMOVE.match(text):
        return {"type": "system", "action": "remove_login", "name": _name(m["a"] or m["b"])}
    if m := _SAVE.match(text):
        return {"type": "system", "action": "save_login", "name": _name(m["a"] or m["b"])}
    if m := _LOGIN.match(text):
        name = _name(m["name"] or m["n2"])
        try:
            known = name in load()
        except AutomationError:
            known = False
        return {"type": "system", "action": "log_in", "name": name} if known else None
    return None


def run(parsed: dict) -> str:
    logins = load()
    if parsed["action"] == "list_logins":
        return ("Saved logins: " + ", ".join(logins) + ".") if logins else \
            'You haven\'t saved any logins. Say "save my github login".'
    name = parsed["name"]
    if name not in logins:
        raise AutomationError(f"You don't have a login saved for {name}.")
    delete_secret(name)
    del logins[name]
    _save(logins)
    return f"Removed your {name} login (and its password from Windows Credential Manager)."


# ── Saving: a small private window ────────────────────────────────────────────

def ask_and_save(name: str) -> str:
    """Show the login window (blocking — run in a thread) and save what's entered."""
    existing = load().get(name, {})
    saved_user = (read_secret(name) or ("", ""))[0]
    entered = _login_window(name, existing.get("url", ""), saved_user, bool(existing.get("two_step")))
    if entered is None:
        return "Okay, nothing saved."
    url, username, password, two_step = entered
    if not url or not username or not password:
        raise AutomationError("I need the login page, the username and the password — nothing was saved.")
    if "//" not in url:
        url = "https://" + url
    save_secret(name, username, password)
    logins = load()
    logins[name] = {"url": url, "two_step": two_step}
    _save(logins)
    logger.info(f"Login saved for {name}")  # never the username or password
    return f'Saved your {name} login. Say "log me in to {name}" to use it.'


def _login_window(name: str, url: str, username: str, two_step: bool) -> tuple[str, str, str, bool] | None:
    import tkinter as tk

    result = {}
    root = tk.Tk()
    root.title(f"F.R.I.D.A.Y — {name} login")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    fields = {}
    for row, (label, value, secret) in enumerate([("Login page", url, False), ("Username", username, False),
                                                   ("Password", "", True)]):
        tk.Label(root, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=6)
        entry = tk.Entry(root, width=42, show="•" if secret else "")
        entry.insert(0, value)
        entry.grid(row=row, column=1, padx=10, pady=6)
        fields[label] = entry
    two_pages = tk.BooleanVar(value=two_step)
    tk.Checkbutton(root, text="Username and password are on separate pages (like Google)",
                   variable=two_pages).grid(row=3, column=0, columnspan=2, sticky="w", padx=10)
    tk.Label(root, text="Stored in Windows Credential Manager — not in FRIDAY's files.",
             fg="gray").grid(row=4, column=0, columnspan=2, padx=10)

    def save(*_):
        result["value"] = (fields["Login page"].get().strip(), fields["Username"].get().strip(),
                           fields["Password"].get(), two_pages.get())
        root.destroy()

    buttons = tk.Frame(root)
    buttons.grid(row=5, column=0, columnspan=2, pady=10)
    tk.Button(buttons, text="Save", width=10, command=save).pack(side="left", padx=5)
    tk.Button(buttons, text="Cancel", width=10, command=root.destroy).pack(side="left", padx=5)
    root.bind("<Return>", save)
    root.bind("<Escape>", lambda *_: root.destroy())
    (fields["Login page"] if not url else fields["Password"]).focus_force()
    root.mainloop()
    return result.get("value")


# ── Logging in ────────────────────────────────────────────────────────────────

def front_window() -> tuple[str | None, str | None]:
    """(program name, title) of the window in front — unfiltered: the activity log hides login-page titles on purpose."""
    import psutil

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    try:
        return psutil.Process(pid.value).name().lower().removesuffix(".exe"), buffer.value
    except psutil.Error:
        return None, buffer.value


def _bring_browser_forward() -> None:
    """FRIDAY runs in the background, so the page it opened can stay behind other windows."""
    from services.automation import app_finder

    windows = app_finder.app_windows(lambda proc: proc.name().lower().removesuffix(".exe") in BROWSERS)
    if windows:
        app_finder.bring_to_front(windows[0])  # the browser's topmost window: where the new tab opened


def log_in(name: str, open_url, foreground_window=front_window) -> str:
    """Open the login page and sign in (blocking). `foreground_window()` → (app, title) of the window in front."""
    login = load().get(name)
    secret = read_secret(name)
    if not login or not secret:
        raise AutomationError(f'I don\'t have your {name} password. Say "save my {name} login" first.')
    username, password = secret
    open_url(login["url"])
    time.sleep(1)
    if not _in_browser(foreground_window)[0]:
        _bring_browser_forward()

    title = _wait_for_login_page(foreground_window)
    if title is None:
        return f"I opened the {name} login page, but it didn't come up in front in time — sign in yourself."
    if not LOGIN_TITLE.search(title):
        return (f'The {name} page ("{title}") doesn\'t look like a login page — maybe you\'re already signed in — '
                "so I didn't type your password.")

    keyboard.type_secret(username)
    if login.get("two_step"):
        keyboard.press_keys("enter")
        time.sleep(NEXT_PAGE_SECONDS)
        if not _still_on_login_page(foreground_window):
            return f"I typed your {name} username, then the page changed unexpectedly, so I stopped before the password."
    else:
        keyboard.press_keys("tab")
    if not _still_on_login_page(foreground_window):  # checked right before the password goes anywhere
        return f"I stopped before typing your {name} password: the browser isn't in front any more."
    keyboard.type_secret(password)
    keyboard.press_keys("enter")
    logger.info(f"Signed in to {name}")
    return f"Signing you in to {name}."


def _in_browser(foreground_window) -> tuple[bool, str]:
    app, title = foreground_window()
    return (app or "") in BROWSERS, title or ""


def _still_on_login_page(foreground_window) -> bool:
    in_browser, title = _in_browser(foreground_window)
    return in_browser and bool(LOGIN_TITLE.search(title))


def _wait_for_login_page(foreground_window) -> str | None:
    """Wait for the browser to be in front with a settled title; returns it (without " - Google Chrome"), or None."""
    deadline = time.monotonic() + PAGE_WAIT_SECONDS
    last, since = None, time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.5)
        in_browser, title = _in_browser(foreground_window)
        if not in_browser or not title or re.match(r"new tab|untitled|loading", title, re.I):
            last = None
            continue
        if title != last:
            last, since = title, time.monotonic()
        elif time.monotonic() - since >= SETTLE_SECONDS:
            return re.sub(r"\s+-\s+(?:Google Chrome|Microsoft​? Edge|Mozilla Firefox|Brave)$", "", title)
    return None
