"""Local-only phone commands; notification content never enters AI/history."""

import asyncio
import re

from services.automation.results import ActionResult
from services.phone import bridge as phone
from services.phone.transport import PhoneError

ACTIONS = {"phone_status", "phone_choose", "phone_forget", "phone_notifications", "phone_read", "phone_reply", "phone_ring"}
PRIVATE_MEMORY = "(Phone command handled locally; notification contents and reply text were not retained.)"


def match_command(message):
    text = " ".join(message.replace("’", "'").split()).strip(" .!?")
    text = re.sub(r"^(?:(?:hey |okay |ok )?friday[, ]+|please )+", "", text, flags=re.I)
    patterns = (
        (r"(?:phone status|list (?:my )?phones|show (?:my )?phones)", "phone_status"),
        (r"(?:forget|disconnect) (?:my |the )?phone(?: selection)?", "phone_forget"),
        (r"(?:read|show|list)(?: me)? (?:my |the )?phone notifications", "phone_notifications"),
        (r"ring (?:my |the )?phone", "phone_ring"),
    )
    for pattern, action in patterns:
        if re.fullmatch(pattern, text, re.I):
            return {"type": "system", "action": action}
    if found := re.fullmatch(r"use phone (.+)", text, re.I):
        return {"type": "system", "action": "phone_choose", "device": found[1]}
    if found := re.fullmatch(r"read (?:phone )?notification (\d{1,2})", text, re.I):
        return {"type": "system", "action": "phone_read", "number": int(found[1])}
    if re.fullmatch(r"read (?:that|the selected) (?:phone )?notification", text, re.I):
        return {"type": "system", "action": "phone_read"}
    # Match against original text to preserve reply punctuation and casing.
    if found := re.match(r"^\s*(?:friday[, ]+)?reply(?: to (?:the )?phone notification)?(?:\s+that|\s+saying|\s*:)\s+(.+)$",
                         message, re.I | re.S):
        return {"type": "system", "action": "phone_reply", "message": found[1].strip()}
    return None


def private_turn(message):
    from services.automation import intent
    if match_command(message):
        return True
    pending = intent._pending.get(intent.remote_request.get())
    reply = " ".join(re.findall(r"[a-z']+", message.lower().replace("’", "'")))
    return bool(pending and pending.parsed.get("action") == "phone_reply"
                and reply in intent.AFFIRMATIVE_REPLIES | intent.NEGATIVE_REPLIES)


async def handle(message, provider):
    from services.automation import intent
    if intent.remote_request.get():
        return ActionResult(False, "Phone notifications and replies are available at the laptop only.", PRIVATE_MEMORY, False)
    if parsed := match_command(message):
        intent.cancel_pending_confirmation()
        result = await asyncio.to_thread(intent._execute, parsed)
    else:
        result = await intent._handle_pending_reply(message, provider)
    if result is None:
        return ActionResult(False, "That phone reply was already handled or cancelled. Read the notification again.",
                            PRIVATE_MEMORY, False)
    return result._replace(memory_message=PRIVATE_MEMORY, repeatable=False)


def run(parsed, confirmed=False):
    from services.automation import intent
    if intent.remote_request.get():
        return ActionResult(False, "Phone commands are available at the laptop only.", PRIVATE_MEMORY, False)
    try:
        action = parsed["action"]
        if action == "phone_reply":
            if not confirmed:
                target, question = phone.bridge.draft(parsed["message"])
                return intent._ask_first({"type": "system", "action": action, "target": target}, question)._replace(
                    memory_message=PRIVATE_MEMORY, repeatable=False)
            text = phone.bridge.submit(parsed["target"])
        else:
            functions = {"phone_status": phone.bridge.status, "phone_ring": phone.bridge.ring,
                         "phone_notifications": phone.bridge.list_notifications, "phone_forget": phone.bridge.forget,
                         "phone_read": lambda: phone.bridge.read(parsed.get("number")),
                         "phone_choose": lambda: phone.bridge.choose(parsed["device"])}
            text = functions[action]()
        return ActionResult(True, text, PRIVATE_MEMORY, False)
    except PhoneError as error:
        return ActionResult(False, str(error), PRIVATE_MEMORY, False)
