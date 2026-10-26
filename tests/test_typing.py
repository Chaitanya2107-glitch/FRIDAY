import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat
from interfaces.tray import backend
from providers.base_provider import ToolCall
from services.automation import intent, keyboard, writer
from services.automation.intent import ActionResult, try_system_action
from services.automation.typing_commands import match_typing_command

LOCAL = "http://127.0.0.1:8000"
CTRL, SHIFT, ALT, WIN = 0x11, 0x10, 0x12, 0x5B


# ── Keys ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("keys, codes", [
    ("enter", [0x0D]),
    ("ctrl+s", [CTRL, ord("S")]),
    ("control s", [CTRL, ord("S")]),
    ("ctrl shift t", [CTRL, SHIFT, ord("T")]),
    ("ctrl plus shift plus t", [CTRL, SHIFT, ord("T")]),
    ("alt+f4", [ALT, 0x73]),
    ("page down", [0x22]),
    ("down arrow", [0x28]),
    ("win+d", [WIN, ord("D")]),
    ("ctrl+0", [CTRL, ord("0")]),
])
def test_key_names_are_understood(keys, codes):
    assert keyboard.parse_keys(keys) == codes


@pytest.mark.parametrize("keys", ["hello", "ctrl+", "s+ctrl", "", "ctrl+banana"])
def test_unknown_keys_are_rejected(keys):
    assert keyboard.parse_keys(keys) is None


@pytest.mark.parametrize("keys, shown", [
    ("ctrl+s", "Ctrl+S"), ("ctrl+shift+t", "Ctrl+Shift+T"), ("enter", "Enter"),
    ("page down", "Page Down"), ("win+d", "Win+D"), ("f5", "F5"),
])
def test_keys_are_described_for_replies(keys, shown):
    assert keyboard.describe_keys(keys) == shown


# ── Sending ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    """Captures what would go to Windows: ("text", chars) and ("keys", codes)."""
    events = []

    def fake_send(inputs):
        text, keys = "", []
        for event in inputs:
            key = event.u.ki
            if key.dwFlags & keyboard.KEYEVENTF_KEYUP:
                continue
            if key.dwFlags & keyboard.KEYEVENTF_UNICODE:
                text += chr(key.wScan)
            else:
                keys.append(key.wVk)
        if text:
            events.append(("text", text))
        if keys:
            events.append(("keys", keys))

    monkeypatch.setattr(keyboard, "_send", fake_send)
    monkeypatch.setattr(keyboard.time, "sleep", lambda s: None)
    return events


def test_typing_sends_the_characters(sent):
    keyboard.type_text("Hi 5!")
    assert sent == [("text", "Hi 5!")]


def test_typing_accented_letters_and_emoji(sent):
    keyboard.type_text("café 😀")
    # The emoji goes as two UTF-16 halves, which rejoin as the original character
    typed = "".join(text for kind, text in sent if kind == "text")
    assert typed.encode("utf-16", "surrogatepass").decode("utf-16") == "café 😀"


def test_long_text_is_sent_in_chunks(sent, monkeypatch):
    monkeypatch.setattr(keyboard, "CHUNK_CHARS", 4)
    keyboard.type_text("abcdefghij")
    assert sent == [("text", "abcd"), ("text", "efgh"), ("text", "ij")]


def test_pressing_a_shortcut_holds_the_modifiers(sent):
    keyboard.press_keys("ctrl+shift+t")
    assert sent == [("keys", [CTRL, SHIFT, ord("T")])]


def test_pressing_a_key_several_times(sent):
    keyboard.press_keys("tab", times=3)
    assert sent == [("keys", [0x09])] * 3


def test_pressing_an_unknown_key_is_an_error(sent):
    with pytest.raises(keyboard.KeyboardError, match="don't know the key"):
        keyboard.press_keys("banana")


def test_blocked_typing_is_reported(monkeypatch):
    class RefusingSendInput:  # Windows refuses to deliver the keystrokes
        argtypes = restype = None

        def __call__(self, count, array, size):
            return 0

    monkeypatch.setattr(keyboard.ctypes, "WinDLL", lambda *a, **k: SimpleNamespace(SendInput=RefusingSendInput()))
    with pytest.raises(keyboard.KeyboardError, match="blocked the typing"):
        keyboard._send([keyboard._vk_events(0x09, up=False)])


