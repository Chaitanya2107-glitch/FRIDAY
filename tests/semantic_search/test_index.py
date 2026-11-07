import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from plugins.semantic_search import documents
from plugins.semantic_search.main import SemanticSearch
from tests.semantic_search.conftest import API, FakeEmbedder, wait_for, write_pdf


def test_corpus_index_metadata_and_float32(indexed):
    stats = indexed.store.stats()
    assert stats['files'] == 20 and stats['vectors'] == stats['chunks'] == 22
    pdf = indexed.search('quantum entanglement')[0]
    slides = indexed.search('transactions durability')[0]
    assert pdf['name'] == 'physics.pdf' and pdf['page'] == 2
    assert slides['name'] == 'databases.pptx' and slides['page'] == 2 and slides['location'] == 'slide'
    with indexed.store.connect() as db:
        assert {r[0] for r in db.execute('SELECT length(embedding) FROM chunks')} == {384 * 4}
    assert indexed.store.vectors()[1].dtype.name == 'float32'


def test_incremental_edit_add_delete_and_hash_only_on_stamp_change(indexed, corpus, monkeypatch):
    calls = indexed.embedder.calls
    original = hashlib.file_digest
    monkeypatch.setattr(hashlib, 'file_digest', lambda *a, **kw: pytest.fail('Unchanged file hashed'))
    indexed.indexer.scan()
    assert indexed.embedder.calls == calls
    monkeypatch.setattr(hashlib, 'file_digest', original)
    (corpus / 'baking.txt').write_text('Pumpernickel rye flour fermentation.', encoding='utf-8')
    (corpus / 'new.txt').write_text('A zeppelin crosses the sky.', encoding='utf-8')
    (corpus / 'space.txt').unlink()
    indexed.indexer.scan()
    assert indexed.search('pumpernickel')[0]['name'] == 'baking.txt'
    assert indexed.search('zeppelin')[0]['name'] == 'new.txt'
    assert all(r['name'] != 'space.txt' for r in indexed.search('Mars rover'))
    assert indexed.store.stats()['files'] == 20


def test_same_content_new_mtime_does_not_reextract(indexed, corpus, monkeypatch):
    import os
    path = corpus / 'baking.txt'
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    monkeypatch.setattr(documents, 'extract', lambda p: pytest.fail('Same hash re-extracted'))
    calls = indexed.embedder.calls
    indexed.indexer.scan()
    assert indexed.embedder.calls == calls


def test_exclusions_nosearch_secrets_size_and_opt_in_code(service, tmp_path):
    root = tmp_path / 'documents'
    root.mkdir()
    for folder in ['node_modules', '.git', 'venv', '__pycache__', 'AppData', 'Windows', 'Program Files', '.hidden', 'private']:
        (root / folder).mkdir()
        (root / folder / 'ignored.txt').write_text('Excluded document canary')
    (root / 'private' / '.nosearch').touch()
    for name in ['.env', '.env.local', 'key.pem', 'certificate.key', 'id_rsa', 'vault.kdbx', 'my_passwords.txt', '~$lock.docx']:
        (root / name).write_text('Secret canary')
    (root / 'photo.jpg').write_bytes(b'image')
    (root / 'too_large.txt').write_text('x' * 2000)
    (root / 'small.txt').write_text('A public note')
    (root / 'source.py').write_text('print("public code")')
    service.api.settings.set('indexed_roots', [str(root)])
    service.api.settings.set('max_file_mb', .001)
    service.indexer.scan()
    assert {Path(p).name for p in service.store.known()} == {'small.txt'}
    service.api.settings.set('include_code', True)
    service.indexer.scan()
    assert {Path(p).name for p in service.store.known()} == {'small.txt', 'source.py'}
    assert not service.command(service.match_command(f'index folder {root / "private"}'))['ok']
    (root / '.nosearch').touch()
    service.indexer.scan()
    assert service.store.stats()['files'] == 0


