"""Conversation delivery and feedback around local cognitive inquiry.

A watcher offers opportunities; the inquiry brain decides whether one grounded
question is useful now or silence is better. Startup/situation tags are context,
not instructions to ask. Durable global interruption limits also cover questions
from proactive features. Explicit requests allow one requested question.

Answers retain their original question/date in shared owner dialogue memory and
feed local executive reasoning. Commands and Telegram traffic do not answer the
laptop's pending question. Existing reaction/training feedback remains available.
Candidate helpers retained here support offline tests/catalogue tools; live
compose() does not pick from a fixed starter bank or fall back to a script.
"""

import asyncio
import json
import random
import re
import time
import winreg
from datetime import datetime, timedelta

from core.config import config
from core.logger import logger
from services.mind import brain, life, thoughts, wonder, wording

path = config.MEMORY_DIR / "mind" / "talk.json"  # tests point this elsewhere
PRIOR = (2.0, 2.0)
PER_MINUTE = 1 / 15       # chance a minute at full welcome → moderate: about every 30–45 min when you're active
OPENING = 2.5             # "just back", "a new app": obvious moments to say something
MIN_GAP_MINUTES = 15
ANSWER_SECONDS = 180
LIKED, DISLIKED, IGNORED = 1.0, 1.5, 0.3
SHORT_ANSWER = 0.4        # "yeah" / "fine" counts a bit less than a real answer
SHUSH_PAUSE_MINUTES = 60
SHUSH_WORDS = 6           # a brush-off is short; a long answer that says "later" is still an answer
BACK_MINUTES = 5          # "just back" stays an opening this long
LAUNCH_MIN_WELCOME = 0.25 # the launch question is skipped only once "not now" at launch has taught her so
LATE_FROM, LATE_UNTIL = 23, 5  # "late at night" for talking
PLAN_HOURS = 8            # what the Boss said they'd do stays in mind this long
AWAY_MINUTES = 20         # idle this long, then active again = "just back"
LONG_MINUTES = 90         # this much of one app in the last 2 hours = "a long stretch"
TYPING_IDLE_SECONDS = 5   # never cut in mid-keystroke
ACTIVE_SECONDS = 60
DECAY = 0.97
ASK_SHARE = 0.7           # how often she asks something specific rather than just checking in
NOTICE = "notice_"        # situations for what her brain noticed: "notice_jump", "notice_new" … one belief each

_SHUSH = re.compile(r"\b(?:not now|shut up|stop talking|be quiet|quiet|later|busy|leave me alone|don'?t (?:disturb|bother)"
                    r"|go away|not the time|enough|stop asking|no (?:more )?questions|that'?s all)\b", re.I)
_ON = re.compile(r"^(?:you can (?:talk|speak)(?: freely| on your own| whenever(?: you want)?)?|talk (?:freely|on your own)"
                 r"|(?:turn on|enable|switch on) (?:free will|talking on your own)|free will on)$", re.I)
_OFF = re.compile(r"^(?:stop talking on your own|don'?t talk (?:on your own|unless (?:i ask|asked))|(?:turn off|disable|switch off) "
                  r"(?:free will|talking on your own)|free will off)$", re.I)
_PAUSE = re.compile(r"^(?:be )?quiet(?: for| please for)? (?:(?P<n>\d+|an?|one) )?(?P<unit>hours?|minutes?|mins?)$", re.I)
_ASK = re.compile(r"^(?:ask me (?:something|anything|a question|stuff)|what (?:else )?do you (?:want|wanna) (?:to )?know(?: about me)?"
                  r"|get to know me(?: better)?|anything you want to (?:ask|know)(?: me)?)$", re.I)
TALK_ACTIONS = {"talk_on", "talk_off", "talk_pause"}

_asks: asyncio.Queue | None = None  # questions for the tray (GET /api/v1/mind/ask): opens the bar + the mic
_was_away = False                   # the previous minute's "away from the laptop"
_back_until = 0.0                   # "just back" is an opening until then
_launch_pending = True              # FRIDAY just started: her first chance goes to "what are you up to?"


# ── State ─────────────────────────────────────────────────────────────────────

