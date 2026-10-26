"""
services/telegram/bot.py

FRIDAY on Telegram (docs/superpowers/specs/2026-09-28-telegram-bot-design.md).
Runs inside the API process (started from interfaces/api/app.py) when
TELEGRAM_BOT_TOKEN is set. It asks Telegram for new messages (long polling), so
the laptop never has to be reachable from outside.

Messages go through the command bar's own path (routes/chat.chat): commands, AI
chat, memory and FRIDAY's yes/no confirmations all work. On top of that:
  - a reply that types into the focused app asks "Type this into …? yes/no" first
  - "take a screenshot" sends the picture back
  - voice notes are transcribed by the local Whisper
  - "send me my <file>" / "/send <file>" uploads the best file-search hit, after a yes
  - "/status", "/lockdown" (undone only by "unlock telegram" at the laptop)
  - send-to-laptop: a link opens in the browser, a file/photo is saved to Downloads\\FRIDAY and
    shown in Explorer (never opened or run), "copy <text>" puts the text on the clipboard
Only TELEGRAM_USER_ID is answered; forwarded and stale messages are never run.
"""

import asyncio
import io
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
from core.errors import FridayError
from core.logger import logger
from services.automation import intent, keyboard
from services.automation.system_control import system
from services.network.status import network
from services.proactive import buttons
from services.telegram import client
from services.telegram.client import TelegramError

POLL_SECONDS = 25            # Telegram holds each request open this long waiting for a message
STALE_SECONDS = 120          # older messages (sent while FRIDAY was off) are not run
CONFIRM_SECONDS = 120
MAX_UPLOAD_BYTES = client.MAX_UPLOAD_BYTES
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # the most a bot may fetch from Telegram
RECEIVED_DIR = Path.home() / "Downloads" / "FRIDAY"  # tests point this elsewhere
FILE_KINDS = {"document": "", "photo": ".jpg", "video": ".mp4", "audio": ".mp3"}  # message key → extension if unnamed
HELP = (
    "I'm FRIDAY. Send me anything you'd type into the command bar, or a voice note.\n"
    "/status — battery, what's in use, whether you're away\n"
    "/send <file> — send a file from the laptop\n"
    "Send a link, file or photo to put it on the laptop; \"copy <text>\" copies text there\n"
    "\"note <text>\" saves a note; \"tell me when blender closes\" (or when it's charged, or <url> changes)\n"
    "/menu — buttons for your usual commands\n"
    "/lock, /sleep, /shutdown [minutes], /restart, /cancel — the laptop's power (sleep/shutdown/restart ask first)\n"
    "/away — pause, lock, and send notifications here straight away until you're back\n"
    "/lockdown — turn off remote control (undo it at the laptop: \"unlock telegram\")"
)
_LINK = re.compile(r"https?://\S+", re.I)
_COPY = re.compile(r"^copy\s+(?P<text>.+?)(?:\s+(?:to|into|onto)\s+(?:the\s+|my\s+)?clipboard)?$", re.I | re.S)
_SEND_FILE = re.compile(r"^(?:/send\s+|send\s+me\s+(?:my|the)\s+)(?P<query>.+?)(?:\s+file)?$", re.I)

started_at = time.time()  # reset when the bot starts
_pending: dict | None = None  # {"do": callable → reply, "expires": monotonic time} waiting for yes/no
_ignored: set[int] = set()


async def say(chat_id: int, text: str, links: list[tuple[str, str]] | None = None) -> None:
    try:
        await asyncio.to_thread(client.send, chat_id, text, links)
    except TelegramError as e:
        logger.warning(f"Telegram: couldn't reply: {e}")


def _yes_no(text: str) -> bool | None:
    reply = " ".join(re.findall(r"[a-z']+", text.lower().replace("’", "'")))
    return True if reply in intent.AFFIRMATIVE_REPLIES else False if reply in intent.NEGATIVE_REPLIES else None


