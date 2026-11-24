"""Draft optional wording with local Ollama and apply it only after owner review."""
import asyncio
from collections import Counter
from datetime import datetime
import json
import re
import sqlite3

from core.config import config
from core.errors import ProviderError
from core.logger import logger
from providers import failover, policy
from providers.base_provider import Message
from services import settings_store
from services.automation.results import ActionResult
from services.mind import state
from services.mind.reviews import redact, reviews
from services.remote.context import remote_origin

DAILY_LIMIT, BATCH_SIZE = 20, 5
IDLE_SECONDS, CHECK_SECONDS = 300, 300
INTENTS = {
    "command": ("update", "result"),
    "task_done": ("update", "completion update"),
    "exam_soon": ("update", "exam reminder", "reminder"),
    "feeling": ("status update", "check-in"),
}
BANDS = ("calm", "focused", "neutral", "bright")
TARGETS = tuple((kind, band) for band in BANDS for kind in INTENTS)
LEADS = {
    "calm": ("A brief {label}", "A short {label}", "A quick {label}"),
    "focused": ("Quick {label}", "A brief {label}", "One {label}"),
    "neutral": ("Here's the {label}", "A quick {label}", "A brief {label}"),
    "bright": ("Here's the {label}", "One quick {label}", "A quick {label}"),
}
ADDRESSES = ("", ", Boss")
TAILS = {
    "calm": ("",),
    "focused": ("",),
    "neutral": ("", " I'm here if you need a hand.", " Just say if you need me."),
    "bright": ("", " Ready for the next thing.", " I'm here if you need a hand."),
}
PROMPT = (
    "You are drafting alternate delivery templates for FRIDAY's owner to review. "
    "Use the requested intent and mood for each candidate. Compose a clean, short line from the "
    "given framing options with the exact {fact} placeholder unchanged. Use a different framing "
    "when the same target appears twice. Do not add facts, promises, jokes, insults, guilt, or claims of feelings. "
    "Return a JSON object with a lines array. Each entry must contain intent, band and template."
)
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lines"],
    "properties": {"lines": {"type": "array", "maxItems": BATCH_SIZE, "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "band", "template"],
        "properties": {"intent": {"type": "string", "enum": list(INTENTS)},
                       "band": {"type": "string", "enum": list(BANDS)},
                       "template": {"type": "string", "maxLength": 120}}
    }}},
}
_LIST = re.compile(r"review lines(?: after #?([1-9][0-9]{0,17}))?", re.I)
_CHANGE = re.compile(r"(approve|edit|reject) line #?([1-9][0-9]{0,17})(?:\s*:\s*(.+))?", re.I)
_MANAGES = re.compile(
    r"^(?:review lines(?:[ .!?]*$|\s+after\b)|(?:approve|edit|reject) line(?:[ .!?]*$|\s+#?[0-9]))",
    re.I,
)
_RECEIPT = "Local writer's room review."


def _frames(kind, band):
    prefixes = {
        lead.format(label=label) + address + ". "
        for lead in LEADS[band] for label in INTENTS[kind] for address in ADDRESSES
    }
    # A follow-on can carry the tone without changing any of the source facts.
    return sorted(prefixes | {""}), TAILS[band]


def valid_template(kind, band, template):
    if kind not in INTENTS or band not in BANDS or not isinstance(template, str) or len(template) > 120:
        return False
    prefix, slot, tail = template.partition("{fact}")
    prefixes, tails = _frames(kind, band)
    return bool(slot and (prefix or tail) and prefix in prefixes and tail in tails and len(template.split()) <= 20)


def _enabled():
    return config.FRIDAY_LLM == "on" and config.AI_WORDING_ENABLED and config.provider_is_configured("ollama")


