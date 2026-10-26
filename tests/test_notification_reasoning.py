import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.errors import ProviderError
from providers import failover
from services.mind import cognition_context, talk, notifications
from services.mind.cognition import cognition
from services.proactive import watcher
from core.config import config

REAL_REASON = notifications._reason


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setattr(notifications, "_reason", REAL_REASON)
    sent = []
    monkeypatch.setattr(watcher, "show_toast", lambda title, text, *a, **kw: sent.append(text) or True)
    monkeypatch.setattr(cognition_context, "live_state", lambda: {"activity": "coding", "away": False})
    return sent


@pytest.mark.parametrize("response", [
    '{"decisions":[{"id":"0","send":false,"reason":"The user is busy; stay silent."}]}',
    '{"decisions":[{"id":"0","send":"true","reason":"Invalid decision"}]}',
    'not JSON',
])
def test_a_candidate_is_not_a_notification_until_brain_approves(sent, monkeypatch, response):
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=response)

    monkeypatch.setattr(failover, "complete_with_failover", decide)
    asyncio.run(watcher._deliver("Battery is at 19%. Plug in soon."))
    assert sent == []


def test_provider_failure_does_not_fall_back_to_automatic_nudges(sent, monkeypatch):
    async def fail(*args, **kwargs):
        raise ProviderError("SENTINEL_PRIVATE_ERROR")

    monkeypatch.setattr(failover, "complete_with_failover", fail)
    asyncio.run(watcher._deliver("Battery is at 19%. Plug in soon."))
    assert sent == []
    assert "SENTINEL_PRIVATE_ERROR" not in str(cognition.recent())


def test_approved_candidate_records_reason_and_actual_transport_outcome(sent, monkeypatch):
    async def decide(*args, **kwargs):
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":true,"reason":"Battery is low and unplugged."}]}')

    monkeypatch.setattr(failover, "complete_with_failover", decide)
    asyncio.run(watcher._deliver("Battery is at 19%. Plug in soon."))
    assert sent == ["Battery is at 19%. Plug in soon."]
    event = cognition.latest("notification_decision")
    assert event and event["status"] == "submitted"
    assert "Battery is low" in event["text"]


def test_self_started_question_can_be_suppressed_without_recording_a_pending_question(sent, monkeypatch):
    monkeypatch.setattr(talk, "choose", lambda *a: {"raw": {"kind": "checkin", "ask": "how training is going"}})

    async def wording(*a):
        return "How is training going?"

    async def decide(*args, **kwargs):
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":false,"reason":"Already asked."}]}')

    monkeypatch.setattr(talk.wording, "say", wording)
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    line = asyncio.run(talk.compose(SimpleNamespace(), "checkin", {}, datetime(2026, 10, 14, 11)))
    assert line is None
    assert not talk.load().get("pending")


def test_one_reasoning_call_decides_a_batch_and_gets_facts_not_private_notifications(sent, monkeypatch):
    from services.memory import schedule
    now = datetime(2026, 10, 14, 11)
    schedule.capture("No classes for the next 4 days because of placement training", now)
    cognition.record("notification", "desktop", "SENTINEL_PRIVATE_CONTENT", status="submitted")
    calls = []

    async def decide(provider, messages, prompt, *args, **kwargs):
        payload = json.loads(messages[0].content)
        calls.append(payload)
        return SimpleNamespace(content=json.dumps({"decisions": [
            {"id": str(i), "send": i == 1, "reason": "Choose only one useful observation"}
            for i in range(len(payload["candidates"]))]}))

    monkeypatch.setattr(failover, "complete_with_failover", decide)

    async def tick():
        with notifications.collect(now) as batch:
            await watcher._deliver("First observation")
            await watcher._deliver("Second observation")
        await notifications.dispatch(batch)

    asyncio.run(tick())
    assert len(calls) == 1 and sent == ["Second observation"]
    assert calls[0]["dated_facts"][0]["through"] == "2026-10-17"
    assert "SENTINEL_PRIVATE_CONTENT" not in str(calls)


def test_fact_added_while_reasoning_prevents_delivery_even_if_model_approves(sent, monkeypatch):
    from services.memory import schedule
    now = datetime(2026, 10, 14, 11)

    async def decide(*args):
        schedule.capture("No classes today", now)
        return [notifications.Choice(id="0", send=True, reason="Model missed the changed fact")]

    monkeypatch.setattr(notifications, "_reason", decide)
    candidate = notifications.Candidate("DBMS starts soon", "class_warning", subject="DBMS",
                                        transport=watcher.show_toast)
    asyncio.run(notifications.dispatch(notifications.Batch(now, [candidate])))
    assert sent == []
    assert cognition.latest("notification_decision")["status"] == "suppressed"


def test_assistance_mode_still_requires_actual_brain_approval(sent, monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    calls = []
    async def decide(*args, **kwargs):
        calls.append(kwargs.get("purpose"))
        assert kwargs["response_schema"] == notifications.Choices.model_json_schema()
        assert 1 <= kwargs["attempt_timeout"] <= 8
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":false,"reason":"Not suitable now."}]}')
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    asyncio.run(watcher._deliver("Unnecessary interruption"))
    assert sent == [] and calls == ["notification_review"]


@pytest.mark.parametrize("ids", [["00"], ["0", "0"], [], ["1"]])
def test_malformed_candidate_id_set_cannot_approve_notifications(sent, monkeypatch, ids):
    async def decide(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"decisions": [
            {"id": ident, "send": True, "reason": "Approve"} for ident in ids]}))
    monkeypatch.setattr(failover, "complete_with_failover", decide)
    asyncio.run(watcher._deliver("Observation"))
    assert sent == []


