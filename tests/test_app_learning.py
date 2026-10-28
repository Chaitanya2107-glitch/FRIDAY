import asyncio
import json
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.config import config
from providers.base_provider import ProviderResponse
from services.activity import categories
from services.activity.log import ActivityLog, activity_log
from services.mind import app_learning, app_verification, knowledge, talk
from services.mind.inquiry import inquiry

NOW = datetime(2026, 10, 27, 15)


@pytest.fixture(autouse=True)
def clean_turns(monkeypatch):
    monkeypatch.setattr(app_verification, "_generation", 0)
    monkeypatch.setattr(app_verification, "_turns", OrderedDict())


def model(monkeypatch, *, description="A note-taking app.", category="documents", **updates):
    seen = []
    async def complete(*args, **kwargs):
        seen.append((args, kwargs))
        return ProviderResponse(content=json.dumps({"known": True, "what": description, "category": category}),
                                provider="openrouter", model="test", **updates)
    monkeypatch.setattr("providers.failover.complete_with_failover", complete)
    return seen


def app(name="mystery", now=NOW):
    with knowledge.db() as conn:
        knowledge.see(conn, "app", name, "other", now, "Private account 487391")
        knowledge.spend(conn, "app", name, 65)
    return knowledge.get("app:" + name)


def proposed(monkeypatch, **kwargs):
    model(monkeypatch, **kwargs)
    asyncio.run(knowledge.look_up(app(), NOW))
    return app_learning.pending()[0]


def offered(monkeypatch, *, mark=True):
    model(monkeypatch)
    activity_log.observe("mystery", datetime.now(), "Personal notes")
    result = asyncio.run(app_verification.handle("learn this app", activity_log))
    assert result.success, result.message
    if mark:
        app_verification.mark_returned(result.message)
    return talk.load()["pending"]


def test_model_output_is_provisional_and_uses_only_app_identity(monkeypatch):
    calls = model(monkeypatch)
    asyncio.run(knowledge.look_up(app(), NOW))
    assert calls[0][0][1][0].content == 'What is "mystery"? It is the name of a Windows program.'
    assert "487391" not in str(calls)
    assert knowledge.get("app:mystery").about is None
    assert categories.app_category("mystery") == "other"
    row = app_learning.pending()[0]
    assert row["description"] == "A note-taking app."
    assert "category: documents" in app_learning.question(row)
    assert "Unverified model suggestion" in knowledge.describe(knowledge.get("app:mystery"))


def test_exact_confirmation_promotes_once_and_preserves_usage(monkeypatch):
    row = proposed(monkeypatch)
    assert app_learning.resolve(app_learning.identity(row), "yes", NOW) == "confirmed"
    thing = knowledge.get("app:mystery")
    assert (thing.about, thing.source, thing.seconds) == ("A note-taking app.", "confirmed", 65)
    assert categories.app_category("mystery") == "documents"
    assert app_learning.resolve(app_learning.identity(row), "yes", NOW) == "stale"


@pytest.mark.parametrize("answer", [
    "maybe", "no, I don't know", "it's probably a game", "actually, I'm not sure",
    "actually, a game I guess", "a game maybe", "it's perhaps a game", "it is unclear",
])
def test_uncertain_answers_do_not_teach(monkeypatch, answer):
    row = proposed(monkeypatch)
    assert app_learning.resolve(app_learning.identity(row), answer, NOW) == "uncertain"
    assert knowledge.get("app:mystery").about is None
    assert categories.app_category("mystery") == "other"


def test_rejection_and_owner_correction_are_distinct(monkeypatch):
    row = proposed(monkeypatch)
    assert app_learning.resolve(app_learning.identity(row), "no", NOW) == "rejected"
    assert knowledge.get("app:mystery").about is None
    asyncio.run(knowledge.look_up(knowledge.get("app:mystery"), NOW))
    row = app_learning.pending()[0]
    assert app_learning.resolve(app_learning.identity(row), "actually, a music player", NOW) == "corrected"
    assert knowledge.get("app:mystery").source == "boss"
    assert categories.app_category("mystery") == "music"


@pytest.mark.parametrize("answer", ["no, that's wrong", "no, wrong app", "no, that is incorrect", "no not right",
                                   "no, it's wrong", "it's not correct", "actually, that's wrong"])
