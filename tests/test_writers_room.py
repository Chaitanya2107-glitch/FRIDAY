import asyncio
from collections import Counter
from datetime import datetime, timedelta
import json

import pytest

from core.config import config
from core.errors import ModelUnavailable
from providers.base_provider import ProviderResponse
from services.mind import writers_room as room
from services.mind.reviews import ReviewStore, reviews
from services.remote.context import origin_scope


NOW = datetime(2026, 11, 18, 16, 0)


def powered(monkeypatch, *, idle=0, plugged=True, mode="on"):
    monkeypatch.setattr(config, "FRIDAY_LLM", mode)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", True)
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "test-writer")
    monkeypatch.setattr(room.state, "snapshot", lambda _: {"idle": idle, "battery": {"plugged": plugged},
                                                           "situation": {"title": "PRIVATE SCHEDULE"}})


def draft_gateway(monkeypatch):
    calls = []
    chosen = Counter()

    async def complete(provider, messages, prompt, max_tokens, **options):
        assert provider == "ollama" and room.policy.purpose.get() == "wording"
        assert "PRIVATE SCHEDULE" not in messages[0].content
        assert options["response_schema"] == room.SCHEMA
        requests = json.loads(messages[0].content)
        calls.append(requests)
        result = []
        for row in requests:
            kind, band = row["intent"], row["band"]
            lead = row["prefix_choices"][1 + chosen[kind, band] % (len(row["prefix_choices"]) - 1)]
            chosen[kind, band] += 1
            result.append({"intent": kind, "band": band, "template": lead + "{fact}"})
        return ProviderResponse(json.dumps({"lines": result}), provider, "test-writer")

    monkeypatch.setattr(room.failover, "complete_exact", complete)
    return calls


def test_off_stops_before_state_and_never_opens_inbox(monkeypatch):
    powered(monkeypatch, mode="off")
    monkeypatch.setattr(room.state, "snapshot", lambda *args: pytest.fail("Off mode read state"))
    monkeypatch.setattr(room.failover, "complete_exact", lambda *args: pytest.fail("Off mode called the gateway"))
    assert asyncio.run(room.tick(NOW)) == 0
    assert "no lines" in asyncio.run(room.handle("review lines")).message
    assert not reviews.path.exists()


def test_idle_or_power_gate(monkeypatch):
    powered(monkeypatch, idle=299, plugged=False)
    calls = draft_gateway(monkeypatch)
    assert asyncio.run(room.tick(NOW)) == 0
    assert calls == []
    powered(monkeypatch, idle=300, plugged=False)
    assert asyncio.run(room.tick(NOW)) == 5
    powered(monkeypatch, idle=0, plugged=True)
    assert asyncio.run(room.tick(NOW)) == 5
    assert len(calls) == 2


def test_budget_is_atomic_persists_and_resets_each_day(monkeypatch):
    powered(monkeypatch)
    calls = draft_gateway(monkeypatch)

    async def race():
        return await asyncio.gather(*(room.tick(NOW) for i in range(10)))

    assert sum(asyncio.run(race())) == 20
    assert len(calls) == 4
    assert len(reviews.queue(kind="line")) == 20
    monkeypatch.setattr(room, "reviews", ReviewStore(reviews.path))
    assert asyncio.run(room.tick(NOW)) == 0
    assert asyncio.run(room.tick(NOW + timedelta(days=1))) == 5
    assert len(calls) == 5
    assert len(reviews.queue(kind="line")) == 25


