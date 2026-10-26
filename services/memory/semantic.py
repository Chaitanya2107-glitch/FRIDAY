"""
services/memory/semantic.py

Long-term memory about the user, searched by meaning.

  - "remember that my sister is Priya" saves it straight away
  - FRIDAY also learns by itself: after a chat reply, a cheap AI model pulls
    lasting facts out of what the user said ("I'm vegetarian") in the background
  - Before each reply, the memories closest in meaning to the message are added
    to the system prompt, so "what should I cook?" gets the vegetarian fact
  - "what do you remember about me" lists them, "forget that …" deletes one,
    "forget everything about me" deletes all
  - "what do you know about Ravi" lists the ones that name him (per-person facts)
  - "what did you learn this week" — and, on Sunday with the weekly summary, a review of what
    was learned by itself that week, so wrong guesses can be forgotten
  - plans with a day ("exam on Friday") keep that date (happens_on): free will asks how it went
    afterwards (services/mind/talk.py), and replies see it as past, not still coming up
  - an update replaces the old fact: a new fact close to an old one (but not a copy) goes to the
    cheap model — "does it replace it?" — and the old one is deleted if so
  - strength: hearing a fact again (or being told it) makes it stronger; learned facts nobody
    uses fade a little each night (fade) and are dropped once they're weak
  - conversations: services/memory/episodes.py saves a short summary of each chat (source
    "episode"); "what did we talk about yesterday" lists them

Memories live in the memories table of MEMORY_DB_PATH, with a vector from the
same local embedding model file search uses (services/files/embed.py) — the
vectors are made on this PC, only the recalled facts go to the AI provider.
"""

import asyncio
import json
import re
import sqlite3
import threading
from services.mind.reasoning_store import reasoning_store
from contextlib import closing
from datetime import date, datetime, timedelta

import numpy as np

from core.config import config
from core.logger import logger
from providers.base_provider import Message
from services.files import embed as default_embedder

# Measured with bge-small: rewordings of one fact score ~0.97, while an updated
# fact ("sister is Anya" vs "Priya") scores ~0.84 — the same as two different
# facts ("likes tea" vs "likes coffee"). So near-copies are merged, and anything
# in between goes to the cheap model to decide whether the new one replaces it.
DUPLICATE_SCORE = 0.93
UPDATE_MIN_SCORE = 0.75
RECALL_MIN_SCORE = 0.5
RECALL_LIMIT = 8
FORGET_MIN_SCORE = 0.6

# Strength: told facts start stronger; unused learned facts fade nightly and are dropped when weak
TOLD_STRENGTH, LEARNED_STRENGTH, MAX_STRENGTH = 2.0, 1.0, 5.0
HEARD_AGAIN, RECALLED = 1.0, 0.05
FADE_AFTER_DAYS, FADE, DROP_BELOW = 14, 0.97, 0.35
FOLLOW_UP_DAYS, COMING_UP_DAYS = 3, 2  # a plan is followed up for this many days after; "coming up" this many before

# Cheap pre-filter: a message with none of these words says nothing about the user
_ABOUT_USER = re.compile(r"\b(i|i'm|im|i've|ive|i'd|my|me|mine|we|our|us)\b", re.IGNORECASE)
_DAY_TAG = re.compile(r"\s*\[?(\d{4}-\d{2}-\d{2})\]?\s*\.?$")  # small models sometimes drop the brackets

LEARN_PROMPT = """You extract lasting facts about the user from their message, for a personal assistant's long-term memory.

Keep: who they are, people in their life, preferences, habits and routines, work, projects, goals, health, places, possessions,
and plans or events on a particular day (an exam, a trip, a deadline, an interview).
Skip: questions, requests and commands, small talk, one-off moods or plans for right now, anything not about the user.
If it's the user's answer to a question Friday asked, read the answer together with the question
("What's your favourite food?" + "pizza" → "User's favourite food is pizza").
For something on a particular day, say the day in the fact and end it with the date in brackets, worked out from
today's date: "User has a DBMS exam on Friday 3 Oct [2026-10-03]".

Return ONLY a JSON array of short third-person statements, e.g. ["User's sister is named Priya", "User is vegetarian"].
Return [] if there is nothing worth remembering. Most messages have nothing."""