@settings_store.synchronized
def _reserve(day):
    if not _enabled():
        return ()
    with reviews.db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS writer_daily (day TEXT PRIMARY KEY, attempts INTEGER NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT attempts FROM writer_daily WHERE day=?", (day.isoformat(),)).fetchone()
        used = previous["attempts"] if previous else 0
        count = min(BATCH_SIZE, DAILY_LIMIT - used)
        if count <= 0:
            return ()
        conn.execute("INSERT INTO writer_daily VALUES (?,?) ON CONFLICT(day) DO UPDATE SET attempts=excluded.attempts",
                     (day.isoformat(), used + count))
        return tuple(TARGETS[(day.toordinal() + slot) % len(TARGETS)] for slot in range(used, used + count))


@settings_store.synchronized
def _stage(rows, model, now):
    if not _enabled() or not rows:
        return 0
    safe_model = redact(model)[:120]
    added = 0
    with reviews.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for kind, band, template in rows:
            context = {"intent": kind, "band": band, "provider": "ollama", "model": safe_model}
            added += conn.execute(
                """INSERT INTO reviews (at, kind, channel, question, context, pattern, subject)
                   SELECT ?, 'line', 'writers_room', ?, ?, ?, ?
                   WHERE NOT EXISTS (SELECT 1 FROM reviews WHERE kind='line' AND pattern=? AND subject=?
                                     AND (question=? OR preferred=?))""",
                (now.timestamp(), template, json.dumps(context), band, kind, band, kind, template, template),
            ).rowcount
    return added


def _drafts(content, targets):
    if not isinstance(content, str) or len(content) > 6000:
        return []
    value = json.loads(content)
    lines = value["lines"] if isinstance(value, dict) and set(value) == {"lines"} else None
    if not isinstance(lines, list) or len(lines) > len(targets):
        return []
    remaining = Counter(targets)
    drafts = []
    for row in lines:
        if not isinstance(row, dict) or set(row) != {"intent", "band", "template"}:
            continue
        kind, band, template = row["intent"], row["band"], row["template"]
        if not isinstance(kind, str) or not isinstance(band, str) or not isinstance(template, str):
            continue
        template = redact(template)
        if remaining[kind, band] and valid_template(kind, band, template):
            remaining[kind, band] -= 1
            drafts.append((kind, band, template))
    return drafts


async def tick(now=None):
    """One scheduled batch, using only local usage, power and the draft quota."""
    if not _enabled():
        return 0
    now = now or datetime.now()
    try:
        present = await asyncio.to_thread(state.snapshot, now)
        battery = present.get("battery") or {}
        if battery.get("plugged") is not True and (present.get("idle") or 0) < IDLE_SECONDS:
            return 0
        if not (targets := await asyncio.to_thread(_reserve, now.date())):
            return 0
        request = []
        for kind, band in targets:
            leads, tails = _frames(kind, band)
            request.append({"intent": kind, "band": band, "prefix_choices": leads, "suffix_choices": tails,
                            "template_structure": "one prefix + {fact} + one suffix, with at least one affix"})
        token = policy.purpose.set("wording")
        try:
            reply = await failover.complete_exact(
                "ollama", [Message("user", json.dumps(request))], PROMPT, 550,
                response_schema=SCHEMA, attempt_timeout=8, temperature=.5,
            )
        finally:
            policy.purpose.reset(token)
        if reply.provider != "ollama" or reply.tool_calls or reply.metadata.get("incomplete"):
            return 0
        return await asyncio.to_thread(_stage, _drafts(reply.content, targets), reply.model, now)
    except (ProviderError, TimeoutError, OSError, sqlite3.Error, TypeError, ValueError) as error:
        logger.debug("Writer's room draft deferred (%s)", type(error).__name__)
        return 0


async def run():
    while True:
        await asyncio.sleep(CHECK_SECONDS)
        await tick()


def approved_templates(kind, band):
    """Read approved local templates and their provenance, with revocations visible immediately."""
    if kind not in INTENTS or band not in BANDS or not reviews.path.exists():
        return []
    try:
        with reviews.db() as conn:
            rows = conn.execute(
                """SELECT id, at, question, preferred, context, reviewed_at FROM reviews
                   WHERE kind='line' AND subject=? AND pattern=? AND state='approved' AND reviewed_at IS NOT NULL
                   ORDER BY id""",
                (kind, band),
            ).fetchall()
        return [{"id": row["id"], "template": row["preferred"],
                 "provenance": json.loads(row["context"]) | {"drafted_at": row["at"],
                    "approved_at": row["reviewed_at"], "owner_edited": row["preferred"] != row["question"]}}
                for row in rows if valid_template(kind, band, row["preferred"])]
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        logger.debug("Approved wording unavailable (%s)", type(error).__name__)
        return []


def _pending(after):
    if not reviews.path.exists():
        return []
    with reviews.db() as conn:
        return conn.execute(
            """SELECT id, subject, pattern, question, preferred FROM reviews
               WHERE kind='line' AND state='pending' AND id>? ORDER BY id LIMIT ?""",
            (after, BATCH_SIZE + 1),
        ).fetchall()


def _apply(command, item, template):
    with reviews.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM reviews WHERE kind='line' AND id=?", (item,)).fetchone()
        if not row or row["state"] not in ("pending", "approved") or (command != "reject" and row["state"] != "pending"):
            raise ValueError("That line is no longer available for this review.")
        if command == "reject":
            conn.execute("UPDATE reviews SET state='rejected', reviewed_at=? WHERE id=?", (datetime.now().timestamp(), item))
            return f"I've set line {item} aside."
        choice = redact(template.strip()) if command == "edit" else row["preferred"] or row["question"]
        if row["subject"] not in INTENTS or row["pattern"] not in BANDS:
            raise ValueError("This draft's framing is unavailable.")
        if not valid_template(row["subject"], row["pattern"], choice):
            prefixes, _ = _frames(row["subject"], row["pattern"])
            raise ValueError("Keep one {fact} slot and use a short, safe frame such as " + prefixes[1] + "{fact}.")
        reviewed = "approved" if command == "approve" else "pending"
        conn.execute("UPDATE reviews SET preferred=?, state=?, reviewed_at=? WHERE id=?",
                     (choice, reviewed, datetime.now().timestamp(), item))
    return (f"Line {item} is now in the library." if command == "approve"
            else f"Line {item} updated. Use approve line {item} when it's ready.")


def _result(success, message):
    return ActionResult(success, message, memory_message=_RECEIPT, repeatable=False, speech="")


async def handle(message, *, remote=False):
    """Owner review commands publish no candidate text into the audio or lesson paths."""
    text = message.strip()
    if not _MANAGES.match(text):
        return None
    if remote or remote_origin.get():
        return _result(False, "The writer's room is available at the laptop.")
    try:
        if listing := _LIST.fullmatch(text.rstrip(" .!?")):
            rows = await asyncio.to_thread(_pending, int(listing[1] or 0))
            if not rows:
                return _result(True, "The writer's room has no lines waiting for review.")
            lines = [f"{r['id']}. {r['subject']} / {r['pattern']} — {r['preferred'] or r['question']}"
                     for r in rows[:BATCH_SIZE]]
            lines.append("Use approve line ID, edit line ID: template, or reject line ID.")
            if len(rows) > BATCH_SIZE:
                lines.append(f"Use review lines after {rows[BATCH_SIZE - 1]['id']} for more.")
            return _result(True, "\n".join(lines))
        change = _CHANGE.fullmatch(text)
        if change and (change[1].lower() == "edit") == bool(change[3]):
            return _result(True, await asyncio.to_thread(_apply, change[1].lower(), int(change[2]), change[3]))
        return _result(False, "Use review lines, approve line ID, edit line ID: template, or reject line ID.")
    except ValueError as error:
        return _result(False, str(error))
    except (OSError, sqlite3.Error) as error:
        logger.debug("Writer's room review unavailable (%s)", type(error).__name__)
        return _result(False, "I couldn't open the local writer's room.")

