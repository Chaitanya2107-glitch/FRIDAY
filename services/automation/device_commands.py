"""
services/automation/device_commands.py

Strict local matchers for device commands: close app, volume, brightness,
mute, clipboard (read, write, history), screenshots and system stats. The words it accepts
live in services/automation/command_words.py.

It needs both a starter word and the thing being controlled, so ordinary chat
can't trigger it by accident — which is also why messages starting with these
words only reach the AI classifier if they start with an AI_COMMAND_STARTERS word.
"""

import re

from services.automation import command_words as words
from services.automation.command_words import first_word, normalize_command
from services.automation.system_control import system

CLIPBOARD_ITEM = re.compile(r"\b(?:item|entry|number|no\.?)\s*#?(\d+)\b")

# The caller only runs this matcher for messages starting with one of these.
DEVICE_STARTERS = (
    {verb.split()[0] for verb in words.CLOSE_VERBS}
    | words.UP_WORDS | words.DOWN_WORDS | words.LEVEL_STARTERS
    | words.VOLUME_NOUNS | words.BRIGHTNESS_NOUNS | words.SCREEN_NOUNS
    | words.MUTE_WORDS | words.UNMUTE_WORDS | words.MAX_WORDS | words.MIN_WORDS
    | words.SCREENSHOT_STARTERS | words.SCREENSHOT_WORDS
    | words.CLIPBOARD_READ_STARTERS | words.CLIPBOARD_HISTORY_LIST_STARTERS
    | words.CLIPBOARD_HISTORY_CLEAR_STARTERS | words.CLIPBOARD_WRITE_STARTERS
    | words.CLIPBOARD_RESTORE_STARTERS
    | {"what", "whats", "sound", "brightness", "restore"}
)


# A volume/brightness command has to start with one of these: "set…", "volume…",
# "louder", "max brightness" — so "a sound at 50 Hz" isn't a volume command.
LEVEL_FIRST_WORDS = (
    words.LEVEL_STARTERS | words.VOLUME_NOUNS | words.BRIGHTNESS_NOUNS | words.SCREEN_NOUNS
    | words.UP_WORDS | words.DOWN_WORDS | words.MAX_WORDS | words.MIN_WORDS | words.HALF_WORDS
)
# Only these can set a level from a bare number: "volume 30", "set brightness 70"
NUMBER_FIRST_WORDS = (
    {"set", "change", "adjust", "put", "turn", "make", "bring"}
    | words.VOLUME_NOUNS | words.BRIGHTNESS_NOUNS | words.SCREEN_NOUNS
)
SOUND_SWITCH_FIRST_WORDS = {"turn", "switch", "put"} | words.VOLUME_NOUNS

_SMALL_NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_SPOKEN_LEVEL = re.compile(
    r"(?P<prefix>(?:(?:set|change|adjust|put|turn|make|bring|increase|decrease|raise|lower|reduce|boost|drop)\s+)?"
    r"(?:(?:the|my)\s+)?(?:volume|sound|audio|brightness)(?:\s+(?:to|at|by))?\s+)"
    r"(?P<level>[a-z -]+?)(?:\s+(?:percent|per cent))?"
)
_COMPARATIVE = re.compile(
    r"(?:make|turn|set|adjust)\s+(?:(?:the|my)\s+)?"
    r"(?:volume|sound|audio|speakers?|brightness|screen|display|monitor)\s+"
    r"(?P<amount>less|more)\s+(?P<quality>loud|quiet|bright|dim)"
)


def _spoken_number(text: str) -> int | None:
    parts = text.replace("-", " ").split()
    if len(parts) == 1:
        return _SMALL_NUMBERS.get(parts[0], _TENS.get(parts[0]))
    if parts in (["one", "hundred"], ["a", "hundred"]):
        return 100
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _SMALL_NUMBERS:
        unit = _SMALL_NUMBERS[parts[1]]
        if 1 <= unit <= 9:
            return _TENS[parts[0]] + unit
    return None


def _step(tokens: set[str]) -> int:
    return words.BIG_STEP if tokens & words.BIG_STEP_WORDS else words.DEFAULT_STEP


