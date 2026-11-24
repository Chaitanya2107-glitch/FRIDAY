"""Versioned explanations for unknown things, pending until the owner confirms."""

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


def pending(key=None, limit=8):
    from services.mind import knowledge
    with knowledge.db() as conn:
        rows = conn.execute(
            "SELECT p.*,t.name,t.kind FROM app_explanations p JOIN things t ON t.key=p.key "
            "JOIN thing_revisions r ON r.key=p.key AND r.token=p.revision "
            "WHERE p.state='pending' AND t.about IS NULL AND (? IS NULL OR p.key=?) "
            "ORDER BY p.proposed_at DESC,p.rowid DESC LIMIT ?", (key, key, limit)).fetchall()
    from services.mind.training import teaching_for
    return [dict(row) for row in rows if not teaching_for("subject", row["key"])]


def evidence():
    return {"app-explanation:" + row["token"]: {**row, "entity_kind": row["kind"], "kind": "app_verification"}
            for row in pending() if row['provider'] != 'waiting for model' and not row['key'].startswith('app:phone:')}


def identity(row):
    return {name: row[name] for name in ("token", "key", "revision")}


def current(offer):
    return next((row for row in pending(offer.get("key")) if identity(row) == offer), None)


def question(row):
    name = row["name"].replace('?', '')
    kind = row.get('entity_kind', row['kind'])
    if row["description"]:
        # Fixed wording binds approval to the actual stored candidate, not a model paraphrase.
        description = " ".join(row["description"].split()).replace("?", ".")
        category = f' and puts it under {row["category"]}' if kind == 'app' else ''
        return f'The model suggests {name} is "{description}"{category} (via {row["provider"]}). Is that right?'
    status = ('The question is in the learning inbox.' if row['provider'] == 'waiting for model'
              else "I tried asking the model and didn't get a reliable answer.")
    return f'{status} What is {name}?'


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
    correction = (re.match(r"^(?:actually[, ]+|(?:no[, ]+)?(?:it's |it is |this (?:app|course|term|place) is ))(.{4,300})$",
                           answer.strip(), re.I)
                  or re.match(r"^no[, ]+(an? .{4,300})$", answer.strip(), re.I))
    no = no or (bool(re.match(r"^no\b", normal)) and correction is None)
    with knowledge.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT p.*,t.source,t.about,t.kind FROM app_explanations p JOIN things t ON t.key=p.key "
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
            from services.mind.cognition import redact
            conn.execute("UPDATE things SET about=?,source=?,category=?,looked_up=? WHERE key=?",
                         (redact(text), source, category, now.isoformat(timespec='seconds'), offer["key"]))
        supersede(conn, offer["key"])
    knowledge.refresh_learned()
    return state


def week(now):
    from datetime import timedelta
    from services.mind import knowledge
    from services.mind.training import teaching_for

    start = (now.date() - timedelta(days=6)).isoformat()
    with knowledge.db() as conn:
        rows = conn.execute("SELECT key,name,about FROM things WHERE source IN ('confirmed','boss') "
                            "AND about IS NOT NULL AND looked_up>=? ORDER BY looked_up DESC,name", (start,)).fetchall()
    confirmed = [f"{row['name']} — {teaching_for('subject', row['key']) or row['about']}" for row in rows
                 if not row['key'].startswith('app:phone:')]
    pending_lines = [f"{row['name']} — {row['description']} ({row['provider']})" if row['description']
                     else f"{row['name']} — waiting for an answer" for row in pending(limit=-1)
                     if not row['key'].startswith('app:phone:')]
    return ('Confirmed in the past seven days\n' + ('\n'.join(confirmed) or 'None yet.') +
            '\n\nPending in the learning inbox\n' + ('\n'.join(pending_lines) or 'None.'))


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
        conn.execute("UPDATE things SET about=NULL,source='rule',category=CASE WHEN kind='topic' THEN 'browsing' "
                     "ELSE 'other' END WHERE source IN ('boss','confirmed')")
        for row in conn.execute("SELECT key FROM thing_revisions").fetchall():
            supersede(conn, row[0])
    knowledge.refresh_learned()
    return count
