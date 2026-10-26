"""
services/mind/knowledge.py

What FRIDAY knows about the things in the Boss's life — her own knowledge, built by watching, with no AI:
every app and every topic (a cleaned window title: a page, a video, a document, a Claude session) she has
seen, with its category, when it was first and last seen, how often, for how long, on how many days, and
at which hours. services/mind/brain.py feeds it on every move and thinks from it.

What she can't place she's curious about:
  1. her own rules first (services/activity/categories.py)
  2. then she looks it up: ONE bare question to the AI model — "What is <name>?" — with the name (and, for
     a program, its window title) and nothing about the Boss. The answer (what it is + a category) is
     stored here, so she never asks twice, and from then on the activity log sorts it into that category.
  3. model unavailable (the small local fallback model isn't trusted with facts), or it doesn't know:
     she asks the Boss (brain.py makes that a thought), and the
     answer is stored the same way (teach).
Everything else here works with no model at all.

State: memory/mind/brain.db (things; services/mind/thoughts.py and foresight.py keep theirs in the same file).
"""

import json
import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
from core.logger import logger
from providers.base_provider import Message
from services.activity import categories
from services.activity.categories import clean_title

db_path = str(config.MEMORY_DIR / "mind" / "brain.db")  # tests point this elsewhere
LOOKUP_MIN_SECONDS = 600     # curious enough to look something up once the Boss has spent this long on it
APP_LOOKUP_MIN_SECONDS = 60  # …a program she can't place: after a minute
MAX_LOOKUPS_A_DAY = 20
UNPLACED = {"app": "other", "topic": "browsing"}  # a program no rule knows; a page no rule knows
PRUNE_AFTER_DAYS = 14        # a topic glanced at once and never explained is forgotten after this
MAX_NAME = 90
# Window titles that say nothing about what the Boss is doing
NOISE = {"new tab", "untitled", "history", "downloads", "settings", "program manager", "task switching",
         "system tray overflow window.", "extensions", "command prompt", "windows powershell", "search",
         "open", "save as", "file explorer", "home"}
NO_TOPIC_APPS = {"explorer", "applicationframehost", "shellhost"}
# The Boss's own words about a thing → its category ("it's a game I play with friends")
CATEGORY_WORDS = [
    ("gaming", r"\bgam(?:e|es|ing)\b|\bplay(?:ing)?\b"),
    ("study", r"\bstud(?:y|ies|ying)\b|college|course|class|assignment|lecture|exam|syllabus"),
    ("coding", r"\bcod(?:e|ing)\b|programming|developer|\bide\b|terminal|repo|compiler|debug"),
    ("ai", r"\bai\b|chatbot|\bllm\b|language model"),
    ("communication", r"\bchat(?:ting)?\b|messag|\bcalls?\b|email|meeting"),
    ("music", r"\bmusic\b|\bsongs?\b|playlist"),
    ("entertainment", r"\bvideos?\b|movie|series|anime|stream|\bwatch"),
    ("social", r"social media|\bfeed\b"),
    ("documents", r"\bnotes?\b|document|\bpdf\b|spreadsheet|slides"),
    ("media", r"photo|image edit|video edit|drawing|\bdesign\b"),
    ("system", r"\bdriver\b|utility|system tool|\bsettings\b|vendor|keyboard lighting|rgb"),
    ("shopping", r"\bshop|\bbuy\b"),
]
KNOWN_CATEGORIES = sorted({*categories.APPS, *categories.SITES, "other"})

LOOKUP_PROMPT = (
    "You identify software, games, websites and topics from their name. Reply with ONLY a JSON object:\n"
    '{"known": true or false, "what": "<one short sentence: what it is>", "category": "<one of: '
    + ", ".join(KNOWN_CATEGORIES) + '>"}\n'
    "If you don't recognise the name for sure, set known to false — never guess. No commentary outside the JSON."
)

_lock = threading.Lock()
_ready_for = None


