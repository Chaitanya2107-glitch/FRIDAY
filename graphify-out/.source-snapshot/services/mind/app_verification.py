"""Scoped app-definition replies, handled before generic chat or personal-fact learning."""

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
    r"actually\b.*|yes[, ]+.*|yeah[, ]+.*|no[, ]+.*|it's\b.*|it is\b.*|this app is\b.*|a .+|an .+)[.! ]*$", re.I)


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
            return ActionResult(True, "I'll stop asking for now. The app explanation stays unconfirmed.", repeatable=False)
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
            return ActionResult(False, "That app explanation is no longer the current question. Ask me to learn the app again.",
                                repeatable=False)
        with inquiry.answer_guard(pending.get("inquiry_id"), pending.get("question")) as valid:
            result = app_learning.resolve(pending["app_verification"], text, datetime.fromtimestamp(now)) if valid else "stale"
        if result == "uncertain":
            # Keep the proposal, but don't keep a dangling approval target.
            _retire(pending, "ignored")
            return ActionResult(True, "I'll leave that app explanation unconfirmed.", repeatable=False)
        _retire(pending, "answered" if result != "stale" else "withheld")
        if result in {"confirmed", "corrected"}:
            from services.activity.log import activity_log
            activity_log.resort()
        messages = {
            "confirmed": "Saved the app explanation you confirmed. That doesn't yet tell me your current task.",
            "corrected": "Saved your correction as the app explanation.",
            "rejected": "Discarded that model explanation. You can tell me what the app is for.",
            "stale": "That app explanation changed, so I haven't applied this answer.",
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
    if text.strip().lower().rstrip("?.!") not in {
            "learn this app", "identify this app", "what is this app", "verify this app"}:
        return None
    seen = activity_awareness.recent_context(log)
    if not seen:
        return ActionResult(False, "Open the app first, then ask me to learn it.", repeatable=False)
    from services.automation import intent
    intent.cancel_pending_confirmation()
    now = datetime.now()
    key = knowledge.key_for("app", seen["app"])
    thing = await asyncio.to_thread(knowledge.get, key)
    if not thing:
        from services.activity.categories import app_category
        with knowledge.db() as conn:
            knowledge.see(conn, "app", seen["app"], app_category(seen["app"]), now)
        thing = knowledge.get(key)
    if thing.about:
        return ActionResult(True, knowledge.describe(thing), repeatable=False)
    rows = app_learning.pending(key)
    if not rows:
        await knowledge.look_up(thing, now)
        rows = app_learning.pending(key)
    if not rows:
        return ActionResult(False, "App explanation lookup is unavailable or disabled. You can tell me what this app is for.",
                            repeatable=False)
    proposal = rows[0]
    question = app_learning.question(proposal)
    from services.mind.inquiry import inquiry, LEASE_SECONDS
    from services.mind.reasoning_store import fingerprint
    ref = "app-explanation:" + proposal["token"]
    known = {**proposal, "kind": "app_verification"}
    with _lock:
        if generation != _generation:
            return ActionResult(False, "A newer request replaced that app question.", repeatable=False)
        talk.retire_question()
        with inquiry._db() as db:
            epoch = db.execute("SELECT epoch FROM inquiry_meta WHERE id=1").fetchone()[0]
            cursor = db.execute("INSERT INTO inquiry_jobs(signature,token,epoch,expires,state,explicit,created,retry_at,"
                "question,topic,reason,basis,gap,gap_version) VALUES(?,?,?,?,'prepared',1,?,0,?,?,?,?,?,?)",
                (fingerprint(known), uuid.uuid4().hex, epoch, time.time() + LEASE_SECONDS, time.time(), question,
                 "app explanation " + key, "Owner explicitly requested app identification.",
                 json.dumps({ref: fingerprint(known)}), ref + ":verify", fingerprint({
                     name: known[name] for name in ("key", "token", "revision", "description", "category")})))
            ident = cursor.lastrowid
        talk._record({"say": question, "inquiry_id": ident, "explicit": True, "app_generation": generation,
                      "app_verification": app_learning.identity(proposal)}, "asked", time.time())
    return ActionResult(True, question, repeatable=False)


def awaiting():
    pending = talk.load().get("pending") or {}
    return bool(pending.get("app_verification") and pending.get("offered")
                and 0 <= time.time() - pending.get("offered_at", 0) <= talk.ANSWER_SECONDS)
