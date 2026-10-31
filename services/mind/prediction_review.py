"""Owner verification of saved predictions; no lessons, provider calls or action grants."""
import json
import re
from collections import Counter
from datetime import datetime

from core.logger import logger
from services.mind import knowledge
from services.mind.reviews import redact


def _row(row):
    if row is None:
        raise ValueError("Saved prediction does not exist")
    result = dict(row)
    result["data"] = json.loads(result["data"])
    return result


def queue(state: str = "pending", limit: int = 10000) -> list[dict]:
    if state not in {"pending", "verified", "all"}:
        raise ValueError("Choose pending, verified or all")
    with knowledge.db() as conn:
        rows = conn.execute(
            "SELECT t.*, r.verdict, r.actual_app, r.notes, r.verified_at FROM thoughts t "
            "LEFT JOIN prediction_reviews r ON r.thought_id=t.id WHERE t.kind='prediction' "
            "AND (?='all' OR (?='pending' AND t.state!='answered' AND r.thought_id IS NULL) "
            "OR (?='verified' AND (r.thought_id IS NOT NULL OR t.state='answered'))) "
            "ORDER BY t.at DESC, t.id DESC LIMIT ?", (state, state, state, limit)).fetchall()
    return [_row(row) for row in rows]


def get(item: int) -> dict:
    with knowledge.db() as conn:
        return _row(conn.execute(
            "SELECT t.*, r.verdict, r.actual_app, r.notes, r.verified_at FROM thoughts t "
            "LEFT JOIN prediction_reviews r ON r.thought_id=t.id WHERE t.id=? AND t.kind='prediction'",
            (item,)).fetchone())


def _context(data):
    context = data.get("context")
    if not isinstance(context, dict) or not all(isinstance(context.get(k), str) and context[k]
                                              for k in ("pattern", "thing", "at")):
        raise ValueError("Prediction has no usable saved context")
    when = datetime.fromisoformat(context["at"])
    if when.tzinfo is not None:
        raise ValueError("Prediction time must use local time")
    if not context["thing"].startswith(("app:", "site:", "project:")):
        raise ValueError("Prediction target is unsupported")
    return context


def record(conn, context, right, now):
    """Shared transaction helper for prediction counts and existing nightly labels."""
    from services.mind.foresight import _pattern

    key, thing = context["pattern"], context["thing"]
    _pattern(conn, key, context.get("frm") or "time", thing)
    conn.execute("UPDATE foresight_patterns SET yes=yes+?, no=no+? WHERE pattern=?",
                 (int(right), int(not right), key))
    if thing.startswith("app:") and context.get("frm"):
        conn.execute("INSERT INTO foresight_labels (at,frm,before,nxt,right,recorded_at) VALUES (?,?,?,?,?,?)",
                     (context["at"], context["frm"], context.get("before"), thing[4:], int(right),
                      now.isoformat(timespec="seconds")))


def verdict(answer: str) -> str:
    from services.mind.foresight import _NO, _YES

    if re.search(r"\b(?:unsure|uncertain|maybe|perhaps|not sure|don't know|do not know|can't tell|cannot tell)\b", answer, re.I):
        return "unsure"
    return "wrong" if _NO.search(answer) else "correct" if _YES.search(answer) else "unsure"


def verify(item: int, verdict: str, *, actual_app: str = "", notes: str = "", now: datetime | None = None) -> bool:
    from services.activity.habit_patterns import APP_NAMES, APP_OPEN_AS

    if verdict not in {"correct", "wrong", "unsure"}:
        raise ValueError("Choose correct, wrong or unsure")
    actual_app = actual_app.strip().lower().removesuffix(".exe")
    aliases = {name.lower(): app for app, name in {**APP_NAMES, **APP_OPEN_AS}.items()}
    actual_app = aliases.get(actual_app, actual_app)
    if actual_app and (verdict != "wrong" or not re.fullmatch(r"[\w.+\-]{1,80}", actual_app)):
        raise ValueError("An actual app requires a wrong verdict and a process name such as spotify or code")
    if len(notes) > 1000:
        raise ValueError("Keep notes within 1000 characters")
    now = now or datetime.now()
    with knowledge.db() as conn:
        # Serialize across the live app and review processes before reading approval state.
        conn.execute("BEGIN IMMEDIATE")
        row = _row(conn.execute("SELECT * FROM thoughts WHERE id=? AND kind='prediction'", (item,)).fetchone())
        context = _context(row["data"])
        if row["state"] == "answered" or conn.execute(
                "SELECT 1 FROM prediction_reviews WHERE thought_id=?", (item,)).fetchone():
            raise ValueError("This prediction was already verified")
        if actual_app and (not context.get("frm") or not context["thing"].startswith("app:")
                           or actual_app in {context["thing"][4:], context["frm"]}):
            raise ValueError("The actual app must differ from both the predicted app and source app")
        if verdict == "unsure":
            return False
        conn.execute("INSERT INTO prediction_reviews VALUES (?,?,?,?,?)",
                     (item, verdict, actual_app, redact(notes.strip()), now.isoformat(timespec="seconds")))
        record(conn, context, verdict == "correct", now)
        if actual_app:
            record(conn, {**context, "pattern": f"{context['frm']}>{actual_app}", "thing": f"app:{actual_app}"}, True, now)
        conn.execute("UPDATE thoughts SET state='answered', answer=? WHERE id=?",
                     (f"{verdict}: {actual_app}" if actual_app else verdict, item))
    logger.debug("Prediction %s verified %s; correction=%s", item, verdict, bool(actual_app))
    return True


def rank(guesses: list[str], app: str, before: str | None, when: datetime) -> list[str]:
    """Use owner verdicts for this source app, previous app, hour and day type."""
    guesses = list(dict.fromkeys(guesses))
    with knowledge.db() as conn:
        rows = conn.execute("SELECT at,nxt,right,recorded_at FROM foresight_labels WHERE frm=? AND before IS ? "
                            "ORDER BY rowid DESC LIMIT 10000", (app, before)).fetchall()
    yes, no = Counter(), Counter()
    for row in rows:
        try:
            at = datetime.fromisoformat(row["at"])
            available = datetime.fromisoformat(row["recorded_at"])
            eligible = available <= when and at <= when and at.hour == when.hour and (at.weekday() >= 5) == (when.weekday() >= 5)
        except (TypeError, ValueError):
            continue
        if not eligible:
            continue
        (yes if row["right"] else no)[row["nxt"]] += 1
    # Include explicit corrections even before they accumulate observed switch counts.
    guesses.extend(nxt for nxt in yes if nxt not in guesses and nxt != app)
    return sorted(guesses, key=lambda nxt: -(yes[nxt] + 1) / (yes[nxt] + no[nxt] + 2))
