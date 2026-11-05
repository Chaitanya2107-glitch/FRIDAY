"""Telegram commands shared by typed and spoken requests at the laptop."""

import asyncio
import re
import time
from pathlib import Path

from core.config import config
from core.errors import MemoryError
from core.logger import logger
from services.automation.command_words import RESULT_NUMBERS, TRAILING_FILLER, normalize_command, strip_leading_filler
from services.automation.results import ActionResult
from services.files import assistant
from services.files.search import find_files
from services.memory.sqlite_memory import MemoryService
from services.telegram import capabilities, client, summaries

_CHANNEL = r"(?:telegram|telgram|tele gram)(?:\s+bot)?"
_DESTINATION = rf"(?:through|via|in|on|over|using|to|with)\s+(?:(?:my|the|your)\s+)?{_CHANNEL}"
_TAIL = rf"(?:[\s,]+(?:{'|'.join(TRAILING_FILLER)}))*[\s.!?]*"
_SEND = re.compile(rf"^(?:send|share|upload)(?:\s+me)?\s+(?P<what>.+?)\s+"
                   rf"{_DESTINATION}{_TAIL}$", re.I | re.S)
_MESSAGE_AFTER = re.compile(rf"^(?:send|share)(?:\s+me)?\s+(?:(?:a|the)\s+)?(?:message|text)\s+"
                            rf"{_DESTINATION}\s+(?:saying|that says|containing)\s+(?P<text>.*)$", re.I | re.S)
_TEXT = re.compile(r"^(?:(?:a|the)\s+)?(?:message|text)(?:\s+(?:saying|that says|containing))?"
                   r"(?:\s+|:\s*|$)(?P<text>.*)$", re.I | re.S)
_FILE = re.compile(r"^(?:(?:a|the|my)\s+)?(?:file|document|attachment)(?:\s+(?P<reference>.+))?$", re.I | re.S)
_ANSWER = re.compile(r"^(?:(?:the|your|that|this)\s+)?(?:last\s+|previous\s+)?(?:answer|reply|response)$", re.I)
_STATUS = re.compile(rf"^(?:{_CHANNEL}\s+status|(?:do you|you)\s+(?:have|know you have|know that you have)\s+"
                     rf"(?:(?:a|the|your)\s+)?{_CHANNEL}|is\s+{_CHANNEL}\s+connected|"
                     rf"are you connected to\s+{_CHANNEL})$", re.I)
_NUMBER = re.compile(r"^(?:the )?(?:(?:file|result) )?(?P<n>\d+|first|second|third|fourth|fifth)"
                     r"(?: (?:file|result|one))?$", re.I)
_REFERENCES = {"it", "that", "this", "that file", "this file", "the file", "the last file", "last file"}
_FOLLOWUP = re.compile(r"^(?:send|share|upload)(?:\s+me)?\s+(?P<what>.+)$", re.I | re.S)
_pending_files: dict[bool, float] = {}  # laptop and Telegram conversations stay separate
FILE_FOLLOWUP_SECONDS = 120


def _remote() -> bool:
    from services.automation.intent import remote_request
    return remote_request.get()


def _unquote(text: str) -> str:
    text = text.strip()
    pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
    return text[1:-1] if len(text) >= 2 and pairs.get(text[0]) == text[-1] else text


def match_command(message: str) -> dict | None:
    # Strip only the command prefix; normalization would rewrite contractions
    # and remove punctuation from the literal message to send.
    original = message.strip()
    text = original[len(original) - len(strip_leading_filler(original)):]
    if _STATUS.fullmatch(normalize_command(text)):
        return {"action": "telegram_status"}
    if found := _MESSAGE_AFTER.fullmatch(text):
        return {"action": "telegram_message", "text": _unquote(found["text"])}
    if found := _SEND.fullmatch(text):
        what = re.sub(r"\s+to me$", "", found["what"], flags=re.I).strip()
        if file := _FILE.fullmatch(what):
            return {"action": "telegram_file", "reference": file["reference"] or "the file"}
        if literal := _TEXT.fullmatch(what):
            return {"action": "telegram_message", "text": _unquote(literal["text"])}
        quoted = re.sub(r"^(?:a|an)\s+", "", what, flags=re.I)
        payload = _unquote(quoted)
        # Quoted paths/names retain their existing file meaning. Explicit
        # 'message'/'text' above can send any literal, including a filename.
        looks_like_file = re.fullmatch(r"\.\w{1,10}", Path(payload).suffix) or re.search(r"[\\/]", payload)
        if (payload != quoted and not looks_like_file) or quoted.lower() in {"hi", "hello", "hey"}:
            return {"action": "telegram_message", "text": payload}
        if _ANSWER.fullmatch(what):
            return {"action": "telegram_answer"}
        clean = re.sub(r"^(?:my|the|today's)\s+", "", what.lower())
        if clean in {"briefing", "daily briefing", "morning briefing"}:
            return {"action": "telegram_summary", "kind": "morning"}
        if clean in {"summary", "daily summary", "nightly summary", "nightly recap", "daily recap", "day summary"}:
            return {"action": "telegram_summary", "kind": "nightly"}
        if clean in {"weekly summary", "weekly recap", "week summary", "week's summary"}:
            return {"action": "telegram_summary", "kind": "weekly"}
        if clean in {"learning report", "training data status", "learning summary"}:
            return {"action": "telegram_summary", "kind": "learning"}
        return {"action": "telegram_file", "reference": what}
    if time.monotonic() < _pending_files.get(_remote(), 0):
        followup = _FOLLOWUP.fullmatch(text)
        # Accept an explicit send, a result number, or a filename/path after
        # asking which file. Other turns end the clarification in try_handle.
        if followup or _NUMBER.fullmatch(text) or re.fullmatch(r'[^\n?]+\.[\w]{1,10}[\"\']?', text):
            reference = followup["what"] if followup else text
            if file := _FILE.fullmatch(reference):
                reference = file["reference"] or "the file"
            return {"action": "telegram_file", "reference": reference}
    # Chat/voice call this before search or other command handlers, so even
    # turns handled before try_handle end an unrelated file clarification.
    _pending_files.pop(_remote(), None)
    return None


