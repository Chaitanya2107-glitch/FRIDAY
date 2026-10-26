"""Durable file results, scoped to laptop or Telegram; metadata only."""

import time
from pathlib import Path

from services.files.search import FileHit
from services.mind import reference_context as context
from services.mind.workspace import workspace


def stamp(path):
    try:
        target = Path(path)
        if not target.is_file() or target.is_symlink() or target.is_junction():
            return None
        stat = target.stat()
        return [str(target.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except OSError:
        return None


class LastResults:
    @property
    def scope(self):
        from services.automation.intent import remote_request
        return "telegram" if remote_request.get() else "local"

    def snapshot(self):
        with workspace._db() as conn:
            row = context.read(conn, "files", self.scope)
        # Monotonic protects against backward wall-clock jumps within this boot.
        if row and 0 <= time.monotonic() - row["payload"]["at"] < context.TTL_SECONDS:
            return row
        return None

    def set(self, hits):
        payload = {"hits": [{"path": h.path, "name": h.name, "stamp": stamp(h.path)} for h in hits[:100]],
                   "at": time.monotonic(), "selected": None, "pending": None}
        with workspace._db() as conn:
            context.remember(conn, "files", payload, self.scope)

    def change(self, row, **fields):
        with workspace._db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            context.require(conn, row)
            context.remember(conn, "files", {**row["payload"], **fields}, self.scope, expires=row["expires"])

    def clear(self):
        with workspace._db() as conn:
            context.clear(conn, "files", self.scope)

    def get(self):
        row = self.snapshot()
        return [FileHit(h["path"], h["name"]) for h in row["payload"]["hits"]] if row else []

    @property
    def hits(self):
        return self.get()

    @hits.setter
    def hits(self, hits):
        self.set(hits)

    @property
    def at(self):
        row = self.snapshot()
        return row["payload"]["at"] if row else 0.0

    @at.setter
    def at(self, value):
        if row := self.snapshot():
            self.change(row, at=value)

    @property
    def selected(self):
        row = self.snapshot()
        if row and row["payload"]["selected"] is not None:
            hit = row["payload"]["hits"][row["payload"]["selected"]]
            return FileHit(hit["path"], hit["name"])
        return None

    @selected.setter
    def selected(self, hit):
        if row := self.snapshot():
            hits = [FileHit(h["path"], h["name"]) for h in row["payload"]["hits"]]
            self.change(row, selected=hits.index(hit) if hit in hits else None, pending=None)