def test_scanned_and_bad_pdf_do_not_crash(service, tmp_path):
    root = tmp_path / 'papers'
    root.mkdir()
    write_pdf(root / 'scanned.pdf', [''])
    (root / 'damaged.pdf').write_bytes(b'not a PDF')
    service.api.settings.set('indexed_roots', [str(root)])
    assert service.indexer.scan()
    assert service.store.known()[str(root / 'scanned.pdf')]['status'] == 'needs OCR'
    assert service.store.stats()['needs_ocr'] == 1 and service.store.stats()['errors'] == 1
    assert service.api.bus.recent('index.done')[-1]['payload']['needs_ocr'] == 1


def test_transient_extraction_error_retried_without_rehashing(service, corpus, monkeypatch):
    service.api.settings.set('indexed_roots', [str(corpus)])
    original = documents.extract
    monkeypatch.setattr(documents, 'extract', lambda p: ([], 'error') if p.name == 'carnot.md' else original(p))
    assert service.indexer.scan()
    assert service.store.known()[str(corpus / 'carnot.md')]['status'] == 'error'
    monkeypatch.setattr(documents, 'extract', original)
    monkeypatch.setattr(hashlib, 'file_digest', lambda *a: pytest.fail('Unchanged error file was rehashed'))
    assert service.indexer.scan()
    assert service.search('Carnot')[0]['name'] == 'carnot.md'


def test_resume_after_mid_file_crash(service, corpus, monkeypatch):
    service.api.settings.set('indexed_roots', [str(corpus)])
    original = documents.extract
    count = 0
    def killed(path):
        nonlocal count
        count += 1
        if count == 6:
            raise KeyboardInterrupt('simulated process termination')
        return original(path)
    monkeypatch.setattr(documents, 'extract', killed)
    with pytest.raises(KeyboardInterrupt):
        service.indexer.scan()
    assert service.store.stats()['pending'] == 1
    monkeypatch.setattr(documents, 'extract', original)
    api = API(service.api.data_dir)
    restarted = SemanticSearch(api, FakeEmbedder())
    try:
        assert restarted.indexer.scan()
        assert restarted.store.stats()['files'] == 20 and restarted.store.stats()['pending'] == 0
        assert restarted.store.stats()['vectors'] == restarted.store.stats()['chunks']
    finally:
        api.bus.close()