def test_negative_feedback_cannot_become_an_app_definition(monkeypatch, answer):
    row = proposed(monkeypatch)
    assert app_learning.resolve(app_learning.identity(row), answer, NOW) == "rejected"
    assert knowledge.get("app:mystery").about is None


def test_owner_teaching_during_lookup_wins(monkeypatch):
    async def complete(*args, **kwargs):
        knowledge.teach("app:mystery", "My music player")
        return ProviderResponse(content='{"known":true,"what":"A game.","category":"gaming"}',
                                provider="openrouter", model="test")
    monkeypatch.setattr("providers.failover.complete_with_failover", complete)
    asyncio.run(knowledge.look_up(app(), NOW))
    assert not app_learning.pending()
    assert knowledge.get("app:mystery").about == "My music player"
    assert categories.app_category("mystery") == "music"


def test_applied_owner_lesson_hides_and_invalidates_candidate(monkeypatch):
    row = proposed(monkeypatch)
    monkeypatch.setattr("services.mind.training.teaching_for",
                        lambda column, key: "An app I use for notes" if key == "app:mystery" else None)
    assert not app_learning.pending()
    assert app_learning.resolve(app_learning.identity(row), "yes", NOW) == "stale"
    assert categories.app_category("mystery") == "other"


@pytest.mark.parametrize("updates", [{"tool_calls": [{"name": "bogus"}]}, {"metadata": {"incomplete": True}}])
def test_failed_or_action_bearing_output_is_not_a_definition(monkeypatch, updates):
    row = proposed(monkeypatch, **updates)
    assert row["description"] == ""
    assert knowledge.get("app:mystery").about is None
    assert "tried asking the model" in app_learning.question(row)


