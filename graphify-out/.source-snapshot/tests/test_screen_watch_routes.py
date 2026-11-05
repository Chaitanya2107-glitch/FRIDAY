import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.config import config
from interfaces.api.routes.chat import chat, ChatRequest
from interfaces.api.routes.voice import _reply, VoiceRequest
from services.mind.cognition import cognition
from services.screen_watch import commands, service


@pytest.fixture
def screen(monkeypatch):
    watch = service.ScreenWatch()
    monkeypatch.setattr(service, "watch", watch)
    return watch


@pytest.mark.parametrize("channel", ["chat", "voice"])
def test_screen_reply_never_reaches_general_history_learning_or_model(screen, monkeypatch, channel):
    screen.control("start")
    async def current():
        return {"at": "2026-10-28T15:00:00", "summary": "SYNTHETIC_PRIVATE_SCREEN_SUMMARY",
                "activity": "Reading graph notes"}
    monkeypatch.setattr(screen, "current", current)
    def forbidden(*a, **k):
        pytest.fail("Screen content reached general memory/model")
    monkeypatch.setattr("services.mind.brain_memory.brain_memory.remember", forbidden)
    monkeypatch.setattr("interfaces.api.routes.chat._memory.save_message", forbidden)
    monkeypatch.setattr("interfaces.api.routes.voice._memory.save_message", forbidden)
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    if channel == "chat":
        result = asyncio.run(chat(ChatRequest(message="what am I doing", speak=False)))
    else:
        result = asyncio.run(_reply("what am I doing", VoiceRequest(speak=False)))
    assert result.private and result.model == "system_control"
    assert "SYNTHETIC_PRIVATE" in result.response
    with cognition._connect() as conn:
        assert "SYNTHETIC_PRIVATE" not in str(conn.execute("SELECT text FROM events").fetchall())


def test_control_cancels_old_action_and_app_question(screen, monkeypatch):
    from services.automation import intent
    from services.mind import talk
    intent._pending[False] = SimpleNamespace(parsed={"action": "shutdown"})
    talk._save({"pending": {"inquiry_id": None, "app_verification": {"token": "old"}, "question": "Old question"}})
    result = asyncio.run(commands.handle("pause screen awareness"))
    assert result.success and not intent.is_awaiting_confirmation()
    assert not talk.load().get("pending")


def test_remote_owner_cannot_enable_or_inspect_desktop_watch(screen):
    assert not asyncio.run(commands.handle("start watching my screen", remote=True)).success
    assert not screen.store.settings()["enabled"]
    assert not asyncio.run(commands.handle("screen memory", remote=True)).success


