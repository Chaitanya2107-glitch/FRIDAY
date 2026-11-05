import asyncio
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat
from services.automation import intent, system_control
from services.automation.device_commands import match_device_command
from services.automation.intent import ActionResult, try_system_action
from services.automation.system_control import AutomationError, SystemControl


# ── Matching ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("close chrome", {"action": "close_app", "app_name": "chrome"}),
    ("Quit Spotify.", {"action": "close_app", "app_name": "spotify"}),
    ("set volume to 40", {"action": "set_volume", "level": 40}),
    ("volume 30%", {"action": "set_volume", "level": 30}),
    ("turn the volume up", {"action": "change_volume", "delta": 10}),
    ("turn volume down by 20", {"action": "change_volume", "delta": -20}),
    ("lower the volume.", {"action": "change_volume", "delta": -10}),
    ("increase volume to 80", {"action": "set_volume", "level": 80}),
    ("mute", {"action": "set_mute", "mute": True}),
    ("unmute the sound", {"action": "set_mute", "mute": False}),
    ("set brightness to 70", {"action": "set_brightness", "level": 70}),
    ("increase brightness", {"action": "change_brightness", "delta": 10}),
    ("dim the screen", {"action": "change_brightness", "delta": -10}),
    ("take a screenshot", {"action": "take_screenshot"}),
    ("screenshot", {"action": "take_screenshot"}),
    ("capture my screen", {"action": "take_screenshot"}),
    ("read my clipboard", {"action": "read_clipboard"}),
    ("show clipboard", {"action": "read_clipboard"}),
    ("copy Hello World to clipboard", {"action": "write_clipboard", "text": "Hello World"}),
    ('copy "ssh user@host" to my clipboard.', {"action": "write_clipboard", "text": "ssh user@host"}),
])
def test_device_commands_are_matched(message, expected):
    assert match_device_command(message) == {"type": "system", **expected}


@pytest.mark.parametrize("message", [
    "close the door behind you",
    "set a reminder for 5pm",
    "take me through fastapi basics",
    "read me a poem",
    "show me how to take a screenshot",
    "mute button on my headphones is broken",
    "turn left at the light",
    "copy that",
    "",
])
def test_ordinary_chat_is_not_a_device_command(message):
    assert match_device_command(message) is None


def _no_ai(name):
    raise AssertionError("AI classifier should not be called")


def test_common_chat_starters_never_reach_ai_classifier(monkeypatch):
    monkeypatch.setattr(intent, "get_provider", _no_ai)
    assert asyncio.run(try_system_action("set up my project plan", "openrouter")) is None
    assert asyncio.run(try_system_action("take me through fastapi basics", "openrouter")) is None


def test_device_command_executes_without_ai(monkeypatch):
    monkeypatch.setattr(intent, "get_provider", _no_ai)
    calls = []
    monkeypatch.setattr(intent.system, "change_volume", lambda delta: calls.append(delta) or f"Volume changed by {delta}.")

    result = asyncio.run(try_system_action("turn the volume up", "openrouter"))

    assert result == ActionResult(True, "Volume changed by 10.")
    assert calls == [10]


@pytest.mark.parametrize("parsed", [
    {"action": "set_volume"},
    {"action": "set_brightness", "level": "loud"},
    {"action": "close_app"},
])
def test_malformed_ai_actions_fall_back_to_chat(parsed):
    assert intent._execute({"type": "system", **parsed}) is None


def test_clipboard_contents_are_not_saved_to_chat_memory(monkeypatch):
    saved = []
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [],
        save_message=lambda role, content: saved.append((role, content)),
    ))
    monkeypatch.setattr("providers.failover.get_provider",lambda name: None)
    monkeypatch.setattr(intent.system, "read_clipboard", lambda: "Your clipboard says: hunter2")

    resp = TestClient(create_app(), base_url="http://127.0.0.1:8000").post("/api/v1/chat", json={"message": "read my clipboard"})

    assert resp.status_code == 200
    assert resp.json()["response"] == "Your clipboard says: hunter2"
    assert saved[0] == ("user", "read my clipboard")
    assert all("hunter2" not in content for _, content in saved)


