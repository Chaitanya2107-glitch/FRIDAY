from datetime import datetime, timezone
import json
from pathlib import Path
import socket

import numpy as np
import pytest

from plugins.semantic_search.embedding import LocalEmbedder
from plugins.semantic_search.query import fuse, parse_filters, snippet
from services.plugin_storage import Settings, user_data_dir
from tests.semantic_search.conftest import EVALUATION, FakeEmbedder


@pytest.mark.parametrize('topic,expected', [(q, name) for q, name, meaning in EVALUATION if not meaning])
def test_evaluation_top_three(indexed, topic, expected):
    assert expected in [row['name'] for row in indexed.search(topic, k=3)]


def test_rrf_combines_channels_without_double_counting():
    scores = fuse([1, 2, 3], [3, 2, 4])
    assert scores[2] == pytest.approx(2 / 62)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert scores[2] > scores[1] and scores[2] > scores[4]
    assert fuse([1, 1, 2])[2] == pytest.approx(1 / 62)


def test_long_document_cannot_starve_other_matching_files(indexed):
    indexed.index_text('long-lecture', 'quantum ' * 55000, {'title': 'Long lecture'})
    indexed.indexer.backfill()
    hits = indexed.search('quantum')
    assert {'Long lecture', 'physics.pdf'} <= {row['name'] for row in hits}


def test_filter_parser_and_filtered_search(indexed):
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    text, filters = parse_filters('the pdf about quantum folder:"Notes" from last week', now)
    assert text == 'quantum' and filters['type'] == 'pdf' and filters['folder'] == 'Notes'
    assert datetime.fromtimestamp(filters['modified_after'], timezone.utc).date().isoformat() == '2026-10-26'
    assert datetime.fromtimestamp(filters['modified_before'], timezone.utc).date().isoformat() == '2026-11-02'
    text, filters = parse_filters('transactions type:slides in the Notes folder this month', now)
    assert text == 'transactions' and filters['type'] == 'slides' and filters['folder'] == 'Notes'
    assert datetime.fromtimestamp(filters['modified_after'], timezone.utc).day == 1
    assert indexed.search('quantum type:pdf folder:Notes')[0]['name'] == 'physics.pdf'
    assert indexed.search('quantum type:slides') == []
    assert indexed.search('quantum', {'modified_before': 1}) == []
    assert indexed.search('quantum', {'folder': 'missing'}) == []


def test_filename_boost_and_snippet(indexed, corpus):
    assert indexed.search(query='quantum', filters={'type': 'pdf'}, k=3)[0]['name'] == 'physics.pdf'
    assert indexed.search('carnot')[0]['name'] == 'carnot.md'
    text = 'Unrelated preamble. ' + 'padding ' * 50 + '. A specific sentence about Carnot reservoirs. More padding.'
    shown = snippet(text, 'Carnot reservoirs')
    assert 'specific sentence about Carnot reservoirs' in shown and len(shown) <= 202


def test_missing_model_still_indexes_keywords_and_can_backfill(service, corpus):
    class Missing:
        def embed(self, texts):
            raise RuntimeError('offline')
    service.embedder = service.indexer.embedder = Missing()
    service.api.settings.set('indexed_roots', [str(corpus)])
    service.indexer.scan()
    assert service.store.stats()['vectors'] == 0
    assert service.search('quantum')[0]['name'] == 'physics.pdf'
    service.embedder = service.indexer.embedder = FakeEmbedder()
    service.indexer.scan()
    assert service.store.stats()['vectors'] == 22


def test_embedder_local_first_and_never_downloads_during_embed(service, monkeypatch):
    model = LocalEmbedder(service.api.data_dir, service.api.settings)
    calls = []
    def missing(local_only):
        calls.append(local_only)
        raise OSError('No connection and no weights')
    monkeypatch.setattr(model, '_load', missing)
    assert not model.prepare(download=False) and calls == [True]
    with pytest.raises(RuntimeError):
        model.embed(['a private document'])
    assert calls == [True]
    assert not model.prepare(download=True) and calls == [True, True, False]
    assert 'Keyword search still works' in model.error


def test_api_search_loads_cached_model_without_download(indexed, monkeypatch):
    model = LocalEmbedder(indexed.api.data_dir, indexed.api.settings)
    calls = []
    class Loaded:
        def embed(self, texts, **kwargs):
            return FakeEmbedder().embed(texts)
    def local_only(local):
        calls.append(local)
        assert local is True
        return Loaded()
    monkeypatch.setattr(model, '_load', local_only)
    indexed.embedder = model
    assert indexed.search('quantum')[0]['name'] == 'physics.pdf'
    assert calls == [True]
    model.lock.acquire()
    try:
        assert model.prepare(download=False) is False
    finally:
        model.lock.release()


def test_model_identity_invalidates_vectors_without_losing_keywords(indexed):
    indexed.store.model_identity('different-model:384')
    assert indexed.store.stats()['vectors'] == 0
    assert indexed.search('quantum')[0]['name'] == 'physics.pdf'


@pytest.mark.parametrize('query,filters,k', [('', None, 5), ('x', {'type': 'exe'}, 5), ('x', {'folder': []}, 5),
    ('x', {'modified_after': float('nan')}, 5), ('x', {'sql': 'DROP TABLE'}, 5), ('x', None, 0)])
def test_service_boundary_validation(indexed, query, filters, k):
    with pytest.raises(ValueError):
        indexed.search(query, filters, k)


@pytest.mark.parametrize('source,text,metadata', [('', 'text', {}), ('x', None, {}), ('x', 'text', {'title': []}),
    ('x', 'text', {'modified_at': float('nan')}), ('x', 'text', {'page': -1}), ('x', 'text', {'type': 'executable'})])
def test_external_boundary_validation(service, source, text, metadata):
    with pytest.raises((ValueError, TypeError)):
        service.index_text(source, text, metadata)


@pytest.mark.slow
def test_real_model_evaluation_offline(corpus, service, monkeypatch):
    """Automatically skipped unless this plugin's model weights are already present."""
    settings = Settings(user_data_dir() / 'plugins' / 'semantic_search' / 'settings.json')
    model = LocalEmbedder(user_data_dir() / 'plugins' / 'semantic_search', settings)
    # Check only existing files; slow tests never download weights.
    if not model.cache_dir.is_dir() and not model.local_folder:
        pytest.skip('Search model not installed. Say prepare search model first.')
    def offline(*args, **kwargs):
        raise AssertionError('Real-model offline test attempted network access')
    monkeypatch.setattr(socket, 'create_connection', offline)
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    if not model.prepare(download=False):
        pytest.skip('Search weights are not installed or not usable locally.')
    service.embedder = service.indexer.embedder = model
    service.store.model_identity(model.identity)
    service.api.settings.set('indexed_roots', [str(corpus)])
    assert service.indexer.scan()
    for query, expected, meaning in EVALUATION:
        assert expected in [row['name'] for row in service.search(query, k=3)], (query, expected)
