import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import config
from interfaces.api.app import create_app
from interfaces.api.routes import chat
from providers.base_provider import ToolCall
from services.automation import command_cache, intent
from services.automation.intent import ActionResult, try_system_action
from services.voice import tts as tts_module

# ── Command cache ─────────────────────────────────────────────────────────────


@pytest.fixture
def ai(monkeypatch):
    """A fake AI that counts its calls. Set `reply` to the tool calls it returns, or an exception."""
    state = SimpleNamespace(calls=0, reply=[ToolCall("set_volume", {"level": 100})])

    def get_provider(name, model=None):
        async def complete(**kwargs):
            state.calls += 1
            if isinstance(state.reply, Exception):
                raise state.reply
            return SimpleNamespace(content="" if state.reply else "CHAT", tool_calls=state.reply)
        return SimpleNamespace(complete=complete, get_model_name=lambda: model or "chat-model")

    monkeypatch.setattr(config, "INTENT_PROVIDER", "")
    monkeypatch.setattr(config, "INTENT_MODEL", "")
    monkeypatch.setattr(intent, "get_provider", get_provider)
    monkeypatch.setattr(intent.system, "set_volume", lambda level: f"Volume set to {level}%.")
    monkeypatch.setattr(intent.system, "write_clipboard", lambda text: f"Copied {text}.")
    return state


def ask(message):
    return asyncio.run(try_system_action(message, "openrouter"))


def test_the_same_message_only_asks_the_ai_once(ai):
    assert ask("volume like a rock concert") == ActionResult(True, "Volume set to 100%.")
    assert ask("volume like a rock concert") == ActionResult(True, "Volume set to 100%.")
    assert ai.calls == 1


def test_cached_decisions_still_run_the_action_each_time(ai, monkeypatch):
    levels = []
    monkeypatch.setattr(intent.system, "set_volume", lambda level: levels.append(level) or "ok")
    ask("volume like a rock concert")
    ask("volume like a rock concert")
    assert levels == [100, 100]


def test_wording_differences_share_one_entry(ai):
    ask("volume like a rock concert")
    ask("Hey Friday, VOLUME like a rock concert please!")
    assert ai.calls == 1


def test_chat_decisions_are_cached_too(ai):
    ai.reply = []
    assert ask("show me something fun") is None
    assert ask("show me something fun") is None
    assert ai.calls == 1


def test_failures_are_not_cached(ai):
    ai.reply = RuntimeError("provider down")
    assert ask("volume like a rock concert") is None
    ai.reply = [ToolCall("set_volume", {"level": 100})]
    assert ask("volume like a rock concert") == ActionResult(True, "Volume set to 100%.")


def test_a_new_app_starts_fresh(ai, monkeypatch):
    ask("volume like a rock concert")
    monkeypatch.setattr(intent.system, "list_apps", lambda: ["chrome", "a brand new app"])
    ask("volume like a rock concert")
    assert ai.calls == 2


def test_a_different_command_model_keeps_the_cache(ai, monkeypatch):
    ask("volume like a rock concert")
    monkeypatch.setitem(config.INTENT_DEFAULT_MODELS, "openrouter", "another-model")  # or offline: the local one
    ask("volume like a rock concert")
    assert ai.calls == 1


class WordEmbedder:
    """Fake bge-small: messages sharing words are close (unit vectors over a hashed bag of words)."""
    def __call__(self, texts):
        import zlib

        import numpy as np
        rows = []
        for text in texts:
            v = np.zeros(512, dtype=np.float32)
            for w in text.lower().split():
                v[zlib.crc32(w.encode()) % 512] += 1  # stable across runs, unlike hash()
            rows.append(v / (np.linalg.norm(v) or 1))
        return np.array(rows, dtype=np.float32)


@pytest.fixture
def meaning(monkeypatch):
    from services.files import embed
    monkeypatch.setattr(command_cache, "SEMANTIC", True)
    monkeypatch.setattr(command_cache, "SIMILAR_ENOUGH", 0.6)  # the fake's scale, not bge's
    monkeypatch.setattr(embed, "encode", WordEmbedder())
    monkeypatch.setattr(embed, "_model", object())  # "loaded"


def test_a_rephrased_command_reuses_the_decision(ai, meaning):
    ai.reply = [ToolCall("open_app", {"app_name": "spotify"})]
    first = asyncio.run(intent._classify_with_ai("open spotify for focus time", "openrouter"))
    again = asyncio.run(intent._classify_with_ai("open spotify for my focus time now", "openrouter"))
    assert first == again and ai.calls == 1  # meant the same: no second AI call

    ai.reply = [ToolCall("set_volume", {"level": 100})]
    asyncio.run(intent._classify_with_ai("volume like a rock concert", "openrouter"))
    asyncio.run(intent._classify_with_ai("volume like a big rock concert", "openrouter"))
    assert ai.calls == 3  # 100 was the AI's idea, not said: a rephrasing asks again (exact repeats still hit)


def test_the_guards(meaning):
    fp = "fp"
    command_cache.put("open spotify", fp, [{"type": "system", "action": "open_app", "app_name": "spotify"}])
    command_cache.put("volume up", fp, [{"type": "system", "action": "volume_up"}])
    command_cache.put("set volume to 30", fp, [{"type": "system", "action": "set_volume", "level": 30}])
    assert command_cache.similar("can you open spotify please", fp)[0]["app_name"] == "spotify"
    assert command_cache.similar("open chrome", fp) is None             # the name acted on wasn't said
    assert command_cache.similar("close spotify", fp) is None           # a flip word differs
    assert command_cache.similar("volume down", fp) is None
    assert command_cache.similar("set volume to 40", fp) is None        # a different number
    assert command_cache.similar("what is spotify", fp) is None         # a question
    assert command_cache.similar("open spotify please", fp, allow_load=False) is not None  # "loaded"


