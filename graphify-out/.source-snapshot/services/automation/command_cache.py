"""
services/automation/command_cache.py

Remembers what the AI decided for a message, so the same message never waits
for the AI twice: an AI decision takes 1–2 seconds, a cache hit about a millisecond.

Only the decision is stored (which actions to run, or "this is chat"), never the
result, so "volume like a rock concert" still changes the volume every time.
Entries live in memory/friday.db, so they survive restarts. Each entry is tied
to the tool list (a new app or command starts fresh), not to the model that
decided, so switching models or going offline keeps it. Clearing chat memory
clears this too.

Commands FRIDAY understood by itself (apps, sites, device, media) are saved as
well, so everything the user normally says is here. A new message that means
almost the same as a saved command (similar(), local bge-small vectors, like file
search) reuses its actions — "can you launch spotify please" → "open spotify" —
but only when every name/number in those actions is in the new message, the flip
words match (open/close, up/down, on/off …), and it isn't a question.
"""

import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing

import numpy as np

from core.config import config
from core.logger import logger
from services.automation.command_words import normalize_command

MAX_ENTRIES = 1000
MAX_AGE_SECONDS = 30 * 24 * 3600
CACHE_VERSION = 2  # bump when the meaning of stored actions changes
SEMANTIC = True  # meaning-based reuse (tests turn it off, except the cache's own)
SIMILAR_ENOUGH = 0.86  # measured: paraphrases 0.86–0.95; "wifi on/off" 0.86 and "what is spotify" 0.85 need the guards
# Which way a command goes: two messages must agree ("launch" = "open", "brighter" = "up"; "close" ≠ "open")
DIRECTION = {
    **dict.fromkeys(("open", "launch", "start", "run", "show", "bring", "fire", "boot"), "open"),
    **dict.fromkeys(("close", "quit", "exit", "kill", "stop", "terminate", "hide", "shut"), "close"),
    **dict.fromkeys(("up", "increase", "raise", "higher", "brighter", "brighten", "louder", "max", "maximum"), "up"),
    **dict.fromkeys(("down", "decrease", "lower", "dimmer", "dim", "quieter", "min", "minimum"), "down"),
    **dict.fromkeys(("on", "enable", "connect", "unmute"), "on"),
    **dict.fromkeys(("off", "disable", "disconnect", "mute"), "off"),
    **dict.fromkeys(("next", "skip", "forward"), "next"), **dict.fromkeys(("previous", "back", "prev"), "previous"),
    **dict.fromkeys(("play", "resume"), "play"), "pause": "pause", "lock": "lock", "unlock": "unlock",
    **dict.fromkeys(("add", "like", "save"), "add"), **dict.fromkeys(("remove", "delete", "unlike"), "remove"),
}
QUESTION_WORDS = {"what", "why", "how", "who", "when", "where", "which", "is", "are", "does", "do", "did", "explain",
                  "tell", "should", "could", "would"}
# Actions that carry the user's exact wording: a lowercased key could replay the wrong text
NEVER_CACHED_ACTIONS = {"write_clipboard", "type_text", "write_text"}

db_path: str | None = None  # None = config.MEMORY_DB_PATH (tests point this elsewhere)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.MEMORY_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS command_cache (
               message     TEXT NOT NULL,
               fingerprint TEXT NOT NULL,
               actions     TEXT NOT NULL,
               saved_at    REAL NOT NULL,
               PRIMARY KEY (message, fingerprint)
           )"""
    )
    if "vector" not in {row[1] for row in conn.execute("PRAGMA table_info(command_cache)")}:
        conn.execute("ALTER TABLE command_cache ADD COLUMN vector BLOB")  # the message's meaning (similar())
    return conn


def _key(message: str) -> str:
    return re.sub(r"\s+", " ", normalize_command(message).lower()).strip(" .!?,")


def fingerprint(*parts) -> str:
    """Identify everything the AI's decision depends on besides the message."""
    raw = json.dumps([CACHE_VERSION, *parts], sort_keys=True, default=repr)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(message: str, fp: str) -> list[dict] | None:
    """The stored actions ([] = chat), or None if this message hasn't been decided yet."""
    try:
        with closing(_connect()) as conn:
            row = conn.execute(
                "SELECT actions, saved_at FROM command_cache WHERE message = ? AND fingerprint = ?",
                (_key(message), fp),
            ).fetchone()
    except sqlite3.Error as e:
        logger.warning(f"Command cache unavailable: {e}")
        return None
    if row is None or time.time() - row[1] > MAX_AGE_SECONDS:
        return None
    return json.loads(row[0])


