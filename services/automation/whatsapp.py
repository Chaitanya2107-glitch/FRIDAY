"""
services/automation/whatsapp.py

WhatsApp messages by voice or command bar:
  "message mom on whatsapp: I'll be late" / "whatsapp mom I'll be late" /
  "send a whatsapp to mom saying I'll be late" / "text mom I'm home"
FRIDAY always asks first ("Send … to Mom on WhatsApp?"); on a yes it opens the
chat in WhatsApp Desktop with the message typed in (a whatsapp://send link)
and presses Enter — only once WhatsApp is the window in front, so the key can
never land in another app. If WhatsApp doesn't come up, the message is left
typed in the chat to send by hand.

Numbers come from memory/contacts.json (editable by hand):
  "save mom's number as 98765 43210", "add contact dad +91 91234 56789",
  "list my contacts", "remove contact mom". A 10-digit number gets
  COUNTRY_CODE in front. A number can also be said directly: "whatsapp 9876543210 hi".
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from core.logger import logger
from services import settings_store
from services.automation import keyboard
from services.automation.system_control import AutomationError

path = Path("memory/contacts.json")  # tests point this elsewhere
COUNTRY_CODE = "91"  # India; numbers saved with 10 digits get it in front
WINDOW_WAIT_SECONDS = 10
CHAT_LOAD_SECONDS = 1.5  # after WhatsApp is in front, for the chat and the typed message to load
WHATSAPP_ACTIONS = {"send_whatsapp", "save_contact", "list_contacts", "remove_contact"}

_WHATSAPP = r"whats\s?app"
_ON_WHATSAPP = re.compile(rf"\s+(?:on|via|in|through|using)\s+{_WHATSAPP}\b", re.I)
_SEND = re.compile(
    rf"^(?:send\s+(?:a\s+|an\s+)?(?:{_WHATSAPP}\s+)?(?:message|msg|text)?\s*to|{_WHATSAPP}(?:\s+to)?"
    r"|message|msg|text|tell|ping)\s+(?P<rest>.+)$", re.I,
)
_BODY_LEAD = re.compile(r"^\s*(?:[:,\-]\s*|(?:saying|that|to say|and say|say|the message|message)\b\s*[:,]?\s*)", re.I)
_NUMBER = re.compile(r"^(?P<num>\+?\d[\d\s-]{8,16}\d)\b")
_NUMBER_ANYWHERE = r"(?P<num>\+?\d[\d\s-]{6,16}\d)"
_SAVE = [
    re.compile(rf"^(?:save|add|store)\s+(?P<name>.+?)(?:'s|s')?\s+(?:whats\s?app\s+)?(?:number|phone(?: number)?|contact)"
               rf"\s+(?:as\s+|is\s+|:\s*)?{_NUMBER_ANYWHERE}$", re.I),
    re.compile(rf"^(?:add|save|new)\s+(?:a\s+)?contact\s+(?P<name>.+?)\s*[:,]?\s*{_NUMBER_ANYWHERE}$", re.I),
    re.compile(rf"^(?P<name>.+?)'s\s+(?:whats\s?app\s+)?(?:number|phone number)\s+is\s+{_NUMBER_ANYWHERE}$", re.I),
]
_LIST = re.compile(r"^(?:(?:list|show)(?: me)?(?: all)?(?: my| the)? (?:whats\s?app )?contacts|my contacts|who are my contacts)$", re.I)
_REMOVE = re.compile(r"^(?:remove|delete|forget)\s+(?:the\s+)?(?:contact\s+(?P<a>.+)|(?P<b>.+?)(?:'s|s')\s+number)$", re.I)


# ── Contacts ──────────────────────────────────────────────────────────────────

def load() -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e
    return {str(name).strip().lower(): str(number) for name, number in data.items()}


def _save(contacts: dict[str, str]) -> None:
    settings_store.save(path, contacts)


def clean_number(number: str) -> str | None:
    """Digits WhatsApp wants: country code + number, no "+", spaces or dashes. None if it can't be a number."""
    digits = re.sub(r"\D", "", number)
    if not number.strip().startswith("+"):
        digits = digits.removeprefix("00")
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            digits = COUNTRY_CODE + digits
    return digits if 10 <= len(digits) <= 15 else None


def _name(text: str) -> str:
    return re.sub(r"^(?:my|the)\s+", "", text.strip(" .,:'\""), flags=re.I).lower()


# ── Matching ──────────────────────────────────────────────────────────────────

