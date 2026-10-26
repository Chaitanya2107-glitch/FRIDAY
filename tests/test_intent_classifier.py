import asyncio
import json
import re
from types import SimpleNamespace

import httpx
import pytest

from core.config import config
from core.errors import ProviderError
from providers.base_provider import Message, Tool, ToolCall, parse_openai_tool_calls
from providers.registry import get_provider
from services.automation import actions, intent, writer
from services.automation.command_tools import build_tools, tool_call_to_action
from services.automation.intent import ActionResult, try_system_action

VOLUME_CALL = [ToolCall("set_volume", {"level": 100})]
CHAT_MODELS = {"openrouter": "chat-model", "anthropic": "claude-chat", "ollama": "gemma-local"}


@pytest.fixture(autouse=True)
def default_intent_settings(monkeypatch):
    monkeypatch.setattr(config, "INTENT_PROVIDER", "")
    monkeypatch.setattr(config, "INTENT_MODEL", "")


@pytest.fixture
def providers(monkeypatch):
    """
    Fake get_provider. `behaviour[(name, model)]` = the tool calls to return
    (an empty list = a text-only reply), or an exception to raise.
    """
    calls, behaviour, requests = [], {}, []
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "none")

    def fake_get_provider(name, model=None):
        resolved = model or CHAT_MODELS[name]

        async def complete(messages, system_prompt, max_tokens, temperature, tools):
            calls.append((name, resolved))
            requests.append(SimpleNamespace(messages=messages, system_prompt=system_prompt, tools=tools))
            outcome = behaviour.get((name, resolved), VOLUME_CALL)
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(content="" if outcome else "CHAT", tool_calls=outcome)

        return SimpleNamespace(complete=complete, get_model_name=lambda: resolved)

    monkeypatch.setattr(intent, "get_provider", fake_get_provider)
    monkeypatch.setattr(intent.system, "set_volume", lambda level: f"Volume set to {level}%.")
    monkeypatch.setattr(intent.system, "set_mute", lambda mute: "Muted." if mute else "Unmuted.")
    return SimpleNamespace(calls=calls, behaviour=behaviour, requests=requests)


AI_ONLY_MESSAGE = "volume like a rock concert"


def classify(message=AI_ONLY_MESSAGE, chat_provider="openrouter"):
    # No word list covers this wording, so only the AI can place it.
    return asyncio.run(try_system_action(message, chat_provider))


CHEAP_OPENROUTER = ("openrouter", config.INTENT_DEFAULT_MODELS["openrouter"])


# ── Which model is asked ──────────────────────────────────────────────────────

def test_uses_cheap_default_model_instead_of_chat_model(providers):
    assert classify() == ActionResult(True, "Volume set to 100%.")
    assert providers.calls == [CHEAP_OPENROUTER]


def test_openrouter_default_is_a_model_that_handles_tools():
    assert config.INTENT_DEFAULT_MODELS["openrouter"] == "openai/gpt-4o-mini"


def test_intent_settings_override_the_chat_provider(providers, monkeypatch):
    monkeypatch.setattr(config, "INTENT_PROVIDER", "ollama")
    monkeypatch.setattr(config, "INTENT_MODEL", "tiny-local")

    classify(chat_provider="anthropic")

    assert providers.calls == [("ollama", "tiny-local")]


def test_falls_back_to_chat_model_when_cheap_model_errors(providers):
    providers.behaviour[CHEAP_OPENROUTER] = ProviderError("model does not support tools")

    assert classify() == ActionResult(True, "Volume set to 100%.")
    assert providers.calls == [CHEAP_OPENROUTER, ("openrouter", "chat-model")]


def test_text_reply_means_chat_without_asking_again(providers):
    providers.behaviour[CHEAP_OPENROUTER] = []
    assert classify("show me something fun") is None
    assert providers.calls == [CHEAP_OPENROUTER]


def test_no_second_call_when_cheap_model_is_the_chat_model(providers, monkeypatch):
    monkeypatch.setitem(config.INTENT_DEFAULT_MODELS, "openrouter", "chat-model")
    providers.behaviour[("openrouter", "chat-model")] = ProviderError("down")

    assert classify() is None
    assert providers.calls == [("openrouter", "chat-model")]


def test_ollama_keeps_its_local_model(providers):
    classify(chat_provider="ollama")
    assert providers.calls == [("ollama", "gemma-local")]


def test_every_model_failing_means_treat_as_chat(providers):
    providers.behaviour[CHEAP_OPENROUTER] = ProviderError("down")
    providers.behaviour[("openrouter", "chat-model")] = ProviderError("also down")
    assert classify() is None


