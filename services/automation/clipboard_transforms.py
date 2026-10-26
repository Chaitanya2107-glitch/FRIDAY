"""
services/automation/clipboard_transforms.py

Change the clipboard's text in place:
  "make my clipboard uppercase" / "lowercase" / "title case" / "sentence case"
  "clipboard to one line" / "remove line breaks from my clipboard"
  "clean up my clipboard" — trims lines, squeezes spaces and blank lines
  "strip formatting from my clipboard" — keeps only the plain text
  "paste as plain text" — that, then Ctrl+V into the app you're in
  "count the words in my clipboard"
"""

import re

from services.automation import clipboard
from services.automation.results import ActionResult

CLIPBOARD_TRANSFORM = "clipboard_transform"
# First match wins, checked in this order
_KINDS = (
    ("count", ("count", "how many words", "how many characters", "how long is")),
    ("upper", ("uppercase", "upper case", "capitals", "all caps", "caps")),
    ("lower", ("lowercase", "lower case", "small letters")),
    ("title", ("title case",)),
    ("sentence", ("sentence case",)),
    ("one_line", ("one line", "single line", "line breaks", "newlines")),
    ("plain", ("plain text", "formatting")),
    ("clean", ("clean", "tidy", "trim")),
)
_PASTE_PLAIN = re.compile(r"^paste(?: it| this)?(?: as| in)? (?:plain(?: text)?|without formatting|unformatted)$", re.I)
_STRIP = re.compile(r"^(?:strip|remove|clear) (?:the )?formatting$", re.I)


def match_clipboard_transform(text: str) -> dict | None:
    text = text.strip().rstrip(".!?").lower()
    if _PASTE_PLAIN.match(text):
        return {"type": "system", "action": CLIPBOARD_TRANSFORM, "kind": "plain", "paste": True}
    if _STRIP.match(text):
        return {"type": "system", "action": CLIPBOARD_TRANSFORM, "kind": "plain", "paste": False}
    if not re.search(r"\bclipboard\b", text) or "history" in text:
        return None
    for kind, words in _KINDS:
        if any(re.search(rf"\b{w}\b", text) for w in words):
            return {"type": "system", "action": CLIPBOARD_TRANSFORM, "kind": kind, "paste": False}
    return None


def _sentence_case(text: str) -> str:
    text = text.lower()
    return re.sub(r"(^\s*|[.!?]\s+)([a-z])", lambda m: m[1] + m[2].upper(), text)


def _clean(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


TRANSFORMS = {
    "upper": (str.upper, "Your clipboard is in UPPERCASE now."),
    "lower": (str.lower, "Your clipboard is in lowercase now."),
    "title": (str.title, "Your clipboard is in Title Case now."),
    "sentence": (_sentence_case, "Your clipboard is in sentence case now."),
    "one_line": (lambda t: " ".join(t.split()), "Your clipboard is on one line now."),
    "clean": (_clean, "Cleaned up your clipboard."),
    "plain": (lambda t: t, "Your clipboard is plain text now."),  # writing text back drops the formatting
}


def run(parsed: dict) -> ActionResult:
    text = clipboard.get_text()
    if not text:
        return ActionResult(False, "Your clipboard has no text.")
    kind = parsed["kind"]
    if kind == "count":
        words = len(text.split())
        return ActionResult(True, f"{words:,} word{'s' if words != 1 else ''}, {len(text):,} characters.",
                            repeatable=False)
    transform, message = TRANSFORMS[kind]
    clipboard.set_text(transform(text))
    if parsed.get("paste"):
        return ActionResult(True, "Pasted as plain text.", keyboard=({"keys": "ctrl+v"},))
    return ActionResult(True, message)