def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def is_on() -> bool:
    return bool(load().get("on", True))  # on unless the Boss switched it off


def set_on(on: bool) -> None:
    state = load()
    state["on"] = on
    state.pop("paused_until", None)
    if not on:
        _cancel_question(state)
    _save(state)


def pause(minutes: int) -> None:
    state = load()
    state["paused_until"] = time.time() + minutes * 60
    _cancel_question(state)
    _save(state)


def _cancel_question(state):
    pending = state.pop('pending', None)
    if pending:
        try:
            from services.mind.life_state import reaction
            reaction(pending, 'shushed', time.time())
            from services.mind.inquiry import inquiry
            inquiry.mark(pending.get('inquiry_id'), 'shushed')
            _evening().stop()
        except Exception as error:
            logger.debug('Question cancellation receipt unavailable (%s)', type(error).__name__)


def _belief(state: dict, where: str) -> tuple[float, float]:
    a, b = state.get("beliefs", {}).get(where, PRIOR)
    return float(a), float(b)


def welcome(where: str, state: dict | None = None) -> float:
    a, b = _belief(load() if state is None else state, where)
    return a / (a + b)


def _learn(state: dict, where: str, liked: float, disliked: float) -> None:
    a, b = _belief(state, where)
    state.setdefault("beliefs", {})[where] = [round(a + liked, 3), round(b + disliked, 3)]


def fade() -> None:
    """Nightly: older evidence counts a little less (so she keeps adapting)."""
    state = load()
    for where, (a, b) in list(state.get("beliefs", {}).items()):
        state["beliefs"][where] = [round(PRIOR[0] + (a - PRIOR[0]) * DECAY, 3), round(PRIOR[1] + (b - PRIOR[1]) * DECAY, 3)]
    _save(state)


# ── Commands ──────────────────────────────────────────────────────────────────

def match_talk_command(text: str) -> dict | None:
    text = text.strip(" .!?")
    if re.fullmatch(r"(?:stop asking(?: me)?(?: questions)?|no more questions|don'?t ask me questions)", text, re.I):
        return {'type': 'system', 'action': 'talk_off'}
    if re.fullmatch(r"not now|later|that'?s all", text, re.I):
        return {'type': 'system', 'action': 'talk_pause', 'minutes': SHUSH_PAUSE_MINUTES}
    if _ON.match(text):
        return {"type": "system", "action": "talk_on"}
    if _OFF.match(text):
        return {"type": "system", "action": "talk_off"}
    if _ASK.match(text):
        return {"type": "system", "action": "talk_ask"}
    if m := _PAUSE.match(text):
        n = m["n"] or "1"
        n = 1 if n.lower() in ("a", "an", "one") else int(n)
        return {"type": "system", "action": "talk_pause", "minutes": n * 60 if m["unit"].lower().startswith("h") else n}
    return None


def run(parsed: dict) -> str:
    if parsed["action"] == "talk_on":
        set_on(True)
        return "Free will on. I'll speak up now and then, Boss — tell me \"not now\" and I'll learn."
    if parsed["action"] == "talk_off":
        set_on(False)
        return "Understood. I'll only talk when you talk to me."
    pause(parsed["minutes"])
    return f"Going quiet for {parsed['minutes']} minutes."


# ── Learning from the answer ──────────────────────────────────────────────────

def retire_question() -> None:
    """A requested clarification replaces an optional question without training a reaction."""
    state = load()
    pending = state.pop('pending', None)
    if pending:
        from services.mind.inquiry import inquiry
        inquiry.mark(pending.get('inquiry_id'), 'withheld')
        _save(state)


