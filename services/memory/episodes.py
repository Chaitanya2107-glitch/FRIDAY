"""
services/memory/episodes.py

Conversations remembered, not just facts: once a chat has gone quiet for QUIET_MINUTES (typed, voice or
conversation mode — they share one history), the new messages are summed up in a sentence or two and
saved to long-term memory as an "episode" (services/memory/semantic.py). Replies recall them by meaning
("Earlier conversation: …"), and "what did we talk about yesterday" lists them.

Checked once a minute from services/proactive/watcher.py. Private messages (notes, journal entries,
text to type, WhatsApp messages) are left out, as in the nightly reflection.
State: memory/mind/episodes.json {"last_id": id of the last message already summed up}.
"""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from core.config import config
from core.logger import logger
from providers.base_provider import Message

path = config.MEMORY_DIR / "mind" / "episodes.json"  # tests point this elsewhere
QUIET_MINUTES = 20
MIN_MESSAGES = 4       # two back-and-forths at least — "open chrome" / "Opening Chrome." isn't a conversation
MAX_CHARS = 6000

PROMPT = (
    "Below is a conversation between the Boss and Friday, their personal AI. Sum it up for Friday's long-term "
    "memory in ONE or TWO short sentences, in the third person: what they talked about, and anything the Boss "
    "decided, felt or asked Friday to keep in mind. Skip the commands (opening apps, volume …). If it was only "
    "commands and nothing worth remembering, reply with just: nothing"
)


def _last_id() -> int | None:
    """None the very first time: older history isn't summed up all at once."""
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("last_id", 0))
    except (OSError, ValueError):
        return None


def _save(last_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_id": last_id}), encoding="utf-8")


def _new_messages(after: int) -> list[tuple[int, str, str, str]]:
    """(id, role, content, UTC timestamp) after `after`, oldest first."""
    try:
        with closing(sqlite3.connect(config.MEMORY_DB_PATH)) as conn:
            return conn.execute("SELECT id, role, content, timestamp FROM conversations WHERE id > ? ORDER BY id",
                                (after,)).fetchall()
    except sqlite3.Error as e:
        logger.warning(f"Episodes couldn't read the chat history: {e}")
        return []


def due(rows: list, now: datetime) -> bool:
    """Enough of a chat, and quiet for QUIET_MINUTES."""
    if len(rows) < MIN_MESSAGES or sum(r[1] == "user" for r in rows) < 2:
        return False
    try:
        last = datetime.fromisoformat(rows[-1][3])
    except ValueError:
        return True
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc) - last).total_seconds() >= QUIET_MINUTES * 60


async def summarize_if_due(now: datetime | None = None) -> str | None:
    """Sum up the chat since the last episode, once it's gone quiet. Returns the summary saved, or None."""
    if config.AI_ASSIST_ONLY:
        return None
    from providers.failover import complete_with_failover
    from services.memory.semantic import semantic_memory
    from services.mind.reflection import _private

    now = now or datetime.now().astimezone()
    last_id = _last_id()
    rows = await asyncio.to_thread(_new_messages, last_id or 0)
    if last_id is None:  # first run: start from here
        _save(rows[-1][0] if rows else 0)
        return None
    if not due(rows, now):
        return None
    _save(rows[-1][0])  # first, so a failure can't repeat it every minute
    chat = "\n".join(f"{'Boss' if role == 'user' else 'Friday'}: {content}" for _, role, content, _ in rows
                     if not (role == "user" and _private(content)))[-MAX_CHARS:]
    try:
        reply = await complete_with_failover(config.ACTIVE_PROVIDER, [Message(role="user", content=chat)], PROMPT, 800)
    except Exception as e:
        logger.warning(f"Couldn't sum up the conversation: {e}")
        return None
    summary = reply.content.strip().strip('"')
    if not summary or summary.lower().strip(" .") == "nothing" or len(summary) > 600:
        return None
    try:
        when = datetime.fromisoformat(rows[0][3]).astimezone()
    except ValueError:
        when = now
    text = f"{when:%a %d %b}, {'morning' if when.hour < 12 else 'afternoon' if when.hour < 17 else 'evening'}: {summary}"
    await asyncio.to_thread(semantic_memory.remember, text, "episode")
    return text