def _level_command(msg: str, first: str, tokens: set[str], noun: str) -> dict | None:
    """Parse "set volume to 40", "volume up by 20", "max brightness", "a lot louder"."""
    if first in words.SOFTENERS:
        return _soft_step(msg, tokens, noun)

    # "less bright" and "more quiet" reverse the adjective's usual direction.
    if tokens & {"less", "more"} and tokens & {"loud", "quiet", "bright", "dim"}:
        match = _COMPARATIVE.fullmatch(msg)
        if not match:
            return None
        if (noun == "volume") != (match["quality"] in {"loud", "quiet"}):
            return None  # "make the screen more loud" has no supported meaning
        direction = 1 if match["quality"] in {"loud", "bright"} else -1
        return {"type": "system", "action": f"change_{noun}",
                "delta": direction * (1 if match["amount"] == "more" else -1) * words.DEFAULT_STEP}

    if spoken := _SPOKEN_LEVEL.fullmatch(msg):
        level = _spoken_number(spoken["level"])
        if level is not None:
            msg = spoken["prefix"] + str(level)

    target = re.search(r"\b(?:to|at)\s+(\d{1,3})\b", msg)
    if target:
        return {"type": "system", "action": f"set_{noun}", "level": int(target.group(1))}

    if tokens & words.MAX_WORDS:
        return {"type": "system", "action": f"set_{noun}", "level": 100}
    if tokens & words.MIN_WORDS:
        return {"type": "system", "action": f"set_{noun}", "level": 0}
    if tokens & words.HALF_WORDS:
        return {"type": "system", "action": f"set_{noun}", "level": 50}

    number = re.search(r"\b(\d{1,3})\b", msg)
    direction = 1 if tokens & words.UP_WORDS else -1 if tokens & words.DOWN_WORDS else 0
    if direction:
        amount = int(number.group(1)) if number else _step(tokens)
        return {"type": "system", "action": f"change_{noun}", "delta": direction * amount}
    if number and first in NUMBER_FIRST_WORDS:
        return {"type": "system", "action": f"set_{noun}", "level": int(number.group(1))}
    return None


def _soft_step(msg: str, tokens: set[str], noun: str) -> dict | None:
    """ "a bit louder", "a little dimmer" — but never "a sound at 50 Hz"."""
    if re.search(r"\d", msg) or len(msg.split()) > 5:
        return None
    direction = 1 if tokens & words.UP_WORDS else -1 if tokens & words.DOWN_WORDS else 0
    return {"type": "system", "action": f"change_{noun}", "delta": direction * _step(tokens)} if direction else None


def _mute_command(first: str, word_list: list[str], tokens: set[str]) -> dict | None:
    # "mute", "mute the laptop sound" — but not "mute button on my headphones is broken"
    if first in words.MUTE_WORDS | words.UNMUTE_WORDS and set(word_list[1:]) <= words.MUTE_OBJECT_WORDS:
        return {"type": "system", "action": "set_mute", "mute": first in words.MUTE_WORDS}
    # "turn the sound off", "sound on"
    if (
        first in SOUND_SWITCH_FIRST_WORDS
        and tokens & words.VOLUME_NOUNS
        and not tokens & (words.UP_WORDS | words.DOWN_WORDS)
        and len(word_list) <= 5
    ):
        if "off" in tokens:
            return {"type": "system", "action": "set_mute", "mute": True}
        if "on" in tokens:
            return {"type": "system", "action": "set_mute", "mute": False}
    return None


