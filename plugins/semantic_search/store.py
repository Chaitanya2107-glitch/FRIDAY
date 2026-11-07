"""Small SQLite/FTS5 store. Each file replacement is one crash-safe transaction."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading

import numpy as np

from .documents import Chunk


class Store:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / 'index.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._vectors = None
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, mtime INTEGER NOT NULL,
                    size INTEGER NOT NULL, hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    kind TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'file', metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                    page INTEGER, offset INTEGER NOT NULL, text TEXT NOT NULL, embedding BLOB
                );
                CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
                CREATE INDEX IF NOT EXISTS chunks_unembedded ON chunks(id) WHERE embedding IS NULL;
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text);
                END;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA secure_delete=ON')
            try:
                with db:
                    yield db
            finally:
                db.close()

    def model_identity(self, identity: str):
        with self.connect() as db:
            old = db.execute("SELECT value FROM meta WHERE key='model'").fetchone()
            if old and old[0] != identity:
                db.execute('UPDATE chunks SET embedding=NULL')
                self._vectors = None
            db.execute("INSERT OR REPLACE INTO meta VALUES ('model',?)", (identity,))

    def known(self, source='file') -> dict:
        with self.connect() as db:
            return {r['path']: dict(r) for r in db.execute('SELECT * FROM files WHERE source=?', (source,))}

    def pending(self, path: str, mtime: int, size: int, kind: str):
        with self.connect() as db:
            db.execute("INSERT INTO files(path,mtime,size,status,kind) VALUES(?,?,?,'pending',?) "
                       "ON CONFLICT(path) DO UPDATE SET status='pending'", (path, mtime, size, kind))

    def stamp(self, path: str, mtime: int, size: int):
        with self.connect() as db:
            db.execute('UPDATE files SET mtime=?,size=? WHERE path=?', (mtime, size, path))

    def replace(self, path: str, mtime: int, size: int, digest: str, status: str, kind: str,
                chunks: list[Chunk], *, source='file', metadata=None):
        with self.connect() as db:
            db.execute('INSERT INTO files(path,mtime,size,hash,status,kind,source,metadata) VALUES(?,?,?,?,?,?,?,?) '
                       'ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime,size=excluded.size,hash=excluded.hash,'
                       'status=excluded.status,kind=excluded.kind,metadata=excluded.metadata',
                       (path, mtime, size, digest, status, kind, source, json.dumps(metadata or {})))
            file_id = db.execute('SELECT id FROM files WHERE path=?', (path,)).fetchone()[0]
            db.execute('DELETE FROM chunks WHERE file_id=?', (file_id,))
            db.executemany('INSERT INTO chunks(file_id,page,offset,text) VALUES(?,?,?,?)',
                           [(file_id, c.page, c.offset, c.text) for c in chunks])
            self._vectors = None

    def forget(self, paths: list[str]):
        with self.connect() as db:
            db.executemany("DELETE FROM files WHERE source='file' AND path=?", [(p,) for p in paths])
            if paths:
                self._vectors = None

    def missing(self, limit=16) -> list:
        with self.connect() as db:
            return db.execute('SELECT id,text FROM chunks WHERE embedding IS NULL LIMIT ?', (limit,)).fetchall()

    def save_vectors(self, ids: list[int], vectors: np.ndarray):
        with self.connect() as db:
            db.executemany('UPDATE chunks SET embedding=? WHERE id=?',
                           [(np.asarray(v, dtype='<f4').tobytes(), i) for i, v in zip(ids, vectors)])
            self._vectors = None

    def vectors(self) -> tuple[np.ndarray, np.ndarray]:
        with self.lock:
            if self._vectors is None:
                with self.connect() as db:
                    rows = db.execute('SELECT id,embedding FROM chunks WHERE embedding IS NOT NULL').fetchall()
                ids = np.array([r[0] for r in rows], dtype=np.int64)
                matrix = np.vstack([np.frombuffer(r[1], dtype='<f4') for r in rows]) if rows else np.empty((0, 0), np.float32)
                self._vectors = ids, matrix
            return self._vectors

    def rows(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT c.id,c.page,c.offset,f.path,f.mtime,f.kind,f.source,'
                                                    'f.metadata FROM chunks c JOIN files f ON f.id=c.file_id')]

    def text(self, chunk_id: int) -> str:
        with self.connect() as db:
            row = db.execute('SELECT text FROM chunks WHERE id=?', (chunk_id,)).fetchone()
            return row[0] if row else ''

    def keywords(self, expression: str, limit: int = 200) -> list[int]:
        if not expression:
            return []
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? '
                                            'ORDER BY bm25(chunks_fts) LIMIT ?', (expression, limit))]

    def stats(self) -> dict:
        with self.connect() as db:
            counts = dict(db.execute('SELECT status,count(*) FROM files GROUP BY status').fetchall())
            count, vectors = db.execute('SELECT count(*),count(embedding) FROM chunks').fetchone()
        size = sum(p.stat().st_size for p in self.path.parent.glob('index.sqlite3*') if p.is_file())
        return dict(files=sum(counts.values()), chunks=count, vectors=vectors, needs_ocr=counts.get('needs OCR', 0),
                    errors=counts.get('error', 0), pending=counts.get('pending', 0), bytes=size)

    def clear(self):
        with self.lock:
            with self.connect() as db:
                db.execute('DELETE FROM files')
                db.execute('DELETE FROM meta')
                db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
                self._vectors = None
            with self.connect() as db:
                db.execute('VACUUM')
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
