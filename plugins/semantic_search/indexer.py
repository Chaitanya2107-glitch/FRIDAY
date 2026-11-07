"""One cooperative worker: scans, model preparation and backfilling are resumable."""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import threading
import time

from . import documents
from .embedding import normalized


def low_priority():
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentThread.restype = ctypes.c_void_p
        kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        kernel.SetThreadPriority(kernel.GetCurrentThread(), -1)


class Indexer:
    def __init__(self, api, store, embedder):
        self.api, self.store, self.embedder = api, store, embedder
        self.wake = threading.Event()
        self.cancel_pass = threading.Event()
        self.lock = threading.Lock()
        self.scan_lock = threading.Lock()
        self.requested = self.prepare_requested = self.delete_requested = False
        self.idle = False
        self.scanning = False
        self.last_scan = 0.
        self.last_elapsed = 0.
        self.last_progress = float('-inf')
        self.model_attempted = False

    def roots(self) -> list[Path]:
        values = self.api.settings.get('indexed_roots', [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not Path(v).is_absolute() for v in values):
            raise ValueError('indexed_roots must be a list of absolute folder paths.')
        return [Path(v) for v in values]

    def options(self) -> tuple[int, bool]:
        megabytes = self.api.settings.get('max_file_mb', 25)
        code = self.api.settings.get('include_code', False)
        if type(megabytes) not in {int, float} or not math.isfinite(megabytes) or megabytes <= 0 or type(code) is not bool:
            raise ValueError('max_file_mb must be positive and include_code must be a boolean.')
        return int(megabytes * 1024 * 1024), code

    def request(self, *, prepare=False, delete=False, cancel=False):
        with self.lock:
            self.requested = True
            self.prepare_requested |= prepare
            self.delete_requested |= delete
            if cancel or delete:
                self.cancel_pass.set()
        self.wake.set()

    def stopped(self) -> bool:
        return self.api.stop_event.is_set() or self.cancel_pass.is_set()

    def checkpoint(self) -> bool:
        while not self.stopped() and self.api.settings.get('indexing_paused', False):
            self.api.stop_event.wait(.1)
        return not self.stopped()

    def throttle(self, cpu_start: float):
        # One inference thread plus three times its CPU time resting targets a 25% duty cycle.
        delay = max(.02, 3 * (time.thread_time() - cpu_start))
        deadline = time.monotonic() + delay
        while not self.stopped() and time.monotonic() < deadline:
            if not self.checkpoint():
                break
            self.api.stop_event.wait(min(.1, max(0, deadline - time.monotonic())))

    def progress(self, phase: str, done: int = 0, total: int = 0, folder: str = ''):
        now = time.monotonic()
        if not self.api.stop_event.is_set() and now - self.last_progress >= 1:
            self.last_progress = now
            self.api.publish('index.progress', dict(phase=phase, done=done, processed=done, total=total,
                                                     current_folder=folder))
            self.api.show_card('Search indexing', f'{phase.replace("_", " ")}: {done}/{total}'
                               + (f' · {folder}' if folder else ''), ttl_s=120)

    def prepare(self, download: bool):
        self.model_attempted = True
        if hasattr(self.embedder, 'prepare'):
            return self.embedder.prepare(download=download)
        return True

    def scan(self, *, download=False) -> bool:
        if not self.scan_lock.acquire(blocking=False):
            return False
        started = time.monotonic()
        self.scanning = True
        try:
            roots = self.roots()
            max_bytes, include_code = self.options()
            self.progress('discovering')
            found = list(documents.walk(roots, self.stopped, self.checkpoint, max_bytes, include_code))
            if not self.checkpoint():
                return False
            known = self.store.known()
            self.store.forget(list(set(known) - {str(p) for p in found}))
            for done, path in enumerate(found, 1):
                if not self.checkpoint():
                    return False
                cpu = time.thread_time()
                try:
                    info = path.stat()
                    old = known.get(str(path))
                    unchanged = old and old['mtime'] == info.st_mtime_ns and old['size'] == info.st_size
                    if unchanged and old['status'] not in {'pending', 'error'}:
                        continue
                    # Recheck exclusions at read time, including newly added .nosearch markers.
                    if not documents.allowed_file(path, roots, max_bytes, include_code):
                        self.store.forget([str(path)])
                        continue
                    if unchanged and old['hash']:
                        digest = old['hash']
                    else:
                        with path.open('rb') as stream:
                            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if old and old['hash'] == digest and old['status'] not in {'pending', 'error'}:
                        self.store.stamp(str(path), info.st_mtime_ns, info.st_size)
                        continue
                    self.store.pending(str(path), info.st_mtime_ns, info.st_size, documents.kind(path))
                    parts, status = documents.extract(path)
                    after = path.stat()
                    if (info.st_mtime_ns, info.st_size) != (after.st_mtime_ns, after.st_size) or not self.checkpoint():
                        continue  # pending is retried after a crash or concurrent edit.
                    self.store.replace(str(path), info.st_mtime_ns, info.st_size, digest, status,
                                       documents.kind(path), parts)
                    self.api.log.debug('Search file indexed: %s (%s)', path.name, status)
                except OSError:
                    self.api.log.debug('Search file unavailable: %s', path.name)
                finally:
                    self.progress('extracting', done, len(found), path.parent.name)
                    self.throttle(cpu)
            if not self.checkpoint():
                return False
            if self.store.missing() and (not self.model_attempted or download):
                self.prepare(download=download)
            self.backfill()
            if self.stopped():
                return False
            self.last_scan = time.time()
            self.last_elapsed = time.monotonic() - started
            stats = self.store.stats()
            self.api.publish('index.done', dict(files=stats['files'], readable=stats['files'] - stats['needs_ocr'] - stats['errors'],
                                                needs_ocr=stats['needs_ocr'], chunks=stats['chunks'], elapsed_s=round(self.last_elapsed, 3)))
            self.api.log.info('Search index: %d files, %d chunks, %.3f seconds', stats['files'], stats['chunks'], self.last_elapsed)
            self.api.show_card('Search index ready', f'{stats["files"]} files, {stats["chunks"]} chunks; '
                               f'{stats["needs_ocr"]} PDFs need OCR. {self.last_elapsed:.2f} seconds.', ttl_s=30)
            return True
        finally:
            self.scanning = False
            self.scan_lock.release()

    def backfill(self):
        stats = self.store.stats()
        done, total = stats['vectors'], stats['chunks']
        while self.checkpoint() and (batch := self.store.missing()):
            cpu = time.thread_time()
            try:
                values = normalized(self.embedder.embed([row['text'] for row in batch]), len(batch))
                if self.checkpoint():
                    self.store.save_vectors([row['id'] for row in batch], values)
                    done += len(batch)
            except Exception:
                break  # Keep FTS and retry missing vectors on the next prepare/reindex.
            self.progress('embedding', done, max(done, total))
            self.throttle(cpu)

    def run(self, stop):
        low_priority()
        # A restart retries any incomplete per-file transactions and missing embeddings.
        if self.roots() or self.store.stats()['chunks']:
            self.request()
        while not stop.is_set():
            self.wake.wait(.2)
            self.wake.clear()
            with self.lock:
                requested, prepare, delete = self.requested, self.prepare_requested, self.delete_requested
                self.requested = self.prepare_requested = self.delete_requested = False
                self.cancel_pass.clear()
            scheduled = self.idle and bool(self.roots()) and time.time() - self.last_scan >= 900
            if not (requested or scheduled):
                continue
            try:
                if delete:
                    self.store.clear()
                    self.api.publish('index.done', dict(files=0, chunks=0, elapsed_s=0))
                    continue
                if prepare:
                    self.prepare(download=True)
                self.scan(download=not self.model_attempted)
            except Exception:
                if not stop.is_set():
                    self.api.log.warning('Search index pass failed; say reindex to retry.')
