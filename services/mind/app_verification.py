"""Scoped owner verification for app, course, term, place and topic explanations."""

import re
import threading
import time
import json
import uuid
from collections import OrderedDict
from datetime import datetime

from services.automation.results import ActionResult
from services.mind import app_learning, talk

_lock = threading.RLock()
SESSION = uuid.uuid4().hex
_generation = 0
_turns = OrderedDict()
_REPLY = re.compile(
    r"^(?:yes|yep|yeah|correct|right|no|nope|incorrect|wrong|maybe|not sure|i don't know|"
    r"i do not know|i'm not sure|i am not sure|that's right|that is right|that's wrong|that is wrong|"
    r"actually\b.*|yes[, ]+.*|yeah[, ]+.*|no[, ]+.*|it's\b.*|it is\b.*|this (?:app|course|term|place) is\b.*|(?:a|an|the) .+)[.! ]*$", re.I)
_NAMED = re.compile(r'^(?:(?:learn|identify|verify) (?:the )?(?:(app|course|term|place|topic) (?:code )?)?'
                    r'|(?:what is|what\'s) (?:the )?(app|course|term|place|topic) (?:code )?)(.+)$', re.I)
_GENERAL = re.compile(r"^(?:what (?:is|are)|what's) (.+)$", re.I)
PRIVATE_PROPOSAL = 'I asked you to review an unverified explanation.'


def _begin_turn():
    global _generation
    from services.mind.cognition import _turn
    turn = _turn.get() or uuid.uuid4().hex
    with _lock:
        if turn not in _turns:
            _generation += 1
            _turns[turn] = _generation
            if len(_turns) > 128:
                _turns.popitem(last=False)
        return _turns[turn]


def _retire(pending, state="withheld"):
    current = talk.load()
    if (current.get("pending") or {}) == pending:
        current.pop("pending", None)
        talk._save(current)
    from services.mind.inquiry import inquiry
    inquiry.mark(pending.get("inquiry_id"), state)


def offer_current(pending):
    offer = pending.get("app_verification")
    row = app_learning.current(offer) if isinstance(offer, dict) else None
    return bool(row and pending.get("app_session") == SESSION
                and pending.get("question") == app_learning.question(row))


def mark_returned(text, *, remote=False):
    """The explicit question has reached its response boundary; preparation alone isn't an offer."""
    if remote:
        return
    with _lock:
        state = talk.load()
        pending = state.get("pending") or {}
        if pending.get("app_verification") and pending.get("explicit") and pending.get("question") == text:
            from services.mind.inquiry import inquiry
            with inquiry._db() as db:
                prepared = db.execute("SELECT j.id FROM inquiry_jobs j JOIN inquiry_meta m ON m.id=1 "
                    "WHERE j.id=? AND j.epoch=m.epoch AND j.state='prepared' AND j.question=? AND j.expires>?",
                    (pending.get("inquiry_id"), text, time.time())).fetchone()
            if (offer_current(pending) and prepared
                    and pending.get("app_generation", _generation) == _generation):
                pending.update(offered=True, offered_at=time.time())
                talk._save(state)
                inquiry.mark(pending.get("inquiry_id"), "submitted")


