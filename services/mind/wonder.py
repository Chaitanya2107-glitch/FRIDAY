"""
services/mind/wonder.py

What FRIDAY wants to know about the Boss — her list of open questions. The nightly reflection
(reflection.py) adds up to 5 new ones from what it noticed (likes, habits, the reasons behind
patterns, people, goals, opinions); before that, and whenever the list runs dry, a starter set of
get-to-know-you questions fills in. talk.py asks one when the moment fits (not while studying or near a
deadline) or when the Boss says "ask me something"; an asked question comes off the
list, and the answer is learned together with the question (services/memory/semantic.py).

Custom/legacy questions: memory/mind/wonder.json. New asked/answered state is stored in
the personal_questions table of the shared review database, so the trainer and FRIDAY can write concurrently.
In assist-only mode, unanswered questions retry after a cooldown and applied teachings settle known questions.
"""

import json
import time
import sqlite3

from core.config import config

path = config.MEMORY_DIR / "mind" / "wonder.json"  # tests point this elsewhere
MAX_ASKED = 300
FITS = {"chill", "back", "long", "coding", "gaming", "late", "asked"}  # a get-to-know-you question fits (not mid-study)

SEEDS = [
    "What do you want to be doing after college?",
    "What kind of music do you actually like, beyond what's on repeat?",
    "What's your favourite food?",
    "Who are your closest friends?",
    "What do you do to relax when you're not gaming?",
    "Which subject do you secretly enjoy, and which one do you dread?",
    "What got you into AI and machine learning?",
    "What's catjang, and what do you want it to become?",
    "When do you feel you study best — mornings or late at night?",
    "What games are you into right now, and why those?",
    "What's something you've been meaning to learn?",
    "What stresses you out the most these days?",
    "What's a perfect day for you?",
    "Is there something you'd like me to remind you about or keep an eye on?",
    "What would you want me to get better at?",
    "Which editor do you prefer for coding?",
    "Which project matters most to you right now?",
    "What is your usual weekday routine?",
    "What time do you prefer to start studying?",
    "How do you like to organise your notes?",
    "What makes a reminder useful to you?",
    "When should I avoid interrupting you?",
    "How often would you like break reminders?",
    "Which apps do you use for college work?",
    "Which folders hold your important projects?",
    "What would make it easier to resume your work?",
    "Which tasks do you repeat every week?",
    "What is your preferred way to review your day?",
    "Which upcoming deadline matters most?",
    "What skill are you practising this month?",
    "How do you decide that a study session went well?",
    "What usually distracts you while working?",
    "What helps you return to a task after a break?",
    "What type of music helps you concentrate?",
    "Which reminders should stay silent?",
    "What do you want to spend less time on?",
    "What do you want to make more time for?",
    "How should I address you?",
    "Would you prefer short replies or detailed explanations?",
    "What is one thing about your work I still misunderstand?",
]


def load() -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def _same(a: str, b: str) -> bool:
    return a.strip().lower().rstrip("?.! ") == b.strip().lower().rstrip("?.! ")


def next_questions(n: int | None = 3, now: float | None = None, *, unasked_only: bool = False) -> list[str]:
    """Her own questions first, then starters; n=None returns every eligible question."""
    state = load()
    asked = state.get("asked", [])
    now = time.time() if now is None else now
    answered = state.get("answers", {})
    asked_at = state.get("asked_at", {})
    from services.mind.lessons import key, owner_question, reply
    from services.mind.training import reviews
    # One snapshot per selection. Only applied teaching (not merely preferred wording) settles a question.
    try:
        known = [{**row, "preferred": ""} for row in reviews.active_lessons() if row["teaching"]]
        saved = reviews.question_states()
        asked_at.update({k: v["asked_at"] for k, v in saved.items()})
        asked += [v["question"] for v in saved.values() if v["asked_at"]]
        answered.update({k: v for k, v in saved.items() if v["answer"]})
    except (OSError, sqlite3.Error, ValueError):
        known = []
    fresh, seen = [], set()
    for question in state.get("questions", []) + SEEDS:
        identity = key(question)
        if identity in seen:
            continue
        seen.add(identity)
        if identity in answered or reply(known, owner_question(question)):
            continue
        if any(_same(question, a) for a in asked):
            if unasked_only or not config.AI_ASSIST_ONLY:
                continue
            if now - asked_at.get(identity, 0) < max(1, config.QUESTION_RETRY_HOURS) * 3600:
                continue
        fresh.append(question)
    return fresh[:n]


def add(questions: list[str]) -> int:
    """New questions from the nightly reflection (newest first). Returns how many were new."""
    state = load()
    from services.mind.training import reviews
    known = state.get("questions", []) + state.get("asked", []) + [v["question"] for v in reviews.question_states().values()]
    new = [q.strip() for q in questions if q.strip() and not any(_same(q, k) for k in known)]
    state["questions"] = new + state.get("questions", [])
    _save(state)
    return len(new)


def mark_asked(question: str, now: float | None = None) -> None:
    from services.mind.training import reviews
    reviews.note_question(question, at=now)


def mark_answered(question: str, answer: str) -> None:
    from services.mind.training import reviews
    reviews.note_question(question, answer=answer)


def answer_for(question: str) -> str | None:
    from services.mind.lessons import key
    from services.mind.training import reviews
    return reviews.question_states().get(key(question), {}).get("answer") or load().get("answers", {}).get(key(question), {}).get("answer")


def summary() -> str:
    wondering = next_questions()
    return ("Things I'd like to know about you: " + " / ".join(wondering)) if wondering else ""
