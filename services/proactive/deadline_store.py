"""Atomic deadline JSON publication with a bounded cross-process writer lock."""

import json
import math
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import closing, contextmanager

from services.automation.system_control import AutomationError

_lock = threading.RLock()


def _links(items, *, proposal=False):
    if not isinstance(items, list):
        raise ValueError("Invalid reminder links")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0 or not isinstance(item.get("text"), str):
            raise ValueError("Invalid linked reminder identity")
        if item["id"] in seen:
            raise ValueError("Duplicate linked reminder")
        seen.add(item["id"])
        for field in ("due_at", "offset", *(["new_due"] if proposal else [])):
            if type(item.get(field)) not in (int, float) or not math.isfinite(item[field]):
                raise ValueError("Invalid linked reminder time")


@contextmanager
def edit(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # SQLite supplies the OS-level writer lock; deadline data remains in JSON.
    with _lock, closing(sqlite3.connect(str(path) + ".lock.sqlite3", timeout=2)) as guard, guard:
        guard.execute("BEGIN IMMEDIATE")
        yield


def read(path):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get("what"), str)
                                            or not isinstance(r.get("due"), str) for r in rows):
            raise ValueError("Invalid deadline records")
        from datetime import datetime
        ids = set()
        for row in rows:
            if datetime.fromisoformat(row["due"]).tzinfo is not None:
                raise ValueError("Deadline must use local time")
            for field in ("id", "revision"):
                if field in row and (not isinstance(row[field], str) or not row[field]):
                    raise ValueError("Invalid deadline identity")
            if row.get("id") in ids:
                raise ValueError("Duplicate deadline identity")
            if row.get("id"):
                ids.add(row["id"])
            if not isinstance(row.get("history", []), list) or not isinstance(row.get("reminder_updates", []), list):
                raise ValueError("Invalid deadline history")
            for change in row.get("history", []):
                if not isinstance(change, dict) or change.get("source") != "owner_report" or not isinstance(change.get("quote"), str):
                    raise ValueError("Invalid deadline provenance")
                for field in ("old_due", "new_due", "noted"):
                    datetime.fromisoformat(change[field])
            _links(row.get("linked_reminders", []))
            for proposal in row.get("reminder_updates", []):
                if (not isinstance(proposal, dict) or proposal.get("status") not in {"pending", "applied", "rejected", "superseded"}
                        or proposal.get("scope") not in {"local", "telegram"}
                        or not all(isinstance(proposal.get(f), str) and proposal[f] for f in ("id", "revision"))):
                    raise ValueError("Invalid reminder proposal")
                _links(proposal["items"], proposal=True)
        return rows
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise AutomationError("Saved deadlines are unreadable. Repair the deadline file before changing it.") from error


def save(path, rows):
    for row in rows:
        row.setdefault("id", uuid.uuid4().hex)
        row.setdefault("revision", uuid.uuid4().hex)
    content = json.dumps(sorted(rows, key=lambda d: d["due"]), indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = stream.name
        try:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            os.unlink(temporary)
            raise
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