def hear(message: str, now: float | None = None) -> str | None:
    """The Boss said something: if it answers her last question, learn from it. Returns the reaction or None."""
    try:
        from services.automation import intent
        if intent.remote_request.get():
            return None  # a Telegram command is not the laptop conversation's answer
        shush = bool(_SHUSH.search(message) and (len(message.split()) <= SHUSH_WORDS or
                     re.search(r"\b(?:stop asking|no more questions|don'?t ask me|do not ask me)\b", message, re.I)))
        if not shush and intent._match_local_step(message):
            return None  # an unrelated command must not become an answer about the owner
        now = time.time() if now is None else now
        state = load()
        if (state.get("pending") or {}).get("app_verification"):
            from services.mind.app_verification import handle_reply
            return "answered" if handle_reply(message, now=now) else None
        pending = state.pop("pending", None)
        if not pending:
            return None
        if now - pending["at"] > ANSWER_SECONDS:
            state['pending'] = pending
            _expire(state, now)
            return "ignored"
        if shush:
            _learn(state, pending["where"], 0.0, DISLIKED)
            state["paused_until"] = now + SHUSH_PAUSE_MINUTES * 60
            felt = "shushed"
        else:
            _learn(state, pending["where"], LIKED if len(message.split()) >= 3 else SHORT_ANSWER, 0.0)
            felt = "answered"
            if pending["where"] == "start":  # "what are you up to?" — she keeps it in mind and follows up
                state["plan"] = {"text": message, "at": now}
        _save(state)
        life.feel(felt, now)
        from services.mind.life_state import reaction
        reaction(pending, felt, now)
        from services.mind.cognition import cognition

        cognition.record("reaction", "proactive", felt, public=True)
        from services.mind.inquiry import inquiry
        inquiry.mark(pending.get('inquiry_id'), felt)
        if felt == 'answered':
            from services.mind.brain_memory import brain_memory
            from services.mind.cognition import _turn, _channel
            brain_memory.remember(message, question=pending.get('question', ''),
                source=_turn.get() or None, channel=_channel.get() if _channel.get() in {'chat', 'voice'} else 'chat',
                now=datetime.fromtimestamp(now), inquiry_id=pending.get('inquiry_id') if pending.get('offered') else None)
        from services.mind.reviews import evidence
        evidence(pending.get("review_id"), text=message, reaction=felt)
        if felt == "answered" and pending.get("thought"):  # her brain keeps the reason, and learns unknown things
            brain.answered(pending["thought"], message, datetime.fromtimestamp(now))
        if felt == "answered" and pending.get("question"):
            if pending.get("wondered"):
                wonder.mark_answered(pending["wondered"], message)
            _learn_answer(pending["question"], message)
        _evening().heard(felt, pending, message)
        logger.info(f"Talk: a question while {pending['where']} was {felt}")
        return felt
    except Exception as e:  # learning must never break a reply
        logger.info(f"Talk learning skipped: {e}")
        return None


def _learn_answer(question: str, answer: str) -> None:
    """Remember what the answer says about the Boss — with her question, so "pizza" means something."""
    from services.memory.semantic import semantic_memory

    try:
        semantic_memory.learn_in_background(answer, config.ACTIVE_PROVIDER, question=question)
    except Exception as e:  # no running loop (tests), memory off …
        logger.info(f"Couldn't learn from the answer: {e}")


def _expire(state: dict, now: float) -> None:
    pending = state.get("pending")
    if pending and now - pending.get("offered_at", pending["at"]) > ANSWER_SECONDS:  # no answer at all
        from services.mind.reviews import evidence
        evidence(pending.get("review_id"), reaction="ignored")
        state.pop("pending")
        if pending.get('inquiry_id'):
            from services.mind.inquiry import inquiry
            inquiry.mark(pending['inquiry_id'], 'ignored')
            state['paused_until'] = max(state.get('paused_until', 0), now + 3600)
        _learn(state, pending["where"], 0.0, IGNORED)
        _save(state)
        life.feel("ignored", now)
        from services.mind.life_state import reaction
        reaction(pending, 'ignored', now)
        _evening().stop()


def _evening():
    from services.mind import evening  # it builds on this module: import late
    return evening


# ── When ──────────────────────────────────────────────────────────────────────

def mic_in_use() -> bool:
    """Another app has the microphone open right now (a call, a recording) — Windows' privacy records."""
    root = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def open_now(key) -> bool:
        for i in range(winreg.QueryInfoKey(key)[0]):
            name = winreg.EnumKey(key, i)
            if name == "NonPackaged" or "python" in name.lower():  # NonPackaged is walked separately; our own mic isn't a call
                continue
            try:
                with winreg.OpenKey(key, name) as sub:
                    if winreg.QueryValueEx(sub, "LastUsedTimeStop")[0] == 0 \
                            and winreg.QueryValueEx(sub, "LastUsedTimeStart")[0] != 0:
                        return True
            except OSError:
                continue
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as key:
            if open_now(key):
                return True
            with winreg.OpenKey(key, "NonPackaged") as sub:
                return open_now(sub)
    except OSError:
        return False


