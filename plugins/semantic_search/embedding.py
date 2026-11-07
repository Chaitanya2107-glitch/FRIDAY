"""Local-only inference; downloading weights is an explicit background operation."""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> NDArray[np.float32]: ...


class ModelUnavailable(RuntimeError):
    pass


def normalized(values: np.ndarray, count: int) -> NDArray[np.float32]:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or len(values) != count or not np.isfinite(values).all():
        raise ModelUnavailable('The search model returned invalid vectors.')
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-12)


class LocalEmbedder:
    """Construction and embed never download. prepare may download model files only."""

    def __init__(self, data_dir: Path, settings, progress=lambda phase: None):
        self.cache_dir = Path(data_dir) / 'models'
        self.settings, self.progress = settings, progress
        self.model = None
        self.lock = threading.Lock()
        self.error = 'Search model is not loaded. Say prepare search model. Keyword search still works.'
        self.backend = settings.get('embedding_backend', 'fastembed')
        self.name = settings.get('model_name', 'BAAI/bge-small-en-v1.5' if self.backend == 'fastembed'
                                 else 'sentence-transformers/all-MiniLM-L6-v2')
        self.local_folder = settings.get('local_model_folder', '')
        if self.backend not in {'fastembed', 'sentence_transformers'} or not isinstance(self.name, str):
            raise ValueError('Invalid search embedding settings.')

    @property
    def identity(self) -> str:
        return f'{self.backend}:{self.name}:{self.local_folder}'

    @property
    def ready(self) -> bool:
        return self.model is not None

    def _load(self, local_only: bool):
        if self.local_folder:
            path = Path(self.local_folder).expanduser()
            if not path.is_absolute() or not path.is_dir():
                raise ModelUnavailable('Local model folder is missing or is not an absolute folder.')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.backend == 'fastembed':
            from fastembed import TextEmbedding
            return TextEmbedding(self.name, cache_dir=str(self.cache_dir), threads=1,
                                 providers=['CPUExecutionProvider'], local_files_only=local_only,
                                 **({'specific_model_path': self.local_folder} if self.local_folder else {}))
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(self.local_folder or self.name, cache_folder=str(self.cache_dir),
                                   device='cpu', local_files_only=local_only, trust_remote_code=False)

    def prepare(self, *, download: bool = False) -> bool:
        if not self.lock.acquire(blocking=download):
            return False  # A local query must not wait behind a model download.
        try:
            if self.ready:
                return True
            try:
                self.progress('loading_model')
                self.model = self._load(True)
            except Exception:
                if download and not self.local_folder:
                    self.progress('downloading_model')
                    try:
                        self.model = self._load(False)
                    except Exception:
                        self.model = None
                if self.model is None:
                    self.error = ('Search model is missing or could not be loaded. If offline, connect once and say '
                                  'prepare search model, or set local_model_folder. Keyword search still works.')
                    self.progress('model_unavailable')
                    return False
            self.error = ''
            self.progress('model_ready')
            return True
        finally:
            self.lock.release()

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        if not self.ready:
            raise ModelUnavailable(self.error)
        # Queries never queue behind an indexing batch.
        if not self.lock.acquire(blocking=False):
            raise ModelUnavailable('Search model is busy. Keyword search still works.')
        try:
            if self.backend == 'fastembed':
                values = list(self.model.embed(texts, batch_size=16, parallel=None))
            else:
                values = self.model.encode(texts, batch_size=16, show_progress_bar=False,
                                           normalize_embeddings=True, convert_to_numpy=True)
            return normalized(values, len(texts))
        except Exception:
            raise ModelUnavailable('Local search model failed. Keyword search still works.') from None
        finally:
            self.lock.release()