@dataclass
class Thing:
    key: str
    kind: str                # app | topic
    name: str
    category: str
    about: str | None        # what it is, once she knows
    source: str              # rule (her own rules) | lookup (asked the model) | boss (the Boss told her)
    first_seen: datetime
    last_seen: datetime
    times: int               # how many separate times it came to the front
    seconds: float
    days: int                # distinct days seen
    hours: list[int]         # per hour of the day: on how many days it was seen then
    last_day: str
    looked_up: str | None    # when she looked it up (answered or not)
    hint: str | None         # a program's latest window title

    @property
    def placed(self) -> bool:
        return bool(self.about) or self.category != UNPLACED[self.kind]


# ── The store ─────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    global _ready_for
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if _ready_for != db_path:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS things (
                key TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
                about TEXT, source TEXT NOT NULL DEFAULT 'rule', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                times INTEGER NOT NULL DEFAULT 0, seconds REAL NOT NULL DEFAULT 0, days INTEGER NOT NULL DEFAULT 0,
                hours TEXT NOT NULL, last_day TEXT NOT NULL, last_slot TEXT NOT NULL, looked_up TEXT, hint TEXT
            );
            CREATE TABLE IF NOT EXISTS thoughts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL,
                data TEXT NOT NULL, strength REAL NOT NULL, state TEXT NOT NULL DEFAULT 'new', answer TEXT
            );
            CREATE TABLE IF NOT EXISTS reasons (pattern TEXT PRIMARY KEY, reason TEXT NOT NULL, at TEXT NOT NULL);
            -- services/mind/foresight.py: both predictors' score per day, the Boss's verdict per pattern, his answers
            CREATE TABLE IF NOT EXISTS foresight_tally (
                day TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0, own_hit INTEGER NOT NULL DEFAULT 0,
                model_n INTEGER NOT NULL DEFAULT 0, model_hit INTEGER NOT NULL DEFAULT 0,
                agreed INTEGER NOT NULL DEFAULT 0, agreed_hit INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS foresight_patterns (
                pattern TEXT PRIMARY KEY, frm TEXT NOT NULL, nxt TEXT NOT NULL, yes INTEGER NOT NULL DEFAULT 0,
                no INTEGER NOT NULL DEFAULT 0, auto INTEGER NOT NULL DEFAULT 0, last_run TEXT
            );
            CREATE TABLE IF NOT EXISTS foresight_labels (at TEXT NOT NULL, frm TEXT NOT NULL, before TEXT, nxt TEXT NOT NULL,
                                                         right INTEGER NOT NULL);
        """)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(foresight_labels)")}
        if "recorded_at" not in columns:
            conn.execute("ALTER TABLE foresight_labels ADD COLUMN recorded_at TEXT")
            conn.commit()
        _ready_for = db_path
    return conn


@contextmanager
def db():
    """One locked, committed visit to her brain's file."""
    with _lock, closing(_connect()) as conn, conn:
        yield conn


def _thing(row) -> Thing | None:
    if row is None:
        return None
    fields = {k: row[k] for k in row.keys() if k != "last_slot"}
    fields.update(first_seen=datetime.fromisoformat(row["first_seen"]), last_seen=datetime.fromisoformat(row["last_seen"]),
                  hours=json.loads(row["hours"]))
    from services.mind.training import teaching_for
    if reviewed := teaching_for("subject", row["key"]):
        fields.update(about=reviewed, source="boss")
    return Thing(**fields)


def key_for(kind: str, name: str) -> str:
    return f"{kind}:{name.lower()}"


def topic_of(app: str | None, title: str | None) -> str | None:
    """What a window is about ("Compare Colibri AirLLM"), or None when its title says nothing."""
    topic = clean_title(title)[:MAX_NAME]
    if not app or app in NO_TOPIC_APPS or len(topic) < 4 or topic.lower() in NOISE or topic.lower() == app:
        return None
    return topic


def get(key: str) -> Thing | None:
    with db() as conn:
        return _thing(conn.execute("SELECT * FROM things WHERE key = ?", (key,)).fetchone())


def find(name: str) -> Thing | None:
    """The thing the Boss means by `name`: a program, what a program's window is called, or a topic."""
    name = name.strip().lower()
    with db() as conn:
        row = conn.execute("SELECT * FROM things WHERE key IN (?, ?) OR (kind = 'app' AND LOWER(hint) = ?) "
                           "ORDER BY seconds DESC", (f"app:{name}", f"topic:{name}", name)).fetchone()
    return _thing(row)


def see(conn, kind: str, name: str, category: str, now: datetime, hint: str | None = None) -> Thing | None:
    """`name` just came to the front. Returns what she knew about it BEFORE this moment (None = never seen)."""
    key, day, slot = key_for(kind, name), now.date().isoformat(), f"{now:%Y-%m-%d %H}"
    row = conn.execute("SELECT * FROM things WHERE key = ?", (key,)).fetchone()
    stamp = now.isoformat(timespec="seconds")
    if row is None:
        hours = [0] * 24
        hours[now.hour] = 1
        conn.execute("INSERT INTO things (key, kind, name, category, first_seen, last_seen, times, days, hours, "
                     "last_day, last_slot, hint) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)",
                     (key, kind, name, category, stamp, stamp, json.dumps(hours), day, slot, hint))
        return None
    hours = json.loads(row["hours"])
    if row["last_slot"] != slot:
        hours[now.hour] += 1
    # her own rules can change (categories.py edited); what she looked up or was told stays
    category = category if row["source"] == "rule" else row["category"]
    conn.execute("UPDATE things SET last_seen = ?, times = times + 1, days = days + ?, hours = ?, last_day = ?, "
                 "last_slot = ?, category = ?, hint = COALESCE(?, hint) WHERE key = ?",
                 (stamp, int(row["last_day"] != day), json.dumps(hours), day, slot, category, hint, key))
    return _thing(row)


def spend(conn, kind: str, name: str, seconds: float) -> None:
    conn.execute("UPDATE things SET seconds = seconds + ? WHERE key = ?", (seconds, key_for(kind, name)))


def is_empty() -> bool:
    with db() as conn:
        return conn.execute("SELECT 1 FROM things LIMIT 1").fetchone() is None


def days_watched() -> int:
    """How many days she has been watching (the most days any one thing was seen on)."""
    with db() as conn:
        return conn.execute("SELECT COALESCE(MAX(days), 0) FROM things").fetchone()[0]


def regulars(min_days: int) -> list[Thing]:
    """Apps seen on at least `min_days` days — the Boss's regulars."""
    with db() as conn:
        return [_thing(r) for r in conn.execute("SELECT * FROM things WHERE kind = 'app' AND days >= ?", (min_days,))]


def refresh_learned() -> None:
    """Hand what she looked up or was told to the activity log's sorter (categories.LEARNED)."""
    learned = {"app": {}, "title": {}}
    try:
        with db() as conn:
            for row in conn.execute("SELECT kind, name, category FROM things WHERE source != 'rule' "
                                    "AND category NOT IN ('other', 'browsing')"):
                learned["app" if row["kind"] == "app" else "title"][row["name"].lower()] = row["category"]
    except sqlite3.Error as e:
        logger.warning(f"Couldn't read what FRIDAY has learned: {e}")
    categories.LEARNED.update(learned)


def prune(now: datetime) -> int:
    """Nightly: forget topics glanced at once and never explained."""
    with db() as conn:
        return conn.execute("DELETE FROM things WHERE kind = 'topic' AND seconds < 60 AND about IS NULL AND last_seen < ?",
                            ((now - timedelta(days=PRUNE_AFTER_DAYS)).isoformat(),)).rowcount


# ── Curiosity ─────────────────────────────────────────────────────────────────

def due_lookup(now: datetime) -> Thing | None:
    """The thing she's most curious about: used for a while, not placed, never looked up. None once today's
    lookups are used up."""
    with db() as conn:
        today = conn.execute("SELECT COUNT(*) FROM things WHERE looked_up >= ?", (now.date().isoformat(),)).fetchone()[0]
        if today >= MAX_LOOKUPS_A_DAY:
            return None
        return _thing(conn.execute(
            "SELECT * FROM things WHERE about IS NULL AND looked_up IS NULL AND ((kind = 'app' AND category = ? "
            "AND seconds >= ?) OR (kind = 'topic' AND category = ? AND seconds >= ?)) ORDER BY seconds DESC LIMIT 1",
            (UNPLACED["app"], APP_LOOKUP_MIN_SECONDS, UNPLACED["topic"], LOOKUP_MIN_SECONDS)).fetchone())


def _question(thing: Thing) -> str:
    if thing.kind == "app":
        window = f', and its window is titled "{thing.hint}"' if thing.hint else ""
        return f'What is "{thing.name}"? It is the name of a Windows program{window}.'
    return f'What is "{thing.name}"? It is the title of a web page or window.'


def _parse(reply: str) -> dict | None:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        data = json.loads(match.group()) if match else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def look_up(thing: Thing, now: datetime) -> Thing | None:
    """Ask the model what `thing` is. Returns the thing as she now knows it; None when no model answered
    (she'll try again later). A thing the model doesn't know comes back with no `about`."""
    from providers.failover import complete_with_failover

    if config.AI_ASSIST_ONLY and not config.AI_KNOWLEDGE_ENABLED:
        return None

    try:
        reply = await complete_with_failover(config.ACTIVE_PROVIDER, [Message(role="user", content=_question(thing))],
                                             LOOKUP_PROMPT, 600, purpose="knowledge", attempt_timeout=8)
    except Exception as e:
        logger.info(f"Lookup of {thing.name} skipped: {e}")
        return None
    if not config.AI_ASSIST_ONLY and reply.provider == "ollama" != config.ACTIVE_PROVIDER:
        return None  # only the small local model answered (offline / providers down): it would make things up
    data = _parse(reply.content) or {}
    known = data.get("known") is True and isinstance(data.get("what"), str) and data["what"].strip()
    category = str(data.get("category") or "").strip().lower()
    with db() as conn:
        if known:
            conn.execute("UPDATE things SET about = ?, source = 'lookup', looked_up = ?, category = ? WHERE key = ?",
                         (str(data["what"]).strip()[:300], now.isoformat(timespec="seconds"),
                          category if category in KNOWN_CATEGORIES and category != "other" else thing.category, thing.key))
        else:
            conn.execute("UPDATE things SET looked_up = ? WHERE key = ?", (now.isoformat(timespec="seconds"), thing.key))
    refresh_learned()
    logger.info(f"Looked up {thing.name}: {'learned' if known else 'unknown'}")
    return get(thing.key)


def teach(key: str, text: str) -> Thing | None:
    """The Boss said what it is: kept in their words, and sorted by the words they used."""
    category = next((c for c, words in CATEGORY_WORDS if re.search(words, text, re.I)), None)
    with db() as conn:
        conn.execute("UPDATE things SET about = ?, source = 'boss', category = COALESCE(?, category) WHERE key = ?",
                     (text.strip()[:300], category, key))
    refresh_learned()
    return get(key)


def learned_on(day: str) -> list[Thing]:
    """What she looked up and understood that day."""
    with db() as conn:
        return [_thing(r) for r in conn.execute(
            "SELECT * FROM things WHERE about IS NOT NULL AND source = 'lookup' AND looked_up LIKE ?", (day + "%",))]


def describe(thing: Thing) -> str:
    """Everything she knows about one thing, in a line or two."""
    from services.activity.log import _duration

    how = {"lookup": "I looked it up", "boss": "you told me", "rule": "worked out myself"}[thing.source]
    what = f"{thing.about} ({how})" if thing.about else f"I file it under {thing.category} ({how})" \
        if thing.placed else "I still don't know what it is"
    busiest = max(range(24), key=lambda h: thing.hours[h])
    usual = f", mostly around {datetime(2000, 1, 1, busiest):%I %p}".replace(" 0", " ") if thing.days >= 3 else ""
    return (f"{thing.name}: {what}. Seen {thing.times} time{'s' if thing.times != 1 else ''} on {thing.days} "
            f"day{'s' if thing.days != 1 else ''}, {_duration(thing.seconds)} in all{usual}; "
            f"first on {thing.first_seen:%d %b}, last on {thing.last_seen:%d %b}.")
