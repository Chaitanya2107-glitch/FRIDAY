"""Conversations remembered (services/memory/episodes.py)."""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.config import config
from providers import failover
from services.memory import episodes
from services.memory.semantic import semantic_memory

START = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def chat(tmp_path, monkeypatch):
    db = tmp_path / "chat.db"
    monkeypatch.setattr(config, "MEMORY_DB_PATH", str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, role TEXT, content TEXT, timestamp TEXT)")
    state = SimpleNamespace(saved=[], asked=[], reply="Talked about the DBMS exam on Friday; the Boss was nervous.")

    def say(*lines, at=START):
        with sqlite3.connect(db) as conn:
            for i, (role, text) in enumerate(lines):
                conn.execute("INSERT INTO conversations (role, content, timestamp) VALUES (?, ?, ?)",
                             (role, text, (at + timedelta(minutes=i)).isoformat()))
    state.say = say

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kwargs):
        state.asked.append(messages[0].content)
        return SimpleNamespace(content=state.reply)
    monkeypatch.setattr(failover, "complete_with_failover", fake_ai)
    monkeypatch.setattr(semantic_memory, "remember", lambda text, source="told", replaces=(): state.saved.append((text, source)))
    return state


def run(now):
    return asyncio.run(episodes.summarize_if_due(now))


TALK = [("user", "I have my DBMS exam on Friday"), ("assistant", "Nervous?"),
        ("user", "a bit, the normalization part scares me"), ("assistant", "We can go over it tonight.")]


def test_first_run_skips_old_history_then_sums_up_a_quiet_chat(chat):
    chat.say(("user", "old stuff"), ("assistant", "ok"), ("user", "more old"), ("assistant", "sure"))
    assert run(START + timedelta(hours=1)) is None and chat.asked == []  # the past isn't summed up all at once
    chat.say(*TALK, at=START + timedelta(hours=2))
    assert run(START + timedelta(hours=2, minutes=10)) is None           # still talking (quiet < 20 min)
    saved = run(START + timedelta(hours=2, minutes=30))
    assert "DBMS exam" in saved and chat.saved == [(saved, "episode")]
    assert "old stuff" not in chat.asked[0] and "Boss: I have my DBMS exam on Friday" in chat.asked[0]
    assert run(START + timedelta(hours=3)) is None                         # summed up once


def test_commands_alone_are_not_a_conversation(chat):
    run(START)  # first run
    chat.say(("user", "open chrome"), ("assistant", "Opening Chrome."))
    assert run(START + timedelta(hours=1)) is None and chat.asked == []


def test_nothing_worth_remembering_saves_nothing(chat):
    run(START)
    chat.reply = "nothing"
    chat.say(*TALK)
    assert run(START + timedelta(hours=1)) is None and chat.saved == []