REPLACES_PROMPT = """A personal assistant's memory has these facts about the user:
{old}

A new fact was just learned: "{new}"

Does the new fact make any old fact WRONG — the very same detail, now changed or corrected? Only then it replaces it.
  replaces: "User lives in Pune" → "User moved to Bangalore"; "User's sister is named Priya" → "User's sister is named Anya";
            "User's DBMS exam is on Friday" → "User's DBMS exam moved to Monday"
  does NOT replace (both can be true): "User likes tea" / "User likes coffee"; "User has a DBMS exam on Friday" /
            "User is nervous about the DBMS exam"; "User works on a project called Friday" / "User has an exam on Friday"
When in doubt, it does NOT replace. Return ONLY a JSON array of the numbers of the old facts it makes wrong, e.g. [2], or []."""

# "remember that X", "please remember X", "note that X", "don't forget that X"
_REMEMBER = re.compile(r"^(?:remember|memori[sz]e|note|don'?t forget|do not forget|keep in mind)(?: that)?[\s,:]+(.+)$", re.IGNORECASE)
_FORGET = re.compile(r"^forget(?: about)?(?: that)?\s+(.+)$", re.IGNORECASE)
_ABOUT = re.compile(r"^what do you (?:know|remember) about (?P<who>(?!me$|you$|yourself$)[a-z][\w' .-]*)$", re.IGNORECASE)
_LEARNED = re.compile(r"^what (?:did|have) you (?:learn|learnt|learned)(?: about me)? this week$", re.IGNORECASE)
_TALKED = re.compile(r"^what (?:did|have) (?:we|i) (?:talk(?:ed)?|chat(?:ted)?) about(?: (?P<when>yesterday|today|this week|last time|lately|recently))?$",
                     re.IGNORECASE)
REVIEW_DAYS = 7
_FORGET_ALL = re.compile(r"^forget (?:everything|all)(?: you know| you remember)?(?: about me)?$", re.IGNORECASE)
_LIST = re.compile(
    r"^(?:what do you (?:know|remember) about me|what have you (?:learned|learnt) about me|"
    r"(?:list|show)(?: me)? (?:your |my )?memories|what do you remember)$",
    re.IGNORECASE,
)


def match_memory_command(text: str) -> dict | None:
    """Memory commands. `text` has already been through normalize_command()."""
    text = text.strip()
    if _LIST.match(text):
        return {"type": "system", "action": "list_memories"}
    if _FORGET_ALL.match(text):
        return {"type": "system", "action": "forget_all_memories"}
    if _LEARNED.match(text):
        return {"type": "system", "action": "learned_this_week"}
    if talked := _TALKED.match(text):
        return {"type": "system", "action": "talked_about", "when": (talked["when"] or "last time").lower()}
    about = _ABOUT.match(text)
    if about:
        return {"type": "system", "action": "memories_about", "who": about["who"].strip()}
    # "forget clipboard history" / "forget reminder 2" belong to those features
    forget = _FORGET.match(text)
    if forget and not re.search(r"\b(clipboard|reminders?)\b", text, re.IGNORECASE):
        return {"type": "system", "action": "forget_memory", "text": forget.group(1)}
    remember = _REMEMBER.match(text)
    if remember:
        return {"type": "system", "action": "remember", "text": remember.group(1)}
    return None


MEMORY_ACTIONS = {"remember", "forget_memory", "forget_all_memories", "list_memories", "memories_about",
                  "learned_this_week", "talked_about"}


