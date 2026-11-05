"""Local evidence of edits to FRIDAY; disk changes do not prove loaded behavior."""

import asyncio
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import threading
import time

from core.config import config
from core.logger import logger
from services.settings_store import save

POLL_SECONDS = 10
RECENT_SECONDS = 120
MAX_FILES = 5000
MAX_ENTRIES = 25000
MAX_DEPTH = 25
MAX_FILE_BYTES = 2 * 1024 * 1024
HISTORY_LIMIT = 10
PATH_LIMIT = 20
ROOTS = {
    'core': 'configuration', 'services': 'assistant services',
    'interfaces': 'interfaces', 'providers': 'AI providers', 'plugins': 'plugins',
    'tests': 'tests', 'docs': 'documentation', 'island/src': 'Island interface',
    'island/src-tauri/src': 'Island native shell', 'island/tests': 'tests',
    'island/src-tauri/capabilities': 'Island native shell',
}
FILES = {
    'main.py': 'backend', 'requirements.txt': 'dependencies',
    'README.md': 'documentation', 'island/README.md': 'documentation',
    'launch_friday.bat': 'launchers', 'launch_friday.vbs': 'launchers',
    'run.bat': 'launchers', 'island/package.json': 'Island interface',
    'train_friday.py': 'backend', 'train_friday.bat': 'launchers',
    'college_schedules.bat': 'launchers', 'college_schedules.vbs': 'launchers',
    'island/package-lock.json': 'Island interface', 'island/tsconfig.json': 'Island interface',
    'island/vite.config.ts': 'Island interface', 'island/index.html': 'Island interface',
    'island/src-tauri/Cargo.toml': 'Island native shell',
    'island/src-tauri/Cargo.lock': 'Island native shell',
    'island/src-tauri/tauri.conf.json': 'Island native shell',
    'island/src-tauri/build.rs': 'Island native shell',
}
EXCLUDED = {'__pycache__', 'node_modules', 'target', 'dist', 'build', 'venv',
            'memory', 'logs', 'assets', 'models', 'secrets', 'credentials'}
SUFFIXES = {'.py', '.ts', '.tsx', '.js', '.css', '.html', '.rs', '.toml', '.md', '.json'}
BACKEND = {'configuration', 'assistant services', 'interfaces', 'AI providers',
           'plugins', 'backend', 'dependencies', 'launchers'}
ISLAND = {'Island interface', 'Island native shell'}


def _component(relative: str) -> str | None:
    parts = PurePosixPath(relative).parts
    if (not parts or PurePosixPath(relative).is_absolute() or '\\' in relative
            or any(p.startswith('.') or p.lower() in EXCLUDED for p in parts)):
        return None
    if relative in FILES:
        return FILES[relative]
    if PurePosixPath(relative).suffix.lower() in SUFFIXES:
        return next((label for root, label in ROOTS.items() if relative.startswith(root + '/')), None)
    return None