def test_nonlocal_http_cannot_enable_watch_or_renew_badge(screen, monkeypatch):
    import httpx
    from interfaces.api.app import create_app
    monkeypatch.setattr(screen, "heartbeat", lambda hwnd: pytest.fail("Remote request touched the native badge"))
    async def request():
        transport = httpx.ASGITransport(app=create_app(), client=("198.51.100.2", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            result = await client.post("/api/v1/chat", json={"message": "start screen awareness", "speak": False})
            assert result.status_code == 200 and "laptop only" in result.json()["response"]
            result = await client.post("/api/v1/screen-watch/indicator", json={"hwnd": 42})
            assert result.json() == {"accepted": False}
    asyncio.run(request())
    assert not screen.store.settings()["enabled"]


def test_explicit_screen_history_is_private_and_not_owner_fact(screen):
    screen.control("start")
    screen.store.save(epoch=screen.store.settings()["epoch"], session="one", scope={"hwnd": 1}, app="notes",
                      summary="Lecture notes visible.", activity="Possibly reading.", source="vision", at=datetime.now())
    result = asyncio.run(chat(ChatRequest(message="screen memory", speak=False)))
    assert result.private and "Provisional" in result.response and "Lecture notes" in result.response
    forgotten = asyncio.run(commands.handle("forget screen memory"))
    assert forgotten.success and screen.store.settings()["paused"]
    assert screen.store.history() == []


def test_badge_missing_reports_waiting_instead_of_claiming_capture(screen):
    result = asyncio.run(commands.handle("start watching my screen"))
    assert result.success and "once the watching badge is visible" in result.message
    assert screen.status()["state"] == "waiting_for_indicator"


@pytest.mark.parametrize("channel", ["chat", "voice", "system"])
def test_requested_speech_uses_only_offline_tts(screen, monkeypatch, channel):
    from interfaces.api.routes import voice
    spoken = []
    monkeypatch.setattr(voice, "_speak_in_background", lambda text, **kw: spoken.append(kw))
    monkeypatch.setattr("interfaces.api.routes.chat._speak_in_background", lambda text, **kw: spoken.append(kw))
    if channel == "chat":
        asyncio.run(chat(ChatRequest(message="screen awareness status", speak=True)))
    elif channel == "voice":
        asyncio.run(_reply("screen awareness status", VoiceRequest(speak=True)))
    else:
        from interfaces.api.routes.system import system_control, SystemRequest
        asyncio.run(system_control(SystemRequest(command="screen awareness status", speak=True)))
    assert spoken == [{"cache": False, "local_only": True}]


def test_local_only_tts_bypasses_network_and_all_audio_caches(monkeypatch):
    from services.voice.tts import tts
    calls = []
    async def audio(fn, *args):
        calls.append(fn.__name__)
    def forbidden(*a, **k):
        pytest.fail("Private screen speech reached an online/cache path")
    monkeypatch.setattr(tts, "_on_audio_thread", audio)
    monkeypatch.setattr(tts, "_cached", forbidden)
    monkeypatch.setattr(tts, "_speak_online", forbidden)
    asyncio.run(tts.speak("A private local summary.", cache=True, local_only=True))
    assert calls == ["_speak_offline"]
    assert not tts._saying


def test_status_endpoint_is_sanitized_and_accepts_no_screen_text(screen):
    from interfaces.api.routes.system import get_runtime_status, ScreenIndicator
    status = get_runtime_status().model_dump()["screen_watch"]
    assert set(status) == {"enabled", "paused", "state", "epoch", "local_only"}
    with pytest.raises(ValueError):
        ScreenIndicator(hwnd=-1)


def test_badge_pause_callback_has_actual_tray_signature():
    from interfaces.taskbar.screen_badge import ScreenBadge
    calls = []
    badge = ScreenBadge.__new__(ScreenBadge)
    badge.tray = SimpleNamespace(runtime_status={"screen_watch": {"epoch": 3}},
                                 screen_indicator=42, _command_action=lambda text: lambda: calls.append(text))
    badge.window = SimpleNamespace(withdraw=lambda: calls.append("hidden"))
    badge.pause()
    assert calls == ["hidden", "pause screen awareness"]
    assert badge.tray.screen_indicator == 0 and badge._pending_pause


def test_panel_resume_callback_has_actual_tray_signature():
    from interfaces.taskbar.panel import ControlPanel
    calls = []
    panel = ControlPanel.__new__(ControlPanel)
    panel.tray = SimpleNamespace(runtime_status={"screen_watch": {"enabled": False}},
                                 _command_action=lambda text: lambda: calls.append(text))
    panel.screen_badge = SimpleNamespace(_pending_pause=False)
    panel._screen_control()
    assert calls == ["resume screen awareness"]


def test_badge_heartbeat_does_not_wait_for_menu_requests():
    import threading
    from interfaces.tray.tray import FridayTray
    stopped, calls = threading.Event(), []
    class Api:
        BackendError = RuntimeError
        def screen_indicator(self, hwnd):
            calls.append(hwnd)
            stopped.set()
        def runtime_status(self):
            pytest.fail("Heartbeat depends on slow menu requests")
    tray = SimpleNamespace(screen_indicator=123, _api=Api(), _stopping=stopped)
    FridayTray._screen_heartbeat_loop(tray)
    assert calls == [123]
