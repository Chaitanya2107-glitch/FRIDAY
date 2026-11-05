"""A file reference belongs to the conversation that produced its results."""

import asyncio
from contextlib import contextmanager

import pytest

from core.config import config
from services.automation.intent import remote_request
from services.files import assistant
from services.files.search import FileHit


@contextmanager
def channel(remote):
    token = remote_request.set(remote)
    try:
        yield
    finally:
        remote_request.reset(token)


@pytest.fixture
def files(tmp_path, monkeypatch):
    hits = []
    for name in ("resume.txt", "cover-letter.txt", "notes.txt"):
        path = tmp_path / name
        path.write_text(name)
        hits.append(FileHit(str(path), name))
    monkeypatch.setattr(config, "FILE_SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "file_search_folders", lambda: [tmp_path])
    monkeypatch.setattr(assistant, "find_files", lambda query: {
        "resume": hits[:2], "notes": hits[2:], "missing": [],
    }[query])
    return hits


def test_telegram_cannot_resolve_a_laptop_result(files):
    assistant.find_reply("resume")
    with channel(True):
        assert assistant.last_results.get() == []
        assert assistant.match_file_command("open 1") is None


@pytest.mark.parametrize("select", ["open_result", "reveal_result"])
def test_interleaved_searches_and_selections_keep_their_own_files(files, monkeypatch, select):
    monkeypatch.setattr(assistant.os, "startfile", lambda path: None)
    monkeypatch.setattr(assistant.subprocess, "Popen", lambda args: None)
    assistant.find_reply("resume")
    getattr(assistant, select)(2)

    with channel(True):
        assistant.find_reply("notes")
        assert assistant.last_results.selected is None
        getattr(assistant, select)(1)
        assert assistant.last_results.selected == files[2]
        assert assistant.match_file_command("open last")["number"] == 1

    assert assistant.last_results.get() == files[:2]
    assert assistant.last_results.selected == files[1]
    assert assistant.match_file_command("open last")["number"] == 2
    assert assistant._result(1) == files[0]


def test_empty_telegram_search_does_not_clear_laptop_results_or_selection(files):
    assistant.find_reply("resume")
    assistant.last_results.selected = files[1]
    with channel(True):
        assistant.find_reply("missing")
        assert assistant.last_results.get() == []
    assert assistant.last_results.get() == files[:2]
    assert assistant.last_results.selected == files[1]


def test_a_new_search_resets_only_its_channels_selection(files):
    assistant.find_reply("resume")
    assistant.last_results.selected = files[1]
    with channel(True):
        assistant.find_reply("notes")
        assistant.last_results.selected = files[2]
    assistant.find_reply("resume")
    assert assistant.last_results.selected is None
    with channel(True):
        assert assistant.last_results.selected == files[2]


def test_search_expiry_is_independent_in_each_channel(files, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(assistant.time, "monotonic", lambda: clock[0])
    assistant.find_reply("resume")
    clock[0] += assistant.RESULTS_VALID_SECONDS - 1
    with channel(True):
        assistant.find_reply("notes")
    clock[0] += 2

    assert assistant.last_results.get() == []
    assert assistant.match_file_command("open 1") is None
    with channel(True):
        assert assistant.last_results.get() == files[2:]
        assert assistant.match_file_command("open 1")["number"] == 1


def test_threaded_searches_persist_in_their_channel_across_async_requests(files):
    async def scenario():
        laptop_searched = asyncio.Event()
        telegram_searched = asyncio.Event()

        async def laptop_request():
            with channel(False):
                await asyncio.to_thread(assistant.find_reply, "resume")
                laptop_searched.set()
                await telegram_searched.wait()
                return await asyncio.to_thread(assistant._result, 1)

        async def telegram_request():
            with channel(True):
                await laptop_searched.wait()
                await asyncio.to_thread(assistant.find_reply, "notes")
                telegram_searched.set()
                return await asyncio.to_thread(assistant._result, 1)

        assert await asyncio.gather(laptop_request(), telegram_request()) == [files[0], files[2]]

    asyncio.run(scenario())
    assert assistant.last_results.get() == files[:2]
    with channel(True):
        assert assistant.last_results.get() == files[2:]