def test_offline_model_leaves_an_owner_clarification(monkeypatch):
    async def offline(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr("providers.failover.complete_with_failover", offline)
    asyncio.run(knowledge.look_up(app(), NOW))
    row = app_learning.pending()[0]
    assert row["description"] == ""
    assert app_learning.resolve(app_learning.identity(row), "I don't know", NOW) == "uncertain"
    assert app_learning.resolve(app_learning.identity(row), "a desktop music player", NOW) == "corrected"


def test_automatic_topic_lookup_never_sends_private_titles(monkeypatch):
    calls = model(monkeypatch)
    with knowledge.db() as conn:
        knowledge.see(conn, "topic", "Private medical appointment", "browsing", NOW)
        knowledge.spend(conn, "topic", "Private medical appointment", 3600)
    assert knowledge.due_lookup(NOW) is None
    assert asyncio.run(knowledge.look_up(knowledge.get("topic:private medical appointment"), NOW)) is None
    assert calls == []


def test_legacy_lookup_migration_preserves_output_but_removes_authority(monkeypatch):
    app()
    with knowledge.db() as conn:
        conn.execute("UPDATE things SET about='A game.',source='lookup',category='gaming',looked_up=?",
                     (NOW.isoformat(),))
    monkeypatch.setattr(knowledge, "_ready_for", None)
    thing = knowledge.get("app:mystery")
    knowledge.refresh_learned()
    assert thing.about is None and thing.seconds == 65
    assert app_learning.pending()[0]["description"] == "A game."
    assert categories.app_category("mystery") == "other"


def test_prepared_but_unoffered_question_cannot_be_approved(monkeypatch):
    offered(monkeypatch, mark=False)
    result = app_verification.handle_reply("yes")
    assert not result.success and knowledge.get("app:mystery").about is None


@pytest.mark.parametrize("answer", ["yes", "yes, that's right", "yeah, that's right", "actually, that's right"])
def test_offered_confirmation_is_scoped_and_not_a_personal_fact(monkeypatch, answer):
    pending = offered(monkeypatch)
    monkeypatch.setattr("services.mind.brain_memory.brain_memory.remember",
                        lambda *a, **k: pytest.fail("app approval became a personal memory"))
    monkeypatch.setattr("services.mind.brain.answered",
                        lambda *a, **k: pytest.fail("literal yes became an app definition"))
    assert app_verification.handle_reply(answer, now=pending["offered_at"] + 120).success
    assert knowledge.get("app:mystery").about == "A note-taking app."
    assert not talk.load().get("pending")


@pytest.mark.parametrize("invalidate", ["epoch", "owner", "session", "expiry"])
def test_stale_offer_never_promotes(monkeypatch, invalidate):
    pending = offered(monkeypatch)
    if invalidate == "epoch":
        with inquiry._db() as db:
            db.execute("UPDATE inquiry_meta SET epoch=epoch+1")
    elif invalidate == "owner":
        knowledge.teach("app:mystery", "My music player")
    elif invalidate == "session":
        monkeypatch.setattr(app_verification, "SESSION", "new desktop session")
    now = pending["offered_at"] + (181 if invalidate == "expiry" else 5)
    assert not app_verification.handle_reply("yes", now=now).success
    assert knowledge.get("app:mystery").source != "confirmed"


def test_uncertain_reply_and_shush_leave_no_dangling_target(monkeypatch):
    offered(monkeypatch)
    assert "unconfirmed" in app_verification.handle_reply("maybe").message
    assert not talk.load().get("pending")
    assert knowledge.get("app:mystery").about is None
    offered(monkeypatch)
    assert "stop asking" in app_verification.handle_reply("stop asking me").message
    assert talk.load()["paused_until"] > time.time()
    assert knowledge.get("app:mystery").about is None


def test_telegram_cannot_confirm_laptop_offer(monkeypatch):
    pending = offered(monkeypatch)
    assert app_verification.handle_reply("yes", remote=True) is None
    assert talk.load()["pending"] == pending
    assert knowledge.get("app:mystery").about is None


def test_old_slow_lookup_cannot_replace_newer_question(tmp_path, monkeypatch):
    old = ActivityLog(str(tmp_path / "old.db"))
    new = ActivityLog(str(tmp_path / "new.db"))
    old.observe("appold", datetime.now())
    new.observe("appnew", datetime.now())
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        async def complete(provider, messages, *args, **kwargs):
            if "appold" in messages[0].content:
                started.set()
                await release.wait()
            return ProviderResponse(content='{"known":true,"what":"A notes app.","category":"documents"}',
                                    provider="openrouter", model="test")
        monkeypatch.setattr("providers.failover.complete_with_failover", complete)
        first = asyncio.create_task(app_verification.handle("learn this app", old))
        await started.wait()
        second = await app_verification.handle("learn this app", new)
        app_verification.mark_returned(second.message)
        release.set()
        stale = await first
        assert not stale.success
        assert talk.load()["pending"]["app_verification"]["key"] == "app:appnew"
        app_verification.mark_returned(stale.message)
        assert app_verification.handle_reply("yes").success
        assert knowledge.get("app:appnew").source == "confirmed"
        assert knowledge.get("app:appold").about is None
    asyncio.run(exercise())


@pytest.mark.parametrize("channel", ["chat", "voice"])
def test_api_handles_app_approval_before_model_and_fact_learning(monkeypatch, channel):
    offered(monkeypatch)
    async def forbidden(*args, **kwargs):
        pytest.fail("app approval reached a model")
    monkeypatch.setattr("providers.failover.complete_with_failover", forbidden)
    monkeypatch.setattr("services.mind.brain_memory.brain_memory.remember",
                        lambda *a, **k: pytest.fail("app approval became a personal memory"))
    if channel == "chat":
        from interfaces.api.routes.chat import chat, ChatRequest
        result = asyncio.run(chat(ChatRequest(message="yes", speak=False)))
    else:
        from interfaces.api.routes.voice import _reply, VoiceRequest
        result = asyncio.run(_reply("yes", VoiceRequest(speak=False)))
    assert result.model == "system_control" and result.action_success
    assert knowledge.get("app:mystery").source == "confirmed"


def test_forget_fences_a_lookup_already_in_flight(monkeypatch):
    async def complete(*args, **kwargs):
        app_learning.forget()
        return ProviderResponse(content='{"known":true,"what":"A game.","category":"gaming"}',
                                provider="openrouter", model="test")
    monkeypatch.setattr("providers.failover.complete_with_failover", complete)
    asyncio.run(knowledge.look_up(app(), NOW))
    assert not app_learning.pending() and knowledge.get("app:mystery").about is None
