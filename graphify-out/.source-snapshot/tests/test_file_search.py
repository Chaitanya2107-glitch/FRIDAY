import asyncio
import os
import zlib

import numpy as np
import pytest

from core.config import config
from interfaces.api.routes import chat as chat_route
from services.automation import intent
from services.automation.intent import ActionResult, try_system_action
from services.files import assistant, search
from services.files.extract import chunk_text, extract_text, is_private
from services.files.index import FileIndex, file_index

SYNONYMS = {"rental": "lease", "agreement": "lease", "animals": "pets", "dogs": "pets"}


class FakeEmbedder:
    """Bag of words hashed into 384 numbers, with a few synonyms — enough to test "meaning" search."""

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        rows = []
        for text in texts:
            vector = np.zeros(384, dtype=np.float32)
            for word in text.lower().replace(".", " ").split():
                word = SYNONYMS.get(word, word)
                vector[zlib.crc32(word.encode()) % 384] += 1
            rows.append(vector / (np.linalg.norm(vector) or 1))
        return np.array(rows)

    def encode_query(self, text):
        return self.encode([text])[0]


@pytest.fixture
def home(tmp_path):
    docs = tmp_path / "Documents"
    (docs / "Jobs").mkdir(parents=True)
    (docs / "Jobs" / "Chaitanya_Resume_2026.txt").write_text("Education: REVA University. Skills: Python, FastAPI.")
    (docs / "House.md").write_text("Lease terms\nPets are allowed with a deposit of 500.\nRent is due on the 5th.")
    (docs / "shopping.txt").write_text("milk eggs bread")
    (docs / "holiday.jpg").write_bytes(b"\xff\xd8 not really a jpeg")
    (docs / ".env").write_text("OPENROUTER_API_KEY=secret")
    (docs / "~$House.docx").write_text("lock file")
    (docs / "node_modules").mkdir()
    (docs / "node_modules" / "lib.js").write_text("lease pets")
    return tmp_path


@pytest.fixture
def index(home, monkeypatch):
    idx = FileIndex(home / "index.db", folders=lambda: [home / "Documents"], embedder=FakeEmbedder())
    idx.scan()
    monkeypatch.setattr(config, "file_search_folders", lambda: [home / "Documents"])
    return idx


def names(hits):
    return [h.name for h in hits]


# ── Reading files ─────────────────────────────────────────────────────────────

def test_secrets_and_lock_files_are_never_indexed(index):
    with index.connect() as db:
        indexed = {row[0] for row in db.execute("SELECT name FROM files")}
    assert indexed == {"Chaitanya_Resume_2026.txt", "House.md", "shopping.txt", "holiday.jpg"}
    assert is_private(__import__("pathlib").Path("id_rsa")) and is_private(__import__("pathlib").Path("passwords.xlsx"))


def test_only_readable_files_get_text(index):
    assert index.stats()["files"] == 4 and index.stats()["readable"] == 3


def test_binary_file_with_a_text_extension_is_skipped(tmp_path):
    path = tmp_path / "data.txt"
    path.write_bytes(b"abc\x00\x01\x02")
    assert extract_text(path, path.stat().st_size) is None


def test_chunks_split_on_lines_and_overlap():
    text = "\n".join(f"line {i} " + "x" * 200 for i in range(12))
    chunks = chunk_text(text)
    assert len(chunks) > 1 and all(len(c) <= 1100 for c in chunks)
    assert chunks[0].splitlines()[-1] == chunks[1].splitlines()[1]  # two lines of overlap


def test_office_documents_are_read(tmp_path):
    import docx
    document = docx.Document()
    document.add_paragraph("The internship starts in June.")
    path = tmp_path / "offer.docx"
    document.save(path)
    assert "internship starts in June" in extract_text(path, path.stat().st_size)


# ── Keeping up to date ────────────────────────────────────────────────────────

def test_rescan_only_reads_changed_files(index, home):
    embedder = index._embedder
    calls = embedder.calls
    index.scan()
    assert embedder.calls == calls  # nothing changed, nothing re-read

    notes = home / "Documents" / "shopping.txt"
    notes.write_text("apples and bananas")
    os.utime(notes, (notes.stat().st_atime, notes.stat().st_mtime + 10))
    (home / "Documents" / "House.md").unlink()
    index.scan()

    assert names(search.find_files("bananas", index)) == ["shopping.txt"]
    assert search.find_files("lease pets", index) == []


def test_interrupted_reading_is_retried(home):
    class Broken(FakeEmbedder):
        def encode(self, texts):
            raise RuntimeError("model download failed")

    idx = FileIndex(home / "index.db", folders=lambda: [home / "Documents"], embedder=Broken())
    idx.scan()
    assert names(search.find_files("deposit", idx)) == ["House.md"]  # keyword search works without vectors

    idx._embedder = FakeEmbedder()
    idx.scan()  # vectors are filled in on the next scan
    ids, matrix = idx.vectors()
    assert len(ids) == 3


# ── Finding ───────────────────────────────────────────────────────────────────