def _ask(question: str, do) -> str:
    global _pending
    _pending = {"do": do, "expires": time.monotonic() + CONFIRM_SECONDS}
    return f"{question} Reply yes or no."


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(n // 1024, 1)} KB"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def status_text() -> str:
    import psutil
    from services.activity.log import activity_log, idle_seconds
    from services.automation import modes

    battery = psutil.sensors_battery()
    idle = idle_seconds()
    mode = modes.active()
    lines = [
        f"Battery {battery.percent:.0f}%{', charging' if battery.power_plugged else ''}" if battery else None,
        f"In use: {activity_log.app}" if activity_log.app else "Nothing in use",
        f"{mode['name'].title()} mode is on" if mode else None,
        "You're at the laptop" if idle < 60 else f"Away for {_duration(idle)}",
        "Remote control is locked" if client.locked() else None,
    ]
    return "\n".join(line for line in lines if line)


def _find_file(query: str):
    from services.files.search import find_files

    if not config.FILE_SEARCH_ENABLED:
        return None
    return next((hit for hit in find_files(query) if os.path.isfile(hit.path)), None)


def _transcribe(file_id: str) -> str:
    from faster_whisper import decode_audio
    from services.voice.stt import SAMPLE_RATE, stt

    audio = decode_audio(io.BytesIO(client.download(file_id)), sampling_rate=SAMPLE_RATE)
    return stt.transcribe(audio)


# ── Handling ──────────────────────────────────────────────────────────────────

async def handle(update: dict) -> None:
    if "callback_query" in update:
        return await _on_button(update["callback_query"])
    message = update.get("message")
    if not message:
        return
    user, chat_id = message.get("from", {}).get("id"), message["chat"]["id"]
    if not config.TELEGRAM_USER_ID:  # setting up: the only thing a stranger could learn is their own ID
        return await say(chat_id, f"Your Telegram ID is {user}. Add TELEGRAM_USER_ID={user} to FRIDAY's .env and restart FRIDAY.")
    if user != config.TELEGRAM_USER_ID:
        if user not in _ignored:
            _ignored.add(user)
            logger.warning(f"Telegram: ignoring messages from user {user} (not TELEGRAM_USER_ID)")
        return
    if message.get("date", 0) < max(started_at, time.time() - STALE_SECONDS):
        return await say(chat_id, "That came in while I was offline, so I didn't run it. Send it again if you still want it.")
    kind = next((key for key in FILE_KINDS if key in message), None)  # a file is only saved: fine forwarded too
    if ("forward_origin" in message or "forward_date" in message) and not kind:
        return await say(chat_id, "I don't run forwarded messages. Type it yourself if you want it done.")

    text = (message.get("text") or "").strip()
    command = text.split("@")[0].lower()  # "/status@FridayBot" in group-style clients
    if command in ("/start", "/help"):
        return await say(chat_id, HELP)
    if command == "/status":
        return await say(chat_id, await asyncio.to_thread(status_text))
    if command == "/lockdown":
        client.set_locked(True)
        return await say(chat_id, 'Remote control is off. Notifications still come here. Say "unlock telegram" at the laptop to turn it back on.')
    if client.locked():
        return await say(chat_id, 'Remote control is locked. Say "unlock telegram" at the laptop to turn it back on.')
    if command == "/menu":
        return await say(chat_id, "Your usual commands:", [(label, f"c|{label}") for label in await asyncio.to_thread(menu)])
    text = slash_command(text) or text

    if kind:
        return await _receive_file(chat_id, message, kind)
    if "voice" in message:
        try:
            text = await asyncio.to_thread(_transcribe, message["voice"]["file_id"])
        except Exception as e:
            logger.warning(f"Telegram voice note failed: {e}")
            text = ""
        if not text:
            return await say(chat_id, "Couldn't make that out. Try typing it.")
        await say(chat_id, f'Heard: "{text}"')
    if not text:
        return await say(chat_id, "I can read text and voice notes.")
    await _run(chat_id, text)


async def _run(chat_id: int, text: str) -> None:
    # Shortcut handlers and their worker threads belong to Telegram too, not
    # just requests that reach the shared chat route.
    token = intent.remote_request.set(True)
    try:
        await _run_remote(chat_id, text)
    finally:
        intent.remote_request.reset(token)


def _drop_command_followups() -> None:
    """A bot-owned turn ends older questions in this conversation only."""
    from services.telegram import commands

    intent.cancel_pending_confirmation()
    commands._pending_files.pop(intent.remote_request.get(), None)


async def _run_remote(chat_id: int, text: str) -> None:
    global _pending
    pending, _pending = _pending, None
    if pending and (answer := _yes_no(text)) is not None:  # any other message drops the question
        _drop_command_followups()
        if time.monotonic() > pending["expires"]:
            return await say(chat_id, "That question timed out, so I didn't do anything. Ask again.")
        if not answer:
            return await say(chat_id, "Okay, cancelled.")
        try:
            return await say(chat_id, await asyncio.to_thread(pending["do"]))
        except (FridayError, TelegramError, OSError) as e:
            return await say(chat_id, f"That didn't work: {getattr(e, 'message', e)}")

    if link := shared_link(text):
        _drop_command_followups()
        try:
            await asyncio.to_thread(system.open_url, link)
        except FridayError as e:
            return await say(chat_id, e.message)
        return await say(chat_id, "Opened it on the laptop.")
    if copy := _COPY.match(text):
        _drop_command_followups()
        try:
            return await say(chat_id, await asyncio.to_thread(system.write_clipboard, copy["text"].strip()))
        except FridayError as e:
            return await say(chat_id, e.message)

    wanted = _SEND_FILE.match(text)
    hit = wanted and await asyncio.to_thread(_find_file, wanted["query"])
    if hit:  # no match → it's probably not about a file: handled like any message
        _drop_command_followups()
        size = os.path.getsize(hit.path)
        if size > MAX_UPLOAD_BYTES:
            return await say(chat_id, f"{hit.name} is {_size(size)} — Telegram only takes files up to 50 MB.")

        def upload():
            client.send_file(chat_id, Path(hit.path))
            return f"Sent {hit.name}."
        return await say(chat_id, _ask(f"Send {hit.name} ({_size(size)})?", upload))

    from interfaces.api.routes.chat import ChatRequest, chat  # the command bar's path

    before = system.last_screenshot
    try:
        response = await chat(ChatRequest(message=text[:4000]))
    except FridayError as e:
        return await say(chat_id, e.message)
    await say(chat_id, response.response)
    if system.last_screenshot and system.last_screenshot != before:
        try:
            await asyncio.to_thread(client.send_file, chat_id, system.last_screenshot, True)
        except (TelegramError, OSError) as e:
            await say(chat_id, f"Couldn't send the screenshot: {e}")
    if response.keyboard:
        await say(chat_id, _confirm_typing(response.keyboard))


def shared_link(text: str) -> str | None:
    """A message that is just a link, or a phone's share ("Title\\nhttps://…"): that link."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    links = [line for line in lines if _LINK.fullmatch(line)]
    return links[0] if len(links) == 1 and len(lines) <= 3 else None


def _unique(folder: Path, name: str) -> Path:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(name).name).strip(" .") or "file"
    target, n = folder / name, 1
    while target.exists():
        target, n = folder / f"{Path(name).stem} ({n}){Path(name).suffix}", n + 1
    return target


def _reveal(path: Path) -> None:
    subprocess.Popen(["explorer", "/select,", str(path)])


async def _receive_file(chat_id: int, message: dict, kind: str) -> None:
    item = message[kind][-1] if kind == "photo" else message[kind]  # photos come in sizes: the largest is last
    size = item.get("file_size", 0)
    if size > MAX_DOWNLOAD_BYTES:
        return await say(chat_id, f"That's {_size(size)} — Telegram only lets me fetch files up to 20 MB.")
    name = item.get("file_name") or f"{kind} {datetime.now():%Y-%m-%d %H-%M-%S}{FILE_KINDS[kind]}"

    def save() -> Path:
        data = client.download(item["file_id"])
        RECEIVED_DIR.mkdir(parents=True, exist_ok=True)
        target = _unique(RECEIVED_DIR, name)
        target.write_bytes(data)
        _reveal(target)  # shown, never opened: it could be anything
        return target
    try:
        target = await asyncio.to_thread(save)
    except (TelegramError, OSError) as e:
        return await say(chat_id, f"Couldn't save it: {e}")
    await say(chat_id, f"Saved {target.name} to Downloads\\FRIDAY.")


def _confirm_typing(steps: list[dict]) -> str:
    from services.activity.log import foreground_window

    app, title = foreground_window()
    preview = " then ".join(f'"{step["text"]}"' if "text" in step else f"press {step.get('keys')}" for step in steps)
    if len(preview) > 300:
        preview = preview[:299] + "…"

    def type_it():
        keyboard.run_steps(steps)
        return "Done."
    return _ask(f"Type {preview} into {title or app or 'the active window'}?", type_it)


_SLASH = {"/lock": "lock the laptop", "/sleep": "put the laptop to sleep", "/restart": "restart the laptop",
          "/away": "I'm going out", "/cancel": "cancel the shutdown"}
MENU_SIZE = 8
MENU_ALWAYS = ["take a screenshot", "what's due", "what classes do I have today"]
# The command a logged action means (the log keeps the action and its app/site, never the typed text)
AS_TEXT = {"open_app": "open {}", "open_url": "go to {}", "media_play": "play music", "play_music": "play music",
           "media_pause": "pause", "media_next": "next song", "take_screenshot": "take a screenshot",
           "run_routine": "run {}", "start_mode": "start {} mode", "resume_project": "resume {}",
           "log_in": "log me in to {}", "lock_pc": "lock the laptop"}


def slash_command(text: str) -> str | None:
    """/lock, /sleep, /shutdown 30, /restart, /away, /cancel → what they mean in words."""
    word, _, rest = text.strip().partition(" ")
    word = word.split("@")[0].lower()
    if word == "/shutdown":
        return f"shut down in {rest.strip()} minutes" if rest.strip().isdigit() else "shut down the laptop"
    return _SLASH.get(word)


def menu(now: datetime | None = None) -> list[str]:
    """The user's most-used commands over the last 30 days, as text (for /menu's buttons, ≤ 64 bytes each)."""
    from collections import Counter

    from services.activity.log import activity_log

    since = ((now or datetime.now()) - timedelta(days=30)).isoformat()
    used = Counter()
    for r in activity_log.command_rows():
        if r["at"] >= since and r["success"] and (template := AS_TEXT.get(r["action"])):
            if "{}" not in template or r["target"]:
                used[template.format(r["target"] or "")] += 1
    labels = [text for text, _ in used.most_common(MENU_SIZE)]
    labels += [t for t in MENU_ALWAYS if t not in labels]
    return [label for label in labels if len(f"c|{label}".encode()) <= 64][:MENU_SIZE]


async def _on_button(query: dict) -> None:
    if not config.TELEGRAM_USER_ID or query.get("from", {}).get("id") != config.TELEGRAM_USER_ID:
        return
    try:
        await asyncio.to_thread(client.call, "answerCallbackQuery", callback_query_id=query["id"])
    except TelegramError:
        pass  # only stops the button's spinner
    chat_id = query["message"]["chat"]["id"]
    if client.locked():
        return await say(chat_id, 'Remote control is locked. Say "unlock telegram" at the laptop to turn it back on.')
    data = query.get("data") or ""
    if data.startswith("c|"):  # a /menu button: run that command as if typed
        return await _run(chat_id, data[2:])
    parts = data.split("|")
    if len(parts) != 3 or parts[0] != "b":
        return
    try:
        reply = await asyncio.to_thread(buttons.respond, parts[1], parts[2])
    except FridayError as e:
        reply = e.message
    await say(chat_id, reply)


# ── The loop ──────────────────────────────────────────────────────────────────

async def run_bot() -> None:
    """Runs for the lifetime of the API process; started from app.py's lifespan. Off without a token."""
    global started_at
    if not client.enabled():
        return
    started_at = time.time()
    logger.info("Telegram bot started" + ("" if config.TELEGRAM_USER_ID else " — waiting for TELEGRAM_USER_ID"))
    offset, delay = 0, 1
    while True:
        if not network.online:  # no internet: nothing to ask Telegram
            await asyncio.sleep(10)
            continue
        try:
            updates = await asyncio.to_thread(
                client.call, "getUpdates", http_timeout=POLL_SECONDS + 10,
                offset=offset, timeout=POLL_SECONDS, allowed_updates=["message", "callback_query"],
            )
            delay = 1
        except TelegramError as e:
            logger.warning(f"Telegram: {e}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                await handle(update)
            except Exception as e:
                logger.error(f"Telegram message failed: {e}", exc_info=True)
