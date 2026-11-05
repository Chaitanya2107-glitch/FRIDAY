import asyncio
from types import SimpleNamespace

import pytest

from core.errors import ProviderError
from core.config import config
from providers.base_provider import Message
from providers.openrouter import client as openrouter


def reply(content, finish, reasoning=""):
    message = SimpleNamespace(content=content, tool_calls=None, model_extra={"reasoning": reasoning})
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=None, model_extra={})


def provider(replies):
    budgets = []

    async def create(**kw):
        budgets.append(kw["max_tokens"])
        return replies.pop(0)
    p = object.__new__(openrouter.OpenRouterProvider)
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return p, budgets


def ask(p, max_tokens=500):
    return asyncio.run(p._complete_with("m", [], max_tokens, 0.7, None))


def test_unfinished_thinking_is_never_shown_as_the_answer():
    thought = "Okay, the user is asking to open code. Let me recap…"
    p, budgets = provider([reply(thought, "length", thought), reply("I can't open that, Boss.", "stop", "…")])
    assert ask(p).content == "I can't open that, Boss."
    assert budgets == [500, openrouter.THINKING_BUDGET]


def test_still_thinking_after_the_retry_fails_over():
    thought = "Hmm, let me think…"
    p, _ = provider([reply(thought, "length", thought), reply(thought, "length", thought)])
    with pytest.raises(ProviderError):
        ask(p)


def test_a_long_real_answer_that_was_cut_is_kept():
    p, budgets = provider([reply("Here are the steps: 1. …", "length", "short plan")])
    assert ask(p).content.startswith("Here are the steps") and budgets == [500]


@pytest.mark.parametrize("images, expected", [
    ([b"test-image"], ["primary", "vision-backup"]),
    ([], ["primary", "text-only-backup"]),
])
def test_image_failover_uses_separate_vision_backups(monkeypatch, images, expected):
    monkeypatch.setattr(config, "OPENROUTER_BACKUP_MODELS", ["text-only-backup"])
    monkeypatch.setattr(config, "OPENROUTER_VISION_BACKUP_MODELS", ["vision-backup"], raising=False)
    p = object.__new__(openrouter.OpenRouterProvider)
    p.model = "primary"
    calls = []

    async def complete(model, *args):
        calls.append(model)
        if model == "primary":
            raise ProviderError("Upstream overloaded")
        return SimpleNamespace(content="ok")

    p._complete_with = complete
    result = asyncio.run(p.complete([Message(role="user", content="test", images=images)]))
    assert result.content == "ok"
    assert calls == expected


def test_provider_reports_the_model_that_actually_answered():
    response = reply("BLUE", "stop")
    response.model = "working-vision:free"
    p, _ = provider([response])
    assert ask(p).model == "working-vision:free"


def test_blank_vision_backups_do_not_use_chat_backups(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_VISION_BACKUP_MODELS", [], raising=False)
    monkeypatch.setattr(config, "OPENROUTER_BACKUP_MODELS", ["text-only-backup"])
    p = object.__new__(openrouter.OpenRouterProvider)
    p.model = "primary"
    calls = []

    async def fail(model, *args):
        calls.append(model)
        raise ProviderError("Upstream overloaded")

    p._complete_with = fail
    with pytest.raises(ProviderError):
        asyncio.run(p.complete([Message(role="user", content="test", images=[b"test-image"])]))
    assert calls == ["primary"]