def test_private_origin_stays_private_after_authorized_review(sent, monkeypatch):
    flags = []
    def transport(title, text, *args, **kwargs):
        flags.append(kwargs["cognition_public"])
        cognition.record("notification", "desktop", text, status="submitted", public=kwargs["cognition_public"])
        return True
    async def approve(*args, **kwargs):
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":true,"reason":"Work finished."}]}')
    monkeypatch.setattr(failover, "complete_with_failover", approve)
    asyncio.run(notifications.notify("SENTINEL_PRIVATE_COMMAND finished", transport=transport, public=False))
    assert flags == [False]
    assert all(not event["public"] for event in cognition.recent() if "SENTINEL_PRIVATE_COMMAND" in event["text"])


@pytest.mark.parametrize("change", ["busy", "facts", "disabled"])
def test_changed_context_after_model_approval_prevents_transport(sent, monkeypatch, change):
    from services.memory import schedule
    busy = [False]
    monkeypatch.setattr(watcher, "is_busy", lambda: busy[0])
    async def approve(*args, **kwargs):
        if change == "busy":
            busy[0] = True
        elif change == "facts":
            schedule.capture("No classes today", datetime(2026, 10, 16, 11))
        else:
            monkeypatch.setattr(config, "NOTIFICATION_REVIEW_ENABLED", False)
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":true,"reason":"Looks useful."}]}')
    monkeypatch.setattr(failover, "complete_with_failover", approve)
    asyncio.run(notifications.notify("A new download is ready", transport=watcher.show_toast,
                                    now=datetime(2026, 10, 16, 11)))
    assert sent == []


def test_incomplete_provider_output_cannot_approve_candidate(sent, monkeypatch):
    async def approve(*args, **kwargs):
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":true,"reason":"Useful."}]}',
                               metadata={"incomplete": True})
    monkeypatch.setattr(failover, "complete_with_failover", approve)
    asyncio.run(watcher._deliver("Observation"))
    assert sent == []


def test_two_approved_candidates_do_not_invalidate_each_other(sent, monkeypatch):
    async def approve(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"decisions": [
            {"id": str(i), "send": True, "reason": "Useful observation"} for i in range(2)]}))
    monkeypatch.setattr(failover, "complete_with_failover", approve)
    def transport(title, text, *args, **kwargs):
        sent.append(text)
        cognition.record("notification", "desktop", text, status="submitted", public=True)
        return True
    batch = notifications.Batch(datetime.now(), [notifications.Candidate(text, transport=transport)
                                                for text in ["First", "Second"]])
    asyncio.run(notifications.dispatch(batch))
    assert sent == ["First", "Second"]


def test_brain_payload_preserves_memory_source_and_date(sent, monkeypatch):
    from services.memory.semantic import semantic_memory
    with semantic_memory._connect() as conn:
        conn.execute("INSERT INTO memories(text,vector,source,created_at,happens_on) VALUES(?,?,?,?,?)",
                     ("Interview moved", b"", "told", "2026-10-15T11:00:00", "2026-10-16"))
    payloads = []
    async def decline(provider, messages, *args, **kwargs):
        payloads.append(json.loads(messages[0].content))
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":false,"reason":"No interruption."}]}')
    monkeypatch.setattr(failover, "complete_with_failover", decline)
    asyncio.run(watcher._deliver("Observation"))
    assert payloads[0]["remembered_facts"][0]["source"] == "told"
    assert payloads[0]["remembered_facts"][0]["happens_on"] == "2026-10-16"


def test_context_changes_between_batch_destinations_stop_later_candidate(sent, monkeypatch):
    busy = [False]
    monkeypatch.setattr(watcher, "is_busy", lambda: busy[0])
    async def approve(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"decisions": [
            {"id": str(i), "send": True, "reason": "Useful observation"} for i in range(2)]}))
    monkeypatch.setattr(failover, "complete_with_failover", approve)
    def transport(title, text, *args, **kwargs):
        sent.append(text)
        busy[0] = True
        return True
    batch = notifications.Batch(datetime.now(), [notifications.Candidate(text, transport=transport)
                                                for text in ["First", "Second"]])
    asyncio.run(notifications.dispatch(batch))
    assert sent == ["First"]
    event = cognition.latest("notification_decision")
    detail = json.loads(event["text"])
    assert event["status"] == "suppressed"
    assert "changed" in detail["reason"]
    assert detail["supersedes"] is not None


@pytest.mark.parametrize("changed_facts", [False, True])
def test_urgent_notice_can_interrupt_but_cannot_ignore_changed_facts(sent, monkeypatch, changed_facts):
    from services.memory import schedule
    now = datetime(2026, 10, 16, 11)
    busy = [False]
    monkeypatch.setattr(watcher, "is_busy", lambda: busy[0])
    async def approve(*args, **kwargs):
        busy[0] = True
        if changed_facts:
            schedule.capture("No classes today", now)
        return SimpleNamespace(content='{"decisions":[{"id":"0","send":true,"reason":"Battery critically low."}]}')
    monkeypatch.setattr(failover, "complete_with_failover", approve)
    asyncio.run(notifications.notify("Battery 1%", transport=watcher.show_toast, urgent=True, now=now))
    assert sent == ([] if changed_facts else ["Battery 1%"])