def run_memory_command(parsed: dict) -> str:
    """The reply to a command from match_memory_command (blocking: it embeds text)."""
    action = parsed["action"]
    if action in {"forget_memory", "forget_all_memories"}:
        from services.mind.executive import executive, clear_derived
        with executive._db() as conn:
            clear_derived(conn)
    if action == "remember":
        text = parsed["text"]
        if semantic_memory.remember(text):
            return f"Got it, I'll remember that {text.rstrip('.')}."
        return "I already remember that."
    if action == "forget_memory":
        from services.memory import schedule
        from services.mind.training import reviews
        lessons = reviews.forget_facts(parsed["text"])
        if lessons:
            return "Withdrew reviewed memories: " + "; ".join(lessons)
        forgotten = reasoning_store.forget(parsed["text"])
        operational = schedule.forget(parsed["text"])
        forgotten = forgotten or operational or semantic_memory.forget(parsed["text"])
        return f"Forgot: {forgotten}." if forgotten else "I don't remember anything like that."
    if action == "memories_about":
        who = parsed["who"]
        from services.mind import training
        texts = [t for t, _ in semantic_memory.all()] + [f"{t} (reviewed lesson #{i})" for i, t in training.facts()]
        found = [t for t in texts if re.search(rf"\b{re.escape(who)}\b", t, re.IGNORECASE)]
        if not found:
            return f"I don't know anything about {who} yet. Say \"remember that {who} …\"."
        return f"What I know about {who}:\n" + "\n".join(f"- {t}" for t in found)
    if action == "learned_this_week":
        return weekly_review() or "I didn't learn anything new about you this week."
    if action == "talked_about":
        return talked_about(parsed["when"])
    if action == "forget_all_memories":
        from services.mind.training import reviews
        count = semantic_memory.forget_all() + len(reviews.forget_facts())
        return f"Done, I forgot all {count} things I remembered about you." if count else "I don't remember anything about you yet."
    from services.mind import training
    memories = semantic_memory.all() + [(f"{t} (reviewed lesson #{i})", "reviewed") for i, t in training.facts()]
    if not memories:
        return "I don't remember anything about you yet. Tell me things, or say \"remember that …\"."
    return f"Here's what I remember about you ({len(memories)}):\n" + "\n".join(f"- {text}" for text, _ in memories)


def talked_about(when: str, today: date | None = None) -> str:
    today = today or date.today()
    start = {"today": today, "yesterday": today - timedelta(days=1)}.get(when, today - timedelta(days=7))
    end = today if when == "yesterday" else today + timedelta(days=1)
    found = semantic_memory.episodes(start.isoformat(), end.isoformat())
    if when in ("last time", "lately", "recently"):
        found = found[-3:]
    if not found:
        return {"today": "We haven't really talked today.", "yesterday": "We didn't really talk yesterday."}.get(
            when, "I don't have any of our recent conversations noted yet.")
    return "What we talked about:\n" + "\n".join(f"- {text}" for text in found)


def weekly_review(now: datetime | None = None) -> str | None:
    """What FRIDAY learned by itself in the last REVIEW_DAYS (it can guess wrong); None if nothing."""
    since = ((now or datetime.now()) - timedelta(days=REVIEW_DAYS)).isoformat()
    learned = semantic_memory.learned_since(since)
    if not learned:
        return None
    return (f"This week I picked up {len(learned)} thing{'s' if len(learned) != 1 else ''} about you: "
            + "; ".join(learned) + ". Say \"forget that …\" for anything wrong.")


def split_day(fact: str) -> tuple[str, str | None]:
    """ "User has an exam on Friday 3 Oct [2026-10-03]" → ("User has an exam on Friday 3 Oct", "2026-10-03")."""
    tag = _DAY_TAG.search(fact)
    if not tag:
        return fact.strip(), None
    try:
        day = date.fromisoformat(tag[1]).isoformat()
    except ValueError:
        day = None
    return fact[:tag.start()].strip(), day