def situation(log, state: dict, now: datetime, came_back: bool) -> tuple[str, float]:
    """(situation, weight): obvious openings first, then what the Boss is doing."""
    from services.mind import humour

    if came_back:
        return "back", OPENING
    if _memory_plans()[0]:  # a plan just happened ("exam on Friday"): ask how it went
        return "followup", OPENING
    if thought := _on_her_mind(now):  # her brain noticed something: the more surprising, the sooner she says it
        return NOTICE + thought.kind, OPENING * thought.now_strength(now)
    app = log.app
    try:
        if app and log.app_seconds(app, now - timedelta(hours=2), now) >= LONG_MINUTES * 60:
            return "long", 1.5
    except Exception:
        pass
    where = humour.situation(now)
    if where not in ("study", "deadline") and (now.hour >= LATE_FROM or now.hour < LATE_UNTIL):
        where = "late"  # 11 PM–5 AM: whether she may talk then is learned from the Boss's reactions
    return where, 1.0


def _memory_plans() -> tuple[list[str], list[str]]:
    from services.memory.semantic import semantic_memory
    try:
        return semantic_memory.plans()
    except Exception as e:  # memory must never stop her talking
        logger.info(f"Talk: couldn't read plans from memory: {e}")
        return [], []


def _on_her_mind(now: datetime) -> "thoughts.Thought | None":
    try:
        return thoughts.top(now)
    except Exception as e:  # her brain must never stop her talking
        logger.info(f"Talk: couldn't read her thoughts: {e}")
        return None


def may_talk(state: dict, now_ts: float, busy: bool, idle: float) -> bool:
    """The hard limits. Quiet hours aren't one: late at night is a situation she learns about like any other."""
    return (state.get("on", True) and not busy and now_ts >= state.get("paused_until", 0)
            and "pending" not in state and now_ts - state.get("last_at", 0) >= MIN_GAP_MINUTES * 60
            and TYPING_IDLE_SECONDS <= idle < ACTIVE_SECONDS)


# ── What ──────────────────────────────────────────────────────────────────────

def _doing(log, now: datetime) -> tuple[str | None, int]:
    """(what the Boss is on right now, for how many minutes) — from her brain; the app alone if that fails."""
    try:
        if here := brain.present(brain.episodes(log, now), now):
            return here.label(), round(here.seconds / 60)
    except Exception as e:
        logger.info(f"Talk: no present episode ({e})")
    try:
        return log.app, round(log.app_seconds(log.app, now - timedelta(hours=3), now) / 60) if log.app else 0
    except Exception:
        return log.app, 0


def choose(log, where: str, state: dict, now: datetime, rng: random.Random = random) -> dict:
    """What to bring up — decided here, with no AI model. Returns {"raw": the facts to word} plus what
    saying it crosses off ("thought", "wondered", "followed_up")."""
    mood, _ = life.mood(now, brain.away_minutes(now))
    base = {"time": f"{now:%A %I:%M %p}", "your_mood": mood}
    if where == "start":
        return {"raw": {"kind": "start", **base, "moment": "you have just come online",
                        "ask": "what the Boss is up to or planning this session"}}
    happened, _coming = _memory_plans()
    if where == "followup" and happened:
        return {"raw": {"kind": "followup", **base, "this_just_happened": happened[0], "ask": "how it went"},
                "followed_up": happened[0]}
    thought = _on_her_mind(now)
    if thought and (where.startswith(NOTICE) or where == "asked"):
        return {"raw": {"kind": thought.kind, **base, **thought.data}, "thought": thought.id}
    doing, minutes = _doing(log, now)
    specific = []
    plan = state.get("plan") or {}
    if plan and now.timestamp() - plan["at"] < PLAN_HOURS * 3600:  # what the Boss said they'd do this session
        specific.append({"raw": {"kind": "plan", **base, "earlier_the_boss_said": plan["text"], "the_boss_is": doing,
                                 "ask": "how it's going"}})
    if where in wonder.FITS and (wondering := wonder.next_questions(1)):
        specific.append({"raw": {"kind": "question", **base, "ask": wondering[0]}, "wondered": wondering[0]})
    if specific and (where == "asked" or rng.random() < ASK_SHARE):
        return rng.choice(specific)
    if where == "back":
        return {"raw": {"kind": "back", **base, "moment": "the Boss just came back to the laptop", "before_leaving": doing}}
    return {"raw": {"kind": "checkin", **base, "situation": where, "the_boss_is": doing, "for_minutes": minutes,
                    "ask": "how it's going"}}