def test_steps_run_in_order(sent):
    keyboard.run_steps([{"text": "hi"}, {"keys": "enter"}, {"nonsense": 1}])
    assert sent == [("text", "hi"), ("keys", [0x0D])]


# ── Pasting (multi-line text) ─────────────────────────────────────────────────

@pytest.fixture
def clipboard(monkeypatch, sent):
    state = SimpleNamespace(content="what was there before", writes=[], fail=False)

    def set_text(text):
        if state.fail:
            raise keyboard.clipboard.ClipboardError("clipboard busy")
        state.writes.append(text)
        state.content = text

    monkeypatch.setattr(keyboard.clipboard, "get_text", lambda: state.content)
    monkeypatch.setattr(keyboard.clipboard, "set_text", set_text)
    return state


def test_multi_line_text_is_pasted_not_typed(clipboard, sent):
    keyboard.type_text("def f():\n    return 1")

    assert clipboard.writes == ["def f():\n    return 1", "what was there before"]
    assert sent == [("keys", [CTRL, ord("V")])]  # Ctrl+V, and nothing typed
    assert clipboard.content == "what was there before"


def test_short_text_is_typed_without_touching_the_clipboard(clipboard, sent):
    keyboard.type_text("hello")
    assert clipboard.writes == [] and sent == [("text", "hello")]


def test_typing_still_works_when_the_clipboard_is_busy(clipboard, sent):
    clipboard.fail = True
    keyboard.type_text("line one\nline two")

    # Typed instead: the characters, plus Enter for the line break, and no paste
    # (one chunk, so this fixture reports its characters and keys separately)
    assert sent == [("text", "line oneline two"), ("keys", [0x0D])]


# ── Wordings ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("type see you at 5.", {"action": "type_text", "text": "see you at 5."}),
    ("Hey Friday, type: Hello there, how are you?",
     {"action": "type_text", "text": "Hello there, how are you?"}),
    ("type hi bro and send it", {"action": "type_text", "text": "hi bro", "then_keys": "enter"}),
    ("type ok then press enter", {"action": "type_text", "text": "ok", "then_keys": "enter"}),
    ("type buy milk new line buy eggs", {"action": "type_text", "text": "buy milk\nbuy eggs"}),
    ("dictate I will be late", {"action": "type_text", "text": "I will be late"}),
    ("write down call mom", {"action": "type_text", "text": "call mom"}),
    ("write an email asking my boss for Friday off",
     {"action": "write_text", "request": "an email asking my boss for Friday off"}),
    ("write a short reply saying thanks and send it",
     {"action": "write_text", "request": "a short reply saying thanks", "then_keys": "enter"}),
    ("press enter", {"action": "press_keys", "keys": "enter", "times": 1}),
    ("hit ctrl+s", {"action": "press_keys", "keys": "ctrl+s", "times": 1}),
    ("press tab 3 times", {"action": "press_keys", "keys": "tab", "times": 3}),
    ("press the down arrow twice", {"action": "press_keys", "keys": "down arrow", "times": 2}),
    ("select all", {"action": "press_keys", "keys": "ctrl+a"}),
    ("undo", {"action": "press_keys", "keys": "ctrl+z"}),
    ("scroll down", {"action": "press_keys", "keys": "page down"}),
])
def test_typing_wordings(message, expected):
    assert match_typing_command(message) == {"type": "system", **expected}


@pytest.mark.parametrize("message", [
    "press hello",
    "type",
    "write-ups are hard",
    "typewriters are cool",
    "what type of dog is that",
    "save me some time",
    "undo my mistakes in life",
])
def test_other_messages_are_not_typing_commands(message):
    assert match_typing_command(message) is None


# ── Running them ──────────────────────────────────────────────────────────────

def ask(message):
    return asyncio.run(try_system_action(message, "openrouter"))


def test_dictation_is_handed_to_the_client_and_kept_out_of_memory():
    result = ask("type my card pin is 1234")
    assert result.success and result.message == "Typing it."
    assert result.keyboard == ({"text": "my card pin is 1234"},)
    assert "1234" not in result.memory_message


def test_dictation_with_a_key_press():
    assert ask("type hi bro and send it").keyboard == (
        {"text": "hi bro"}, {"keys": "enter", "times": 1},
    )