def handle_reply(text, *, remote=False, now=None):
    if remote:
        return None
    text = text.replace("\u2019", "'")
    with _lock:
        pending = talk.load().get("pending") or {}
        if not pending.get("app_verification"):
            return None
        if talk._SHUSH.search(text) and (len(text.split()) <= talk.SHUSH_WORDS or
                re.search(r"\b(?:stop asking|no more questions|don't ask me|do not ask me)\b", text, re.I)):
            talk.pause(talk.SHUSH_PAUSE_MINUTES)
            return ActionResult(True, "I'll stop asking for now. The explanation stays in the inbox.", repeatable=False)
        if not _REPLY.fullmatch(text.strip()):
            _retire(pending)
            return None
        from services.automation import intent
        if intent.is_awaiting_confirmation():
            _retire(pending)
            return None  # never share a yes with an action confirmation
        now = time.time() if now is None else now
        offered = pending.get("offered_at", pending.get("at", 0))
        from services.mind.inquiry import inquiry
        if (not pending.get("offered") or not 0 <= now - offered <= talk.ANSWER_SECONDS
                or not offer_current(pending)):
            _retire(pending)
            return ActionResult(False, "That explanation is no longer the current question. Ask me to verify it again.",
                                repeatable=False)
        with inquiry.answer_guard(pending.get("inquiry_id"), pending.get("question")) as valid:
            result = app_learning.resolve(pending["app_verification"], text, datetime.fromtimestamp(now)) if valid else "stale"
        from services.mind.life_state import reaction
        if result != 'stale':
            reaction(pending, 'acted_on' if result in {'confirmed', 'corrected'} else 'answered', now)
        if result == "uncertain":
            # Keep the proposal, but don't keep a dangling approval target.
            _retire(pending, "ignored")
            return ActionResult(True, "I'll leave that explanation unconfirmed.", repeatable=False)
        _retire(pending, "answered" if result != "stale" else "withheld")
        if result in {"confirmed", "corrected"} and pending['app_verification']['key'].startswith(('app:', 'topic:')):
            from services.activity.log import activity_log
            activity_log.resort()
        messages = {
            "confirmed": "Saved the explanation you confirmed.",
            "corrected": "Saved your correction as the explanation.",
            "rejected": "Discarded that explanation.",
            "stale": "That explanation changed. Ask me to verify the current version.",
        }
        return ActionResult(result != "stale", messages[result], repeatable=False)


async def handle(text, log, *, remote=False):
    """Explicit awareness commands and scoped verification replies."""
    import asyncio
    from services.mind import activity_awareness, knowledge
    if remote:
        return None
    generation = _begin_turn()
    if generation != _generation:
        return None
    def local_turn():
        with _lock:
            if generation != _generation:
                return ActionResult(False, "A newer request replaced that activity update.", repeatable=False)
            return handle_reply(text) or activity_awareness.command(text, log)
    report = await asyncio.to_thread(local_turn)
    if report is not None:
        return report
    from services.automation.command_words import normalize_command
    command = normalize_command(text).strip(' ?.!')
    if re.fullmatch(r"what (?:did|have) you learn(?:ed)? this week", command, re.I):
        return ActionResult(True, await asyncio.to_thread(app_learning.week, datetime.now()), repeatable=False, speech='')
    if correction := re.fullmatch(r"this app is (.{4,300})[.!]?", text.strip(), re.I):
        seen = activity_awareness.recent_context(log)
        if not seen:
            return ActionResult(False, "Open the app first so I can attach that explanation to it.", repeatable=False)
        if app_learning.uncertain(correction[1]):
            return ActionResult(True, "I'll leave that explanation unconfirmed.", repeatable=False)
        key = knowledge.key_for("app", seen["app"])
        if not knowledge.get(key):
            from services.activity.categories import app_category
            with knowledge.db() as conn:
                knowledge.see(conn, "app", seen["app"], app_category(seen["app"]), datetime.now())
        with _lock:
            if generation != _generation:
                return ActionResult(False, "A newer request replaced that app explanation.", repeatable=False)
            knowledge.teach(key, correction[1])
        await asyncio.to_thread(log.resort)
        return ActionResult(True, "Saved your explanation of this app.", repeatable=False)
    if command.casefold() in {"learn this app", "identify this app", "what is this app", "verify this app"}:
        seen = activity_awareness.recent_context(log)
        if not seen:
            return ActionResult(False, "Open the app first, then ask me to learn it.", repeatable=False)
        return await _present(seen['app'], 'app', generation, observed=True)
    if match := _NAMED.fullmatch(command):
        kind = match[1] or match[2]
        if kind is None and command.casefold().startswith('identify '):
            return None  # Existing feature aliases such as identifying the current song own this wording.
        if kind is None and command.casefold().startswith('learn '):
            from services.proactive.timetable import match_timetable_command
            if (match_timetable_command(command) or {}).get('action') == 'import_timetable':
                return None
        return await _present(match[3], kind.casefold() if kind else None, generation)
    return None


