"""Owner-reviewed training data, independent of the live question/pending state.

The app appends evidence; only the separate review CLI can approve/apply it.
No network calls or model weight updates happen here. SQLite permits the CLI
and FRIDAY's processes to use the same queue without rewriting each other's data.
"""
from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from core.config import config
from core.logger import logger
from services.mind.cognition import redact

PRIVATE_KEYS = {"clipboard", "password", "passwords", "token", "secret", "typed_text", "notes", "diary"}


def nudge_key(title, text):
    """Known changing sensor readings share a type; unrelated notices retain their identity."""
    lowered = text.lower()
    for prefix, kind in (("eye break:", "eye_break"), ("your gpu has", "gpu"),
                         ("memory is", "memory"), ("drive c is", "disk")):
        if lowered.startswith(prefix):
            return kind
    if lowered.startswith("battery is at"):
        return "battery_critical" if "plug in now" in lowered else "battery"
    template = re.sub(r"(for )\d+( hours straight)", r"\1#\2", lowered)
    return hashlib.sha256((title.lower() + "\n" + " ".join(template.split())).encode()).hexdigest()


def _clean(value):
    if isinstance(value, dict):
        return {str(k): "[excluded]" if str(k).lower() in PRIVATE_KEYS else _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return redact(value)
    return value


class ReviewStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=1)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, kind TEXT NOT NULL,
                channel TEXT NOT NULL, question TEXT NOT NULL, context TEXT NOT NULL,
                pattern TEXT NOT NULL, subject TEXT NOT NULL, delivery TEXT NOT NULL DEFAULT 'prepared',
                live_answer TEXT NOT NULL DEFAULT '', reaction TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL DEFAULT '', teaching TEXT NOT NULL DEFAULT '',
                preferred TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'pending', exportable INTEGER NOT NULL DEFAULT 0,
                reviewed_at REAL, trained_at REAL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS nudge_preferences (
                key TEXT PRIMARY KEY, rating TEXT NOT NULL, minutes INTEGER NOT NULL,
                until REAL NOT NULL DEFAULT 0, last_sent REAL NOT NULL DEFAULT 0,
                review_id INTEGER NOT NULL, updated_at REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS personal_questions (
                key TEXT PRIMARY KEY, question TEXT NOT NULL, asked_at REAL NOT NULL DEFAULT 0,
                answer TEXT NOT NULL DEFAULT '', answered_at REAL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS review_lessons ON reviews(state,trained_at,id)")
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(row):
        if row is None:
            raise ValueError("Review item does not exist")
        result = dict(row)
        result["context"] = json.loads(result["context"])
        return result

    def capture(self, kind: str, question: str, context: dict, *, channel="proactive", at=None) -> int:
        if kind not in {"question", "nudge", "example"}:
            raise ValueError("Unknown review kind")
        context = _clean(context)
        with self.db() as conn:
            item = conn.execute(
                "INSERT INTO reviews (at, kind, channel, question, context, pattern, subject) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (at if at is not None else time.time(), kind, channel, redact(question),
                 json.dumps(context, ensure_ascii=False), str(context.get("pattern") or ""),
                 str(context.get("subject") or ""))).lastrowid
        logger.debug("Training review captured item %s (%s)", item, kind)
        return item

    def get(self, item: int) -> dict:
        with self.db() as conn:
            return self._row(conn.execute("SELECT * FROM reviews WHERE id = ?", (item,)).fetchone())

    def list(self, state="pending", limit=100) -> list[dict]:
        if state not in {"pending", "approved", "trained", "rejected", "all"}:
            raise ValueError("Unknown review state")
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE (? = 'all' OR state = ?) ORDER BY id LIMIT ?",
                                (state, state, max(1, min(limit, 10000)))).fetchall()
        return [self._row(row) for row in rows]

    def answer(self, item: int | None, text: str, reaction: str):
        if item is not None:
            with self.db() as conn:
                conn.execute("UPDATE reviews SET live_answer = ?, reaction = ? WHERE id = ?",
                             (redact(text), reaction, item))

    def delivered(self, item: int | None, status: str):
        if item is not None:
            with self.db() as conn:
                conn.execute("UPDATE reviews SET delivery = ? WHERE id = ?", (status, item))

    def review(self, item: int, *, answer="", teaching="", preferred="", notes="", approve=False, exportable=False):
        fields = [redact(s.strip()) for s in (answer, teaching, preferred, notes)]
        if approve and not (fields[1] or fields[2]):
            raise ValueError("Approval needs a teaching statement or preferred FRIDAY response")
        if len(fields[1]) > 1000 or len(fields[2]) > 1000:
            raise ValueError("Keep each teaching statement/preferred response within 1000 characters")
        with self.db() as conn:
            self._row(conn.execute("SELECT * FROM reviews WHERE id = ?", (item,)).fetchone())
            conn.execute("""UPDATE reviews SET answer = ?, teaching = ?, preferred = ?, notes = ?,
                state = ?, exportable = ?, reviewed_at = ?, trained_at = NULL WHERE id = ?""",
                         (*fields, "approved" if approve else "pending", int(approve and exportable), time.time(), item))
        logger.debug("Training review updated item %s: %s", item, "approved" if approve else "pending")

    def reject(self, item: int):
        with self.db() as conn:
            self._row(conn.execute("SELECT * FROM reviews WHERE id = ?", (item,)).fetchone())
            conn.execute("UPDATE reviews SET state = 'rejected', exportable = 0, trained_at = NULL WHERE id = ?", (item,))

    def train(self, item: int):
        with self.db() as conn:
            # The write predicate also protects against another process revoking approval.
            changed = conn.execute("UPDATE reviews SET state = 'trained', trained_at = COALESCE(trained_at, ?) "
                                   "WHERE id = ? AND state IN ('approved', 'trained')", (time.time(), item)).rowcount
            if not changed:
                raise ValueError("Only approved examples can be trained")
        logger.debug("Training review applied item %s", item)

    def learned(self, limit=20) -> list[dict]:
        if not self.path.exists():
            return []
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE state = 'trained' ORDER BY trained_at DESC, id DESC LIMIT ?",
                                (max(1, min(limit, 10000)),)).fetchall()
        return [self._row(row) for row in rows]

    def local_reply(self, query: str) -> str | None:
        from services.mind.lessons import reply
        return reply(self.active_lessons(), query)

    def active_lessons(self):
        if not self.path.exists():
            return []
        with self.db() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,kind,question,teaching,preferred,subject,pattern,trained_at FROM reviews "
                "WHERE state='trained' ORDER BY trained_at DESC,id DESC LIMIT 10000")]

    def facts(self) -> list[tuple[int, str]]:
        """Reviewed text stays in its source record, so revoke/edit takes effect immediately."""
        seen, result = set(), []
        for row in self.active_lessons():
            if row["teaching"] and row["teaching"] not in seen:
                seen.add(row["teaching"])
                result.append((row["id"], row["teaching"]))
        return result

    def queue(self, state="pending", *, kind="all", grouped=False, limit=100) -> list[dict]:
        if kind not in {"learning", "all", "question", "nudge", "example"}:
            raise ValueError("Unknown review kind")
        if state not in {"pending", "approved", "trained", "rejected", "all"}:
            raise ValueError("Unknown review state")
        with self.db() as conn:
            rows = [self._row(row) for row in conn.execute(
                "SELECT * FROM reviews WHERE (?='all' OR state=?) AND (?='all' OR kind=? OR (?='learning' AND kind != 'nudge')) ORDER BY id DESC LIMIT 10000",
                (state, state, kind, kind, kind))]
        if grouped:
            groups = {}
            # ponytail: grouping the latest 10k captures; index a stored type key if this queue grows larger.
            for row in reversed(rows):
                identity = ("nudge", nudge_key(row["context"].get("title", ""), row["question"])) if row["kind"] == "nudge" else (row["kind"], row["id"])
                prior = groups.get(identity)
                row["count"] = 1 + (prior["count"] if prior else 0)
                row["first_at"] = prior["first_at"] if prior else row["at"]
                groups[identity] = row  # retain most recent capture as the review target
            rows = list(groups.values())
        return sorted(rows, key=lambda r: (r["kind"] == "nudge", not bool(r["live_answer"]), -r["at"], -r["id"]))[:max(1, min(limit, 10000))]

    def feedback(self, item, rating, minutes=60, now=None):
        if rating not in {"useful", "badly_timed", "too_frequent", "incorrect"}:
            raise ValueError("Choose useful, badly_timed, too_frequent or incorrect")
        if not isinstance(minutes, int) or not 1 <= minutes <= 10080:
            raise ValueError("Feedback duration must be 1–10080 minutes")
        now = time.time() if now is None else now
        with self.db() as conn:
            row = self._row(conn.execute("SELECT * FROM reviews WHERE id=?", (item,)).fetchone())
            if row["kind"] != "nudge":
                raise ValueError("Delivery feedback applies only to nudges")
            identity = nudge_key(row["context"].get("title", ""), row["question"])
            previous = conn.execute("SELECT last_sent FROM nudge_preferences WHERE key=?", (identity,)).fetchone()
            last_sent = max(previous[0] if previous else 0, row["at"] if row["delivery"] == "submitted" else 0)
            conn.execute("""INSERT INTO nudge_preferences (key,rating,minutes,until,last_sent,review_id,updated_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET rating=excluded.rating,
                minutes=excluded.minutes,until=excluded.until,last_sent=excluded.last_sent,
                review_id=excluded.review_id,updated_at=excluded.updated_at""",
                (identity, rating, minutes, now + minutes * 60 if rating == "badly_timed" else 0, last_sent, item, now))
        logger.debug("Nudge feedback applied to review %s: %s", item, rating)
        return {"useful": "Normal delivery restored.", "badly_timed": f"This nudge type is snoozed for {minutes} minutes.",
                "too_frequent": f"This nudge type has a {minutes}-minute minimum interval.",
                "incorrect": "This nudge type is disabled until you mark it useful."}[rating]

    def allows_nudge(self, title, text, *, now=None, urgent=False):
        if urgent or not self.path.exists():
            return True
        now = time.time() if now is None else now
        with self.db() as conn:
            row = conn.execute("SELECT * FROM nudge_preferences WHERE key=?", (nudge_key(title, text),)).fetchone()
        if not row:
            return True
        return (row["rating"] != "incorrect" and now >= row["until"] and
                (row["rating"] != "too_frequent" or now - row["last_sent"] >= row["minutes"] * 60))

    def nudge_sent(self, title, text, now=None):
        if self.path.exists():
            with self.db() as conn:
                conn.execute("UPDATE nudge_preferences SET last_sent=? WHERE key=?",
                             (time.time() if now is None else now, nudge_key(title, text)))

    def question_states(self):
        if not self.path.exists():
            return {}
        with self.db() as conn:
            return {row["key"]: dict(row) for row in conn.execute("SELECT * FROM personal_questions")}

    def note_question(self, question, *, answer=None, at=None):
        """SQLite serializes the interview CLI and FRIDAY's live question tracking."""
        from services.mind.lessons import key
        stamp = time.time() if at is None else at
        with self.db() as conn:
            if answer is None:
                conn.execute("INSERT INTO personal_questions(key,question,asked_at) VALUES(?,?,?) "
                             "ON CONFLICT(key) DO UPDATE SET asked_at=excluded.asked_at", (key(question), question, stamp))
            elif answer.strip():
                conn.execute("INSERT INTO personal_questions(key,question,answer,answered_at) VALUES(?,?,?,?) "
                             "ON CONFLICT(key) DO UPDATE SET answer=excluded.answer,answered_at=excluded.answered_at",
                             (key(question), question, redact(answer.strip())[:1000], stamp))

    def forget_facts(self, description=None):
        from services.mind.lessons import keywords, personal_question
        terms = keywords(description) if description else set()
        items = [row for row in self.active_lessons() if
                 (row["teaching"] or personal_question(row["question"])) and
                 (description is None or (terms and terms <= keywords(row["teaching"])))]
        with self.db() as conn:
            for row in items:
                conn.execute("UPDATE reviews SET state='pending',exportable=0,trained_at=NULL WHERE id=?", (row["id"],))
            if description is None:
                conn.execute("UPDATE personal_questions SET answer='',answered_at=NULL")
        return [row["teaching"] or row["question"] for row in items]

    def effect(self, item: int) -> str:
        row = self.get(item)
        if row["state"] != "trained":
            return "Not applied; no active lesson."
        effects = []
        if row["teaching"]:
            effects.append("searchable reviewed memory")
            if row["subject"]:
                effects.append("app/topic explanation")
            if row["pattern"]:
                effects.append("activity-pattern explanation")
        if row["preferred"] and row["kind"] != "nudge":
            effects.append("exact local answer to the reviewed question")
        return "Applied: " + ", ".join(effects) + "." if effects else "Applied; no local reply target. Use nudge feedback to change delivery."

    def teaching_for(self, column: str, value: str) -> str | None:
        if column not in {"pattern", "subject"}:
            raise ValueError("Unknown lesson target")
        if not value or not self.path.exists():
            return None
        with self.db() as conn:
            row = conn.execute(f"SELECT teaching FROM reviews WHERE {column} = ? AND state = 'trained' "
                               "AND teaching != '' ORDER BY trained_at DESC, id DESC LIMIT 1", (value,)).fetchone()
        return row["teaching"] if row else None

    def export(self, target: Path) -> int:
        """Export opted-in reviewed text only; never raw activity or unreviewed live answers."""
        target = Path(target)
        if target.exists():
            raise FileExistsError("Choose a new dataset path; existing files are never overwritten")
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE state IN ('approved', 'trained') "
                                "AND exportable = 1 ORDER BY id").fetchall()
        if not rows:
            return 0
        records = []
        for raw in rows:
            row = self._row(raw)
            if row["kind"] == "example":
                prompt, response = row["question"], row["preferred"] or row["teaching"]
            elif row["preferred"]:
                prompt = "Give a preferred FRIDAY response for this previous question or nudge: " + row["question"]
                response = row["preferred"]
            else:
                prompt = "What did I teach you when you asked: " + row["question"]
                response = row["teaching"]
            records.append({"messages": [{"role": "user", "content": redact(prompt)},
                                         {"role": "assistant", "content": redact(response)}],
                            "metadata": {"review_id": row["id"], "kind": row["kind"], "reviewed_at": row["reviewed_at"]}})
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as output:
            output.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
        return len(records)


reviews = ReviewStore(config.MEMORY_DIR / "training" / "reviews.db")


def capture(kind: str, text: str, context: dict, **kwargs) -> int | None:
    """Best effort evidence collection: unavailable storage cannot silence FRIDAY."""
    try:
        return reviews.capture(kind, text, context, **kwargs)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Training review capture unavailable: %s", type(error).__name__)
        return None


def evidence(item: int | None, *, text="", reaction="", delivery=""):
    try:
        if delivery:
            reviews.delivered(item, delivery)
        else:
            reviews.answer(item, text, reaction)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Training review evidence unavailable: %s", type(error).__name__)
