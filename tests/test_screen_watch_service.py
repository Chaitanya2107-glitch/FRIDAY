import asyncio
from datetime import datetime
import time
from types import SimpleNamespace

import pytest

from services.mind.cognition import Cognition
from services.screen_watch import capture, inference, service
from services.screen_watch.store import ScreenStore


@pytest.fixture
def screen(tmp_path, monkeypatch):
    watch = service.ScreenWatch(ScreenStore(Cognition(tmp_path / "screen.db")))
    watch.control("start")
    watch._indicator, watch._lease = {"hwnd": 12}, time.monotonic() + 1000
    window = {"app": "notepad", "title": "Graph notes", "scope": {"hwnd": 10, "pid": 20, "created": 100, "title_hash": "abc"}}
    live = {"window": window, "visible": True}
    monkeypatch.setattr(capture, "foreground", lambda: live["window"])
    monkeypatch.setattr(capture, "indicator_valid", lambda badge: live["visible"])
    monkeypatch.setattr(service, "idle_seconds", lambda: 5)
    readers, models = [], []
    frame = {"text": "Graph theory lecture notes. " * 5, "url_hash": None, "content_hash": "content1"}
    class Reader:
        def __init__(self, *args, **kwargs):
            self.calls, self.closed = [], False
            readers.append(self)
        async def call(self, name, *args):
            self.calls.append(name)
            return {**frame, **({"image": b"synthetic"} if name == "image" else {})}
        async def aclose(self):
            self.closed = True
    async def analyze(app, text, image=None):
        models.append(image)
        return inference.Interpretation(summary="Graph notes are visible.", activity="May be reading graphs.",
                                        needs_vision=False, sensitive=False)
    monkeypatch.setattr(service, "ProcessRuntime", Reader)
    monkeypatch.setattr(inference, "analyze", analyze)
    monkeypatch.setattr(service, "watch", watch)
    return SimpleNamespace(watch=watch, window=window, live=live, readers=readers, models=models, frame=frame)


def observe(screen):
    return asyncio.run(screen.watch.observe(screen.window, screen.watch.store.settings()["epoch"],
                                           screen.watch._generation))


def test_accessible_text_is_used_before_any_image(screen):
    observe(screen)
    assert screen.models == [None] and screen.readers[0].calls == ["read", "read"]
    assert screen.readers[0].closed
    assert screen.watch.store.history()[0]["source"] == "accessible_text"
    assert "Graph" in asyncio.run(screen.watch.current())["summary"]


def test_inadequate_accessible_text_uses_active_window_vision(screen):
    screen.frame["text"] = ""
    observe(screen)
    assert screen.models == [b"synthetic"]
    assert screen.readers[0].calls == ["read", "image", "read"]
    assert screen.watch.store.history()[0]["source"] == "vision"


def test_no_visible_indicator_means_no_uia_no_screenshot_no_model(screen):
    screen.live["visible"] = False
    observe(screen)
    assert not screen.models and screen.readers[0].calls == []
    assert screen.watch.store.history() == []


def test_private_uia_result_never_falls_back_to_pixels(screen):
    screen.frame["blocked"] = "private_window"
    observe(screen)
    assert screen.readers[0].calls == ["read"] and not screen.models
    assert screen.watch.store.history() == []


@pytest.mark.parametrize("invalidate", ["pause", "forget", "window", "indicator", "text", "url"])
def test_inference_cannot_commit_after_source_or_permission_changes(screen, monkeypatch, invalidate):
    async def analyze(*args, **kwargs):
        if invalidate == "pause":
            screen.watch.control("pause")
        elif invalidate == "forget":
            screen.watch.store.forget()
        elif invalidate == "window":
            screen.live["window"] = {**screen.window, "scope": {"hwnd": 999}}
        elif invalidate == "indicator":
            screen.live["visible"] = False
        elif invalidate == "text":
            screen.frame["content_hash"] = "content2"
        else:
            screen.frame["url_hash"] = "new_page"
        return inference.Interpretation(summary="Old graph page.", activity="Reading graphs.",
                                        needs_vision=False, sensitive=False)
    monkeypatch.setattr(inference, "analyze", analyze)
    observe(screen)
    assert not screen.watch.store.history()


def test_live_navigation_cannot_return_an_older_same_title_page(screen):
    observe(screen)
    screen.frame["url_hash"] = "another_page"
    assert asyncio.run(screen.watch.current()) is None


def test_only_one_background_observation_is_in_flight(screen, monkeypatch):
    async def check():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []
        async def slow(*args):
            calls.append(True)
            started.set()
            await finish.wait()
        monkeypatch.setattr(screen.watch, "observe", slow)
        screen.watch._scope = screen.window["scope"]
        screen.watch._epoch = screen.watch.store.settings()["epoch"]
        screen.watch._settled = 0
        await screen.watch.tick()
        await started.wait()
        screen.watch._next = 0
        await screen.watch.tick()
        assert len(calls) == 1
        finish.set()
        await screen.watch._job
    asyncio.run(check())


def test_late_model_that_ignores_cancellation_is_discarded(screen, monkeypatch):
    async def check():
        started = asyncio.Event()
        async def late(*args):
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                return inference.Interpretation(summary="Old data.", activity="Unknown",
                                                needs_vision=False, sensitive=False)
        monkeypatch.setattr(inference, "analyze", late)
        watch = screen.watch
        watch._job = asyncio.create_task(watch.observe(screen.window, watch.store.settings()["epoch"], watch._generation))
        await started.wait()
        await asyncio.to_thread(watch.control, "pause")
        await watch._job
        assert screen.readers[0].calls == ["read"] and screen.readers[0].closed
        assert watch.store.history() == []
    asyncio.run(check())


def test_status_has_no_screen_content_or_identity(screen):
    observe(screen)
    status = screen.watch.status()
    assert set(status) == {"enabled", "paused", "state", "epoch", "local_only"}
    assert "Graph" not in str(status) and "hwnd" not in str(status)


def test_pruning_runs_even_while_disabled(screen, monkeypatch):
    calls = []
    screen.watch.control("stop")
    monkeypatch.setattr(screen.watch.store, "prune", lambda: calls.append(True))
    asyncio.run(screen.watch.tick())
    assert calls == [True]
