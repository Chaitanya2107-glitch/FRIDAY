"""Bounded extraction with page/slide locations and conservative path exclusions."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import itertools
import logging
import os
from pathlib import Path
import re
import stat
import threading
import zipfile

from services.files.extract import is_private

TEXT = {'.txt', '.md', '.rst', '.csv'}
OFFICE = {'.pdf', '.docx', '.pptx'}
CODE = {'.py', '.js', '.java', '.c', '.cpp'}
SKIP = {'node_modules', '.git', 'venv', '.venv', 'env', '__pycache__', 'appdata',
        'windows', 'program files', 'program files (x86)', '$recycle.bin', 'site-packages'}


@dataclass(frozen=True)
class Chunk:
    page: int | None
    offset: int
    text: str


def kind(path: Path) -> str:
    return 'pdf' if path.suffix.lower() == '.pdf' else 'slides' if path.suffix.lower() == '.pptx' else (
        'code' if path.suffix.lower() in CODE else 'notes')


def blocked_folder(path: Path) -> bool:
    try:
        info = path.lstat()
        return (path.name.casefold() in SKIP or path.name.startswith('.') or path.is_symlink()
                or bool(getattr(info, 'st_file_attributes', 0) & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_REPARSE_POINT))
                or (path / '.nosearch').exists())
    except OSError:
        return True


def allowed_root(path: Path) -> bool:
    return path.is_absolute() and path.is_dir() and not any(blocked_folder(p) for p in (path, *path.parents))


def allowed_file(path: Path, roots: list[Path], max_bytes: int, include_code: bool = False) -> bool:
    try:
        info = path.lstat()
        return (not path.is_symlink() and path.is_file() and not is_private(path)
                and not path.name.startswith('.')
                and not getattr(info, 'st_file_attributes', 0) & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_REPARSE_POINT)
                and info.st_size <= max_bytes and path.suffix.lower() in TEXT | OFFICE | (CODE if include_code else set())
                and any(path.is_relative_to(root) for root in roots)
                and not any(blocked_folder(p) for p in path.parents))
    except OSError:
        return False


def walk(roots: list[Path], stop, checkpoint, max_bytes: int, include_code: bool):
    seen = set()
    for root in roots:
        if not allowed_root(root):
            continue
        for folder, dirs, names in os.walk(root, followlinks=False):
            if stop() or not checkpoint():
                return
            parent = Path(folder)
            if blocked_folder(parent):
                dirs[:] = []
                continue
            dirs[:] = sorted(d for d in dirs if not blocked_folder(parent / d))
            for name in sorted(names):
                path = parent / name
                if path not in seen and allowed_file(path, roots, max_bytes, include_code):
                    seen.add(path)
                    yield path


def chunks(text: str, page: int | None = None) -> list[Chunk]:
    words = list(re.finditer(r'\S+', text))
    result = []
    for start in range(0, len(words), 210):
        end = min(start + 250, len(words))
        result.append(Chunk(page, words[start].start(), text[words[start].start():words[end - 1].end()]))
        if end == len(words):
            break
    return result


@contextmanager
def quiet_parsers():
    """Third-party diagnostics can contain document bytes; silence this thread only."""
    current = threading.get_ident()
    class Filter(logging.Filter):
        def filter(self, record):
            return record.thread != current
    guard = Filter()
    loggers = [logging.getLogger(name) for name in list(logging.Logger.manager.loggerDict)
               if name.split('.')[0] in {'pypdf', 'docx', 'pptx'}]
    # A parser may create its logger during the read. Guard existing sinks too,
    # including pytest capture and lastResort, so that first warning stays private.
    all_loggers = [logging.getLogger(), *list(logging.Logger.manager.loggerDict.values())]
    handlers = {handler for logger in all_loggers if isinstance(logger, logging.Logger) for handler in logger.handlers}
    if logging.lastResort is not None:
        handlers.add(logging.lastResort)
    guarded = [*loggers, *handlers]
    for target in guarded:
        target.addFilter(guard)
    try:
        yield
    finally:
        for target in guarded:
            target.removeFilter(guard)


def extract(path: Path) -> tuple[list[Chunk], str]:
    """Errors become statuses, never exception strings containing document content."""
    try:
        ext = path.suffix.lower()
        if ext in {'.docx', '.pptx'}:
            with zipfile.ZipFile(path) as archive:
                if len(archive.infolist()) > 10000 or sum(item.file_size for item in archive.infolist()) > 100 * 1024**2:
                    return [], 'error'
        if ext == '.pdf':
            from pypdf import PdfReader
            with quiet_parsers():
                reader = PdfReader(path, strict=True)
                result = [chunk for page, item in enumerate(reader.pages, 1)
                          for chunk in chunks(item.extract_text() or '', page)]
            return result, 'ready' if result else 'needs OCR'
        if ext == '.docx':
            from docx import Document
            with quiet_parsers():
                document = Document(path)
                text = '\n'.join([p.text for p in document.paragraphs] +
                                 [' | '.join(c.text for c in row.cells) for t in document.tables for row in t.rows])
            return chunks(text), 'ready' if text.strip() else 'empty'
        if ext == '.pptx':
            from pptx import Presentation
            with quiet_parsers():
                result = [chunk for number, slide in enumerate(Presentation(path).slides, 1)
                          for chunk in chunks('\n'.join(s.text_frame.text for s in slide.shapes if s.has_text_frame), number)]
            return result, 'ready' if result else 'empty'
        with path.open('r', encoding='utf-8-sig', errors='replace') as stream:
            text = ''.join(itertools.islice(stream, 200)) if ext == '.csv' else stream.read()
        return ([], 'error') if '\x00' in text else (chunks(text), 'ready' if text.strip() else 'empty')
    except Exception:
        return [], 'error'