# ── SystemControl ─────────────────────────────────────────────────────────────

@pytest.fixture
def controller():
    return SystemControl()


class FakeEndpointVolume:
    def __init__(self, scalar=0.35, muted=1):
        self.scalar, self.muted = scalar, muted

    def GetMasterVolumeLevelScalar(self):
        return self.scalar

    def SetMasterVolumeLevelScalar(self, value, context):
        self.scalar = value

    def SetMute(self, mute, context):
        self.muted = mute

    def GetMute(self):
        return self.muted


def test_set_volume_clamps_and_unmutes(monkeypatch, controller):
    fake = FakeEndpointVolume()
    monkeypatch.setattr(controller, "_endpoint_volume", lambda: fake)
    assert controller.set_volume(150) == "Volume set to 100%."
    assert fake.scalar == 1.0 and fake.muted == 0


def test_change_volume_is_relative_to_current_level(monkeypatch, controller):
    fake = FakeEndpointVolume(scalar=0.35)
    monkeypatch.setattr(controller, "_endpoint_volume", lambda: fake)
    assert controller.change_volume(10) == "Volume set to 45%."
    assert controller.change_volume(-80) == "Volume set to 0%."


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeProcess:
    def __init__(self, name, exe=""):
        self._name, self._exe = name, exe

    def name(self):
        return self._name

    def exe(self):
        return self._exe


def fake_windows(monkeypatch, processes, accepted=True):
    """One fake window per process for close_app to pick from; returns the windows it closed."""
    closed = []
    monkeypatch.setattr(system_control.app_finder, "app_windows",
                        lambda is_app: [i for i, proc in enumerate(processes) if is_app(proc)])
    monkeypatch.setattr(system_control.app_finder, "close_windows",
                        lambda hwnds: closed.extend(hwnds) or (len(hwnds) if accepted else 0))
    return closed