def test_key_press_reply_names_the_shortcut():
    result = ask("press ctrl+s")
    assert result == ActionResult(True, "Pressing Ctrl+S.", keyboard=({"keys": "ctrl+s", "times": 1},))


def test_ai_written_text_is_typed(monkeypatch):
    async def fake_write(request, provider_name):
        assert request == "an email asking for friday off"
        return "Hi,\n\nCould I take Friday off?\n\nThanks"
    monkeypatch.setattr(writer, "write", fake_write)

    result = ask("write an email asking for friday off")

    assert result.message == "Typing it now — 7 words."
    assert result.keyboard == ({"text": "Hi,\n\nCould I take Friday off?\n\nThanks"},)
    assert result.memory_message.endswith("Could I take Friday off?\n\nThanks")
    assert result.repeatable is False


def test_the_ai_can_also_choose_typing(monkeypatch):
    classified = []
    async def fake_classify(message, provider_name):
        classified.append(message)
        return [{"type": "system", "action": "type_text", "text": "hello"},
                {"type": "system", "action": "press_keys", "keys": "enter"}]
    monkeypatch.setattr(intent, "_classify_with_ai", fake_classify)

    # An unfamiliar single request exercises AI typing; partially recognized
    # explicit batches are deliberately rejected before any tool executes.
    message = "show hello in the box with Enter to submit"
    result = ask(message)

    assert classified == [message]
    assert result.keyboard == ({"text": "hello"}, {"keys": "enter", "times": 1})


def test_a_bad_key_from_the_ai_is_reported(monkeypatch):
    async def fake_classify(message, provider_name):
        return [{"type": "system", "action": "press_keys", "keys": "the any key"}]
    monkeypatch.setattr(intent, "_classify_with_ai", fake_classify)

    result = ask("press the any key")
    assert result == ActionResult(False, 'I don\'t know the key "the any key".')


def test_writing_nothing_is_not_typed(monkeypatch):
    async def fake_write(request, provider_name):
        return ""
    monkeypatch.setattr(writer, "write", fake_write)
    assert ask("write an essay about nothing") is None


# ── What the AI writes is cleaned up ──────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("Sure! Here's your email:\n\nHi Bob,\nSee you at 5.", "Hi Bob,\nSee you at 5."),
    ("```python\nprint('hi')\n```", "print('hi')"),
    ('"Thanks for the update."', "Thanks for the update."),
    ("  Already clean.  ", "Already clean."),
])
def test_writer_cleans_the_reply(raw, expected):
    assert writer.clean(raw) == expected


# ── Clients ───────────────────────────────────────────────────────────────────

def test_chat_replies_carry_the_keys(monkeypatch):
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda role, content: None,
    ))
    client = TestClient(create_app(), base_url=LOCAL)

    body = client.post("/api/v1/chat", json={"message": "type hello there"}).json()

    assert body["response"] == "Typing it."
    assert body["keyboard"] == [{"text": "hello there"}]


def test_tray_client_reads_the_keys(monkeypatch):
    monkeypatch.setattr(backend, "_request", lambda *a, **k: {
        "response": "Typing it.", "keyboard": [{"text": "hi"}],
    })
    assert backend.chat("type hi") == backend.ChatReply("Typing it.", False, ({"text": "hi"},))


def test_voice_replies_are_typed_by_the_tray(monkeypatch):
    from tests.test_tray import FakeApi  # the tray's fake backend
    from services.automation import keyboard as keyboard_module
    typed = []
    api = FakeApi()
    api.voice_results = [{"transcription": "type hello", "response": "Typing it.",
                          "keyboard": [{"text": "hello"}]}]

    from interfaces.tray.tray import FridayTray
    import interfaces.tray.tray as tray_module
    monkeypatch.setattr(tray_module, "_in_background", lambda fn, *args: fn(*args))
    monkeypatch.setattr(tray_module.pystray, "Icon", __import__("tests.test_tray", fromlist=["FakeIcon"]).FakeIcon)

    tray = FridayTray(show_command_bar=lambda: None, quit_app=lambda: None,
                      confirm=lambda *a: True, api=api, typist=typed.append)
    tray.online = True
    tray.listen()

    assert typed == [[{"text": "hello"}]]
    assert keyboard_module.run_steps is not None  # the real typist by default