async def compose(log, where: str, state: dict, now: datetime) -> dict | None:
    """The local brain may generate one grounded question, or choose silence."""
    from services.mind.inquiry import inquiry
    return await inquiry.propose(now, explicit=where in {'asked', 'day_review', 'learning'}, intention=where)


# ── The minute ────────────────────────────────────────────────────────────────

def asks() -> asyncio.Queue:
    global _asks
    if _asks is None:
        _asks = asyncio.Queue(maxsize=1)
    return _asks


async def tick(log, now: datetime, busy: bool, idle: float, rng: random.Random = random) -> str | None:
    """Maybe say something. Returns what she said, or None."""
    global _was_away, _back_until, _launch_pending
    now_ts = now.timestamp()
    if _was_away and idle < ACTIVE_SECONDS:
        _back_until = now_ts + BACK_MINUTES * 60
    _was_away = idle >= AWAY_MINUTES * 60
    came_back = now_ts < _back_until
    state = load()
    _expire(state, now_ts)
    if not may_talk(state, now_ts, busy, idle) or await asyncio.to_thread(mic_in_use):
        return None
    if _launch_pending:  # just started: always ask what the Boss is up to — unless they've taught her not to
        where = "start"
        if welcome(where, state) < LAUNCH_MIN_WELCOME:
            _launch_pending = False
            return None
    else:
        where, _weight = situation(log, state, now, came_back)
    line = await compose(log, where, state, now)
    if not line:
        return None  # the launch question is tried again next minute
    _back_until, _launch_pending = 0.0, False
    _record(line, where, now_ts)
    return line["say"]


def _record(line: dict, where: str, now_ts: float) -> None:
    """She said it: wait for the answer, and cross it off her lists."""
    state = load()  # compose took a few seconds
    from services.mind.cognition import cognition

    cognition.record("question", "proactive", line["say"], status="prepared")
    from services.mind import training
    review_id = training.question(line, where, now_ts)
    state.update(last_at=now_ts, pending={"where": where, "at": time.time(), "question": line["say"],
                                          "thought": line.get("thought"), "review_id": review_id,
                                          "wondered": line.get("wondered"),
                                          "decision_id": line.get("decision_id")})
    state['pending']['inquiry_id'] = line.get('inquiry_id')
    if line.get('app_verification'):
        state['pending']['app_verification'] = line['app_verification']
        from services.mind.app_verification import SESSION
        state['pending']['app_session'] = SESSION
        if 'app_generation' in line:
            state['pending']['app_generation'] = line['app_generation']
    state['pending'].update(behavior_context=line.get('behavior_context'),
                            explicit=line.get('explicit', where in {'asked', 'day_review', 'learning'}), offered=False)
    state["recent"] = (state.get("recent", []) + [line["say"]])[-10:]
    _save(state)
    if line.get("thought"):  # said: it leaves her mind
        thoughts.mark_said(line["thought"])
    if line.get("wondered"):
        wonder.mark_asked(line["wondered"], now_ts)
    if line.get("followed_up"):  # asked how the exam went: not again
        from services.memory.semantic import semantic_memory
        try:
            semantic_memory.mark_followed_up(line["followed_up"])
        except Exception as e:
            logger.info(f"Talk: couldn't mark the follow-up: {e}")
    logger.info(f"Talk ({where}): {line['say']}")


