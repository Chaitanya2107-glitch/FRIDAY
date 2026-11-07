"""FRIDAY's opt-in, offline notes/document search plugin."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

from . import documents, query as search_query
from .embedding import LocalEmbedder
from .indexer import Indexer
from .store import Store

PATTERNS = [
    r'(?:index|start indexing) folder (?P<index_path>.+)',
    r'stop indexing folder (?P<stop_path>.+)',
    r'(?P<operation>list indexed folders|reindex|pause indexing|resume indexing|prepare search model|show index size|'
    r'delete search index|confirm delete search index|cancel delete search index|show more(?: search results)?)',
    r'(?:open|show me) (?:search )?result (?P<number>\d+|one|two|three|four|five)',
    r'(?:find|search my notes for|what (?:did|do) my notes say about) (?P<query>.+)',
]
COMMANDS = [re.compile(pattern, re.I) for pattern in PATTERNS]
PRIVATE_MEMORY = 'Local search command handled privately; document text was not retained.'


def result(text: str, *, ok=True, error=None, data=None) -> dict:
    return dict(ok=ok, text=text, error=error, speech='', **({'data': data} if data is not None else {}))


class SemanticSearch:
    def __init__(self, api, embedder=None):
        self.api = api
        self.store = Store(api.data_dir)
        self.embedder = embedder or LocalEmbedder(api.data_dir, api.settings, self.model_progress)
        self.store.model_identity(getattr(self.embedder, 'identity', type(self.embedder).__name__))
        self.indexer = Indexer(api, self.store, self.embedder)
        self.snapshots = OrderedDict()
        self.lock = threading.RLock()
        self.last_token = ''
        self.confirmation = None

    def model_progress(self, phase: str):
        self.indexer.progress(phase)
        messages = {'downloading_model': 'Downloading search model once. Download progress appears in the backend console. '
                    'Files and searches stay on this computer.',
                    'model_ready': 'Search model ready. Future indexing and searches work offline.',
                    'model_unavailable': 'Search model missing or unavailable offline. Keyword search still works. '
                    'Connect once and say prepare search model, or configure a local model folder.'}
        if phase in messages and not self.api.stop_event.is_set():
            self.api.show_card('Search model', messages[phase], ttl_s=60)

    @staticmethod
    def match_command(text: str):
        from services.automation.command_words import normalize_command
        text = normalize_command(text) or text.strip().rstrip('.!?').strip()
        return next((match for pattern in COMMANDS if (match := pattern.fullmatch(text))), None)

    def search(self, query: str, filters: dict | None = None, k: int = 5) -> list[dict]:
        """Return JSON results locally. This method never downloads model files."""
        self.api._active()
        if isinstance(self.embedder, LocalEmbedder) and not self.embedder.ready:
            self.embedder.prepare(download=False)
        return search_query.search(self.store, self.embedder, query, filters, k)

    def index_text(self, source_id: str, text: str, metadata: dict | None = None) -> dict:
        """Upsert external text; source IDs have their own namespace, without file actions."""
        self.api._active()
        if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 256 or '\n' in source_id:
            raise ValueError('source_id must be nonempty text up to 256 characters.')
        if not isinstance(text, str) or len(text) > 2_000_000:
            raise ValueError('External text must be text up to 2000000 characters.')
        metadata = metadata if metadata is not None else {}
        if not isinstance(metadata, dict) or len(json.dumps(metadata, allow_nan=False)) > 16384:
            raise ValueError('metadata must be a small JSON object.')
        for key in ('title', 'folder'):
            if key in metadata and (not isinstance(metadata[key], str) or len(metadata[key]) > 500):
                raise ValueError('External title and folder must be text up to 500 characters.')
        modified = metadata.get('modified_at', time.time())
        if type(modified) not in {int, float} or not 0 <= modified < 1e12:
            raise ValueError('modified_at must be a finite Unix timestamp.')
        file_kind = metadata.get('type', 'notes')
        if file_kind not in {'pdf', 'slides', 'notes', 'code'}:
            raise ValueError('External type must be pdf, slides, notes or code.')
        page = metadata.get('page', metadata.get('slide'))
        if page is not None and (type(page) is not int or page < 1):
            raise ValueError('Page or slide must be a positive integer.')
        parts = documents.chunks(text, page)
        self.store.replace('plugin:' + source_id, int(modified * 1e9), len(text.encode()), hashlib.sha256(text.encode()).hexdigest(),
                           'ready' if parts else 'empty', file_kind, parts, source='external', metadata=metadata)
        self.indexer.request()
        return dict(chunks=len(parts), source_id=source_id)

    @staticmethod
    def format_hits(hits: list[dict], start=0) -> str:
        return '\n\n'.join(f"{i}. {h['name']} — {h['folder']}"
                            + (f" · {h['location']} {h['page']}" if h['page'] else '')
                            + f" · score {h['score']:.4f}\n{h['snippet']}" for i, h in enumerate(hits, start + 1))

    def remember(self, hits: list[dict]) -> str:
        with self.lock:
            token = secrets.token_hex(16)
            self.snapshots[token] = (time.monotonic(), hits)
            self.last_token = token
            while len(self.snapshots) > 8:
                self.snapshots.popitem(last=False)
            return token

    def hits(self, token: str) -> list[dict]:
        with self.lock:
            item = self.snapshots.get(token)
            return item[1] if item and time.monotonic() - item[0] < 600 else []

    def card(self, token: str, start=0, count=3, *, detail=False):
        hits = self.hits(token)
        shown = hits[start:start + count]
        if not shown:
            return
        actions = [dict(id='select', label=f'Result {i + 1} actions', payload=dict(token=token, number=i + 1))
                   for i in range(start, min(start + count, len(hits)))]
        if detail and shown[0]['source'] == 'file':
            actions = [dict(id=action, label=label, payload=dict(token=token, number=start + 1))
                       for action, label in [('open', 'Open file'), ('folder', 'Open containing folder'), ('copy', 'Copy path')]]
        elif start + count < len(hits):
            actions.append(dict(id='more', label='Show more', payload=dict(token=token)))
        # Event history carries counts/names and opaque references, never snippets/query text.
        self.api.publish('ui.card', dict(title='Search results', body='\n'.join(f'{i}. {h["name"] if h["source"] == "file" else "External text"}'
                         for i, h in enumerate(shown, start + 1)), actions=actions, ttl_s=120,
                         content_ref=token, result_start=start, result_count=count))

    def content(self, request: dict) -> dict:
        params = request.get('query', {})
        try:
            start, count = int(params.get('start', 0)), int(params.get('count', 3))
            if not 0 <= start <= 4 or not 1 <= count <= 5:
                raise ValueError()
            hits = self.hits(params.get('ref', ''))
            return {'body': self.format_hits(hits[start:start + count], start)[:4000] if hits else 'Search results expired. Search again.'}
        except (ValueError, TypeError):
            return {'body': 'Invalid result reference.'}

    def action(self, action: str, payload: dict) -> dict:
        try:
            if action not in {'more', 'select', 'open', 'folder', 'copy'}:
                return result('Unknown search action.', ok=False, error='invalid_action')
            token = payload.get('token', '')
            hits = self.hits(token)
            if not hits:
                return result('Search results expired. Search again.', ok=False, error='expired')
            if action == 'more':
                self.card(token, 3)
                return result('Showing the remaining search results.')
            number = payload.get('number', 0)
            if type(number) is not int or not 1 <= number <= len(hits):
                return result('Choose a valid result number.', ok=False, error='invalid_result')
            if action == 'select':
                self.card(token, number - 1, 1, detail=True)
                return result('Result actions are ready.')
            hit = hits[number - 1]
            path = Path(hit['path'])
            if hit['source'] != 'file' or not documents.allowed_file(path, self.indexer.roots(), *self.indexer.options()):
                return result('This file is missing, excluded, or no longer indexed.', ok=False, error='file_unavailable')
            if action == 'copy':
                from services.automation.clipboard import set_text
                set_text(str(path))
                return result('Path copied.')
            os.startfile(str(path.parent if action == 'folder' else path))
            return result('Opened containing folder.' if action == 'folder' else f'Opened {path.name}.')
        except Exception:
            return result('Could not complete this file action.', ok=False, error='file_action_failed')

    def delete(self, token: str | None = None) -> dict:
        with self.lock:
            pending = self.confirmation
            if not pending or time.monotonic() - pending[1] > 60 or (token is not None and token != pending[0]):
                return result('Ask delete search index first; confirmation expires after one minute.', ok=False, error='confirmation_required')
            self.confirmation = None
            self.api.settings.set('indexed_roots', [])
            self.snapshots.clear()
            self.last_token = ''
            self.indexer.request(delete=True)
        return result('Deleting the search index and clearing indexed folders. Your documents and downloaded model are kept.')

    def command(self, match) -> dict:
        try:
            return self._command(match)
        except (ValueError, OSError, TypeError):
            return result('Invalid search setting, path or query. Use an absolute readable folder path and valid settings.',
                          ok=False, error='invalid_input')

    def _command(self, match) -> dict:
        groups = match.groupdict()
        if topic := groups.get('query'):
            hits = self.search(topic)
            if hasattr(self.embedder, 'ready') and not self.embedder.ready and not self.indexer.model_attempted:
                self.indexer.request(prepare=True)
            token = self.remember(hits)
            if hits:
                self.card(token)
            text = self.format_hits(hits) or 'No matching indexed documents. Say index folder <absolute path> to add notes.'
            if hasattr(self.embedder, 'ready') and not self.embedder.ready:
                text += '\n' + self.embedder.error
            return result(text, data={'results': hits})
        if number := groups.get('number'):
            number = {'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5'}.get(number.casefold(), number)
            return self.action('open', dict(token=self.last_token, number=int(number)))
        roots = self.indexer.roots()
        if raw := groups.get('index_path') or groups.get('stop_path'):
            path = Path(raw.strip().strip('"\'')).expanduser()
            if not path.is_absolute() or '..' in path.parts:
                raise ValueError('Absolute folder required.')
            if groups.get('index_path') and not documents.allowed_root(path):
                return result('That folder is unavailable or excluded (hidden/system folder or .nosearch).', ok=False, error='excluded_folder')
            path = path.resolve()
            if groups.get('stop_path'):
                roots = [r for r in roots if r != path]
            elif path not in roots:
                roots.append(path)
            self.api.settings.set('indexed_roots', [str(r) for r in roots])
            self.indexer.request(cancel=True)
            return result(f'{"Stopped indexing" if groups.get("stop_path") else "Indexing queued for"} {path.name}. '
                          'Watch index.progress events. Say show index size for status.')
        operation = groups['operation'].casefold()
        if operation == 'list indexed folders':
            return result('\n'.join(str(p) for p in roots) or 'No indexed folders. Say index folder <absolute path>.')
        if operation in {'pause indexing', 'resume indexing'}:
            self.api.settings.set('indexing_paused', operation == 'pause indexing')
            if operation == 'resume indexing':
                self.indexer.request()
            return result('Indexing paused.' if operation == 'pause indexing' else 'Indexing resumed.')
        if operation in {'reindex', 'prepare search model'}:
            self.indexer.request(prepare=operation == 'prepare search model')
            return result('Search model preparation queued. The first download needs internet; progress appears here and in the backend console.'
                          if operation == 'prepare search model' else 'Reindex queued.')
        if operation == 'show index size':
            stats = self.store.stats()
            return result(f"{stats['files']} files, {stats['chunks']} chunks, {stats['vectors']} vectors; "
                          f"{stats['bytes'] / 1024**2:.2f} MB; {stats['needs_ocr']} PDFs need OCR; {stats['errors']} unreadable files. "
                          f"{'Indexing.' if self.indexer.scanning else 'Idle.'} Last pass: {self.indexer.last_elapsed:.3f} s.", data=stats)
        if operation == 'delete search index':
            token = secrets.token_hex(16)
            self.confirmation = token, time.monotonic()
            self.api.show_card('Delete search index?', 'Delete indexed text/vectors and clear indexed folders? Your documents and model stay. '
                               'Say confirm delete search index within one minute, or cancel delete search index.',
                               actions=[dict(id='confirm_delete', label='Delete index', payload={'confirmation': token})], ttl_s=60)
            return result('Delete the search index and clear indexed folders? Say confirm delete search index or cancel delete search index.')
        if operation == 'confirm delete search index':
            return self.delete()
        if operation == 'cancel delete search index':
            self.confirmation = None
            return result('Search index deletion cancelled.')
        return self.action('more', {'token': self.last_token})


def register(api):
    service = SemanticSearch(api)
    api.provide('semantic_search', service)
    api.on_command(PATTERNS, service.command, help='Offline hybrid search of explicitly indexed notes/documents.',
                   examples=['find the pdf about thermodynamics', 'search my notes for entropy', 'prepare search model', 'show index size'])
    api.add_route('GET', 'results', service.content)
    for action in ('open', 'folder', 'copy', 'select', 'more'):
        api.on_action(action, lambda payload, action=action: service.action(action, payload))
    api.on_action('confirm_delete', lambda payload: service.delete(payload.get('confirmation', '')))
    api.subscribe('activity.idle_started', lambda event: setattr(service.indexer, 'idle', True))
    api.subscribe('activity.idle_ended', lambda event: setattr(service.indexer, 'idle', False))
    api.run_background(service.indexer.run)