def _clipboard_command(text: str, msg: str, first: str, tokens: set[str]) -> dict | None:
    item = CLIPBOARD_ITEM.search(msg)
    if first in words.CLIPBOARD_RESTORE_STARTERS and item:
        return {"type": "system", "action": "restore_clipboard_item", "number": int(item.group(1))}

    if "history" in tokens:
        if first in words.CLIPBOARD_HISTORY_CLEAR_STARTERS:
            return {"type": "system", "action": "clear_clipboard_history"}
        if first in words.CLIPBOARD_HISTORY_LIST_STARTERS or first in {"what", "whats"}:
            return {"type": "system", "action": "list_clipboard_history"}
        return None

    if first in words.CLIPBOARD_WRITE_STARTERS:
        copy = re.match(
            r"[a-z]+\s+(.+?)\s+(?:to|into|onto|on)\s+(?:the\s+|my\s+)?clipboard\W*$",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if copy:
            return {"type": "system", "action": "write_clipboard", "text": copy.group(1).strip("\"' ")}
    if first in words.CLIPBOARD_READ_STARTERS or words.CLIPBOARD_READ_PHRASES.match(msg):
        return {"type": "system", "action": "read_clipboard"}
    return None


def _close_command(msg: str) -> dict | None:
    rest = words.strip_verb(msg, words.CLOSE_VERBS)
    if not rest:
        return None
    target = words.clean_target(rest)
    # A listed app, or an installed one (Everything) that has a window open — "close the tab" stays with the AI
    app_name = words.resolve_app(target, system.list_apps()) or (target if system.is_open(target) else None)
    return {"type": "system", "action": "close_app", "app_name": app_name} if app_name else None


def _is_screenshot(msg: str, first: str, tokens: set[str]) -> bool:
    if first not in words.SCREENSHOT_STARTERS | words.SCREENSHOT_WORDS:
        return False
    return bool(tokens & words.SCREENSHOT_WORDS or words.SCREENSHOT_PHRASES.search(msg))


def _is_brightness(first: str, word_list: list[str], tokens: set[str]) -> bool:
    if tokens & words.BRIGHTNESS_NOUNS or first in words.BRIGHTNESS_UP | words.BRIGHTNESS_DOWN:
        return True
    # "make the screen brighter", "turn the display down"
    if tokens & words.SCREEN_NOUNS and len(word_list) <= 7:
        return bool(tokens & (words.BRIGHTNESS_UP | words.BRIGHTNESS_DOWN | {"bright"})) or (
            first in words.LEVEL_STARTERS and bool(tokens & (words.UP_WORDS | words.DOWN_WORDS))
        )
    return False


def match_stats_command(message: str) -> dict | None:
    """ "how's my system?", "battery", "how hot is my gpu", "what's using my ram"."""
    msg = re.sub(r"\s+", " ", normalize_command(message).lower())
    if words.STATS_EVERYTHING.fullmatch(msg):
        top = {"top": True} if words.STATS_SLOW.search(msg) else {}
        return {"type": "system", "action": "system_stats", **top}
    if words.STATS_CHARGING.fullmatch(msg):
        return {"type": "system", "action": "system_stats", "part": "battery"}
    for part, pattern in words.STATS_PART_PATTERNS.items():
        if msg in words.STATS_BARE and re.fullmatch(words.STATS_PARTS[part], msg):
            return {"type": "system", "action": "system_stats", "part": part}
        match = pattern.fullmatch(msg)
        if match:
            top = {"top": True} if match.group("top") else {}
            return {"type": "system", "action": "system_stats", "part": part, **top}
    return None


def match_device_command(message: str) -> dict | None:
    text = normalize_command(message)
    msg = text.lower()
    word_list = re.findall(r"[a-z0-9]+", msg)
    if not word_list:
        return None
    first = first_word(msg)
    tokens = set(word_list)

    if first in {v.split()[0] for v in words.CLOSE_VERBS}:
        close = _close_command(msg)
        if close:
            return close

    mute = _mute_command(first, word_list, tokens)
    if mute:
        return mute

    if "clipboard" in tokens or words.CLIPBOARD_READ_PHRASES.match(msg):
        return _clipboard_command(text, msg, first, tokens)

    if _is_screenshot(msg, first, tokens):
        return {"type": "system", "action": "take_screenshot"}

    if first not in LEVEL_FIRST_WORDS:
        return None

    if _is_brightness(first, word_list, tokens):
        return _level_command(msg, first, tokens, "brightness")

    if tokens & words.VOLUME_NOUNS:
        return _level_command(msg, first, tokens, "volume")

    # "louder", "a bit quieter" — short, with no other subject
    if tokens & (words.VOLUME_ALONE_UP | words.VOLUME_ALONE_DOWN) and len(word_list) <= 5:
        return _level_command(msg, first, tokens, "volume")

    return None
