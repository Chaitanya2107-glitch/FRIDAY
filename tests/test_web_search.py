import asyncio
from types import SimpleNamespace

import pytest
from ddgs.exceptions import DDGSException
from fastapi.testclient import TestClient

from core.errors import SearchError
from interfaces.api.app import create_app
from interfaces.api.routes import chat
from services.search import web_search
from services.search.web_search import SearchResult, build_search_context, extract_search_query

FAKE_RESULTS = [
    SearchResult(title="Paris weather", url="https://weather.example/paris", snippet="Sunny, 24°C"),
    SearchResult(title="Forecast", url="https://forecast.example", snippet="Rain tomorrow"),
]


@pytest.mark.parametrize("message, expected", [
    ("\\s bitcoin price", "bitcoin price"),
    ("look up the weather in Paris", "the weather in Paris"),
    ("Look Up Python release dates", "Python release dates"),
    ("search the web for best laptops", "best laptops"),
    ("web search fastapi lifespan", "fastapi lifespan"),
    ("  \\s   padded query  ", "padded query"),
])
def test_extract_search_query_matches_triggers(message, expected):
    assert extract_search_query(message) == expected


@pytest.mark.parametrize("message", [
    "what's the weather",
    "search cats on google",
    "look up",
    "\\s",
    "\\o chrome",
    "",
])
def test_extract_search_query_ignores_other_messages(message):
    assert extract_search_query(message) is None


def test_context_includes_numbered_results_and_citation_rule(monkeypatch):
    monkeypatch.setattr(web_search, "_search", lambda query: FAKE_RESULTS)
    context = asyncio.run(build_search_context("look up weather in Paris"))
    assert '"weather in Paris"' in context
    assert "[1] Paris weather — https://weather.example/paris\nSunny, 24°C" in context
    assert "[2] Forecast" in context
    assert "Cite sources inline" in context


def test_voice_context_asks_for_no_citations(monkeypatch):
    monkeypatch.setattr(web_search, "_search", lambda query: FAKE_RESULTS)
    context = asyncio.run(build_search_context("look up weather in Paris", cite=False))
    assert "Cite sources" not in context
    assert "spoken aloud" in context


def test_normal_message_never_searches(monkeypatch):
    def fail(query):
        raise AssertionError("search should not run for normal chat")
    monkeypatch.setattr(web_search, "_search", fail)
    assert asyncio.run(build_search_context("hello friday")) is None


def test_empty_results_tell_ai_not_to_guess(monkeypatch):
    monkeypatch.setattr(web_search, "_search", lambda query: [])
    context = asyncio.run(build_search_context("\\s zzqqxx"))
    assert "returned no results" in context


def _fake_ddgs(error_message):
    class FakeDDGS:
        def text(self, query, max_results):
            raise DDGSException(error_message)
    return FakeDDGS


def test_ddgs_no_results_exception_becomes_empty_list(monkeypatch):
    monkeypatch.setattr(web_search, "DDGS", _fake_ddgs("No results found."))
    assert web_search._search("zzqqxx") == []


def test_ddgs_network_failure_raises_search_error(monkeypatch):
    monkeypatch.setattr(web_search, "DDGS", _fake_ddgs("ConnectError: timed out"))
    with pytest.raises(SearchError):
        web_search._search("anything")


class FakeMemory:
    def __init__(self):
        self.saved = []

    def get_recent_history(self):
        return []

    def save_message(self, role, content):
        self.saved.append((role, content))


class FakeProvider:
    def __init__(self):
        self.system_prompt = None

    async def complete(self, messages, system_prompt, max_tokens):
        self.system_prompt = system_prompt
        return SimpleNamespace(content="It's sunny [1].", provider="fake", model="fake-model", tokens_used=42)


@pytest.fixture
def chat_client(monkeypatch):
    provider, memory = FakeProvider(), FakeMemory()
    monkeypatch.setattr(chat, "_memory", memory)
    monkeypatch.setattr("providers.failover.get_provider",lambda name: provider)

    async def no_system_action(message, provider_name):
        raise AssertionError("web search requests must not reach system-command matching")
    monkeypatch.setattr(chat, "try_system_action", no_system_action)

    return TestClient(create_app(), base_url="http://127.0.0.1:8000"), provider, memory


def test_chat_route_answers_from_search_results(monkeypatch, chat_client):
    client, provider, memory = chat_client
    monkeypatch.setattr(web_search, "_search", lambda query: FAKE_RESULTS)

    resp = client.post("/api/v1/chat", json={"message": "look up weather in Paris"})

    assert resp.status_code == 200
    assert resp.json()["response"] == "It's sunny [1]."
    assert provider.system_prompt.startswith(chat.config.SYSTEM_PROMPT.rsplit("Today's date", 1)[0])  # the clock may tick
    assert "Sunny, 24°C" in provider.system_prompt
    assert memory.saved == [("user", "look up weather in Paris"), ("assistant", "It's sunny [1].")]


def test_chat_route_returns_502_when_search_fails(monkeypatch, chat_client):
    client, _, memory = chat_client

    def broken(query):
        raise SearchError("Web search failed — check your internet connection and try again.")
    monkeypatch.setattr(web_search, "_search", broken)

    resp = client.post("/api/v1/chat", json={"message": "\\s anything"})

    assert resp.status_code == 502
    assert "Web search failed" in resp.json()["message"]
    assert memory.saved == []
