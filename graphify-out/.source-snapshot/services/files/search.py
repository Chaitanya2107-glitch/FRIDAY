"""
services/files/search.py

Searching the file index (services/files/index.py) three ways at once, then
merging the rankings (reciprocal rank fusion):

  names     query words in the file name ("resume" → Chaitanya_Resume.pdf)
  keywords  full-text search of the files' text (exact words, rare terms)
  meaning   vector similarity, so "rental agreement" finds a lease that never
            uses those words

find_files() ranks whole files, for "find my resume". find_passages() ranks
pieces of text, for answering "what does my lease say about pets?".
"""

import math
import os
import re
from typing import NamedTuple

import numpy as np

from core.logger import logger
from services.files.index import FileIndex, file_index

RRF_K = 60
CANDIDATES = 60
NAME_WEIGHT = 2.0         # a name match says more than a word somewhere inside
MIN_FIND_SIMILARITY = 0.72  # bge-small: unrelated text scores ~0.6–0.68, real matches 0.73+
MAX_NAME_ROWS = 5000

STOPWORDS = {
    "a", "an", "the", "my", "me", "i", "is", "are", "was", "of", "for", "to", "in", "on", "at", "and",
    "or", "with", "about", "called", "named", "that", "this", "which", "where", "what", "file", "files",
    "document", "documents", "doc", "docs", "folder", "some", "any", "all", "one", "it", "from", "by",
}
# "find my passport photo" → only images, searching for "passport"
TYPE_WORDS = {
    ("pdf", "pdfs"): {".pdf"},
    ("word", "docx"): {".docx", ".doc"},
    ("excel", "spreadsheet", "spreadsheets", "sheet", "xlsx"): {".xlsx", ".xls", ".csv"},
    ("powerpoint", "presentation", "presentations", "slides", "ppt", "pptx"): {".pptx", ".ppt"},
    ("photo", "photos", "picture", "pictures", "image", "images", "screenshot", "screenshots", "pic", "pics"):
        {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tiff"},
    ("video", "videos", "recording", "recordings", "clip"): {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"},
    ("song", "songs", "audio", "voice", "mp3"): {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"},
    ("zip", "archive"): {".zip", ".rar", ".7z"},
    ("code", "script"): {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".go", ".rs"},
}


class FileHit(NamedTuple):
    path: str
    name: str


class Passage(NamedTuple):
    path: str
    name: str
    text: str


def parse_query(query: str) -> tuple[list[str], set[str] | None]:
    """ "my resume pdf" → (["resume"], {".pdf"}) """
    words, types = [], set()
    for word in re.findall(r"[a-z0-9]+", query.lower()):
        hint = next((exts for names, exts in TYPE_WORDS.items() if word in names), None)
        if hint:
            types |= hint
        elif word not in STOPWORDS and word not in words:
            words.append(word)
    return words, types or None


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _rrf(*rankings: tuple[list, float]) -> list:
    scores: dict = {}
    for ranking, weight in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + weight / (RRF_K + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


# ── The three rankings ────────────────────────────────────────────────────────

def _by_name(index: FileIndex, words: list[str], types: set[str] | None) -> list[int]:
    if not words:
        if not types:
            return []
        # "find my recent pdfs": newest files of that type
        placeholders = " OR ".join("name LIKE ?" for _ in types)
        with index.connect() as db:
            rows = db.execute(f"SELECT id FROM files WHERE {placeholders} ORDER BY mtime DESC LIMIT ?",
                              [f"%{ext}" for ext in types] + [CANDIDATES]).fetchall()
        return [r[0] for r in rows]

    placeholders = " OR ".join("name LIKE ?" for _ in words)
    with index.connect() as db:
        rows = db.execute(f"SELECT id, name, mtime FROM files WHERE {placeholders} LIMIT ?",
                          [f"%{w}%" for w in words] + [MAX_NAME_ROWS]).fetchall()
    needed = len(words) if len(words) <= 2 else math.ceil(len(words) * 0.6)
    scored = []
    for file_id, name, mtime in rows:
        if types and _ext(name) not in types:
            continue
        lowered = name.lower()
        matched = sum(w in lowered for w in words)
        if matched >= needed:
            scored.append((matched, mtime, file_id))
    scored.sort(reverse=True)
    return [file_id for _, _, file_id in scored[:CANDIDATES]]


def _by_keywords(index: FileIndex, words: list[str]) -> list[int]:
    """Chunk ids, best first."""
    if not words:
        return []
    expression = " OR ".join(f'"{w}"' for w in words)
    with index.connect() as db:
        rows = db.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
            (expression, CANDIDATES),
        ).fetchall()
    return [r[0] for r in rows]


def _by_meaning(index: FileIndex, text: str, min_similarity: float = 0.0) -> list[int]:
    """Chunk ids, most similar first."""
    ids, matrix = index.vectors()
    if not len(ids):
        return []
    try:
        query = index.embed_query(text)
    except Exception as e:
        logger.warning(f"File search couldn't embed the query: {e}")
        return []
    similarity = matrix @ query
    top = np.argsort(-similarity)[:CANDIDATES]
    return [int(ids[i]) for i in top if similarity[i] >= min_similarity]


def _chunks(index: FileIndex, chunk_ids: list[int]) -> dict[int, tuple[int, str, str, str]]:
    """chunk id → (file id, path, name, text)"""
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    with index.connect() as db:
        rows = db.execute(
            f"SELECT chunks.id, files.id, files.path, files.name, chunks.text FROM chunks "
            f"JOIN files ON files.id = chunks.file_id WHERE chunks.id IN ({placeholders})", chunk_ids,
        ).fetchall()
    return {row[0]: row[1:] for row in rows}


def _best_file_per_chunk(ranked_chunks: list[int], chunks: dict, types: set[str] | None) -> list[int]:
    files = []
    for chunk_id in ranked_chunks:
        info = chunks.get(chunk_id)
        if info and info[0] not in files and (not types or _ext(info[1]) in types):
            files.append(info[0])
    return files


# ── Public ────────────────────────────────────────────────────────────────────

def find_files(query: str, index: FileIndex = file_index, limit: int = 5) -> list[FileHit]:
    words, types = parse_query(query)
    by_name = _by_name(index, words, types)
    by_keyword = _by_keywords(index, words)
    by_meaning = _by_meaning(index, " ".join(words), MIN_FIND_SIMILARITY) if words else []
    chunks = _chunks(index, list(dict.fromkeys(by_keyword + by_meaning)))
    ranked = _rrf(
        (by_name, NAME_WEIGHT),
        (_best_file_per_chunk(by_keyword, chunks, types), 1.0),
        (_best_file_per_chunk(by_meaning, chunks, types), 1.0),
    )[:limit]
    if not ranked:
        return []
    placeholders = ",".join("?" * len(ranked))
    with index.connect() as db:
        rows = dict((r[0], r[1:]) for r in db.execute(
            f"SELECT id, path, name FROM files WHERE id IN ({placeholders})", ranked))
    return [FileHit(*rows[file_id]) for file_id in ranked if file_id in rows]


def find_passages(question: str, index: FileIndex = file_index, limit: int = 6) -> list[Passage]:
    words, _ = parse_query(question)
    ranked = _rrf((_by_keywords(index, words), 1.0), (_by_meaning(index, question), 1.0))[:limit]
    chunks = _chunks(index, ranked)
    return [Passage(chunks[c][1], chunks[c][2], chunks[c][3]) for c in ranked if c in chunks]