def _file(reference: str) -> Path:
    text = reference.strip().strip('"').strip("'")
    hits = assistant.last_results.get()
    if text.lower() in _REFERENCES:
        selected = assistant.last_results.selected
        if hits and selected in hits:
            return Path(selected.path)
        if len(hits) == 1:
            return Path(hits[0].path)
        if hits:
            raise ValueError("Which file? Say 'send me file 2 through telegram', or give its name.")
        raise ValueError("Which file? Find it first or say 'send me <file name> through telegram'.")
    if number := _NUMBER.fullmatch(text):
        n = int(number["n"]) if number["n"].isdigit() else RESULT_NUMBERS[number["n"].lower()]
        if not 1 <= n <= len(hits):
            raise ValueError("That file result is unavailable or expired. Find the file again.")
        return Path(hits[n - 1].path)
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    if not config.FILE_SEARCH_ENABLED:
        raise ValueError("File search is off. Give the file's full path or enable FILE_SEARCH_ENABLED.")
    query = re.sub(r"^(?:my|the)\s+", "", text, flags=re.I)
    hits = find_files(query)
    exact = [hit for hit in hits if hit.name.lower() == query.lower()]
    candidates = exact or hits
    assistant.last_results.set(candidates)
    if len(candidates) == 1:
        return Path(candidates[0].path)
    if not candidates:
        raise ValueError("I couldn't find that file. Give its name or full path.")
    shown = "; ".join(f"{n}. {hit.name}" for n, hit in enumerate(candidates[:5], 1))
    raise ValueError(f"Which file? {shown}. Say 'send me file 2 through telegram'.")


def run(parsed: dict) -> ActionResult:
    _pending_files.pop(_remote(), None)
    if parsed["action"] == "telegram_status":
        success, text = capabilities.status()
        return ActionResult(success, text, repeatable=False)
    if not capabilities.ready():
        return ActionResult(False, "My Telegram bot needs TELEGRAM_BOT_TOKEN and TELEGRAM_USER_ID configured.", repeatable=False)
    try:
        logger.debug("Telegram command matched: %s", parsed["action"])
        if parsed["action"] == "telegram_message":
            if not parsed["text"].strip():
                return ActionResult(False, "What text should I send through Telegram?", repeatable=False)
            client.send_long(config.TELEGRAM_USER_ID, parsed["text"])
            return ActionResult(True, "Sent your message through my Telegram bot.", repeatable=False)
        if parsed["action"] == "telegram_answer":
            answer = MemoryService().get_last_assistant_message()
            if not answer or not answer.strip():
                return ActionResult(False, "I don't have a saved answer to send yet. Ask me a question first.", repeatable=False)
            client.send_long(config.TELEGRAM_USER_ID, answer)
            return ActionResult(True, "Sent your previous answer exactly as written through my Telegram bot.", repeatable=False)
        if parsed["action"] == "telegram_summary":
            summaries.deliver(parsed["kind"])
            return ActionResult(True, f"Sent your {parsed['kind']} summary through my Telegram bot.", repeatable=False)
        # Explorer supplies a structured path; preserve filename punctuation.
        path = Path(parsed["path"]) if "path" in parsed else _file(parsed["reference"])
        if not path.is_file():
            raise ValueError("That file is no longer available. Find it again or give its current path.")
        if path.stat().st_size > client.MAX_UPLOAD_BYTES:
            raise ValueError("That file is over Telegram's 50 MB upload limit.")
        client.send_file(config.TELEGRAM_USER_ID, path)
        assistant.last_results.selected = next((hit for hit in assistant.last_results.get()
                                                if Path(hit.path) == path), None)
        return ActionResult(True, f"Sent {path.name} through my Telegram bot.",
                            memory_message="Sent the requested file through Telegram.", repeatable=False)
    except ValueError as error:
        if parsed["action"] == "telegram_file" and "path" not in parsed:
            _pending_files[_remote()] = time.monotonic() + FILE_FOLLOWUP_SECONDS
        return ActionResult(False, str(error), memory_message="Telegram needs a specific available file.", repeatable=False)
    except MemoryError as error:
        logger.warning("Telegram answer could not be read: %s", type(error).__name__)
        return ActionResult(False, "I couldn't read the saved answer. Try again in a moment.", repeatable=False)
    except (client.TelegramError, OSError) as error:
        logger.warning("Telegram command failed: %s", type(error).__name__)
        return ActionResult(False, "I couldn't send that through Telegram. Check the connection and bot settings, then try again.",
                            repeatable=False)


async def try_handle(message: str) -> ActionResult | None:
    parsed = match_command(message)
    return await asyncio.to_thread(run, parsed) if parsed else None