class SemanticMemory:
    COLUMNS = "id, text, created_at, source, strength, happens_on, followed_up, last_used"

    def __init__(self, db_path: str | None = None, embedder=default_embedder):
        self.db_path = db_path or config.MEMORY_DB_PATH
        self.embedder = embedder
        self._lock = threading.Lock()
        self._cache = None  # (rows, vectors) — reloaded after every change
        self._ready_for = None
        self._background: set[asyncio.Task] = set()

    # ── Storage ───────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        if self._ready_for != self.db_path:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    text       TEXT NOT NULL,
                    vector     BLOB NOT NULL,
                    source     TEXT NOT NULL,  -- 'told' (remember that…), 'learned', or 'episode' (a conversation)
                    created_at TEXT NOT NULL
                )
            """)
            have = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
            for column, kind in (("strength", "REAL NOT NULL DEFAULT 1.0"), ("happens_on", "TEXT"),
                                 ("followed_up", "INTEGER NOT NULL DEFAULT 0"), ("last_used", "TEXT")):
                if column not in have:
                    conn.execute(f"ALTER TABLE memories ADD COLUMN {column} {kind}")
            conn.commit()
            self._ready_for = self.db_path
            self._cache = None
        return conn

    def _load(self):
        # ponytail: every vector in RAM, linear scan — fine to ~100k memories; add an ANN index past that
        if self._cache is None:
            with closing(self._connect()) as conn:
                rows = conn.execute(f"SELECT {self.COLUMNS}, vector FROM memories ORDER BY id").fetchall()
            vectors = np.stack([np.frombuffer(r[-1], dtype=np.float32) for r in rows]) if rows else np.zeros((0, 0), np.float32)
            self._cache = ([r[:-1] for r in rows], vectors)
        return self._cache

    def _change(self, sql: str, params=()) -> int:
        """One write; the cache is reloaded next time. Call with the lock held."""
        with closing(self._connect()) as conn, conn:
            count = conn.execute(sql, params).rowcount
        self._cache = None
        return count

    # ── Public API (blocking — call from a thread in async code) ──────────────

    def remember(self, text: str, source: str = "told", replaces: list[int] = ()) -> bool:
        """Save a memory (deleting the ids it `replaces`). False if a near-identical one is already
        saved — that one gets stronger instead ("heard again")."""
        text, happens_on = split_day(text.strip())
        text = text.rstrip(".")
        if not text:
            return False
        vector = self.embedder.encode([text])[0]
        with self._lock:
            rows, vectors = self._load()
            if source != "episode" and rows:
                scores = vectors @ vector
                best = int(scores.argmax())
                if scores[best] >= DUPLICATE_SCORE:
                    self._change("UPDATE memories SET strength = MIN(?, strength + ?) WHERE id = ?",
                                 (MAX_STRENGTH, HEARD_AGAIN, rows[best][0]))
                    return False
            for old in replaces:
                self._change("DELETE FROM memories WHERE id = ?", (old,))
            self._change(
                "INSERT INTO memories (text, vector, source, created_at, strength, happens_on) VALUES (?, ?, ?, ?, ?, ?)",
                (text, vector.astype(np.float32).tobytes(), source, datetime.now().isoformat(timespec="seconds"),
                 TOLD_STRENGTH if source == "told" else LEARNED_STRENGTH, happens_on),
            )
        logger.info(f"Remembered ({source}): {text}" + (f" — replacing {len(replaces)}" if replaces else ""))
        return True

    def similar(self, text: str) -> list[tuple[int, str]]:
        """Facts close to `text` but not copies of it — ones it might update. (id, text), closest first."""
        text = split_day(text)[0]
        with self._lock:
            rows, vectors = self._load()
        if not rows:
            return []
        scores = vectors @ self.embedder.encode([text])[0]
        order = np.argsort(scores)[::-1]
        return [(rows[i][0], rows[i][1]) for i in order
                if UPDATE_MIN_SCORE <= scores[i] < DUPLICATE_SCORE and rows[i][3] != "episode"][:5]

    def recall(self, query: str, limit: int = RECALL_LIMIT) -> list[tuple[str, str]]:
        """The memories closest in meaning to `query`, as (text, date) — best first."""
        return [(text, noted) for text, noted, _, _ in self._recall(query, limit)]

    def _recall(self, query: str, limit: int) -> list[tuple[str, str, str, str | None]]:
        """(text, date noted, source, happens_on) — and the recalled ones count as used."""
        with self._lock:
            rows, vectors = self._load()
            if not rows:
                return []
            scores = vectors @ self.embedder.encode_query(query)
            best = [i for i in np.argsort(scores)[::-1][:limit] if scores[i] >= RECALL_MIN_SCORE]
            if best:
                ids = [rows[i][0] for i in best]
                self._change(f"UPDATE memories SET last_used = ?, strength = MIN(?, strength + ?) "
                             f"WHERE id IN ({','.join('?' * len(ids))})",
                             (datetime.now().isoformat(timespec="seconds"), MAX_STRENGTH, RECALLED, *ids))
        return [(rows[i][1], rows[i][2][:10], rows[i][3], rows[i][5]) for i in best]

    def forget(self, description: str) -> str | None:
        """Delete the memory that best matches `description`; return its text, or None."""
        with self._lock:
            rows, vectors = self._load()
            if not rows:
                return None
            scores = vectors @ self.embedder.encode_query(description)
            best = int(scores.argmax())
            if scores[best] < FORGET_MIN_SCORE:
                return None
            self._change("DELETE FROM memories WHERE id = ?", (rows[best][0],))
        if self is semantic_memory:
            from services.mind.executive import executive, clear_derived
            with executive._db() as conn:
                clear_derived(conn)
        logger.info(f"Forgot: {rows[best][1]}")
        return rows[best][1]

    def forget_all(self) -> int:
        from services.memory import schedule
        with self._lock:
            return self._change("DELETE FROM memories") + schedule.forget_all(self.db_path) + (reasoning_store.forget_all() if self is semantic_memory else 0)

    def learned_since(self, since: str) -> list[str]:
        """Memories FRIDAY learned by itself (not told) since an ISO time, oldest first."""
        with self._lock, closing(self._connect()) as conn:
            rows = conn.execute("SELECT text FROM memories WHERE source = 'learned' AND created_at >= ? ORDER BY created_at",
                                (since,)).fetchall()
        return [text for (text,) in rows]

    def all(self) -> list[tuple[str, str]]:
        """Facts (not conversations), as (text, date noted)."""
        with self._lock:
            rows, _ = self._load()
        from services.memory import schedule
        return [(r[1], r[2][:10]) for r in rows if r[3] != "episode"] + schedule.remembered(self.db_path) + (reasoning_store.remembered() if self is semantic_memory else [])

    def episodes(self, start: str, end: str) -> list[str]:
        """Conversation summaries noted from `start` up to (not including) `end` (ISO dates), oldest first."""
        with self._lock:
            rows, _ = self._load()
        return [r[1] for r in rows if r[3] == "episode" and start <= r[2][:10] < end]

    def highlights(self, limit: int = 8) -> list[str]:
        """The facts she's surest of — strongest, then newest (for free will to build on)."""
        with self._lock:
            rows, _ = self._load()
        facts = sorted((r for r in rows if r[3] != "episode"), key=lambda r: (r[4], r[2]), reverse=True)
        return [r[1] for r in facts[:limit]]

    def plans(self, today: date | None = None) -> tuple[list[str], list[str]]:
        """(just happened and not followed up yet, coming up soon) — plans with a day."""
        today = today or date.today()
        with self._lock:
            rows, _ = self._load()
        past, soon = [], []
        for r in rows:
            if not r[5]:
                continue
            days = (date.fromisoformat(r[5]) - today).days
            if -FOLLOW_UP_DAYS <= days < 0 and not r[6]:
                past.append(r[1])
            elif 0 <= days <= COMING_UP_DAYS:
                soon.append(r[1])
        return past, soon

    def mark_followed_up(self, text: str) -> None:
        with self._lock:
            self._change("UPDATE memories SET followed_up = 1 WHERE text = ?", (text.strip().rstrip("."),))

    def fade(self, now: datetime | None = None) -> int:
        """Nightly: learned facts unused for FADE_AFTER_DAYS weaken; weak ones are dropped. Returns how many."""
        cutoff = ((now or datetime.now()) - timedelta(days=FADE_AFTER_DAYS)).isoformat(timespec="seconds")
        with self._lock:
            self._change("UPDATE memories SET strength = strength * ? WHERE source = 'learned' "
                         "AND COALESCE(last_used, created_at) < ?", (FADE, cutoff))
            dropped = self._change("DELETE FROM memories WHERE source = 'learned' AND strength < ?", (DROP_BELOW,))
        if dropped:
            logger.info(f"Memory: {dropped} unused guess{'es' if dropped != 1 else ''} faded out")
        return dropped

    # ── Chat integration ──────────────────────────────────────────────────────

    async def prompt_section(self, message: str) -> str:
        """Memories relevant to `message`, ready to append to the system prompt ('' if none)."""
        try:
            memories = await asyncio.to_thread(self._recall, message, RECALL_LIMIT)
        except Exception as e:
            logger.warning(f"Memory recall failed: {e}")
            return ""
        if not memories:
            return ""
        today = date.today().isoformat()
        lines = []
        for text, noted, source, happens_on in memories:
            from services.memory import schedule
            if timed := schedule.parse(text, datetime.fromisoformat(noted)):
                text += f" (fixed dates {timed.start} through {timed.end}; not relative to today)"
            if source == "episode":
                lines.append(f"- Earlier conversation: {text}")
            elif happens_on:
                lines.append(f"- {text} ({'already happened' if happens_on < today else 'coming up'}: {happens_on})")
            else:
                lines.append(f"- {text} ({'owner-told' if source == 'told' else 'learned inference'}, noted {noted})")
        return (
            "\n\nThings you remember about the user from earlier conversations. Use them when they "
            "help; don't list them back unprompted. Prefer explicitly owner-told facts and fixed date bounds "
            "over learned inferences; a newer explicit correction takes precedence.\n" + "\n".join(lines)
        )

    def learn_in_background(self, message: str, provider_name: str, question: str | None = None) -> None:
        """Pull lasting facts out of the user's message without delaying the reply.
        question: what FRIDAY asked, when this answers it ("pizza" only means something with the question)."""
        if config.AI_ASSIST_ONLY or not config.SEMANTIC_MEMORY_LEARN:
            return
        if question:
            message = f'Friday asked the user: "{question}"\nThe user answered: "{message}"'
        elif not _ABOUT_USER.search(message):
            return
        task = asyncio.create_task(self._learn(message, provider_name))
        self._background.add(task)  # keep a reference so the task isn't garbage-collected
        task.add_done_callback(self._background.discard)

    async def _learn(self, message: str, provider_name: str) -> None:
        from providers.failover import complete_with_failover  # avoid an import cycle at startup
        try:
            result = await complete_with_failover(
                config.INTENT_PROVIDER or provider_name,
                [Message(role="user", content=f"Today is {datetime.now():%A %Y-%m-%d}.\n\n{message}")],
                LEARN_PROMPT,
                1000,  # reasoning models spend tokens thinking before the short JSON answer
                model_for=_cheap_model,
            )
            batch = _parse_facts(result.content)
            for fact in batch:
                await self.add_learned(fact, provider_name, keep=batch)
        except Exception as e:
            logger.warning(f"Could not learn from message: {e}")

    async def add_learned(self, fact: str, provider_name: str | None = None, keep: list[str] = ()) -> bool:
        """Save a fact FRIDAY worked out herself — replacing any old fact it updates.
        keep: facts learned from the same message — they never replace each other."""
        same_message = {split_day(f)[0].rstrip(".") for f in keep}
        close = [(i, t) for i, t in await asyncio.to_thread(self.similar, fact) if t not in same_message]
        replaces = await _replaced(close, fact, provider_name or config.ACTIVE_PROVIDER) if close else []
        return await asyncio.to_thread(self.remember, fact, "learned", replaces)