def test_close_app_closes_its_windows_like_alt_f4(monkeypatch, controller):
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    closed = fake_windows(monkeypatch, [
        FakeProcess("chrome.exe", chrome),
        FakeProcess("Code.exe", r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
        FakeProcess("chrome.exe", chrome),
    ])
    assert controller.close_app("chrome") == "Closing Chrome."
    assert closed == [0, 2]  # both Chrome windows, not VS Code


def test_close_app_uses_process_names_for_store_apps(monkeypatch, controller):
    closed = fake_windows(monkeypatch, [FakeProcess("WhatsApp.Root.exe")])
    assert controller.close_app("whatsapp") == "Closing Whatsapp."
    assert closed == [0]


def test_close_app_reports_when_not_open(monkeypatch, controller):
    fake_windows(monkeypatch, [FakeProcess("Code.exe")])
    assert controller.close_app("whatsapp") == "Whatsapp isn't open."


def test_close_app_refused_by_an_admin_app_raises(monkeypatch, controller):
    fake_windows(monkeypatch, [FakeProcess("Taskmgr.exe")], accepted=False)
    with pytest.raises(AutomationError, match="administrator"):
        controller.close_app("task manager")


def test_close_app_finds_unlisted_apps_by_their_folder(monkeypatch, controller):
    # "black myth" isn't listed: Everything finds b1.exe, but the running game is b1-Win64-Shipping.exe
    monkeypatch.setattr(system_control.app_finder, "find_app", lambda name: r"C:\games\Black Myth Wukong\b1.exe")
    closed = fake_windows(monkeypatch, [
        FakeProcess("b1-Win64-Shipping.exe", r"C:\games\Black Myth Wukong\b1\Binaries\Win64\b1-Win64-Shipping.exe"),
        FakeProcess("other.exe", r"C:\games\Other Game\other.exe"),
    ])
    assert controller.close_app("black myth") == "Closing Black Myth."
    assert closed == [0]


def test_close_app_in_a_shared_folder_matches_the_program_only(monkeypatch, controller):
    monkeypatch.setattr(system_control.app_finder, "find_app", lambda name: r"C:\Start Menu\Zoom.lnk")
    monkeypatch.setattr(system_control.app_finder, "shortcut_target",
                        lambda path: r"C:\Users\me\AppData\Roaming\Zoom\bin\Zoom.exe")
    closed = fake_windows(monkeypatch, [
        FakeProcess("Zoom.exe", r"C:\Users\me\AppData\Roaming\Zoom\bin\Zoom.exe"),
        FakeProcess("other.exe", r"C:\Users\me\AppData\Roaming\Zoom\bin\other.exe"),  # "bin" is shared
    ])
    assert controller.close_app("zoom") == "Closing Zoom."
    assert closed == [0]


@pytest.mark.parametrize("app_name", ["explorer", "not a real app"])
def test_close_app_refuses_explorer_and_unknown_apps(controller, app_name):
    with pytest.raises(AutomationError):
        controller.close_app(app_name)


def test_close_command_takes_unlisted_apps_only_when_open(monkeypatch):
    from services.automation.device_commands import match_device_command
    arduino = r"C:\Program Files\Arduino IDE\Arduino IDE.exe"
    monkeypatch.setattr(system_control.app_finder, "find_app", lambda name: arduino)
    assert match_device_command("close arduino") is None  # installed but not open: the AI decides
    fake_windows(monkeypatch, [FakeProcess("Arduino IDE.exe", arduino)])
    assert match_device_command("close arduino") == {"type": "system", "action": "close_app", "app_name": "arduino"}


def test_set_brightness_clamps_level(monkeypatch, controller):
    scripts = []
    monkeypatch.setattr(system_control, "_run_hidden", lambda args: scripts.append(args[-1]) or _completed(0))
    assert controller.set_brightness(-5) == "Brightness set to 0%."
    assert "WmiSetBrightness(1, 0)" in scripts[0]


def test_change_brightness_reads_current_level(monkeypatch, controller):
    outputs = iter([_completed(0, "40\n"), _completed(0)])
    scripts = []
    monkeypatch.setattr(system_control, "_run_hidden", lambda args: scripts.append(args[-1]) or next(outputs))
    assert controller.change_brightness(25) == "Brightness set to 65%."
    assert "WmiSetBrightness(1, 65)" in scripts[1]


def test_brightness_on_unsupported_display_raises(monkeypatch, controller):
    monkeypatch.setattr(system_control, "_run_hidden", lambda args: _completed(1, stderr="Not supported"))
    with pytest.raises(AutomationError):
        controller.set_brightness(50)


def test_take_screenshot_saves_png(monkeypatch, controller, tmp_path):
    saved = []
    monkeypatch.setattr(system_control, "SCREENSHOT_DIR", tmp_path / "Screenshots")
    monkeypatch.setattr(system_control.ImageGrab, "grab", lambda all_screens: SimpleNamespace(save=saved.append))

    message = controller.take_screenshot()

    assert len(saved) == 1
    assert saved[0].parent == tmp_path / "Screenshots" and saved[0].suffix == ".png"
    assert message == "Screenshot saved to your Screenshots folder."


def test_read_clipboard_handles_no_text(monkeypatch, controller):
    monkeypatch.setattr(system_control.clipboard, "get_text", lambda: None)
    assert "doesn't have any text" in controller.read_clipboard()


def test_write_clipboard_previews_long_text(monkeypatch, controller):
    written = []
    monkeypatch.setattr(system_control.clipboard, "set_text", written.append)
    message = controller.write_clipboard("x" * 100)
    assert written == ["x" * 100]
    assert message.endswith("...")


def test_folder_replies_say_the_folder_name_not_the_full_path(monkeypatch, controller, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "photo.jpg").write_text("x")
    monkeypatch.setattr(system_control.subprocess, "Popen", lambda args: None)

    assert controller.open_folder(str(downloads)) == "Opening Downloads."
    assert controller.organise_folder(str(downloads)) == "Organised 1 file in Downloads."
    with pytest.raises(AutomationError, match=r"^Couldn't find the folder Music\.$"):
        controller.open_folder(str(tmp_path / "Music"))
