"""
services/files/embed.py

Turns text into vectors for meaning-based file search, with a small local
model (FILE_SEARCH_EMBED_MODEL, default bge-small-en-v1.5: 384 numbers per
text). Runs on the GPU when there is one. Nothing is sent anywhere.
"""

import threading
import time

import numpy as np

from core.config import config
from core.errors import ModelUnavailable
from core.logger import logger
from providers.failover import run_embedding
from services.automation import media_control  # noqa: F401 — loads the right msvcp140.dll before torch

DIMENSIONS = 384
BATCH_SIZE = 64
# bge models find passages better when the question carries this instruction
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None
_lock = threading.RLock()


def _load(*, local_only=False):
    global _model
    with _lock:
        if _model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading the file search model {config.FILE_SEARCH_EMBED_MODEL} on {device}")
            _model = SentenceTransformer(config.FILE_SEARCH_EMBED_MODEL, device=device,
                                         **({'local_files_only': True} if local_only else {}))
    return _model


def encode(texts: list[str]) -> np.ndarray:
    """Unit-length float32 vectors, one row per text."""
    if not texts:
        return np.zeros((0, DIMENSIONS), dtype=np.float32)
    def operation():
        with _lock:
            model = _load()
            return _validated(model.encode(texts, batch_size=BATCH_SIZE, normalize_embeddings=True,
                                           show_progress_bar=False), len(texts))
    return run_embedding("file-embeddings", operation, timeout=8)


def _validated(values, count):
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or len(values) != count or not np.isfinite(values).all():
        raise ModelUnavailable("The embedding model returned invalid vectors.")
    return values


def encode_query(text: str) -> np.ndarray:
    prefix = QUERY_PREFIX if "bge" in config.FILE_SEARCH_EMBED_MODEL.lower() else ""
    return encode([prefix + text])[0]


def encode_local(texts: list[str], *, deadline=None) -> np.ndarray:
    """Recall may reuse installed weights, but must never download missing assets."""
    def check_deadline():
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError('Local recall exceeded its wait budget')
    check_deadline()
    if not texts:
        return np.zeros((0, DIMENSIONS), dtype=np.float32)
    def operation():
        if not _lock.acquire(blocking=False):
            raise InterruptedError('Local embedding model busy')
        try:
            model = _load(local_only=True)
            vectors = []
            for offset in range(0, len(texts), BATCH_SIZE):
                check_deadline()
                vectors.append(model.encode(texts[offset:offset + BATCH_SIZE], batch_size=BATCH_SIZE,
                    normalize_embeddings=True, show_progress_bar=False))
            check_deadline()
            return _validated(np.concatenate(vectors), len(texts))
        finally:
            _lock.release()

    remaining = max(0, deadline - time.monotonic()) if deadline is not None else 3
    return run_embedding("file-embeddings", operation, timeout=min(3, remaining))
