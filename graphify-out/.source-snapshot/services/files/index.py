"""
services/files/index.py

The file index behind "find my resume" and "what do my notes say about X".
Kept in memory/file_index.db (SQLite):

  files       every file in FILE_SEARCH_FOLDERS: path, name, size, modified time
  chunks      ~900-character pieces of each readable file's text, with a vector
  chunks_fts  full-text (keyword) index of the same pieces

scan() walks the folders, drops deleted files and re-reads only new or changed
ones, so after the first run a rescan mostly just checks modification times.
It runs in a background thread at startup and every FILE_SEARCH_RESCAN_MINUTES
(run_indexer). Program, cache and hidden folders are skipped (SKIP_DIRS).
"""

import asyncio
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from core.config import config
from core.logger import logger
from services.files import embed as default_embedder
from services.files.extract import chunk_text, extract_text, is_private, is_readable

DB_PATH = config.MEMORY_DIR / "file_index.db"
SKIP_DIRS = {
    "venv", ".venv", "env", "node_modules", "__pycache__", "site-packages", "dist", "build",
    "target", "bin", "obj", "out", ".git", ".svn", ".hg", ".idea", ".vscode", ".cache",
    ".next", ".gradle", ".tox", ".pytest_cache", ".mypy_cache", "appdata",
    "$recycle.bin", "system volume information",
}
MAX_FILES = 500_000
EMBED_BATCH_CHUNKS = 256  # chunks embedded together, for the GPU
MAX_CHUNKS_PER_FILE = 400
NOT_READ_YET = -1.0  # mtime stored until a file's text is in, so an interrupted scan reads it again


def _own_runtime_dirs() -> set[str]:
    # FRIDAY's own log and database change constantly — indexing them would never settle
    return {os.path.normcase(str(p.resolve())) for p in (config.MEMORY_DIR, config.LOGS_DIR)}


