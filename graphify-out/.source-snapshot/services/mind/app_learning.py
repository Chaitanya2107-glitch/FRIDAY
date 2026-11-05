"""Model explanations are proposals. Only the owner can confirm app knowledge."""

import hashlib
import json
import re
import uuid
from datetime import datetime


def initialize(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS thing_revisions (key TEXT PRIMARY KEY, token TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_explanations (
            token TEXT PRIMARY KEY, key TEXT NOT NULL, revision TEXT NOT NULL,
            description TEXT NOT NULL, category TEXT NOT NULL, provider TEXT NOT NULL,
            proposed_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS app_explanation_key ON app_explanations(key, state);
    """)
    # Keep old model output and all usage history, but withdraw its former factual status.
    for row in conn.execute("SELECT * FROM things WHERE source='lookup'").fetchall():
        revision = uuid.uuid4().hex
        conn.execute("INSERT OR REPLACE INTO thing_revisions VALUES (?,?)", (row["key"], revision))
        conn.execute("INSERT INTO app_explanations VALUES (?,?,?,?,?,?,?,'pending',NULL)",
                     (uuid.uuid4().hex, row["key"], revision, row["about"] or "", row["category"],
                      "legacy model lookup", row["looked_up"] or row["last_seen"]))
        conn.execute("UPDATE things SET about=NULL,source='rule',category=? WHERE key=?",
                     ("other" if row["kind"] == "app" else "browsing", row["key"]))
    conn.commit()


def revision(conn, key):
    row = conn.execute("SELECT token FROM thing_revisions WHERE key=?", (key,)).fetchone()
    if row:
        return row[0]
    token = uuid.uuid4().hex
    conn.execute("INSERT INTO thing_revisions VALUES (?,?)", (key, token))
    return token


def supersede(conn, key):
    conn.execute("UPDATE app_explanations SET state='superseded' WHERE key=? AND state='pending'", (key,))
    conn.execute("INSERT OR REPLACE INTO thing_revisions VALUES (?,?)", (key, uuid.uuid4().hex))


def stage(conn, key, expected, description, category, provider, now):
    row = conn.execute("SELECT * FROM things WHERE key=?", (key,)).fetchone()
    if not row or row["source"] in {"boss", "confirmed"} or revision(conn, key) != expected:
        return False
    conn.execute("UPDATE app_explanations SET state='superseded' WHERE key=? AND state='pending'", (key,))
    conn.execute("INSERT INTO app_explanations VALUES (?,?,?,?,?,?,?,'pending',NULL)",
                 (uuid.uuid4().hex, key, expected, description[:300], category, provider,
                  now.isoformat(timespec="seconds")))
    conn.execute("UPDATE things SET looked_up=? WHERE key=?", (now.isoformat(timespec="seconds"), key))
    return True


def pending(key=None):
    from services.mind import knowledge
    with knowledge.db() as conn:
        rows = conn.execute(
            "SELECT p.*,t.name,t.kind FROM app_explanations p JOIN things t ON t.key=p.key "
            "JOIN thing_revisions r ON r.key=p.key AND r.token=p.revision "
            "WHERE p.state='pending' AND t.about IS NULL AND (? IS NULL OR p.key=?) "
            "ORDER BY p.proposed_at DESC LIMIT 8", (key, key)).fetchall()
    from services.mind.training import teaching_for
    return [dict(row) for row in rows if not teaching_for("subject", row["key"])]


def evidence():
    return {"app-explanation:" + row["token"]: {**row, "kind": "app_verification"} for row in pending()
            if row["kind"] == "app"}


def identity(row):
    return {name: row[name] for name in ("token", "key", "revision")}


def current(offer):
    return next((row for row in pending(offer.get("key")) if identity(row) == offer), None)


def question(row):
    name = row["name"]
    if row["description"]:
        # Fixed wording binds approval to the actual stored candidate, not a model paraphrase.
        description = " ".join(row["description"].split()).replace("?", ".")
        return f'The model suggests {name} is: "{description}" (category: {row["category"]}). Is that right?'
    return f"I tried asking the model about {name}, but couldn't identify it reliably. What is this app for?"


def resolve(offer, answer, now=None):
    """Consume the exact current candidate once. Ambiguous replies never teach."""
    from services.mind import knowledge
    from services.mind.training import teaching_for
    if teaching_for("subject", offer.get("key", "")):
        return "stale"
    now = now or datetime.now()
    answer = answer.replace("\u2019", "'")
    normal = " ".join(re.sub(r"[,!.]", " ", answer.strip().lower()).split()).removeprefix("actually ")
    yes = normal in {"yes", "yep", "yeah", "correct", "right", "that's right", "that is right", "yes that's right",
                     "yes correct", "yes that is right", "yeah that's right"}
    no = normal in {"no", "nope", "incorrect", "wrong", "that's wrong", "that is wrong"}
    no = no or bool(re.fullmatch(r"(?:no )?(?:that's|that is|it's|it is) "
                                r"(?:wrong|incorrect|not right|not correct|not that app)", normal))
    correction = (re.match(r"^(?:actually[, ]+|(?:no[, ]+)?(?:it's |it is |this app is ))(.{4,300})$",
                           answer.strip(), re.I)
                  or re.match(r"^no[, ]+(an? .{4,300})$", answer.strip(), re.I))
    no = no or (bool(re.match(r"^no\b", normal)) and correction is None)
    with knowledge.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT p.*,t.source,t.about FROM app_explanations p JOIN things t ON t.key=p.key "
                           "JOIN thing_revisions r ON r.key=p.key AND r.token=p.revision "
                           "WHERE p.token=? AND p.key=? AND p.revision=? AND p.state='pending'",
                           (offer.get("token"), offer.get("key"), offer.get("revision"))).fetchone()
        if not row or row["about"] or row["source"] in {"boss", "confirmed"}:
            return "stale"
        if uncertain(answer):
            return "uncertain"
        text = None
        if yes and row["description"]:
            text, source, state, category = row["description"], "confirmed", "confirmed", row["category"]
        elif no:
            state = "rejected"
        elif correction:
            text, source, state = correction[1].strip(), "boss", "corrected"
            category = next((c for c, words in knowledge.CATEGORY_WORDS if re.search(words, text, re.I)), "other")
        elif not row["description"] and re.match(r"^(?:an?|the)\s", normal) and len(answer.split()) >= 3 and normal not in {
                "i don't know", "i do not know", "not really sure", "i am not sure"}:
            text, source, state = answer.strip()[:300], "boss", "corrected"
            category = next((c for c, words in knowledge.CATEGORY_WORDS if re.search(words, text, re.I)), "other")
        else:
            return "uncertain"
        if text and uncertain(text):
            return "uncertain"
        if text and source == "boss" and re.search(r"\b(?:not|isn't|is not|don't|cannot)\b", text, re.I):
            category = "other"
        conn.execute("UPDATE app_explanations SET state=?,resolved_at=? WHERE token=? AND state='pending'",
                     (state, now.isoformat(timespec="seconds"), offer["token"]))
        if text:
            conn.execute("UPDATE things SET about=?,source=?,category=? WHERE key=?",
                         (text, source, category, offer["key"]))
        supersede(conn, offer["key"])
    knowledge.refresh_learned()
    return state


def version(row):
    return hashlib.sha256(json.dumps(identity(row), sort_keys=True).encode()).hexdigest()


def uncertain(text):
    return bool(re.search(r"\b(?:maybe|perhaps|probably|guess|not sure|unsure|unclear|not certain|don't know|do not know|"
                          r"might be|could be)\b", text, re.I))


def forget():
    """Withdraw app explanations and fence in-flight lookups, retaining observed usage rows."""
    from services.mind import knowledge
    with knowledge.db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM things WHERE about IS NOT NULL AND source IN ('boss','confirmed')").fetchone()[0]
        conn.execute("DELETE FROM app_explanations")
        conn.execute("UPDATE things SET about=NULL,source='rule',category=CASE WHEN kind='app' THEN 'other' "
                     "ELSE 'browsing' END WHERE source IN ('boss','confirmed')")
        for row in conn.execute("SELECT key FROM thing_revisions").fetchall():
            supersede(conn, row[0])
    knowledge.refresh_learned()
    return count