async def ask_now(log, now: datetime) -> str:
    """An explicit request for one context-reviewed question, or a clear abstention."""
    line = await compose(log, "asked", load(), now)
    if not line:
        return "I don't have a useful new question right now, Boss. You can inspect brain status for the reason."
    _record(line, "asked", now.timestamp())
    return line["say"]


async def deliver(text: str) -> None:
    """Say it, show it, put it in the chat history (so the answer makes sense), and tell the tray to listen."""
    from interfaces.api.routes.voice import _speak_in_background
    from services.memory.sqlite_memory import MemoryService
    from services.reminders.service import show_toast
    from services.mind.cognition import cognition
    from services.mind.inquiry import inquiry
    state = load()
    if not state.get('on', True) or state.get('paused_until', 0) > time.time():
        return
    pending = state.get('pending') or {}
    if pending.get('app_verification'):
        from services.mind.app_verification import offer_current
        if not offer_current(pending):
            retire_question()
            return
    if pending.get('inquiry_id') and pending.get('question') == text:
        try:
            allowed = await asyncio.to_thread(inquiry.deliverable, pending['inquiry_id'])
        except Exception:
            allowed = False
        if not allowed:
            inquiry.mark(pending['inquiry_id'], 'withheld')
            state = load()
            if (state.get('pending') or {}).get('inquiry_id') == pending['inquiry_id']:
                state.pop('pending', None)
                _save(state)
            return

    cognition.record("reply", "proactive", text, status="prepared")
    try:
        MemoryService().save_message("assistant", text)
    except Exception as e:
        logger.warning(f"Couldn't save FRIDAY's question to the chat history: {e}")
    from services import body_state

    accepted = await asyncio.to_thread(show_toast, "F.R.I.D.A.Y", text, cognition_public=True)
    from services.mind.reviews import evidence
    pending = load().get("pending") or {}
    if pending.get("question") == text:
        inquiry.mark(pending.get('inquiry_id'), 'submitted' if accepted is True else
                     'failed' if accepted is False else 'attempted')
        cognition.finish(pending.get("decision_id"), "submitted" if accepted is True else
                         "failed" if accepted is False else "attempted")
        evidence(pending.get("review_id"), delivery="submitted" if accepted is True else
                 "failed" if accepted is False else "attempted")
    body_state.push("say", text)  # a speech bubble next to her body
    _speak_in_background(text)
    queue = asks()
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(text)
    state = load()
    if (state.get('pending') or {}).get('inquiry_id') == pending.get('inquiry_id') and (state.get('pending') or {}).get('question') == text:
        state['pending']['offered'] = True  # offered/attempted, never proof the owner read or heard it
        state['pending']['offered_at'] = time.time()
        _save(state)


def summary() -> str:
    state = load()
    if not state.get("on", True):
        return "Free will is off — I only talk when you talk to me."
    beliefs = state.get("beliefs", {})
    if not beliefs:
        return "Free will is on; I'm still learning when you're happy to chat."
    names = {"start": "I've just come online", "back": "you've just come back", "followup": "something you had planned just happened", "long": "you've been on one thing for ages",
             "notice_new": "I spot something new", "notice_returned": "you're back on something old",
             "notice_odd_hour": "you're on something at an odd hour", "notice_jump": "you drop work for a break",
             "notice_restless": "you can't settle", "notice_dropped": "you've left something hanging",
             "notice_skipped": "a regular of yours is missing", "notice_learned": "I've just learned what something is",
             "notice_unknown": "I can't place something", "notice_prediction": "I have a guess at your next move",
             "notice_automate": "I'd like to take something over", "evening": "it's time for my end-of-day questions",
             "study": "you're studying", "deadline": "a deadline is close", "late": "it's late", "gaming": "you're gaming",
             "coding": "you're coding", "chill": "you're chilling"}
    good = [names.get(w, w) for w in beliefs if welcome(w, state) >= 0.55]
    bad = [names.get(w, w) for w in beliefs if welcome(w, state) < 0.35]
    parts = ([f"you're happy to chat when {', '.join(good)}"] if good else []) + \
            ([f"I stay quiet when {', '.join(bad)}"] if bad else [])
    return "Talking on my own: " + ("; ".join(parts) if parts else "still working out when you like it") + "."
