"""Bounded short references in the existing workspace DB. No learned commands."""

import json
import re
import time
import uuid

from services.automation.command_words import strip_leading_filler
from services.mind.lessons import key

TTL_SECONDS = 15 * 60


def read(conn, kind, scope="local"):
    row = conn.execute("SELECT * FROM workspace_reference_context WHERE scope=? AND kind=?", (scope, kind)).fetchone()
    if row is None or row["expires"] <= time.time():
        return None
    return {**dict(row), "payload": json.loads(row["payload"])}


def remember(conn, kind, payload, scope="local", *, expires=None):
    token = uuid.uuid4().hex
    conn.execute("INSERT INTO workspace_reference_context VALUES(?,?,?,?,?) "
                 "ON CONFLICT(scope,kind) DO UPDATE SET payload=excluded.payload,expires=excluded.expires,token=excluded.token",
                 (scope, kind, json.dumps(payload), time.time() + TTL_SECONDS if expires is None else expires, token))
    return token


def require(conn, context):
    current = read(conn, context["kind"], context["scope"])
    if current is None or current["token"] != context["token"]:
        raise ValueError("The reference changed or expired. Repeat the request with its name.")


def clear(conn, kind=None, scope="local"):
    if kind is None:
        conn.execute("DELETE FROM workspace_reference_context WHERE scope=?", (scope,))
    else:
        conn.execute("DELETE FROM workspace_reference_context WHERE scope=? AND kind=?", (scope, kind))


def choices(text, names):
    """Return only explicit offered names/ordinals, never recency guesses."""
    raw = strip_leading_filler(text).strip().rstrip(".!?")
    literal = len(raw) > 1 and raw[0] in "\"'" and raw[-1] == raw[0]
    query = key(raw.strip("\"'"))
    exact = [i for i, name in enumerate(names) if key(name) == query]
    if exact or literal:
        return exact
    ordinal = re.fullmatch(r"(?:the )?(\d+|first|second|third|fourth|fifth|last)(?: one| file| task| result)?", query)
    if ordinal:
        word = ordinal[1]
        index = int(word) - 1 if word.isdigit() else {"first": 0, "second": 1, "third": 2, "fourth": 3,
                                                   "fifth": 4, "last": len(names) - 1}[word]
        return [index] if 0 <= index < len(names) else []
    query = re.sub(r"^(?:the|my) ", "", query)
    terms = set(query.split())
    return [i for i, name in enumerate(names) if terms and terms <= set(key(name).split())]