def put(message: str, fp: str, actions: list[dict]) -> None:
    if any(a.get("action") in NEVER_CACHED_ACTIONS for a in actions):
        return
    try:
        json.dumps(actions)
    except (TypeError, ValueError):  # a local match carrying something that isn't data: nothing to replay
        return
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO command_cache (message, fingerprint, actions, saved_at) VALUES (?, ?, ?, ?)",
                (_key(message), fp, json.dumps(actions), time.time()),
            )
            conn.execute(
                """DELETE FROM command_cache WHERE saved_at < ? OR rowid NOT IN (
                       SELECT rowid FROM command_cache ORDER BY saved_at DESC LIMIT ?)""",
                (time.time() - MAX_AGE_SECONDS, MAX_ENTRIES),
            )
    except sqlite3.Error as e:
        logger.warning(f"Couldn't save to the command cache: {e}")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _values(actions: list[dict]) -> list[str]:
    """The names and numbers a decision acts on ("spotify", "30"), lowercased."""
    return [str(v).lower() for a in actions for k, v in a.items()
            if k not in ("type", "action") and isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip()]


def _compatible(new: str, saved: str, actions: list[dict]) -> bool:
    """Guards on top of meaning: same flip words and numbers, every acted-on name said, and not a question."""
    new_words, saved_words = _words(new), _words(saved)
    if new_words & QUESTION_WORDS and not saved_words & QUESTION_WORDS:
        return False
    if {DIRECTION[w] for w in new_words if w in DIRECTION} != {DIRECTION[w] for w in saved_words if w in DIRECTION}:
        return False
    if {w for w in new_words if w.isdigit()} != {w for w in saved_words if w.isdigit()}:
        return False
    flat = " " + " ".join(re.findall(r"[a-z0-9]+", new.lower())) + " "
    return all(f" {' '.join(re.findall(r'[a-z0-9]+', value))} " in flat for value in _values(actions))


def similar(message: str, fp: str, allow_load: bool = True) -> list[dict] | None:
    """The actions of a saved command that means the same as `message` (see the module doc), or None.
    allow_load=False: only if the embedding model is already loaded (loading takes a few seconds)."""
    from services.files import embed

    if not SEMANTIC or (not allow_load and embed._model is None):
        return None
    key = _key(message)
    try:
        with closing(_connect()) as conn:
            rows = conn.execute("SELECT rowid, message, actions, vector FROM command_cache WHERE fingerprint = ? "
                                "AND actions != '[]' AND saved_at > ?", (fp, time.time() - MAX_AGE_SECONDS)).fetchall()
            missing = [(rowid, text) for rowid, text, _, vector in rows if vector is None]
            if missing:  # saved before (or while) the model wasn't loaded: fill in now
                vectors = embed.encode([text for _, text in missing])
                with conn:
                    conn.executemany("UPDATE command_cache SET vector = ? WHERE rowid = ?",
                                     [(v.tobytes(), rowid) for v, (rowid, _) in zip(vectors, missing)])
                filled = {rowid: v.tobytes() for v, (rowid, _) in zip(vectors, missing)}
                rows = [(r, t, a, v if v is not None else filled[r]) for r, t, a, v in rows]
    except sqlite3.Error as e:
        logger.warning(f"Command cache unavailable: {e}")
        return None
    if not rows:
        return None
    query = embed.encode([key])[0]
    scored = sorted(((float(np.frombuffer(v, dtype=np.float32) @ query), text, json.loads(a)) for _, text, a, v in rows),
                    reverse=True)
    for score, text, actions in scored[:5]:
        if score < SIMILAR_ENOUGH:
            break
        if _compatible(key, text, actions):
            logger.info(f"Command cache: {message!r} means {text!r} ({score:.2f})")
            return actions
    return None


def clear() -> None:
    try:
        with closing(_connect()) as conn, conn:
            conn.execute("DELETE FROM command_cache")
    except sqlite3.Error as e:
        logger.warning(f"Couldn't clear the command cache: {e}")