def test_falls_back_to_other_providers_when_chat_provider_is_down(providers, monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_PROVIDERS", "ollama")
    providers.behaviour[CHEAP_OPENROUTER] = ProviderError("down")
    providers.behaviour[("openrouter", "chat-model")] = ProviderError("also down")
    classify()
    assert providers.calls[-1] == ("ollama", "gemma-local")


# ── What the model is sent ────────────────────────────────────────────────────

def test_request_carries_the_tools_and_only_the_message(providers):
    classify()
    request = providers.requests[0]
    names = {tool.name for tool in request.tools}
    assert {"open_app", "set_volume", "organise_folder", "set_reminder"} <= names
    assert [m.content for m in request.messages] == [AI_ONLY_MESSAGE]
    assert "JSON" not in request.system_prompt


def test_every_tool_is_an_action_intent_can_run():
    tools = build_tools(["chrome"], ["downloads"])
    # Actions run in actions.py (intent._execute calls it); write_text is first turned into text by the writer
    source = "".join(open(m.__file__, encoding="utf-8").read() for m in (intent, actions, writer))
    assert len({t.name for t in tools}) == len(tools)
    for tool in tools:
        assert tool.parameters["type"] == "object"
        assert re.search(rf'action(?:\.get\("action"\))? (?:== |in \([^)]*)"{tool.name}"', source), tool.name


def test_known_apps_and_folders_are_offered():
    tools = {t.name: t for t in build_tools(["chrome", "spotify"], ["downloads", "music"])}
    assert "chrome, spotify" in tools["open_app"].parameters["properties"]["app_name"]["description"]
    assert tools["organise_folder"].parameters["properties"]["folder"]["enum"] == ["downloads", "music"]


# ── Running the calls ─────────────────────────────────────────────────────────

def test_several_tool_calls_run_in_order_as_one_reply(providers):
    providers.behaviour[CHEAP_OPENROUTER] = [
        ToolCall("set_mute", {"mute": True}),
        ToolCall("set_volume", {"level": 30}),
    ]
    assert classify("mute it, then set the volume to thirty") == ActionResult(True, "Muted. Volume set to 30%.")


def test_one_failing_call_marks_the_reply_unsuccessful(providers, monkeypatch):
    def broken(app_name):
        raise intent.AutomationError(f"I don't know how to open {app_name}.")
    monkeypatch.setattr(intent.system, "open_app", broken)
    providers.behaviour[CHEAP_OPENROUTER] = [ToolCall("open_app", {"app_name": "zzz"}), *VOLUME_CALL]

    # A partially recognized explicit batch is rejected before the AI. Keep
    # this an unfamiliar single request to exercise AI tool-result aggregation.
    result = classify("open zzz with the sound cranked all the way up")

    assert providers.calls == [CHEAP_OPENROUTER]
    assert result == ActionResult(False, "I don't know how to open zzz. Volume set to 100%.")


def test_private_replies_stay_out_of_memory_when_combined(providers, monkeypatch):
    monkeypatch.setattr(intent.system, "read_clipboard", lambda: "Clipboard: hunter2")
    providers.behaviour[CHEAP_OPENROUTER] = [*VOLUME_CALL, ToolCall("read_clipboard", {})]

    result = classify("volume like a rock concert while showing what I copied")

    assert providers.calls == [CHEAP_OPENROUTER]
    assert result.message == "Volume set to 100%. Clipboard: hunter2"
    assert "hunter2" not in result.memory_message
    assert result.memory_message.startswith("Volume set to 100%.")


def test_ai_cannot_close_apps_the_user_did_not_name(providers, monkeypatch):
    closed = []
    monkeypatch.setattr(intent.system, "close_app", lambda app_name: closed.append(app_name) or f"Closed {app_name}.")
    providers.behaviour[CHEAP_OPENROUTER] = [
        ToolCall("close_app", {"app_name": "spotify"}),
        ToolCall("close_app", {"app_name": "whatsapp"}),
    ]

    result = classify("close the Spotify stuff please")

    assert closed == ["spotify"]
    assert result == ActionResult(True, "Closed spotify.")


def test_unknown_or_malformed_calls_are_ignored(providers):
    providers.behaviour[CHEAP_OPENROUTER] = [
        ToolCall("format_hard_drive", {}),
        ToolCall("set_volume", {}),  # missing its level
    ]
    assert classify() is None


def test_folder_names_become_paths_and_organising_still_asks_first(providers, monkeypatch):
    organised = []
    monkeypatch.setattr(intent.system, "count_files_to_organise", lambda path: 3)
    monkeypatch.setattr(intent.system, "organise_folder", lambda path: organised.append(path) or "Done.")
    providers.behaviour[CHEAP_OPENROUTER] = [ToolCall("organise_folder", {"folder": "Downloads"})]

    result = classify("clean up that downloads mess")

    assert result.message.startswith("Organise Downloads? This moves 3 files")
    assert organised == []
    assert intent.is_awaiting_confirmation()
    assert asyncio.run(try_system_action("yes", "openrouter")) == ActionResult(True, "Done.")
    assert organised == [intent.FOLDER_MAP["downloads"]]


def test_unknown_folder_is_not_organised():
    action = tool_call_to_action(ToolCall("organise_folder", {"folder": "system32"}), intent.FOLDER_MAP)
    assert "path" not in action
    assert intent._execute(action) is None


# ── Providers: sending tools and reading calls back ───────────────────────────

VOLUME_TOOL = Tool("set_volume", "Set the volume.", {"type": "object", "properties": {"level": {"type": "integer"}}})


@pytest.fixture
def api_keys(monkeypatch):
    for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setattr(config, key, "test-key")


def _openai_reply(content, tool_calls):
    message = SimpleNamespace(content=content, tool_calls=[
        SimpleNamespace(function=SimpleNamespace(name=name, arguments=args)) for name, args in tool_calls
    ] or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        usage=SimpleNamespace(total_tokens=50, prompt_tokens=40, completion_tokens=10),
    )


def test_openai_tool_calls_with_bad_arguments_are_dropped():
    raw = _openai_reply(None, [("set_volume", '{"level": 40}'), ("set_mute", "{not json"), ("x", "[1]")])
    assert parse_openai_tool_calls(raw.choices[0].message.tool_calls) == [ToolCall("set_volume", {"level": 40})]


@pytest.mark.parametrize("name", ["openrouter", "openai"])
def test_openai_style_providers_send_tools_and_read_calls(name, api_keys, monkeypatch):
    provider = get_provider(name)
    sent = {}

    async def create(**kwargs):
        sent.update(kwargs)
        return _openai_reply(None, [("set_volume", '{"level": 40}')])

    monkeypatch.setattr(provider.client.chat.completions, "create", create)
    result = asyncio.run(provider.complete([Message("user", "volume 40")], tools=[VOLUME_TOOL]))

    assert sent["tools"] == [VOLUME_TOOL.openai_format()]
    assert result.content == ""
    assert result.tool_calls == [ToolCall("set_volume", {"level": 40})]


@pytest.mark.parametrize("name", ["openrouter", "openai"])
def test_openai_style_providers_send_no_tools_for_plain_chat(name, api_keys, monkeypatch):
    provider = get_provider(name)
    sent = {}

    async def create(**kwargs):
        sent.update(kwargs)
        return _openai_reply("Hello!", [])

    monkeypatch.setattr(provider.client.chat.completions, "create", create)
    result = asyncio.run(provider.complete([Message("user", "hi")]))

    assert "tools" not in sent
    assert (result.content, result.tool_calls) == ("Hello!", [])


def test_anthropic_sends_tools_and_reads_mixed_blocks(api_keys, monkeypatch):
    provider = get_provider("anthropic")
    sent = {}

    async def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Sure."),
                SimpleNamespace(type="tool_use", name="set_volume", input={"level": 40}),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=40, output_tokens=10),
        )

    monkeypatch.setattr(provider.client.messages, "create", create)
    result = asyncio.run(provider.complete([Message("user", "volume 40")], tools=[VOLUME_TOOL]))

    assert sent["tools"] == [{
        "name": "set_volume", "description": "Set the volume.", "input_schema": VOLUME_TOOL.parameters,
    }]
    assert result.content == "Sure."
    assert result.tool_calls == [ToolCall("set_volume", {"level": 40})]