class FileIndex:
    def __init__(self, db_path: Path = DB_PATH, folders=None, embedder=default_embedder):
        self.db_path = Path(db_path)
        self._folders = folders or config.file_search_folders
        self._embedder = embedder
        self._scan_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._vectors: tuple[np.ndarray, np.ndarray] | None = None  # (chunk ids, matrix), loaded lazily
        self.scanning = False
        self.progress = (0, 0)  # (files read, files to read) during a scan
        self.last_scan: float | None = None
        self._ready = False

    # ── Database ──────────────────────────────────────────────────────────────

    @contextmanager
    def connect(self):
        """A connection that commits on success and is always closed."""
        if not self._ready:
            self._create()
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _create(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            with db:
                db.execute("PRAGMA journal_mode = WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                        size INTEGER NOT NULL, mtime REAL NOT NULL, has_text INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS chunks (
                        id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL,
                        position INTEGER NOT NULL, text TEXT NOT NULL, vector BLOB
                    );
                    CREATE INDEX IF NOT EXISTS chunks_by_file ON chunks(file_id);
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text);
                    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
                """)
                model = db.execute("SELECT value FROM meta WHERE key = 'model'").fetchone()
                if model and model[0] != config.FILE_SEARCH_EMBED_MODEL:
                    # Vectors from another model can't be compared — embed everything again
                    logger.info("File search model changed — the index will re-embed every file")
                    db.execute("UPDATE chunks SET vector = NULL")
                db.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (config.FILE_SEARCH_EMBED_MODEL,))
        finally:
            db.close()
        self._ready = True

    def stats(self) -> dict:
        with self.connect() as db:
            files, readable = db.execute("SELECT COUNT(*), COALESCE(SUM(has_text), 0) FROM files").fetchone()
        return {
            "files": files, "readable": readable, "scanning": self.scanning,
            "progress": list(self.progress), "last_scan": self.last_scan,
        }

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _walk(self, folders: list[Path]):
        """(path, size, mtime) of every file worth indexing under the folders."""
        skip_paths = _own_runtime_dirs()
        stack = [str(f) for f in folders if f.is_dir()]
        count = 0
        while stack:
            folder = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue  # no permission, or it vanished
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        name = entry.name.lower()
                        if (name not in SKIP_DIRS and not name.startswith(".")
                                and os.path.normcase(entry.path) not in skip_paths):
                            stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and not is_private(Path(entry.name)):
                        info = entry.stat(follow_symlinks=False)
                        yield entry.path, info.st_size, info.st_mtime
                        count += 1
                        if count >= MAX_FILES:
                            logger.warning(f"File search stopped at {MAX_FILES} files")
                            return
                except OSError:
                    continue

    def scan(self) -> bool:
        """Bring the index up to date. Returns False if a scan was already running."""
        if not self._scan_lock.acquire(blocking=False):
            return False
        self.scanning = True
        started = time.monotonic()
        try:
            found = {path: (size, mtime) for path, size, mtime in self._walk(self._folders())}
            with self.connect() as db:
                known = {path: (file_id, size, mtime)
                         for file_id, path, size, mtime in db.execute("SELECT id, path, size, mtime FROM files")}

            gone = [known[path][0] for path in known.keys() - found.keys()]
            changed = [path for path, stamp in found.items()
                       if path not in known or known[path][1:] != stamp]
            self._forget(gone)
            self._drop_unreadable()
            to_read = self._record_names(changed, found, known)
            self._read_files(to_read)
            self._embed_missing()

            self.last_scan = time.time()
            logger.info(
                f"File index updated in {time.monotonic() - started:.0f}s: {len(found)} files, "
                f"{len(changed)} new or changed, {len(gone)} removed, {len(to_read)} read"
            )
            return True
        finally:
            self.scanning = False
            self.progress = (0, 0)
            self._scan_lock.release()

    @staticmethod
    def _drop_chunks(db: sqlite3.Connection, file_id: int) -> None:
        db.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE file_id = ?)", (file_id,))
        db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    def _forget(self, file_ids: list[int]) -> None:
        if not file_ids:
            return
        with self._write_lock, self.connect() as db:
            for file_id in file_ids:
                self._drop_chunks(db, file_id)
            db.executemany("DELETE FROM files WHERE id = ?", [(i,) for i in file_ids])
        self._vectors = None

    def _drop_unreadable(self) -> None:
        """Text of file types that are no longer read (the list in extract.py changed)."""
        with self.connect() as db:
            stale = [file_id for file_id, path in db.execute("SELECT id, path FROM files WHERE has_text = 1")
                     if not is_readable(Path(path))]
        if not stale:
            return
        with self._write_lock, self.connect() as db:
            for file_id in stale:
                self._drop_chunks(db, file_id)
            db.executemany("UPDATE files SET has_text = 0 WHERE id = ?", [(i,) for i in stale])
        self._vectors = None

    def _record_names(self, paths: list[str], found: dict, known: dict) -> list[tuple[int, str, int, float]]:
        """Save new/changed files by name. Returns (id, path, size, mtime) of those whose text should be read."""
        to_read = []
        with self._write_lock, self.connect() as db:
            for path in paths:
                size, mtime = found[path]
                readable = is_readable(Path(path))
                db.execute(
                    "INSERT INTO files (path, name, size, mtime) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime, has_text = 0",
                    (path, os.path.basename(path), size, NOT_READ_YET if readable else mtime),
                )
                file_id = db.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()[0]
                if path in known:
                    self._drop_chunks(db, file_id)  # the old text
                if readable:
                    to_read.append((file_id, path, size, mtime))
        self._vectors = None
        # Newest first, so recent work is searchable soonest
        to_read.sort(key=lambda item: item[3], reverse=True)
        return to_read

    def _read_files(self, files: list[tuple[int, str, int, float]]) -> None:
        # Whole files only go into a batch, so a file is never half stored
        batch: list[tuple] = []  # (file id, mtime, position, text, text to embed)
        for done, (file_id, path, size, mtime) in enumerate(files, start=1):
            self.progress = (done, len(files))
            text = extract_text(Path(path), size)
            if not text:
                with self._write_lock, self.connect() as db:
                    db.execute("UPDATE files SET mtime = ? WHERE id = ?", (mtime, file_id))
                continue
            name = os.path.basename(path)
            chunks = chunk_text(text)[:MAX_CHUNKS_PER_FILE]
            batch += [(file_id, mtime, position, chunk, f"{name}\n{chunk}")
                      for position, chunk in enumerate(chunks)]
            if len(batch) >= EMBED_BATCH_CHUNKS:
                self._store_chunks(batch)
                batch = []
        self._store_chunks(batch)

    def _vectors_for(self, texts: list[str]) -> list[bytes | None]:
        try:
            vectors = self._embedder.encode(texts)
        except Exception as e:
            # Keyword search still works without vectors; the next scan tries again
            logger.warning(f"File search couldn't embed text: {e}")
            return [None] * len(texts)
        return [v.astype(np.float16).tobytes() for v in vectors]

    def _store_chunks(self, batch: list[tuple]) -> None:
        if not batch:
            return
        vectors = self._vectors_for([item[4] for item in batch])
        with self._write_lock, self.connect() as db:
            for (file_id, _, position, text, _), vector in zip(batch, vectors):
                cursor = db.execute(
                    "INSERT INTO chunks (file_id, position, text, vector) VALUES (?, ?, ?, ?)",
                    (file_id, position, text, vector),
                )
                db.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (cursor.lastrowid, text))
            done = {file_id: mtime for file_id, mtime, *_ in batch}
            db.executemany("UPDATE files SET mtime = ?, has_text = 1 WHERE id = ?",
                           [(mtime, file_id) for file_id, mtime in done.items()])
        self._vectors = None

    def _embed_missing(self) -> None:
        """Chunks saved while the model was unavailable (or from another model) get vectors now."""
        while True:
            with self.connect() as db:
                rows = db.execute(
                    "SELECT chunks.id, files.name, chunks.text FROM chunks JOIN files ON files.id = chunks.file_id "
                    "WHERE chunks.vector IS NULL LIMIT ?", (EMBED_BATCH_CHUNKS,),
                ).fetchall()
            if not rows:
                return
            vectors = self._vectors_for([f"{name}\n{text}" for _, name, text in rows])
            if vectors[0] is None:
                return  # the model still isn't available
            with self._write_lock, self.connect() as db:
                db.executemany("UPDATE chunks SET vector = ? WHERE id = ?",
                               [(vector, chunk_id) for (chunk_id, _, _), vector in zip(rows, vectors)])
            self._vectors = None

    # ── Vectors for search ────────────────────────────────────────────────────

    def embed_query(self, text: str) -> np.ndarray:
        return self._embedder.encode_query(text)

    def warm_up(self) -> None:
        """Load the model and vectors now, so the first search doesn't wait ~20 s for them."""
        self.vectors()
        self._embedder.encode(["warm up"])

    def vectors(self) -> tuple[np.ndarray, np.ndarray]:
        """(chunk ids, matrix with one unit vector per row), cached until the index changes."""
        cached = self._vectors
        if cached is not None:
            return cached
        with self.connect() as db:
            rows = db.execute("SELECT id, vector FROM chunks WHERE vector IS NOT NULL").fetchall()
        if rows:
            ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
            matrix = np.vstack([np.frombuffer(r[1], dtype=np.float16) for r in rows]).astype(np.float32)
        else:
            ids, matrix = np.zeros(0, dtype=np.int64), np.zeros((0, 0), dtype=np.float32)
        self._vectors = (ids, matrix)
        return self._vectors


file_index = FileIndex()


async def run_indexer(index: FileIndex = file_index) -> None:
    """Background task: index at startup, then rescan every FILE_SEARCH_RESCAN_MINUTES."""
    if not config.FILE_SEARCH_ENABLED:
        return
    await asyncio.sleep(10)  # let the speech model and TTS warm up first
    while True:
        try:
            scanned = await asyncio.to_thread(index.scan)
            if scanned:
                await asyncio.to_thread(index.warm_up)
        except Exception as e:
            logger.error(f"File indexing failed: {e}")
        await asyncio.sleep(config.FILE_SEARCH_RESCAN_MINUTES * 60)