async def _replaced(close: list[tuple[int, str]], fact: str, provider_name: str) -> list[int]:
    """Which of the close old facts the new one replaces (the cheap model decides); [] if unsure."""
    if config.AI_ASSIST_ONLY:
        return []
    from providers.failover import complete_with_failover
    old = "\n".join(f"{n}. {text}" for n, (_, text) in enumerate(close, 1))
    try:
        result = await complete_with_failover(config.INTENT_PROVIDER or provider_name,
                                              [Message(role="user", content=REPLACES_PROMPT.format(old=old, new=fact))],
                                              "", 600, model_for=_cheap_model)
        numbers = json.loads(re.search(r"\[.*?\]", result.content, re.DOTALL).group())
    except Exception as e:
        logger.info(f"Couldn't check whether '{fact}' updates an old fact: {e}")
        return []
    if result.provider == "ollama":
        # ponytail: the small local model judged 5 of 7 test pairs right and wrongly deleted a true fact — with it,
        # keep both (replies trust the newer one). Let it decide if a bigger local model ever proves reliable.
        return []
    return [close[n - 1][0] for n in numbers if isinstance(n, int) and 1 <= n <= len(close)]


def _cheap_model(provider: str) -> str | None:
    """The command classifier's cheap model — learning is a small task too."""
    if config.INTENT_PROVIDER and provider == config.INTENT_PROVIDER:
        return config.INTENT_MODEL or None
    return config.INTENT_DEFAULT_MODELS.get(provider)


def _parse_facts(reply: str) -> list[str]:
    """The JSON array from the model's reply, tolerating code fences and chatter around it."""
    match = re.search(r"\[.*\]", reply, re.DOTALL)
    if not match:
        return []
    try:
        facts = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()][:5]


semantic_memory = SemanticMemory()