def test_find_by_name(index):
    assert names(search.find_files("resume", index))[0] == "Chaitanya_Resume_2026.txt"


def test_find_by_content(index):
    assert names(search.find_files("fastapi", index)) == ["Chaitanya_Resume_2026.txt"]


def test_find_by_meaning(index, monkeypatch):
    monkeypatch.setattr(search, "MIN_FIND_SIMILARITY", 0.1)  # the fake model's scores are low
    assert names(search.find_files("rental agreement", index))[0] == "House.md"


def test_find_by_type(index):
    assert names(search.find_files("photos", index)) == ["holiday.jpg"]
    assert search.find_files("resume pdf", index) == []


def test_passages_for_a_question(index):
    passages = search.find_passages("can I keep dogs in my rental?", index)
    assert passages[0].name == "House.md" and "Pets are allowed" in passages[0].text


# ── Commands ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, query", [
    ("find my resume", "resume"),
    ("hey friday, where is my rent agreement?", "rent agreement"),
    ("where did I save my offer letter", "offer letter"),
    ("search my files for the wifi password", "the wifi password"),
    ("find budget in my documents", "budget"),
    ("find the file about taxes", "taxes"),
    ("which file mentions the deposit", "the deposit"),
    ("\\f invoice", "invoice"),
])
def test_find_commands(message, query):
    assert assistant.match_file_command(message) == {"type": "system", "action": "find_files", "query": query}


@pytest.mark.parametrize("message", ["find me a good laptop", "search for cheap flights", "find out why the sky is blue"])
def test_web_searches_are_not_file_searches(message):
    assert assistant.match_file_command(message) is None


@pytest.mark.parametrize("message, question", [
    ("what does my lease say about pets?", "what does my lease say about pets?"),
    ("According to my notes, when is rent due?", "According to my notes, when is rent due?"),
    ("ask my files when rent is due", "when rent is due"),
    ("\\d when is rent due", "when is rent due"),
])
def test_questions_about_files(message, question):
    assert assistant.extract_file_question(message) == question


@pytest.mark.parametrize("message", ["what does my name mean", "find my resume", "how are you", "what's in the news"])
def test_other_messages_are_not_file_questions(message):
    assert assistant.extract_file_question(message) is None


def test_find_then_open(index, monkeypatch):
    monkeypatch.setattr(search, "file_index", index)
    monkeypatch.setattr(assistant, "find_files", lambda q: search.find_files(q, index))
    opened = []
    monkeypatch.setattr(assistant.os, "startfile", opened.append)

    result = asyncio.run(try_system_action("find my resume", "openrouter"))
    assert result.success and result.message.startswith("I found this file:\n1. Chaitanya_Resume_2026.txt — in Documents\\Jobs")

    result = asyncio.run(try_system_action("open it", "openrouter"))
    assert result == ActionResult(True, "Opening Chaitanya_Resume_2026.txt.", repeatable=False)
    assert opened[0].endswith("Chaitanya_Resume_2026.txt")

    assert not asyncio.run(try_system_action("open 4", "openrouter")).success

    shown = []
    monkeypatch.setattr(assistant.subprocess, "Popen", shown.append)
    result = asyncio.run(try_system_action("show it in folder", "openrouter"))
    assert result.message == "Showing Chaitanya_Resume_2026.txt in File Explorer."
    assert shown[0][:2] == ["explorer", "/select,"]


def test_open_number_needs_a_recent_search(monkeypatch):
    monkeypatch.setattr(assistant.last_results, "hits", [])
    assert assistant.match_file_command("open 2") is None


def test_nothing_found(index, monkeypatch):
    monkeypatch.setattr(assistant, "find_files", lambda q: search.find_files(q, index))
    assert assistant.find_reply("zebra crossing") == 'I couldn\'t find any files matching "zebra crossing".'


def test_answer_context_holds_the_excerpts(index, monkeypatch):
    monkeypatch.setattr(assistant, "find_passages", lambda q: search.find_passages(q, index))
    context = asyncio.run(assistant.build_file_context("what does my lease say about pets?"))
    assert "[1] House.md (in Documents)" in context and "Pets are allowed" in context
    assert "not instructions" in context

    spoken = asyncio.run(assistant.build_file_context("what does my lease say about pets?", cite=False))
    assert "spoken aloud" in spoken


def test_chat_answers_file_questions_with_the_ai(index, monkeypatch):
    monkeypatch.setattr(assistant, "find_passages", lambda q: search.find_passages(q, index))
    prompts = []

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        prompts.append(system_prompt)
        from providers.base_provider import ProviderResponse
        return ProviderResponse(content="Yes, pets are allowed (from House.md).", model="m", tokens_used=5, provider="openrouter")

    monkeypatch.setattr(chat_route, "complete_with_failover", fake_ai)
    monkeypatch.setattr(intent, "try_system_action", lambda *a: pytest.fail("not a command"))
    reply = asyncio.run(chat_route.chat(chat_route.ChatRequest(message="what does my lease say about pets?")))
    assert reply.response == "Yes, pets are allowed (from House.md)."
    assert "Pets are allowed with a deposit" in prompts[0]