def _linked(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _linked_within(path: Path, root: Path) -> bool:
    while path != root:
        if _linked(path):
            return True
        path = path.parent
    return False


def _difference(before: dict, after: dict) -> dict:
    return {'added': sorted(after.keys() - before.keys()),
            'modified': sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
            'deleted': sorted(before.keys() - after.keys())}


def _summary(changes: dict) -> dict:
    components = sorted({_component(p) for group in changes.values() for p in group})
    return {'counts': {kind: len(paths) for kind, paths in changes.items()},
            'components': components,
            'files': {kind: paths[:PATH_LIMIT] for kind, paths in changes.items()}}


class DevelopmentAwareness:
    def __init__(self, root: Path, path: Path):
        self.root, self.path = Path(root).resolve(), Path(path).absolute()
        self._lock = threading.Lock()
        self._manifest = self._baseline = None
        self._cache = {}
        self._history = []
        self._running = False
        self._view = {'available': False, 'checked_at': None, 'last_change_at': None,
                      'scan_error': None, 'history_state': 'not loaded', 'storage_error': False,
                      'watched_files': 0, 'since_startup': _summary(_difference({}, {})),
                      'recent_changes': []}

    def _files(self):
        if not self.root.is_dir() or _linked(self.root):
            raise OSError('Source root unavailable')
        for relative in FILES:
            target = self.root / relative
            if not _linked_within(target, self.root):
                if target.exists():
                    yield target
        inspected = 0
        for relative in ROOTS:
            base = self.root / relative
            if not base.exists() or _linked_within(base, self.root):
                continue
            pending = [(base, 0)]
            while pending:
                parent, depth = pending.pop()
                if _linked_within(parent, self.root):
                    continue
                if not parent.resolve().is_relative_to(self.root):
                    raise ValueError('Source escaped root')
                with os.scandir(parent) as entries:
                    for entry in entries:
                        inspected += 1
                        if inspected > MAX_ENTRIES:
                            raise ValueError('Source entry limit')
                        target = Path(entry.path)
                        if entry.name.startswith('.') or entry.name.lower() in EXCLUDED or _linked(target):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if depth >= MAX_DEPTH:
                                raise ValueError('Source depth limit')
                            pending.append((target, depth + 1))
                        elif _component(target.relative_to(self.root).as_posix()):
                            yield target

    def _snapshot(self):
        manifest, cache = {}, {}
        for target in self._files():
            if _linked_within(target, self.root):
                raise OSError('Source became a link')
            if not target.resolve().is_relative_to(self.root):
                raise ValueError('Source escaped root')
            relative = target.relative_to(self.root).as_posix()
            info = target.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES or len(manifest) >= MAX_FILES:
                raise ValueError('Source scan limit or nonregular file')
            previous = self._cache.get(relative)
            with target.open('rb') as source:
                # Windows path.stat and fstat expose different ctime meanings; use one handle.
                opened = os.fstat(source.fileno())
                signature = (opened.st_mtime_ns, opened.st_ctime_ns, opened.st_size, opened.st_ino)
                if opened.st_ino != info.st_ino or opened.st_size > MAX_FILE_BYTES:
                    raise OSError('Source changed before read')
                if previous and previous[0] == signature:
                    digest = previous[1]
                else:
                    content = source.read(MAX_FILE_BYTES + 1)
                    if len(content) > MAX_FILE_BYTES:
                        raise ValueError('Source read limit')
                    digest = hashlib.sha256(content).hexdigest()
                after = os.fstat(source.fileno())
                if signature != (after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_ino):
                    raise OSError('Source changed during scan')
            manifest[relative] = digest
            cache[relative] = (signature, digest)
        return manifest, cache

    def _load(self):
        try:
            if not self.path.exists():
                return None, [], 'new baseline'
            if self.path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError('History limit')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data['version'] != 1 or data['root'] != hashlib.sha256(str(self.root).encode()).hexdigest():
                raise ValueError('Different source root or history version')
            manifest, history = data['manifest'], data['history']
            if not isinstance(manifest, dict) or len(manifest) > MAX_FILES or not isinstance(history, list) or len(history) > HISTORY_LIMIT:
                raise ValueError('Invalid history')
            for name, digest in manifest.items():
                if not _component(name) or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('Invalid manifest')
            cleaned = []
            for event in history:
                if (type(event['at']) not in {int, float} or not math.isfinite(event['at'])
                        or event['origin'] not in {'during run', 'between runs'}):
                    raise ValueError('Invalid event')
                counts = {k: event['counts'][k] for k in ('added', 'modified', 'deleted')}
                if any(type(n) is not int or not 0 <= n <= MAX_FILES for n in counts.values()):
                    raise ValueError('Invalid event counts')
                components = event['components']
                if not isinstance(components, list) or any(c not in set(ROOTS.values()) | set(FILES.values()) for c in components):
                    raise ValueError('Invalid components')
                files = {k: event['files'][k] for k in counts}
                if any(not isinstance(paths, list) or len(paths) > PATH_LIMIT or any(not isinstance(p, str) or not _component(p) for p in paths) for paths in files.values()):
                    raise ValueError('Invalid event paths')
                cleaned.append({'at': event['at'], 'origin': event['origin'], 'counts': counts,
                                'components': sorted(set(components)), 'files': files})
            return manifest, cleaned, 'restored'
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError):
            logger.debug('Development history unavailable; establishing a fresh baseline')
            return None, [], 'previous history unavailable'

    def scan(self, now: float | None = None) -> dict:
        """Only this worker performs IO; prompts read an atomically replaced view."""
        now = time.time() if now is None else now
        with self._lock:
            try:
                manifest, cache = self._snapshot()
            except (OSError, ValueError, RuntimeError) as error:
                logger.debug('Development scan deferred (%s)', type(error).__name__)
                self._view = {**self._view, 'available': False, 'scan_error': type(error).__name__}
                return self.status(now)
            first = self._manifest is None
            history_state = self._view['history_state']
            if first:
                previous, self._history, history_state = self._load()
                self._baseline = manifest
            else:
                previous = self._manifest
            changed = _summary(_difference(previous, manifest)) if previous is not None else None
            if changed and any(changed['counts'].values()):
                event = {'at': now, 'origin': 'between runs' if first else 'during run', **changed}
                self._history = [*self._history, event][-HISTORY_LIMIT:]
            else:
                changed = None
            self._manifest, self._cache = manifest, cache
            storage_error = False
            if first or changed or self._view['storage_error']:
                try:
                    save(self.path, {'version': 1, 'root': hashlib.sha256(str(self.root).encode()).hexdigest(),
                                     'manifest': manifest, 'history': self._history})
                except OSError:
                    storage_error = True
                    logger.debug('Development snapshot persistence unavailable')
            self._view = {'available': True, 'checked_at': now,
                          'last_change_at': self._history[-1]['at'] if self._history else None,
                          'scan_error': None, 'history_state': history_state, 'storage_error': storage_error,
                          'watched_files': len(manifest), 'recent_changes': self._history,
                          'since_startup': _summary(_difference(self._baseline, manifest))}
            if changed:
                from services.mind.cognition import cognition
                cognition.record('observation', 'system',
                    'FRIDAY source changes observed: ' + json.dumps(changed['counts'])
                    + '. Components: ' + ', '.join(changed['components'])
                    + '. Saved source does not prove loaded behavior or successful validation.', public=True)
                logger.debug('Development awareness recorded %s source changes', sum(changed['counts'].values()))
            return self.status(now)

    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        view = deepcopy(self._view)
        recent = view['last_change_at']
        components = set(view['since_startup']['components'])
        return {**view, 'monitor_running': self._running,
                'recent_edits': bool(view['available'] and recent is not None and 0 <= now - recent <= RECENT_SECONDS),
                'restart_recommended': bool(components & BACKEND),
                'island_rebuild_recommended': bool(components & ISLAND),
                'runtime_verification': 'Disk snapshots only; loaded code and upgrade success are unverified.'}

    def context(self) -> dict:
        """Fixed labels and counts only; no filenames, hashes, roots or source text."""
        view = self.status()
        latest = view['recent_changes'][-1] if view['recent_changes'] else {}
        return {k: view[k] for k in ('available', 'monitor_running', 'checked_at', 'recent_edits',
                                    'restart_recommended', 'island_rebuild_recommended', 'runtime_verification',
                                    'history_state', 'storage_error')} | {
            'changed_since_startup': sum(view['since_startup']['counts'].values()),
            'components_since_startup': view['since_startup']['components'],
            'last_observed_change': {k: latest[k] for k in ('at', 'origin', 'counts', 'components') if k in latest}}

    def describe(self, *, details: bool = True) -> str:
        view = self.status()
        if view['checked_at'] is None:
            return "My code-change monitor has not established a source baseline yet. I can't verify edits right now."
        lines = ['I noticed recent edits to my own source, Boss.' if view['recent_edits']
                 else 'My local code-change monitor has no recent source activity to report.']
        if not view['available']:
            lines[0] = 'My last source scan failed; current code changes are unknown. The last good snapshot is retained.'
        from datetime import datetime
        lines.append(f"Last successful check: {datetime.fromtimestamp(view['checked_at']).astimezone():%Y-%m-%d %H:%M:%S %Z}.")
        pending = sum(view['since_startup']['counts'].values())
        lines.append(f"{pending} files differ from my monitor-startup snapshot.")
        if view['restart_recommended']:
            lines.append('Restart FRIDAY to load backend changes reliably.')
        if view['island_rebuild_recommended']:
            lines.append('Rebuild and relaunch the Island to use its source changes.')
        for event in view['recent_changes'][-3:]:
            counts = event['counts']
            lines.append(f"Observed {event['origin']}: {counts['added']} added, {counts['modified']} modified, "
                         f"{counts['deleted']} deleted; {', '.join(event['components'])}.")
            for kind, paths in (event['files'].items() if details else []):
                if paths:
                    lines.append(kind.title() + ': ' + ', '.join(paths) +
                                 (f" (showing {len(paths)} of {counts[kind]})" if counts[kind] > len(paths) else '') + '.')
        if view['storage_error'] or view['history_state'] == 'previous history unavailable':
            lines.append('Persistent change history is incomplete; earlier edits may be unavailable.')
        lines.append("File edits don't tell me who made them, what behavior improved, or whether checks passed.")
        return '\n'.join(lines)

    async def run(self):
        self._running = True
        try:
            while True:
                try:
                    await asyncio.to_thread(self.scan)
                except Exception as error:
                    self._view = {**self._view, 'available': False, 'scan_error': type(error).__name__}
                    logger.debug('Development monitor retrying (%s)', type(error).__name__)
                await asyncio.sleep(POLL_SECONDS)
        finally:
            self._running = False


development = DevelopmentAwareness(config.ROOT_DIR, config.MEMORY_DIR / 'mind' / 'development.json')
