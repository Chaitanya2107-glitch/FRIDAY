import asyncio
from datetime import datetime

import pytest

from services.activity import journal
from services.automation import intent
from services.memory import notes, reading_list, semantic
from services.memory.semantic import SemanticMemory, match_memory_command
from tests.test_semantic_memory import WordEmbedder


def say(message):
    return asyncio.run(intent.try_system_action(message, "openai"))


# ── Reading list ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("add this to my reading list", {"action": "add_reading", "url": None, "title": None}),
    ("save this for later", {"action": "add_reading", "url": None, "title": None}),
    ("add the attention paper to my reading list", {"action": "add_reading", "url": None, "title": "the attention paper"}),
    ("what's on my reading list", {"action": "list_reading"}),
    ("open item 2 from my reading list", {"action": "open_reading", "number": 2}),
    ("done with reading list 1", {"action": "done_reading", "number": 1}),
    ("clear my reading list", {"action": "clear_reading"}),
])
def test_reading_list_commands(text, expected):
    match = reading_list.match_reading_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected


def test_reading_list_keeps_the_urls_case_and_this_page(monkeypatch):
    assert say("add https://arxiv.org/abs/1706.03762v7 to my reading list").message.startswith(
        "Added to your reading list: https://arxiv.org/abs/1706.03762v7")
    monkeypatch.setattr(reading_list, "last_page", lambda: ("https://youtu.be/X", "Backprop explained"))
    assert say("save this for later").message == "Added to your reading list: Backprop explained. (2 on it.)"
    assert say("save this for later").message == "That's already on your reading list."
    assert say("what's on my reading list").message == \
        "Your reading list:\n1. https://arxiv.org/abs/1706.03762v7\n2. Backprop explained"
    opened = []
    monkeypatch.setattr(reading_list.system, "open_url", lambda url: opened.append(url) or "Opened.")
    say("open reading list 2")
    assert opened == ["https://youtu.be/X"]
    assert say("done with reading list 1").message == "Crossed off: https://arxiv.org/abs/1706.03762v7."
    assert len(reading_list.load()) == 1


def test_no_recent_page_is_said(monkeypatch):
    monkeypatch.setattr(reading_list, "last_page", lambda: None)
    assert "couldn't find a page" in say("add this to my reading list").message


# ── Journal search ────────────────────────────────────────────────────────────

def test_search_journals_and_todays_diary():
    journal.JOURNAL_DIR.mkdir(parents=True)
    (journal.JOURNAL_DIR / "2026-09-28.md").write_text("# Monday\n\n## Diary\n- 21:00 — DBMS viva prep\n", encoding="utf-8")
    notes.add_diary("the viva went well", datetime(2026, 9, 30, 18, 5))
    reply = say("search my journal for viva")
    assert reply.message == ('"viva" in your journals:\nWed 30 Sep: 18:05 — the viva went well\n'
                             'Mon 28 Sep: 21:00 — DBMS viva prep')
    assert say("what did I write about cricket").message == 'Nothing about "cricket" in your journals.'


# ── Memory: per person, weekly review ─────────────────────────────────────────

@pytest.fixture
def memory(tmp_path, monkeypatch):
    m = SemanticMemory(str(tmp_path / "mem.db"), embedder=WordEmbedder())
    monkeypatch.setattr(semantic, "semantic_memory", m)
    return m


def test_what_do_you_know_about_a_person(memory):
    memory.remember("Ravi likes cricket")
    memory.remember("Priya is my sister")
    memory.remember("Ravindra is my cousin")
    assert match_memory_command("what do you know about me")["action"] == "list_memories"
    parsed = match_memory_command("what do you know about Ravi")
    assert semantic.run_memory_command(parsed) == "What I know about Ravi:\n- Ravi likes cricket"
    assert "don't know anything about Anya" in semantic.run_memory_command(match_memory_command("what do you know about Anya"))


def test_weekly_review_lists_only_what_was_learned(memory):
    memory.remember("User is vegetarian", source="learned")
    memory.remember("my USN is 1RV23", source="told")
    assert semantic.weekly_review() == \
        'This week I picked up 1 thing about you: User is vegetarian. Say "forget that …" for anything wrong.'
    assert semantic.weekly_review(datetime(2027, 1, 1)) is None
