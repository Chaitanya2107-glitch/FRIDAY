"""
services/mind/thoughts.py

What's on FRIDAY's mind: the things she noticed and wonders about (services/mind/brain.py makes them).
A thought is raw data — what she saw, the numbers behind it, her own guess at the reason — never a
finished sentence. It starts with a strength (how surprising it was) that halves every HALF_LIFE_MINUTES,
so her mind moves on; the strongest one still alive is what she'd say next (services/mind/talk.py),
what "what's on your mind" shows, and a "?" over her body.

The same thing isn't wondered about twice within REPEAT_HOURS. When the Boss answers a thought, the
answer is kept as the reason for that pattern (reasons): next time she already knows why, and says so.

State: the thoughts and reasons tables of memory/mind/brain.db (services/mind/knowledge.py).
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from services.mind import knowledge

HALF_LIFE_MINUTES = 45
ALIVE_HOURS = 3
REPEAT_HOURS = 20
WORTH_SAYING = 0.3       # weaker than this, she keeps it to herself
KEEP_DAYS = 60


@dataclass
class Thought:
    id: int
    at: datetime
    kind: str            # new, returned, odd_hour, jump, restless, dropped, skipped, learned, unknown
    subject: str         # what it's about: a thing's key, or a pattern like "study>gaming"
    data: dict           # the raw facts, as she'd hand them to the model to word
    strength: float

    def now_strength(self, now: datetime) -> float:
        return self.strength * 0.5 ** (max(0.0, (now - self.at).total_seconds()) / 60 / HALF_LIFE_MINUTES)


def _thought(row) -> Thought:
    return Thought(row["id"], datetime.fromisoformat(row["at"]), row["kind"], row["subject"],
                   json.loads(row["data"]), row["strength"])


def add(kind: str, subject: str, data: dict, strength: float, now: datetime) -> int | None:
    """A new thought, unless she already had it recently. Returns its id."""
    with knowledge.db() as conn:
        again = conn.execute("SELECT 1 FROM thoughts WHERE kind = ? AND subject = ? AND at >= ?",
                             (kind, subject, (now - timedelta(hours=REPEAT_HOURS)).isoformat())).fetchone()
        if again:
            return None
        return conn.execute("INSERT INTO thoughts (at, kind, subject, data, strength) VALUES (?, ?, ?, ?, ?)",
                            (now.isoformat(timespec="seconds"), kind, subject, json.dumps(data, ensure_ascii=False),
                             strength)).lastrowid


def alive(now: datetime) -> list[Thought]:
    """Unsaid thoughts still on her mind, strongest first."""
    with knowledge.db() as conn:
        rows = conn.execute("SELECT * FROM thoughts WHERE state = 'new' AND at >= ? AND at <= ?",
                            ((now - timedelta(hours=ALIVE_HOURS)).isoformat(), now.isoformat())).fetchall()
    return sorted((_thought(r) for r in rows), key=lambda t: -t.now_strength(now))


def unsaid_on(day: str | None) -> list[Thought]:
    """Everything she noticed that day and never got to say, most surprising first — for her evening questions
    (services/mind/evening.py). None includes all stored days for the training inbox.
    Thoughts that only report ("learned") aren't questions."""
    with knowledge.db() as conn:
        rows = conn.execute("SELECT * FROM thoughts WHERE state = 'new' AND kind != 'learned' AND at LIKE ? "
                            "ORDER BY strength DESC, at DESC", ((day + "%") if day else "%",)).fetchall()
    return [_thought(r) for r in rows]


def top(now: datetime) -> Thought | None:
    """The one she'd say next, if any is still worth saying."""
    live = alive(now)
    return live[0] if live and live[0].now_strength(now) >= WORTH_SAYING else None


def get(thought_id: int) -> Thought | None:
    with knowledge.db() as conn:
        row = conn.execute("SELECT * FROM thoughts WHERE id = ?", (thought_id,)).fetchone()
    return _thought(row) if row else None


def mark_said(thought_id: int) -> None:
    with knowledge.db() as conn:
        conn.execute("UPDATE thoughts SET state = 'said' WHERE id = ?", (thought_id,))


def answered(thought_id: int, answer: str, now: datetime) -> Thought | None:
    """The Boss answered it: kept with the thought, and as the reason for its pattern."""
    thought = get(thought_id)
    if not thought:
        return None
    with knowledge.db() as conn:
        conn.execute("UPDATE thoughts SET state = 'answered', answer = ? WHERE id = ?", (answer, thought_id))
        if pattern := thought.data.get("pattern"):
            conn.execute("INSERT OR REPLACE INTO reasons (pattern, reason, at) VALUES (?, ?, ?)",
                         (pattern, answer.strip()[:300], now.isoformat(timespec="seconds")))
    return thought


def reason_for(pattern: str) -> str | None:
    """What the Boss said the last time she asked about this pattern."""
    from services.mind.training import teaching_for
    if reviewed := teaching_for("pattern", pattern):
        return reviewed
    with knowledge.db() as conn:
        row = conn.execute("SELECT reason FROM reasons WHERE pattern = ?", (pattern,)).fetchone()
    return row["reason"] if row else None


def counts_on(day: str) -> dict[str, int]:
    """How many thoughts she had that day, and what became of them: {"noticed", "said", "answered"}."""
    with knowledge.db() as conn:
        rows = dict(conn.execute("SELECT state, COUNT(*) FROM thoughts WHERE at LIKE ? GROUP BY state", (day + "%",)).fetchall())
    return {"noticed": sum(rows.values()), "said": rows.get("said", 0) + rows.get("answered", 0),
            "answered": rows.get("answered", 0)}


def forget_old(now: datetime) -> None:
    with knowledge.db() as conn:
        conn.execute("DELETE FROM thoughts WHERE at < ?", ((now - timedelta(days=KEEP_DAYS)).isoformat(),))
