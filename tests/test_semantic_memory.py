import asyncio
import re
import zlib
from types import SimpleNamespace

import numpy as np
import pytest

from core.config import config
from providers import failover
from services.automation import intent
from services.memory import semantic
from services.memory.semantic import SemanticMemory, match_memory_command, _parse_facts


class WordEmbedder:
    """Fake embedder: texts sharing more words are closer. Same shape as services/files/embed.py."""
    DIM = 4096

    def encode(self, texts):
        rows = []
        for text in texts:
            v = np.zeros(self.DIM, np.float32)
            for word in re.findall(r"[a-z]+", text.lower()):
                v[zlib.crc32(word.encode()) % self.DIM] += 1  # not hash(): it changes every run (flaky collisions)
            rows.append(v / (np.linalg.norm(v) or 1))
        return np.array(rows, np.float32)

    def encode_query(self, text):
        return self.encode([text])[0]


@pytest.fixture
def memory(tmp_path, monkeypatch):
    m = SemanticMemory(str(tmp_path / "mem.db"), embedder=WordEmbedder())
    monkeypatch.setattr(semantic, "semantic_memory", m)
    return m


# ── Commands ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("remember that my sister is Priya", {"action": "remember", "text": "my sister is Priya"}),
    ("don't forget I'm allergic to peanuts", {"action": "remember", "text": "I'm allergic to peanuts"}),
    ("forget that my sister is Priya", {"action": "forget_memory", "text": "my sister is Priya"}),
    ("forget everything about me", {"action": "forget_all_memories"}),
    ("what do you remember about me", {"action": "list_memories"}),
    ("forget clipboard history", None),   # the clipboard feature's command
    ("forget reminder 2", None),          # the reminders feature's command
    ("remind me at 5pm to call mom", None),
    ("tell me a joke", None),
])
def test_memory_commands(text, expected):
    match = match_memory_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected


def test_remember_recall_forget(memory):
    assert memory.remember("User's sister is named Priya")
    assert memory.remember("User is vegetarian")
    assert not memory.remember("User is vegetarian.")  # near-copy isn't saved twice

    assert memory.recall("who is my sister Priya")[0][0] == "User's sister is named Priya"
    assert memory.recall("zzz qqq") == []  # nothing related

    assert memory.forget("my sister named Priya") == "User's sister is named Priya"
    assert [t for t, _ in memory.all()] == ["User is vegetarian"]
    assert memory.forget("favourite football team") is None
    assert memory.forget_all() == 1 and memory.all() == []


def test_memories_survive_a_restart(memory):
    memory.remember("User is vegetarian")
    again = SemanticMemory(memory.db_path, embedder=WordEmbedder())
    assert [t for t, _ in again.all()] == ["User is vegetarian"]


def test_commands_run_through_the_system_action_flow(memory):
    said = asyncio.run(intent.try_system_action("hey friday, remember that I am vegetarian", "openai"))
    assert said.success and "remember" in said.message
    listed = asyncio.run(intent.try_system_action("what do you remember about me", "openai"))
    assert "I am vegetarian" in listed.message


def test_prompt_section_lists_relevant_memories(memory, monkeypatch):
    monkeypatch.setattr(semantic, "RECALL_MIN_SCORE", 0.1)  # word overlap scores lower than the real model
    assert asyncio.run(memory.prompt_section("anything")) == ""
    memory.remember("User is vegetarian and cooks dinner at home")
    section = asyncio.run(memory.prompt_section("what should I cook for dinner"))
    assert "User is vegetarian" in section and "explicitly owner-told" in section


# ── Learning in the background ────────────────────────────────────────────────

@pytest.mark.parametrize("reply, facts", [
    ('["User is vegetarian", "User lives in Pune"]', ["User is vegetarian", "User lives in Pune"]),
    ('```json\n["User is vegetarian"]\n```', ["User is vegetarian"]),
    ("[]", []),
    ("Nothing to remember.", []),
    ("[not json", []),
])
def test_parse_facts(reply, facts):
    assert _parse_facts(reply) == facts