def test_recover_after_process_is_killed_mid_file(service, corpus, tmp_path):
    marker = tmp_path / 'worker-entered-file'
    script = '''
from pathlib import Path
import sys, time
from plugins.semantic_search import documents
from plugins.semantic_search.main import SemanticSearch
from tests.semantic_search.conftest import API, FakeEmbedder
root, data, marker = map(Path, sys.argv[1:])
original_blocked = documents.blocked_folder
ancestors = set(root.parent.parents)
documents.blocked_folder = lambda p: False if p in ancestors else original_blocked(p)
api = API(data)
api.settings.set('indexed_roots', [str(root)])
service = SemanticSearch(api, FakeEmbedder())
original = documents.extract
count = 0
def interrupted(path):
    global count
    count += 1
    if count == 6:
        marker.touch()
        time.sleep(60)
    return original(path)
documents.extract = interrupted
service.indexer.scan()
'''
    child = subprocess.Popen([sys.executable, '-B', '-c', script, str(corpus), str(service.api.data_dir), str(marker)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(marker.exists)
        child.terminate()  # Only this test's own child process; no backend/user processes.
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    assert service.store.stats()['pending'] == 1
    assert service.indexer.scan()
    assert service.store.stats()['files'] == 20 and service.store.stats()['pending'] == 0
    assert service.store.stats()['vectors'] == 22


def test_chunks_overlap_offsets_and_csv_limit(tmp_path):
    text = ' '.join(f'word{i}' for i in range(600))
    parts = documents.chunks(text, 4)
    assert len(parts[0].text.split()) == 250
    assert parts[0].text.split()[-40:] == parts[1].text.split()[:40]
    assert all(p.page == 4 and text[p.offset:].startswith(p.text) for p in parts)
    path = tmp_path / 'table.csv'
    path.write_text('\n'.join(f'line{i}' for i in range(300)))
    extracted, status = documents.extract(path)
    assert status == 'ready' and 'line199' in extracted[0].text
    assert 'line200' not in ''.join(p.text for p in extracted)


def test_external_index_text_is_upserted_and_survives_rescan(indexed):
    indexed.index_text('lecture:7', 'Capacitance stores electrostatic energy.',
                       {'title': 'Lecture seven', 'folder': 'Lectures', 'slide': 8, 'type': 'slides'})
    indexed.indexer.scan()
    hit = indexed.search('electrostatic')[0]
    assert hit['name'] == 'Lecture seven' and hit['source'] == 'external' and hit['page'] == 8
    assert not indexed.action('open', {'token': indexed.remember([hit]), 'number': 1})['ok']
    indexed.index_text('lecture:7', 'Dielectric materials increase capacitance.', {'title': 'Lecture revised'})
    indexed.indexer.scan()
    assert indexed.search('Dielectric')[0]['name'] == 'Lecture revised'
    assert len(indexed.store.known('external')) == 1


def test_progress_throttled_and_pause_resume_cancel(indexed, monkeypatch):
    clock = [100.]
    monkeypatch.setattr('plugins.semantic_search.indexer.time.monotonic', lambda: clock[0])
    indexed.indexer.last_progress = float('-inf')
    before = len(indexed.api.bus.recent('index.progress'))
    for i in range(10):
        indexed.indexer.progress('extracting', i, 10, 'Notes')
        clock[0] += .1
    assert len(indexed.api.bus.recent('index.progress')) - before == 1
    indexed.api.settings.set('indexing_paused', True)
    indexed.api.stop_event.set()
    assert not indexed.indexer.checkpoint()


def test_background_commands_idle_rescan_and_reload(host, corpus):
    service = host.get_service('semantic_search')
    assert service.indexer.roots() == []
    assert 'No indexed folders' in host.command('list indexed folders')['text']
    assert host.command('pause indexing')['ok']
    assert host.command(f'index folder "{corpus}"')['ok']
    assert host.command('resume indexing')['ok']
    wait_for(lambda: bool(host.bus.recent('index.done')))
    assert service.store.stats()['files'] == 20
    assert host.command('find the pdf about quantum entanglement')['data']['results'][0]['page'] == 2
    host.scan(force=True)
    newer = host.get_service('semantic_search')
    assert newer is not service and newer.indexer.roots() == [corpus]
    (corpus / 'idle.txt').write_text('Automatic idle rescan')
    newer.indexer.last_scan = __import__('time').time()
    newer.indexer.idle = True
    newer.indexer.last_scan -= 901
    wait_for(lambda: str(corpus / 'idle.txt') in newer.store.known())
    assert host.command(f'stop indexing folder "{corpus}"')['ok']
    wait_for(lambda: newer.store.stats()['files'] == 0)


def test_background_pause_keeps_commands_responsive(host, corpus):
    service = host.get_service('semantic_search')
    host.command('pause indexing')
    assert host.command(f'index folder "{corpus}"')['ok']
    wait_for(lambda: service.indexer.scanning)
    time.sleep(.15)
    assert service.store.stats()['files'] == 0
    start = time.monotonic()
    assert host.command('list indexed folders')['ok']
    assert time.monotonic() - start < .5
    assert host.command('resume indexing')['ok']
    wait_for(lambda: service.store.stats()['vectors'] == 22)


def test_external_only_index_resumes_after_reload_without_roots(host, monkeypatch):
    service = host.get_service('semantic_search')
    monkeypatch.setattr(service.indexer, 'request', lambda **kwargs: None)
    service.index_text('lecture:unfinished', 'Capacitance stores electrostatic energy.', {'title': 'Lecture'})
    assert service.store.stats()['vectors'] == 0 and service.indexer.roots() == []
    host.scan(force=True)
    newer = host.get_service('semantic_search')
    wait_for(lambda: newer.store.stats()['vectors'] == 1)
    assert newer.search('electrostatic')[0]['name'] == 'Lecture'