def match_whatsapp_command(text: str, original: str | None = None) -> dict | None:
    """
    WhatsApp commands. `text` has been through normalize_command(); `original` is the message as said,
    so the message keeps its punctuation ("are you coming?").
    """
    text = text.strip()
    for pattern in _SAVE:
        if m := pattern.match(text):
            return {"type": "system", "action": "save_contact", "name": _name(m["name"]), "number": m["num"]}
    if _LIST.match(text):
        return {"type": "system", "action": "list_contacts"}
    if m := _REMOVE.match(text):
        return {"type": "system", "action": "remove_contact", "name": _name(m["a"] or m["b"])}

    mentions_whatsapp = bool(re.search(rf"\b{_WHATSAPP}\b", text, re.I))
    m = _SEND.match(_ON_WHATSAPP.sub("", text, count=1))
    if not m:
        return None
    rest = m["rest"].strip()
    try:
        contacts = load()
    except AutomationError:
        contacts = {}

    who, body = None, None
    if number := _NUMBER.match(rest):
        who, body = number["num"], rest[number.end():]
    else:
        for name in sorted(contacts, key=len, reverse=True):  # "whatsapp mom I'll be late": a saved name first
            if re.match(rf"(?:my\s+)?{re.escape(name)}\b", rest, re.I):
                who = name
                body = re.sub(rf"^(?:my\s+)?{re.escape(name)}", "", rest, count=1, flags=re.I)
                break
        if who is None and mentions_whatsapp:  # an unknown name needs a clear break before the message
            parts = re.split(r"\s*[:,]\s*|\s+(?:saying|that|to say|and say)\s+", rest, maxsplit=1)
            if len(parts) == 2:
                who, body = _name(parts[0]), parts[1]
    if who is None or not (mentions_whatsapp or who in contacts):  # "tell me a joke" isn't a message
        return None
    body = _BODY_LEAD.sub("", body or "", count=1).strip()
    if original and body:  # take the message as it was said, punctuation and all
        at = original.lower().rfind(body.lower())
        if at >= 0:
            body = original[at:].strip()
    return {"type": "system", "action": "send_whatsapp", "contact": who, "text": body}


# ── Doing it ──────────────────────────────────────────────────────────────────

def recipient(contact: str) -> tuple[str, str]:
    """(display name, number) for a saved name or a number said directly."""
    if re.fullmatch(r"\+?[\d\s-]+", contact):
        number = clean_number(contact)
        if not number:
            raise AutomationError(f"{contact} doesn't look like a phone number.")
        return number, number
    number = load().get(contact)
    if not number:
        raise AutomationError(
            f'I don\'t have a number for {contact}. Say "save {contact}\'s number as …" first.')
    return contact.title(), number


def confirmation(parsed: dict) -> str:
    name, number = recipient(parsed["contact"])
    if not parsed["text"]:
        raise AutomationError(f'What should I say to {name}? Try "message {parsed["contact"]} on WhatsApp: …".')
    parsed['_recipient_number'] = number
    return f'Send "{parsed["text"]}" to {name} on WhatsApp? Reply "yes" to send or "no" to cancel.'


def send(parsed: dict, foreground_app) -> str:
    """Open the chat with the message typed in, then press Enter once WhatsApp is in front."""
    with settings_store.lock:
        name, number = recipient(parsed["contact"])
        if parsed.get('_recipient_number', number) != number:
            raise AutomationError('That contact changed since confirmation. Ask again to review the recipient.')
    try:
        os.startfile(f"whatsapp://send?phone={number}&text={quote(parsed['text'])}")
    except OSError as e:
        logger.warning(f"WhatsApp link failed: {e}")
        raise AutomationError("Couldn't open WhatsApp — is WhatsApp Desktop installed?")

    deadline = time.monotonic() + WINDOW_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if (foreground_app() or "").startswith("whatsapp"):
            break
    else:
        return f"I opened your chat with {name} with the message typed in — press Enter in WhatsApp to send it."
    time.sleep(CHAT_LOAD_SECONDS)
    if not (foreground_app() or "").startswith("whatsapp"):  # the user clicked away meanwhile: don't press Enter there
        return f"The message to {name} is typed in WhatsApp — press Enter there to send it."
    keyboard.press_keys("enter")
    logger.info(f"WhatsApp message sent to {name}")
    return f"Sent to {name} on WhatsApp."


@settings_store.synchronized
def run_contacts(parsed: dict) -> str:
    action, contacts = parsed["action"], load()
    if action == "list_contacts":
        if not contacts:
            return 'You haven\'t saved any contacts yet. Say "save mom\'s number as 98765 43210".'
        return "Your contacts: " + ", ".join(f"{n.title()} ({num})" for n, num in contacts.items()) + "."
    name = parsed["name"]
    if action == "remove_contact":
        if name not in contacts:
            raise AutomationError(f"You don't have a contact called {name}.")
        del contacts[name]
        _save(contacts)
        return f"Removed {name.title()} from your contacts."
    number = clean_number(parsed["number"])
    if not number or not name:
        raise AutomationError(f'"{parsed["number"]}" doesn\'t look like a phone number.')
    verb = "Updated" if name in contacts else "Saved"
    contacts[name] = number
    _save(contacts)
    return f'{verb} {name.title()}: +{number}. Say "message {name} on WhatsApp: …" to send one.'