def test_learns_facts_from_chat_messages(memory, monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_MEMORY_LEARN", True)
    asked = []

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        asked.append(messages[0].content)
        return SimpleNamespace(content='["User is vegetarian"]')
    monkeypatch.setattr(failover, "complete_with_failover", fake_ai)

    async def chat_turns():
        memory.learn_in_background("hi friday", "openai")               # nothing about the user: no AI call
        memory.learn_in_background("I stopped eating meat last year", "openai")
        await asyncio.gather(*memory._background)

    asyncio.run(chat_turns())
    assert len(asked) == 1 and asked[0].endswith("\n\nI stopped eating meat last year")
    assert asked[0].startswith("Today is ")  # so "on Friday" can become a date
    assert memory.all()[0][0] == "User is vegetarian"


def test_learning_off_makes_no_ai_calls(memory, monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_MEMORY_LEARN", False)
    monkeypatch.setattr(failover, "complete_with_failover", lambda *a, **k: pytest.fail("must not call the AI"))

    async def turn():
        memory.learn_in_background("I am vegetarian", "openai")
    asyncio.run(turn())



# ── Plans, updates, strength, conversations ───────────────────────────────────

def test_a_plan_keeps_its_day_and_is_followed_up_once_it_has_happened(memory):
    from datetime import date
    memory.remember("User has a DBMS exam on Friday 3 Oct [2026-10-03]", "learned")
    assert memory.all()[0][0] == "User has a DBMS exam on Friday 3 Oct"  # the tag isn't part of the text
    assert memory.plans(date(2026, 10, 2)) == ([], ["User has a DBMS exam on Friday 3 Oct"])  # coming up
    assert memory.plans(date(2026, 10, 4)) == (["User has a DBMS exam on Friday 3 Oct"], [])  # ask how it went
    memory.mark_followed_up("User has a DBMS exam on Friday 3 Oct")
    assert memory.plans(date(2026, 10, 4)) == ([], [])
    assert memory.plans(date(2026, 10, 20)) == ([], [])  # long past: not followed up any more


def test_replies_see_a_plan_as_past_or_coming_up(memory):
    memory.remember("User has a DBMS exam [2020-01-01]", "learned")
    section = asyncio.run(memory.prompt_section("User DBMS exam"))
    assert "(already happened: 2020-01-01)" in section


def test_an_update_replaces_the_old_fact(memory, monkeypatch):
    memory.remember("User's sister is named Priya", "learned")
    monkeypatch.setattr(semantic, "UPDATE_MIN_SCORE", 0.3)  # the fake embedder's scores are lower than bge-small's

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        assert "1. User's sister is named Priya" in messages[0].content
        return SimpleNamespace(content="[1]", provider="openai")
    monkeypatch.setattr(failover, "complete_with_failover", fake_ai)
    asyncio.run(memory.add_learned("User's sister is named Anya", "openai"))
    assert [t for t, _ in memory.all()] == ["User's sister is named Anya"]


def test_facts_that_can_both_be_true_are_kept(memory, monkeypatch):
    memory.remember("User likes tea", "learned")
    monkeypatch.setattr(semantic, "UPDATE_MIN_SCORE", 0.3)

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        return SimpleNamespace(content="[]", provider="openai")
    monkeypatch.setattr(failover, "complete_with_failover", fake_ai)
    asyncio.run(memory.add_learned("User likes coffee", "openai"))
    assert len(memory.all()) == 2


def test_heard_again_is_stronger_and_unused_guesses_fade_out(memory):
    from datetime import datetime, timedelta
    memory.remember("User is vegetarian", "learned")
    memory.remember("User is vegetarian.", "learned")  # heard again
    memory.remember("User plays the guitar", "learned")
    memory.remember("User's USN is 1RV23", "told")
    assert memory.highlights()[-1] == "User plays the guitar"  # heard once; told and heard-twice facts rank above
    later = datetime.now() + timedelta(days=60)
    for night in range(40):
        memory.fade(later + timedelta(days=night))
    left = [t for t, _ in memory.all()]
    assert "User plays the guitar" not in left              # a weak guess nobody used faded out
    assert "User is vegetarian" in left and "User's USN is 1RV23" in left  # heard twice / told: still there


def test_conversations_are_listed_by_day(memory):
    from datetime import date
    memory.remember("Talked about the DBMS exam; the Boss was stressed", "episode")
    today = date.today()
    assert "DBMS exam" in semantic.talked_about("today", today)
    assert semantic.talked_about("yesterday", today) == "We didn't really talk yesterday."
    assert [t for t, _ in memory.all()] == []  # conversations aren't listed as facts
    assert match_memory_command("what did we talk about yesterday")["when"] == "yesterday"



def test_the_small_local_model_never_deletes_a_fact(memory, monkeypatch):
    memory.remember("User has been working on Friday for a while", "learned")
    monkeypatch.setattr(semantic, "UPDATE_MIN_SCORE", 0.2)

    async def local_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        return SimpleNamespace(content="[1]", provider="ollama")  # a wrong call, as measured
    monkeypatch.setattr(failover, "complete_with_failover", local_ai)
    asyncio.run(memory.add_learned("User has a DBMS exam on Friday 3 Oct [2026-10-03]", "openrouter"))
    assert len(memory.all()) == 2


def test_facts_from_one_message_never_replace_each_other(memory, monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_MEMORY_LEARN", True)
    monkeypatch.setattr(semantic, "UPDATE_MIN_SCORE", 0.2)

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        if system_prompt == semantic.LEARN_PROMPT:
            return SimpleNamespace(content='["User has a DBMS exam on Friday", "User is nervous about the DBMS exam"]',
                                   provider="openai")
        return SimpleNamespace(content="[1]", provider="openai")
    monkeypatch.setattr(failover, "complete_with_failover", fake_ai)
    asyncio.run(memory._learn("I have my DBMS exam on Friday and I'm nervous", "openai"))
    assert len(memory.all()) == 2


def test_a_date_without_brackets_still_counts():
    assert semantic.split_day("User has an exam on Wednesday 2026-09-30") == ("User has an exam on Wednesday", "2026-09-30")
