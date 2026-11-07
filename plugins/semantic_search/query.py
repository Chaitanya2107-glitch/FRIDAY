"""Offline hybrid ranking and small, explicit query filters."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re

import numpy as np

from .embedding import normalized

TYPES = {'pdf': 'pdf', 'pdfs': 'pdf', 'slides': 'slides', 'slide': 'slides', 'pptx': 'slides',
         'notes': 'notes', 'note': 'notes', 'code': 'code'}


def parse_filters(query: str, now: datetime | None = None) -> tuple[str, dict]:
    now = now or datetime.now().astimezone()
    filters = {}
    def type_filter(match):
        filters['type'] = TYPES[match[1].casefold()]
        return ' '
    query = re.sub(r'\btype:(pdfs?|slides?|pptx|notes?|code)\b', type_filter, query, flags=re.I)
    query = re.sub(r'^(?:the\s+)?(pdfs?|slides?|notes?|code)\s+(?:about|on|for)\s+', type_filter, query, flags=re.I)
    def folder_filter(match):
        filters['folder'] = next(g for g in match.groups() if g is not None).strip()
        return ' '
    query = re.sub(r'\bfolder:(?:"([^"]+)"|([^\s]+))', folder_filter, query, flags=re.I)
    query = re.sub(r'\s+in\s+(?:the\s+)?(?:folder\s+"([^"]+)"|folder\s+([^,]+?)|([^,]+?)\s+folder)(?=\s+(?:from last week|this month)\b|$)',
                   folder_filter, query, flags=re.I)
    if re.search(r'\b(?:from\s+)?last week\b', query, re.I):
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        filters.update(modified_after=(monday - timedelta(days=7)).timestamp(), modified_before=monday.timestamp())
        query = re.sub(r'\b(?:from\s+)?last week\b', ' ', query, flags=re.I)
    if re.search(r'\b(?:from\s+)?this month\b', query, re.I):
        filters.update(modified_after=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp(),
                       modified_before=now.timestamp() + 1)
        query = re.sub(r'\b(?:from\s+)?this month\b', ' ', query, flags=re.I)
    return ' '.join(query.split()), filters


def fuse(*rankings: list, constant: int = 60) -> dict:
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(dict.fromkeys(ranking), 1):
            scores[item] = scores.get(item, 0) + 1 / (constant + rank)
    return scores


def snippet(text: str, query: str, length: int = 200) -> str:
    terms = {w.casefold() for w in re.findall(r'\w+', query) if len(w) > 2}
    sentences = list(re.finditer(r'[^.!?\n]+[.!?]?', text))
    best = max(sentences, key=lambda s: len(terms & set(re.findall(r'\w+', s[0].casefold()))), default=None)
    start = best.start() if best else 0
    if best and len(best[0]) > length:
        term = next((m for m in re.finditer(r'\w+', best[0]) if m[0].casefold() in terms), None)
        start += max(0, (term.start() if term else 0) - length // 3)
    return ('…' if start else '') + ' '.join(text[start:start + length].split()) + ('…' if start + length < len(text) else '')


def search(store, embedder, query: str, filters: dict | None = None, k: int = 5) -> list[dict]:
    if not isinstance(query, str) or not 0 < len(query.strip()) <= 2000 or type(k) is not int or not 1 <= k <= 100:
        raise ValueError('Use a nonempty query up to 2000 characters and k between 1 and 100.')
    query, parsed = parse_filters(query)
    if filters is not None and not isinstance(filters, dict):
        raise ValueError('Search filters must be an object.')
    parsed.update(filters or {})
    if set(parsed) - {'type', 'folder', 'modified_after', 'modified_before'}:
        raise ValueError('Unknown search filter.')
    if 'type' in parsed and parsed['type'] not in {'pdf', 'slides', 'notes', 'code'}:
        raise ValueError('Search type must be pdf, slides, notes or code.')
    if 'folder' in parsed and (not isinstance(parsed['folder'], str) or not parsed['folder'].strip()):
        raise ValueError('Folder filter must be nonempty text.')
    for key in ('modified_after', 'modified_before'):
        if key in parsed and (type(parsed[key]) not in {int, float} or not np.isfinite(parsed[key])):
            raise ValueError('Modified date filters must be finite Unix timestamps.')
    rows = store.rows()
    eligible = {}
    for row in rows:
        folder = str(Path(row['path']).parent) if row['source'] == 'file' else json.loads(row['metadata']).get('folder', '')
        modified = row['mtime'] / 1e9
        if (('type' not in parsed or row['kind'] == parsed['type'])
                and ('folder' not in parsed or parsed['folder'].casefold() in folder.casefold())
                and modified >= parsed.get('modified_after', float('-inf'))
                and modified < parsed.get('modified_before', float('inf'))):
            eligible[row['id']] = row
    terms = re.findall(r'\w+', query)[:40]
    expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
    # Filter before truncating each channel, so a small filtered folder is not starved.
    lexical = [i for i in store.keywords(expression, max(200, len(rows))) if i in eligible]
    semantic = []
    if query and eligible:
        try:
            values = normalized(embedder.embed([query]), 1)[0]
            ids, matrix = store.vectors()
            if len(ids) and matrix.shape[1] == len(values):
                selected = np.flatnonzero(np.isin(ids, list(eligible)))
                similarities = matrix[selected] @ values
                semantic = [int(ids[selected[i]]) for i in np.argsort(-similarities, kind='stable')
                            if similarities[i] > .15]
        except Exception:
            pass  # Keyword search is always available when model files are missing/busy.
    names = [i for i, row in eligible.items() if query and
             query.casefold() in {Path(row['path']).name.casefold(), Path(row['path']).stem.casefold()}]
    def file_ranking(ranking):
        best = {}
        for item in ranking:
            path = eligible[item]['path']
            if path not in best:
                best[path] = item
                if len(best) == 200:
                    break
        return best
    lexical_files, semantic_files, named_files = map(file_ranking, (lexical, semantic, names))
    # Fuse files so long documents cannot occupy every candidate slot; preserve
    # the winning chunk for its snippet, even when channels choose different pages.
    scores = fuse(list(lexical_files), list(semantic_files), list(named_files))
    for path in named_files:
        scores[path] += 1 / 60
    best = {**named_files, **semantic_files, **lexical_files}
    result = []
    for path in sorted(scores, key=lambda p: (-scores[p], p.casefold())):
        row = eligible[best[path]]
        meta = json.loads(row['metadata'])
        name = Path(row['path']).name if row['source'] == 'file' else meta.get('title', row['path'][7:])
        result.append(dict(path=row['path'], name=name, folder=str(Path(row['path']).parent) if row['source'] == 'file'
                           else meta.get('folder', ''), page=row['page'], location='slide' if row['kind'] == 'slides' else 'page',
                           offset=row['offset'], snippet=snippet(store.text(best[path]), query), score=round(scores[path], 6),
                           type=row['kind'], source=row['source']))
        if len(result) == k:
            break
    return result
