"""
services/mind/reflection.py

FRIDAY thinking over what the Boss told her — every REFLECT_EVERY_HOURS while there's something new, and
every night (at JOURNAL_HOUR, from services/proactive/watcher.py):
it reads the Boss's messages from today (and how her jokes landed), and rewrites a short profile —
"what I know about the Boss" — that every chat reply sees (prompt_section()). It also saves new
lasting facts to long-term memory (source "learned", so the Sunday review lists them) and a line
about what humour worked.

Privacy (the Boss's choice): the online model gets today's typed/spoken messages — nothing about what
the Boss did on the PC (no apps, minutes, titles, sites or files): thinking about that is her brain's
job, locally (services/mind/brain.py). Messages that are private by nature are left out: notes and
journal entries, text to type, WhatsApp messages.

State: memory/mind/profile.json {"lines": [...], "humour": "...", "updated": "YYYY-MM-DD"}.
"""

import json
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

from core.config import config
from core.logger import logger
from providers.base_provider import Message

path = config.MEMORY_DIR / "mind" / "profile.json"  # tests point this elsewhere
MAX_LINES = 12
MAX_CHAT_CHARS = 8000
MAX_FACTS = 6
MAX_QUESTIONS = 5
REFLECT_EVERY_HOURS = 3  # during the day, when there's something new to think about (plus the nightly run)

REFLECT_PROMPT = (
    "You are the reflective memory of Friday, the Boss's personal AI. Every few hours and each night you read what "
    "the Boss said to Friday today, and you update your understanding of them.\n"
    "Return ONLY a JSON object:\n"
    '{"profile": [...], "facts": [...], "humour": "...", "questions": [...]}\n'
    f"- profile: at most {MAX_LINES} short lines describing the Boss as you now understand them — habits, "
    "routines, goals, preferences, what they're working on, what stresses them, how they like to be talked to. "
    "Start from the current profile: keep what still holds, update what changed, drop what's outdated, add what's "
    "new. Write about the Boss in the third person (\"The Boss …\"). Only claims the data supports.\n"
    f"- facts: up to {MAX_FACTS} NEW lasting facts worth remembering word for word (names, dates, preferences) "
    "that aren't already in the profile. Empty list if none.\n"
    "- humour: one line on what kind of jokes worked or didn't today (from the reactions), or \"\" if unknown.\n"
    f"- questions: up to {MAX_QUESTIONS} things you'd genuinely like to know about the Boss next — about anything: "
    "what they like, their habits, people, plans, opinions, things they mentioned in passing. "
    "Not things already in the profile. Short, friendly questions.\n"
    "No markdown, no commentary outside the JSON."
)


# ── State ─────────────────────────────────────────────────────────────────────

