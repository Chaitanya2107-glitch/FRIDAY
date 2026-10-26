"""
services/voice/voice_commands.py

Commands about FRIDAY's voice:
  "read this" / "read the selection" / "read it out loud" — copies what's selected in the app
      in front and reads it aloud. From the command bar (which is in front itself) it reads
      what you copied. ("read my clipboard" only shows it: device_commands.py)
  "stop reading" / "stop talking"
  "talk faster" / "speak slower" / "normal speed" — kept after a restart (tts.set_rate)
  "how many false wakes" — how often "Hey Friday" woke by mistake (services/voice/wake.py)
"""

import ctypes
import re
import time

from services.automation import clipboard, keyboard
from services.automation.results import ActionResult
from services.voice import wake
from services.voice.tts import MAX_RATE, tts

VOICE_ACTIONS = {"read_aloud", "stop_speaking", "speech_speed", "wake_stats"}
SPEED_STEP = 15  # % per "faster" / "slower"
COPY_WAIT_SECONDS = 0.6
MAX_READ_CHARS = 5000
BAR_CLASS = "FridayQuickBarWindow"  # the command bar's window (interfaces/popup/app.py)

_READ = re.compile(
    r"^read(?: (?:this|that|it|the selection|the selected text|what(?:'s| is) selected)"
    r"(?: (?:aloud|out loud|out|to me|for me))?| (?:aloud|out loud))$", re.I)
_STOP = re.compile(r"^(?:stop|quit) (?:reading|talking|speaking)(?: that| it| out loud)?$", re.I)
_SPEED = re.compile(
    r"^(?:(?:talk|speak|read)(?: a (?:bit|little))? (?P<dir>faster|quicker|slower)"
    r"|(?P<phrase>speed up|slow down)(?: your (?:voice|speech|talking))?)(?: please)?$", re.I)
_NORMAL = re.compile(r"^(?:(?:talk|speak) at )?normal (?:speed|speaking speed|voice speed)$"
                     r"|^reset (?:your )?(?:voice |speech |talking |speaking )?speed$", re.I)
_WAKE_STATS = re.compile(r"\b(?:false wakes?|wake(?: word)? stats|(?:woke|wake) (?:up )?by mistake)\b", re.I)


def match_voice_command(text: str) -> dict | None:
    """`text` has already been through normalize_command()."""
    text = text.strip().rstrip(".!?")
    if _READ.match(text):
        return {"type": "system", "action": "read_aloud"}
    if _STOP.match(text):
        return {"type": "system", "action": "stop_speaking"}
    if m := _SPEED.match(text):
        faster = (m["dir"] or m["phrase"]).lower() in ("faster", "quicker", "speed up")
        return {"type": "system", "action": "speech_speed", "change": SPEED_STEP if faster else -SPEED_STEP}
    if _NORMAL.match(text):
        return {"type": "system", "action": "speech_speed", "change": None}
    if _WAKE_STATS.search(text):
        return {"type": "system", "action": "wake_stats"}
    return None


def _bar_in_front() -> bool:
    user32 = ctypes.windll.user32
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(user32.GetForegroundWindow(), name, 64)
    return name.value == BAR_CLASS


def _copy_selection() -> bool:
    """Ctrl+C in the app in front; True if something was copied."""
    before = clipboard.sequence_number()
    keyboard.press_keys("ctrl+c")
    deadline = time.monotonic() + COPY_WAIT_SECONDS
    while time.monotonic() < deadline:
        if clipboard.sequence_number() != before:
            return True
        time.sleep(0.05)
    return False


def read_aloud() -> ActionResult:
    if not _bar_in_front() and not _copy_selection():
        return ActionResult(False, "Nothing's selected — select some text first.")
    if clipboard.is_private():  # a password manager asked clipboard tools to leave it alone
        return ActionResult(False, "What's copied is marked private, so I won't read it out.")
    text = " ".join((clipboard.get_text() or "").split())
    if not text:
        return ActionResult(False, "There's no text to read.")
    words = len(text.split())
    return ActionResult(True, f"Reading it out ({words} word{'s' if words != 1 else ''}). \"Stop reading\" stops it.",
                        memory_message="(Read some text aloud.)", repeatable=False, speech=text[:MAX_READ_CHARS])


def set_speed(change: int | None) -> str:
    old = tts.rate
    new = tts.set_rate(0 if change is None else old + change)
    if new == old:
        if change is None:
            return "I'm already at normal speed."
        return "That's as fast as I go." if new >= MAX_RATE else "That's as slow as I go."
    if new == 0:
        return "Okay, back to normal speed."
    return f"Okay — talking {'faster' if new > old else 'slower'} now ({abs(new)}% {'above' if new > 0 else 'below'} normal)."


def run(parsed: dict) -> ActionResult:
    action = parsed["action"]
    if action == "read_aloud":
        return read_aloud()
    if action == "stop_speaking":
        tts.stop()
        return ActionResult(True, "Okay.", speech="")  # nothing more to say
    if action == "speech_speed":
        return ActionResult(True, set_speed(parsed["change"]), repeatable=False)
    return ActionResult(True, wake.stats(), repeatable=False)