async def general(text, *, remote=False):
    """General lookups run after deterministic commands and before language-model routing."""
    from services.automation.command_words import normalize_command
    from services.mind import training
    from services.mind.lessons import personal_question
    text = normalize_command(text).strip(' ?.!')
    match = _GENERAL.fullmatch(text)
    if (remote or not match or personal_question(text) or training.local_reply(text)
            or re.search(r'\b(?:my|mine|your|our|this|that|me|you|us|weather|like|how|when|why|of (?:a|an|the))\b', match[1], re.I)):
        return None
    return await _present(match[1], None, _begin_turn())


async def _present(name, kind, generation, *, observed=False):
    import asyncio
    from services.automation import intent
    from services.mind import knowledge
    with _lock:
        if generation != _generation:
            return ActionResult(False, 'A newer request replaced that question.', repeatable=False)
        intent.cancel_pending_confirmation()
    now = datetime.now()
    if kind in {None, 'course'}:
        from services.automation.command_slots import course
        try:
            saved = course(name)
        except (OSError, ValueError) as error:
            from core.logger import logger
            logger.debug('Local course lookup unavailable (%s)', type(error).__name__)
            saved = None
        if saved:
            return ActionResult(True, f'{saved} is on your timetable.', repeatable=False)
    thing = await asyncio.to_thread(knowledge.requested_thing, name, kind, now)
    if not thing:
        return ActionResult(False, 'Give me the short name of the thing you want me to identify.', repeatable=False)
    key = thing.key
    if thing.placed:
        return ActionResult(True, knowledge.describe(thing) if observed else f'{thing.name}. {thing.about or thing.category}.', repeatable=False)
    await knowledge.look_up(thing, now, requested=True)
    if (current := knowledge.get(key)) and current.about:
        return ActionResult(True, f'{current.name}. {current.about}', repeatable=False)
    rows = app_learning.pending(key)
    if not rows:
        return ActionResult(False, "The lookup hasn't produced a review item yet. Ask me to verify the name again.",
                            repeatable=False)
    proposal = rows[0]
    question = app_learning.question(proposal)
    from services.mind.inquiry import inquiry, LEASE_SECONDS
    from services.mind.reasoning_store import fingerprint
    ref = "app-explanation:" + proposal["token"]
    known = {**proposal, "kind": "app_verification"}
    with _lock:
        if generation != _generation:
            return ActionResult(False, "A newer request replaced that question.", repeatable=False)
        talk.retire_question()
        with inquiry._db() as db:
            epoch = db.execute("SELECT epoch FROM inquiry_meta WHERE id=1").fetchone()[0]
            cursor = db.execute("INSERT INTO inquiry_jobs(signature,token,epoch,expires,state,explicit,created,retry_at,"
                "question,topic,reason,basis,gap,gap_version) VALUES(?,?,?,?,'prepared',1,?,0,?,?,?,?,?,?)",
                (fingerprint(known), uuid.uuid4().hex, epoch, time.time() + LEASE_SECONDS, time.time(), question,
                 "app explanation " + key, "Owner explicitly requested identification.",
                 json.dumps({ref: fingerprint(known)}), ref + ":verify", fingerprint({
                     name: known[name] for name in ("key", "token", "revision", "description", "category")})))
            ident = cursor.lastrowid
        talk._record({"say": question, "inquiry_id": ident, "explicit": True, "app_generation": generation,
                      "app_verification": app_learning.identity(proposal)}, "asked", time.time())
    return ActionResult(True, question, memory_message=PRIVATE_PROPOSAL, repeatable=False, speech="")


def awaiting():
    pending = talk.load().get("pending") or {}
    return bool(pending.get("app_verification") and pending.get("offered")
                and 0 <= time.time() - pending.get("offered_at", 0) <= talk.ANSWER_SECONDS)