def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(profile: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")


def prompt_section() -> str:
    """For the chat system prompt: FRIDAY's own notes about the Boss ("" before the first night)."""
    profile = load()
    lines = profile.get("lines") or []
    if not lines:
        return ""
    text = "What you've come to know about the Boss (your own notes, updated nightly — use them naturally, " \
           "don't recite them):\n" + "\n".join(f"- {line}" for line in lines)
    if profile.get("humour"):
        text += f"\nHumour notes: {profile['humour']}"
    return text


# ── Gathering the day ─────────────────────────────────────────────────────────

def _private(message: str) -> bool:
    """Messages the online model never sees: notes/journal, text to type, WhatsApp messages."""
    from services.automation.command_words import normalize_command
    from services.automation.typing_commands import match_typing_command
    from services.automation.whatsapp import match_whatsapp_command
    from services.memory.notes import is_note

    try:
        return is_note(message) or bool(match_typing_command(message)) or \
            bool(match_whatsapp_command(normalize_command(message), message))
    except Exception:
        return True  # when unsure, keep it private


def messages_on(day: date) -> list[str]:
    """The Boss's own messages that day (UTC timestamps in the history table), private ones left out."""
    start = datetime.combine(day, datetime.min.time()).astimezone()
    end = start + timedelta(days=1)
    try:
        with closing(sqlite3.connect(config.MEMORY_DB_PATH)) as conn:
            rows = conn.execute("SELECT content, timestamp FROM conversations WHERE role = 'user' ORDER BY id").fetchall()
    except sqlite3.Error as e:
        logger.warning(f"Reflection couldn't read the chat history: {e}")
        return []
    found = []
    for content, stamp in rows:
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if start <= when.astimezone() < end and not _private(content):
            found.append(content)
    return found


def joke_reactions(day: date) -> str:
    from services.mind import humour

    return "; ".join(f"{r['kind']} joke while {r['where']}: {r['felt']}" for r in humour.load().get("recent", [])
                     if r.get("day") == day.isoformat()) or "none"


# ── Thinking ──────────────────────────────────────────────────────────────────

def _parse(reply: str) -> dict | None:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def reflect_if_due(log, now: datetime) -> str | None:
    """During the day: think again every REFLECT_EVERY_HOURS, if the Boss has said something new since last time —
    so what they tell her at 2 PM already shapes her 5 PM questions."""
    profile = load()
    if now.timestamp() - profile.get("reflected_at", 0) < REFLECT_EVERY_HOURS * 3600:
        return None
    seen = profile.get("messages_seen", 0) if profile.get("updated") == now.date().isoformat() else 0
    if len(messages_on(now.date())) <= seen:
        return None
    _save({**profile, "reflected_at": now.timestamp()})  # first, so a failure waits for the next round
    return await reflect(log, now.date())


async def reflect(log, day: date | None = None, provider_name: str | None = None) -> str | None:
    """Think over what the Boss said on `day` and update the profile (`log` is no longer read: activity stays
    local). Returns a one-line summary, or None if nothing was said / it failed."""
    if config.AI_ASSIST_ONLY:
        return None
    from providers.failover import complete_with_failover
    from services.memory.semantic import semantic_memory

    day = day or date.today()
    said = messages_on(day)
    if not said:
        return None
    chat = "\n".join(f"- {m}" for m in said)[-MAX_CHAT_CHARS:] or "(nothing)"
    current = load()
    brief = (f"Current profile:\n" + ("\n".join(f"- {l}" for l in current.get("lines", [])) or "(empty — first night)")
             + f"\n\nWhat the Boss said today ({day:%A %d %B %Y}):\n{chat}\n\nReactions to your jokes: {joke_reactions(day)}")
    try:
        reply = await complete_with_failover(provider_name or config.ACTIVE_PROVIDER, [Message(role="user", content=brief)],
                                             REFLECT_PROMPT, 1500)
    except Exception as e:
        logger.warning(f"Reflection failed: {e}")
        return None
    data = _parse(reply.content)
    if not data or not isinstance(data.get("profile"), list):
        logger.warning("Reflection gave no usable profile")
        return None
    lines = [str(l).strip() for l in data["profile"] if str(l).strip()][:MAX_LINES]
    facts = [str(f.get("fact", "") if isinstance(f, dict) else f).strip()  # some models wrap each fact: {"fact": …}
             for f in data.get("facts") or []]
    facts = [f for f in facts if f][:MAX_FACTS]
    _save({**load(), "lines": lines, "humour": str(data.get("humour") or "").strip() or current.get("humour", ""),
           "updated": day.isoformat(), "messages_seen": len(said)})
    saved = 0
    for fact in facts:
        try:
            saved += bool(await semantic_memory.add_learned(fact, provider_name))  # may replace a fact it updates
        except Exception as e:
            logger.warning(f"Couldn't save a reflected fact: {e}")
    from services.mind import wonder
    wonder.add([str(q) for q in data.get("questions") or [] if str(q).strip()][:MAX_QUESTIONS])
    logger.info(f"Reflection done: {len(lines)} profile lines, {saved} new facts")
    return f"Thought over today: {len(lines)} notes on you, {saved} new thing{'s' if saved != 1 else ''} learned."


# ── "What's on your mind?" ────────────────────────────────────────────────────

MIND_ACTION = "whats_on_your_mind"
_MIND = re.compile(r"^(?:what(?:'s| is| are) (?:on|in) your (?:mind|head|brain)|what are you thinking(?: about)?"
                   r"|what have you (?:learned|learnt) (?:lately|recently)|how(?:'s| is) your (?:brain|mind))$", re.I)


def match_mind_command(text: str) -> dict | None:
    return {"type": "system", "action": MIND_ACTION} if _MIND.match(text.strip(" ?!.")) else None


def on_my_mind() -> str:
    """Her mood and live thoughts, then everything FRIDAY has learned by itself: the profile, humour,
    corrections and the predictor's scores."""
    from services.mind import brain, corrections, humour, learner, life, talk, thoughts, wonder

    now = datetime.now()
    profile = load()
    word, why = life.mood(now, brain.away_minutes(now))
    noticed = [t.data.get("noticed", t.kind) + (f" ({t.data['program']})" if t.data.get("program") else "")
               for t in thoughts.alive(now)[:4]]
    parts = [f"Mood: {word} — {why}. Today {life.day_line(now.date().isoformat())}",
             ("Things I've noticed and haven't brought up yet:\n" + "\n".join(f"- {n}" for n in noticed))
             if noticed else "Nothing unexplained on my mind right now.",
             ("What I've worked out about you:\n" + "\n".join(f"- {l}" for l in profile["lines"][:6]))
             if profile.get("lines") else "No notes on you yet — I think over the day each night, starting tonight."]
    parts.append(humour.summary())
    parts.append(talk.summary())
    if wondering := wonder.summary():
        parts.append(wondering)
    fixed = corrections.recent()
    if fixed:
        parts.append("You corrected me on: " + "; ".join(f"\"{m}\" → {w}" for m, w in fixed[-5:]) + ".")
    parts.append(learner.summary())
    return "\n\n".join(parts)