def test_review_batches_local_only_edit_approval_provenance_and_revoke(monkeypatch, tmp_path):
    powered(monkeypatch)
    draft_gateway(monkeypatch)
    asyncio.run(room.tick(NOW))
    asyncio.run(room.tick(NOW))
    first = min(reviews.queue(kind="line"), key=lambda row: row["id"])
    item, kind, band = first["id"], first["subject"], first["pattern"]
    assert room.approved_templates(kind, band) == []
    preview = asyncio.run(room.handle("review lines"))
    assert preview.success and preview.speech == ""
    assert first["question"] in preview.message and first["question"] not in preview.memory_message
    assert len([line for line in preview.message.splitlines() if line[0].isdigit()]) == 5
    cursor = preview.message.splitlines()[-1].split()[-3]
    second = asyncio.run(room.handle(f"review lines after {cursor}"))
    assert all(not line.startswith(f"{item}. ") for line in second.message.splitlines())
    with origin_scope(True):
        private = asyncio.run(room.handle("review lines"))
        assert private.success is False and first["question"] not in private.message
        assert not asyncio.run(room.handle(f"approve line {item}")).success
    assert not asyncio.run(room.handle(f"edit line {item}: Boss, you left me lonely. {{fact}}")).success
    edited = next(lead + "{fact}" for lead in room._frames(kind, band)[0][1:] if lead + "{fact}" != first["question"])
    assert asyncio.run(room.handle(f"edit line {item}: {edited}")).success
    assert room.approved_templates(kind, band) == []
    assert reviews.get(item)["question"] == first["question"]  # preserve source
    with pytest.raises(ValueError, match="writer's room"):
        reviews.review(item, preferred=edited, approve=True)
    assert reviews.queue(kind="learning") == []
    assert asyncio.run(room.handle(f"approve line {item}")).success
    with pytest.raises(ValueError, match="approved"):
        reviews.train(item)
    record, = room.approved_templates(kind, band)
    assert record["id"] == item and record["template"] == edited
    assert record["provenance"] == {
        "intent": kind, "band": band, "provider": "ollama", "model": "test-writer",
        "drafted_at": NOW.timestamp(), "approved_at": reviews.get(item)["reviewed_at"], "owner_edited": True,
    }
    monkeypatch.setattr(config, "FRIDAY_LLM", "off")
    assert room.approved_templates(kind, band) == [record]
    assert reviews.learned() == [] and reviews.facts() == []
    assert reviews.export(tmp_path / "dataset.jsonl") == 0
    assert asyncio.run(room.handle(f"reject line {item}")).success
    assert room.approved_templates(kind, band) == []


@pytest.mark.parametrize("bad", [
    "A quick update. You're lazy. {fact}", "You've finally come back. {fact}",
    "You made me upset. {fact}", "I feel actual joy. {fact}", "A quick update.",
    "A quick update. {fact} {fact}", "A quick update. {fact!r}", "A quick update. {fact.__class__}",
    "A quick update. {fact} " + "A " * 250, "A quick update. {fact}\nReady for the next thing.",
    "a quick update. {fact}", "A quick update. {fact} Don't leave me.",
])
def test_hard_template_grammar(bad):
    assert room.valid_template("command", "bright", "A quick update, Boss. {fact} Ready for the next thing.")
    assert not room.valid_template("command", "bright", bad)


@pytest.mark.parametrize("failure", ["slow", "garbage", "mode_change", "unsafe"])
def test_bad_generation_never_reaches_inbox(monkeypatch, failure):
    powered(monkeypatch)
    async def complete(provider, messages, *args, **kwargs):
        if failure == "slow":
            raise ModelUnavailable("Timed out")
        request = json.loads(messages[0].content)[0]
        candidate = {key: request[key] for key in ("intent", "band")}
        candidate["template"] = request["prefix_choices"][1] + "{fact}"
        if failure == "mode_change":
            monkeypatch.setattr(config, "FRIDAY_LLM", "off")
        if failure == "unsafe":
            candidate["template"] = "I really feel bad you left. {fact}"
        text = "{nonsense" if failure == "garbage" else json.dumps({"lines": [candidate]})
        return ProviderResponse(text, "ollama", "test-writer")

    monkeypatch.setattr(room.failover, "complete_exact", complete)
    assert asyncio.run(room.tick(NOW)) == 0
    assert reviews.queue(kind="line") == []

