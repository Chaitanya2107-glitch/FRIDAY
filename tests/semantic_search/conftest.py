"""Synthetic documents only; no user files, models, apps or network in fast tests."""
import json
import logging
from pathlib import Path
import re
import shutil
import threading
import time
import zlib

import numpy as np
import pytest

from plugins.semantic_search import documents
from plugins.semantic_search.main import SemanticSearch
from services.event_bus import EventBus
from services.plugin_manager import PluginManager
from services.plugin_api import PluginAPI
from services.plugin_storage import Settings

MANAGED_BACKGROUND = PluginAPI.run_background

EVALUATION = [
    ('Carnot cycle reservoirs', 'carnot.md', False),
    ('lease pets deposit', 'lease.txt', False),
    ('photosynthesis chlorophyll', 'botany.md', False),
    ('bread sourdough starter', 'baking.txt', False),
    ('mortgage interest amortization', 'mortgage.md', False),
    ('Mars rover geology', 'space.txt', False),
    ('firewall network packets', 'network.rst', False),
    ('mitochondria ATP', 'biology.txt', False),
    ('volcano magma eruption', 'geology.md', False),
    ('budget expenses revenue', 'budget.csv', False),
    ('quantum entanglement', 'physics.pdf', False),
    ('database transactions durability', 'databases.pptx', False),
    ('heat engine efficiency', 'carnot.md', True),
    ('can my landlord let me keep a dog', 'lease.txt', True),
    ('turning sunlight into plant food', 'botany.md', True),
]


def pytest_configure(config):
    config.addinivalue_line('markers', 'slow: real local embedding model; skipped when weights are absent')


class FakeEmbedder:
    identity = 'test-crc32-v1'

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        rows = np.zeros((len(texts), 384), np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r'\w+', text.casefold()):
                rows[i, zlib.crc32(word.encode()) % 384] += 1
        return rows / np.maximum(np.linalg.norm(rows, axis=1, keepdims=True), 1e-12)


def write_pdf(path, pages):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            stream.set_data(f'BT /F1 12 Tf 40 740 Td ({escaped}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as output:
        writer.write(output)


class API:
    def __init__(self, folder):
        self.data_dir = folder
        self.settings = Settings(folder / 'settings.json')
        self.log = logging.getLogger('friday.plugins.semantic_search')
        self.stop_event = threading.Event()
        self.bus = EventBus()

    def _active(self):
        if self.stop_event.is_set():
            raise RuntimeError('Unloaded')

    def publish(self, topic, payload):
        self._active()
        return self.bus.publish(topic, payload, plugin_id='semantic_search')

    def show_card(self, title, body, actions=(), ttl_s=30):
        return self.publish('ui.card', dict(title=title, body=body, actions=list(actions), ttl_s=ttl_s))


@pytest.fixture(autouse=True)
def temporary_roots(tmp_path, monkeypatch):
    # Windows pytest temp directories live under hidden AppData. Allow only the
    # test environment's ancestors, retaining every exclusion inside each corpus.
    ancestors = set(tmp_path.parents)
    original = documents.blocked_folder
    monkeypatch.setattr(documents, 'blocked_folder', lambda p: False if p in ancestors else original(p))


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / 'Notes'
    root.mkdir()
    content = {
        'carnot.md': 'The Carnot cycle operates reversibly between hot and cold reservoirs. Its upper bound is one minus the ratio of their absolute temperatures.',
        'lease.txt': 'Lease terms: pets are allowed with a deposit of 500. Rent is due on the fifth. The tenant must keep animals indoors.',
        'botany.md': 'Photosynthesis uses chlorophyll in leaves. Carbon dioxide and water become glucose with solar radiation.',
        'baking.txt': 'Bread recipes: feed your sourdough starter daily. Knead the dough, proof it and bake in a hot oven.',
        'mortgage.md': 'Mortgage interest and amortization determine the monthly loan payment on a house.',
        'space.txt': 'The Mars rover studies geology and samples ancient rocks on the red planet.',
        'network.rst': 'A firewall inspects network packets and rejects unauthorized inbound connections.',
        'biology.txt': 'Mitochondria produce ATP during cellular respiration in eukaryotic cells.',
        'geology.md': 'A volcano releases magma during an eruption. Lava cools into igneous rock.',
        'budget.csv': 'category,amount\nrevenue,5000\nexpenses,2000\nbudget,3000\n',
        'running.txt': 'Marathon training alternates easy runs, interval sessions and a weekly long run.',
        'gardening.md': 'Tomatoes need regular watering, compost and at least six hours of sun.',
        'music.txt': 'A minor chord contains the root, minor third and perfect fifth.',
        'travel.md': 'The Kyoto itinerary includes temples, trains and a spring visit to the bamboo grove.',
        'statistics.rst': 'A confidence interval estimates uncertainty around a sample mean.',
        'history.txt': 'The Roman senate debated legislation before the imperial period.',
        'painting.md': 'Watercolour techniques include wet washes and transparent layers of pigment.',
    }
    for name, text in content.items():
        (root / name).write_text(text, encoding='utf-8')
    write_pdf(root / 'physics.pdf', ['Classical mechanics describes momentum.', 'Quantum entanglement correlates distant particles.'])
    from docx import Document
    doc = Document()
    doc.add_paragraph('A project meeting scheduled the architecture review for Tuesday.')
    doc.save(root / 'meeting.docx')
    from pptx import Presentation
    deck = Presentation()
    for text in ['Database overview', 'Database transactions provide atomicity, consistency, isolation and durability.']:
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, 6000000, 1000000).text = text
    deck.save(root / 'databases.pptx')
    assert len(list(root.iterdir())) == 20
    return root


@pytest.fixture
def service(tmp_path):
    api = API(tmp_path / 'userdata')
    value = SemanticSearch(api, FakeEmbedder())
    yield value
    api.stop_event.set()
    api.bus.close()


@pytest.fixture
def indexed(service, corpus):
    service.api.settings.set('indexed_roots', [str(corpus)])
    assert service.indexer.scan()
    return service


@pytest.fixture
def host(tmp_path, monkeypatch):
    # The shared autouse fixture suppresses native plugin jobs for legacy tests;
    # this isolated fake-embedder host explicitly exercises the managed worker.
    monkeypatch.setattr(PluginAPI, 'run_background', MANAGED_BACKGROUND)
    folder = tmp_path / 'code' / 'semantic_search'
    shutil.copytree(Path(__file__).resolve().parents[2] / 'plugins' / 'semantic_search', folder)
    source = folder / 'main.py'
    source.write_text(source.read_text(encoding='utf-8').replace('service = SemanticSearch(api)',
                      'from tests.semantic_search.conftest import FakeEmbedder\n    service = SemanticSearch(api, FakeEmbedder())'), encoding='utf-8')
    helper = folder / 'documents.py'
    helper.write_text(helper.read_text(encoding='utf-8') + '\nfrom plugins.semantic_search.documents import blocked_folder\n', encoding='utf-8')
    manager = PluginManager(folder.parent, tmp_path / 'data', bus=EventBus())
    manager.scan()
    assert manager.get_service('semantic_search') is not None, manager.list_plugins()
    yield manager
    manager.close()
    manager.bus.close()


def wait_for(predicate, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'Search background worker did not finish'