def _fake_ollama(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "providers.ollama.client.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_ollama_sends_tools_and_reads_calls(monkeypatch):
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": "set_volume", "arguments": {"level": 40}}}],
        }})

    _fake_ollama(monkeypatch, handler)
    result = asyncio.run(get_provider("ollama").complete([Message("user", "volume 40")], tools=[VOLUME_TOOL]))

    assert sent["tools"] == [VOLUME_TOOL.openai_format()]
    assert result.tool_calls == [ToolCall("set_volume", {"level": 40})]


def test_ollama_model_without_tool_support_is_a_provider_error(monkeypatch):
    _fake_ollama(monkeypatch, lambda request: httpx.Response(
        400, json={"error": "registry.ollama.ai/library/gemma3:4b does not support tools"}))

    with pytest.raises(ProviderError, match="does not support tools"):
        asyncio.run(get_provider("ollama").complete([Message("user", "volume 40")], tools=[VOLUME_TOOL]))


# ── Config ────────────────────────────────────────────────────────────────────

def test_config_rejects_intent_model_without_provider(monkeypatch):
    monkeypatch.setattr(config, "INTENT_MODEL", "some-model")
    assert any("INTENT_MODEL" in error for error in config.validate())


def test_config_rejects_unknown_intent_provider(monkeypatch):
    monkeypatch.setattr(config, "INTENT_PROVIDER", "gemini")
    assert any("INTENT_PROVIDER" in error for error in config.validate())


def test_config_rejects_intent_provider_without_its_api_key(monkeypatch):
    monkeypatch.setattr(config, "INTENT_PROVIDER", "openai")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    assert any("INTENT_PROVIDER=openai needs its API key" in error for error in config.validate())


@pytest.mark.parametrize("name, model_setting", [
    ("openrouter", "OPENROUTER_MODEL"),
    ("anthropic", "ANTHROPIC_MODEL"),
    ("openai", "OPENAI_MODEL"),
    ("ollama", "OLLAMA_MODEL"),
])
def test_get_provider_model_override(name, model_setting, api_keys):
    # The SDKs refuse to build a client without a key, even though no request is sent.
    assert get_provider(name).get_model_name() == getattr(config, model_setting)
    assert get_provider(name, model="override-model").get_model_name() == "override-model"
