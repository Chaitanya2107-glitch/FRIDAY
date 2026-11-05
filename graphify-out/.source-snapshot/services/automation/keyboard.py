"""
services/automation/keyboard.py

Types text and presses keys in whatever app has focus, through Windows'
SendInput. Text is sent as Unicode characters, so any language or emoji works
regardless of the keyboard layout.

The backend only decides WHAT to type: its replies carry a list of steps, and
the client that owns the user's focus (the command bar or the tray, for voice)
calls run_steps() once the right window is in front.

A step is {"text": "..."} or {"keys": "ctrl+s", "times": 1}.

Multi-line or long text is pasted (clipboard + Ctrl+V) rather than typed, since
editors auto-indent typed line breaks. The clipboard is put back afterwards, but
the paste can still show up in the clipboard history.
"""

import ctypes
import re
import time
from ctypes import wintypes

from core.logger import logger
from services.automation import clipboard

CHUNK_CHARS = 32           # characters per SendInput call
CHUNK_PAUSE_SECONDS = 0.01  # lets slower apps (Electron, browsers) keep up
PASTE_OVER_CHARS = 200      # longer than this is pasted, not typed
PASTE_SETTLE_SECONDS = 0.15
MAX_KEY_REPEATS = 50

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_RETURN, VK_TAB = 0x0D, 0x09

# Spoken or written key names → virtual-key codes
KEY_CODES = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "windows": 0x5B,
    "enter": VK_RETURN, "return": VK_RETURN, "tab": VK_TAB, "space": 0x20, "spacebar": 0x20,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "back space": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "up arrow": 0x26, "down arrow": 0x28, "left arrow": 0x25, "right arrow": 0x27,
    "home": 0x24, "end": 0x23, "page up": 0x21, "pageup": 0x21, "page down": 0x22, "pagedown": 0x22,
    "caps lock": 0x14, "print screen": 0x2C,
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE, "dot": 0xBE, "slash": 0xBF,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
    **{chr(c): c for c in range(ord("0"), ord("9") + 1)},
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
}
MODIFIERS = {0x11, 0x12, 0x10, 0x5B}
EXTENDED_KEYS = {0x2E, 0x2D, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x5B}


class KeyboardError(Exception):
    """Typing failed. The message is user-facing."""


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):  # only here so the union has the right size
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)
    return event


def _vk_events(vk: int, up: bool) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_KEYS else 0)
    return _key_event(vk=vk, flags=flags)


def _send(events: list[INPUT]) -> None:
    if not events:
        return
    array = (INPUT * len(events))(*events)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise KeyboardError(
            "Windows blocked the typing — the app you're using may be running as administrator."
        )


def _text_events(text: str) -> list[INPUT]:
    events = []
    for char in text.replace("\r\n", "\n").replace("\r", "\n"):
        if char in "\n\t":
            vk = VK_RETURN if char == "\n" else VK_TAB
            events += [_vk_events(vk, up=False), _vk_events(vk, up=True)]
            continue
        # Characters outside the basic plane (emoji) are sent as two UTF-16 halves
        data = char.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            events += [_key_event(scan=unit, flags=KEYEVENTF_UNICODE),
                       _key_event(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


def _paste(text: str) -> bool:
    """Put text on the clipboard and press Ctrl+V, then put back what was there."""
    try:
        previous = clipboard.get_text()
        clipboard.set_text(text)
    except clipboard.ClipboardError as e:
        logger.warning(f"Couldn't use the clipboard to paste, typing instead: {e}")
        return False

    press_keys("ctrl+v")
    time.sleep(PASTE_SETTLE_SECONDS)  # the app needs a moment to read the clipboard
    if previous is not None:
        try:
            clipboard.set_text(previous)
        except clipboard.ClipboardError as e:
            logger.warning(f"Couldn't put your clipboard back: {e}")
    return True


def type_text(text: str) -> None:
    # Editors auto-indent each new line, which doubles the indentation of typed
    # code, so anything with line breaks (or very long) is pasted instead.
    if "\n" in text or len(text) > PASTE_OVER_CHARS:
        if _paste(text):
            return
    for start in range(0, len(text), CHUNK_CHARS):
        _send(_text_events(text[start:start + CHUNK_CHARS]))
        time.sleep(CHUNK_PAUSE_SECONDS)


def type_secret(text: str) -> None:
    """Type a password: always key by key — never through the clipboard, where the clipboard history would keep it."""
    for start in range(0, len(text), CHUNK_CHARS):
        _send(_text_events(text[start:start + CHUNK_CHARS]))
        time.sleep(CHUNK_PAUSE_SECONDS)


def parse_keys(keys: str) -> list[int] | None:
    """ "ctrl+shift+s", "control s", "alt f4", "page down" → key codes; None if a name is unknown."""
    keys = keys.strip()
    if not keys or keys.endswith("+"):
        return None
    text = re.sub(r"\s*(?:\+|\bplus\b(?=\s*\w))\s*", " + ", keys.lower())
    text = re.sub(r"\s+", " ", text)
    names = sorted(KEY_CODES, key=len, reverse=True)
    pattern = re.compile(rf"\s*({'|'.join(map(re.escape, names))})\s*(?:\+\s*)?")
    codes, position = [], 0
    while position < len(text):
        match = pattern.match(text, position)
        if not match:
            return None
        codes.append(KEY_CODES[match.group(1)])
        position = match.end()
    if not codes or any(code not in MODIFIERS for code in codes[:-1]):
        return None  # only the last key may be a normal key: "ctrl+s", not "s+ctrl"
    return codes


def press_keys(keys: str, times: int = 1) -> None:
    codes = parse_keys(keys)
    if codes is None:
        raise KeyboardError(f"I don't know the key \"{keys}\".")
    for _ in range(max(1, min(times, MAX_KEY_REPEATS))):
        _send([_vk_events(c, up=False) for c in codes] + [_vk_events(c, up=True) for c in reversed(codes)])
        time.sleep(CHUNK_PAUSE_SECONDS)


def run_steps(steps: list[dict]) -> None:
    """Type the backend's keyboard steps into the focused app, in order."""
    for step in steps:
        if "text" in step:
            type_text(str(step["text"]))
        elif "keys" in step:
            press_keys(str(step["keys"]), int(step.get("times", 1)))
        else:
            logger.warning(f"Unknown keyboard step: {step}")


def describe_keys(keys: str) -> str:
    """ "ctrl+s" → "Ctrl+S" for replies."""
    codes = parse_keys(keys)
    if codes is None:
        return keys
    labels = {0x11: "Ctrl", 0x12: "Alt", 0x10: "Shift", 0x5B: "Win"}
    names = {}
    for name, code in KEY_CODES.items():  # the first name listed for a key is its label
        if len(name) > 1 or name.isdigit():
            names.setdefault(code, name)
    return "+".join(
        labels.get(c) or (chr(c) if 0x41 <= c <= 0x5A else names.get(c, "?").title()) for c in codes
    )