def test_local_commands_are_remembered_for_rephrasings(ai, meaning, monkeypatch):
    monkeypatch.setattr(intent.system, "open_app", lambda name: f"Opening {name.title()}.")
    assert ask("open notepad").message == "Opening Notepad."
    stored = command_cache.similar("please open notepad for me", intent._cache_fp())
    assert stored and stored[0]["app_name"] == "notepad"
    assert ask("notepad open for me please").message == "Opening Notepad."  # not a command starter, still runs
    assert ai.calls == 0


def test_clipboard_text_is_never_cached(ai):
    ai.reply = [ToolCall("write_clipboard", {"text": "Secret Plan"})]
    ask("look, stash Secret Plan somewhere")
    ask("look, stash Secret Plan somewhere")
    assert ai.calls == 2


def test_old_entries_expire(ai, monkeypatch):
    ask("volume like a rock concert")
    monkeypatch.setattr(command_cache, "MAX_AGE_SECONDS", -1)
    ask("volume like a rock concert")
    assert ai.calls == 2


def test_cache_keeps_only_the_newest_entries(monkeypatch):
    monkeypatch.setattr(command_cache, "MAX_ENTRIES", 2)
    for message in ["one", "two", "three"]:
        command_cache.put(message, "fp", [])
    assert command_cache.get("one", "fp") is None
    assert command_cache.get("three", "fp") == []


def test_broken_cache_never_breaks_commands(ai, monkeypatch, tmp_path):
    monkeypatch.setattr(command_cache, "db_path", str(tmp_path))  # a folder, not a database
    assert ask("volume like a rock concert") == ActionResult(True, "Volume set to 100%.")


# ── Speech cache ──────────────────────────────────────────────────────────────

class FakeCommunicate:
    requests = []

    def __init__(self, text, voice, connect_timeout):
        FakeCommunicate.requests.append((text, voice))

    async def stream(self):
        yield {"type": "audio", "data": b"mp3-audio"}


@pytest.fixture
def new_speaker(monkeypatch):
    """Makes a fresh TextToSpeech, like a restart of FRIDAY. Nothing really plays."""
    FakeCommunicate.requests = []
    monkeypatch.setattr("edge_tts.Communicate", FakeCommunicate)
    played = []

    def make():
        speaker = tts_module.TextToSpeech()
        speaker._play = lambda chunks, generation: played.append(b"".join(chunks))
        return speaker

    return SimpleNamespace(make=make, played=played)


def test_confirmations_stay_instant_after_a_restart(new_speaker):
    asyncio.run(new_speaker.make().speak("Volume set to 40%.", cache=True))
    asyncio.run(new_speaker.make().speak("Volume set to 40%.", cache=True))
    assert [text for text, _ in FakeCommunicate.requests] == ["Volume set to 40%."]
    assert new_speaker.played == [b"mp3-audio", b"mp3-audio"]


def test_private_replies_are_not_saved(new_speaker):
    asyncio.run(new_speaker.make().speak("Clipboard: hunter2"))
    assert not list(tts_module.CACHE_DIR.glob("*.mp3"))
    asyncio.run(new_speaker.make().speak("Clipboard: hunter2"))
    assert len(FakeCommunicate.requests) == 2


def test_prewarm_uses_saved_phrases(new_speaker):
    asyncio.run(new_speaker.make().prewarm())
    asyncio.run(new_speaker.make().prewarm())
    assert len(FakeCommunicate.requests) == len(tts_module.PREWARM_PHRASES)


def test_changing_the_voice_does_not_replay_the_old_one(new_speaker, monkeypatch):
    asyncio.run(new_speaker.make().speak("Muted.", cache=True))
    monkeypatch.setattr(config, "EDGE_TTS_VOICE", "en-GB-SoniaNeural")
    asyncio.run(new_speaker.make().speak("Muted.", cache=True))
    assert [voice for _, voice in FakeCommunicate.requests] == [
        tts_module.tts.edge_voice, "en-GB-SoniaNeural",
    ]


def test_disk_cache_is_pruned(new_speaker, monkeypatch):
    monkeypatch.setattr(tts_module, "CACHE_FILES", 2)
    speaker = new_speaker.make()
    for text in ["One.", "Two.", "Three."]:
        asyncio.run(speaker.speak(text, cache=True))
    assert len(list(tts_module.CACHE_DIR.glob("*.mp3"))) == 2


def test_clearing_chat_memory_clears_both_caches(new_speaker, monkeypatch):
    command_cache.put("volume like a rock concert", "fp", [{"action": "set_volume", "level": 100}])
    tts_module.tts._remember("Muted.", b"mp3-audio")
    assert list(tts_module.tts.cache_dir.glob("*.mp3"))

    monkeypatch.setattr(chat, "_memory", SimpleNamespace(clear_history=lambda: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    assert client.delete("/api/v1/history").status_code == 200

    assert command_cache.get("volume like a rock concert", "fp") is None
    assert not list(tts_module.tts.cache_dir.glob("*.mp3"))
    assert "Muted." not in tts_module.tts._cache
