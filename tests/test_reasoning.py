import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.config import config
from services.mind.cognition import cognition, Cognition

NOW = datetime(2026, 10, 14, 10)
TEXT = "For four days starting today, placement workshops replace every lecture."


def report(quote=TEXT, effect=None, **changes):
    result = {"facts": [{"id": "f0", "quote": quote, "certainty": "confirmed", "supersedes": []}],
              "conclusions": [{"kind": "implication", "text": "Regular classes are replaced by training.",
                               "evidence": ["f0"], "confidence": 0.98,
                               "start": "2026-10-14", "end": "2026-10-17",
                               "effect": effect or {"type": "class_availability", "available": False, "subject": "",
                                                    "basis": "explicit"}}], "questions": []}
    result.update(changes)
    return result


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(config, "REASONING_ENABLED", True)
    from providers import failover
    captured = []
    async def complete(provider, messages, prompt, *args, **kwargs):
        payload = json.loads(messages[0].content)
        captured.append(payload)
        # "Starting today" follows the caller's clock, including route tests
        # that intentionally use real time rather than the explicit NOW fixture.
        when = datetime.fromisoformat(payload["time"])
        data = report()
        data["conclusions"][0].update(start=when.date().isoformat(), end=(when + timedelta(days=3)).date().isoformat())
        return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    from services.mind import reasoning
    async def accept_known_test_report(*args): pass
    monkeypatch.setattr(reasoning, "critique", accept_known_test_report)
    return captured


def test_unrecognised_wording_produces_real_dated_class_consequences(engine):
    from services.mind import reasoning
    from services.memory import schedule
    from services.proactive import timetable, attendance, college
    assert schedule.parse(TEXT, NOW) is None
    timetable._save([dict(day=d, start="09:00", end="10:00", subject="DBMS", room="204") for d in timetable.DAYS])
    result = asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert result["status"] == "completed"
    assert timetable.classes_for_date(NOW.date()) == []
    assert attendance.due_asks(NOW.replace(hour=10, minute=5)) == []
    assert college.class_start_offer(NOW.replace(hour=9, minute=2), True, False) is None
    assert timetable.classes_for_date((NOW + timedelta(days=4)).date())
    assert len(timetable.load()) == 7
    assert engine[0]["time"].startswith("2026-10-14")


def test_arbitrary_facts_and_predictions_are_distinct_and_survive_restart(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import ReasoningStore, reasoning_store
    from providers import failover
    text = "I will be in a pottery workshop tomorrow morning."
    data = report(text, effect={"type": "guidance"})
    data["conclusions"][0].update(kind="prediction", text="The user may be unavailable for laptop work tomorrow morning.")
    async def complete(*args, **kwargs):
        return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze(text, "test", NOW))
    saved = ReasoningStore(Cognition(cognition.path)).context(NOW)
    assert saved["facts"][0]["quote"] == text
    assert saved["conclusions"][0]["kind"] == "prediction"
    assert saved["conclusions"][0]["status"] == "inferred"
    assert reasoning_store.remembered()[0][0] == text


@pytest.mark.parametrize("change", ["fabricated_quote", "unknown_evidence", "shell", "bad_dates", "duplicate_id"])
def test_invalid_model_output_cannot_change_any_service(engine, monkeypatch, change):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.memory import schedule
    from providers import failover
    data = report()
    if change == "fabricated_quote": data["facts"][0]["quote"] = "I cancelled all classes forever"
    if change == "unknown_evidence": data["conclusions"][0]["evidence"] = ["made_up"]
    if change == "shell": data["conclusions"][0]["effect"] = {"type": "run_shell", "command": "erase files"}
    if change == "bad_dates": data["conclusions"][0]["end"] = "2026-10-01"
    if change == "duplicate_id": data["facts"].append(dict(data["facts"][0]))
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    result = asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert result["status"] == "unavailable"
    assert not reasoning_store.context(NOW)["facts"]
    assert schedule.allowed(NOW.date(), "DBMS")


def test_uncertain_inference_only_proposes_and_approval_is_explicit(engine, monkeypatch):
    from services.mind import reasoning, reasoning_commands
    from services.mind.reasoning_store import reasoning_store
    from services.memory import schedule
    from providers import failover
    data = report(effect={"type": "class_availability", "available": False, "subject": "", "basis": "inferred"})
    data["facts"][0]["certainty"] = "uncertain"
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    proposal = reasoning_store.context(NOW)["conclusions"][0]
    assert proposal["status"] == "proposed" and schedule.allowed(NOW.date())
    from services.mind import reasoning_effects
    apply = reasoning_effects.apply
    monkeypatch.setattr(reasoning_effects, "apply", lambda ident: apply(ident, NOW))
    result = asyncio.run(reasoning_commands.run({"action": "apply", "id": str(proposal["id"])}))
    assert result.success and not schedule.allowed(NOW.date())


def test_correction_invalidates_old_conclusions_and_forgetting_restores_schedule(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.memory import schedule
    from providers import failover
    asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    fact_id = reasoning_store.context(NOW)["facts"][0]["id"]
    corrected = "Actually, my regular lectures will run as usual."
    data = report(corrected)
    data["facts"][0]["supersedes"] = [fact_id]
    data["conclusions"][0]["effect"]["available"] = True
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze(corrected, "test", NOW + timedelta(hours=1)))
    assert schedule.allowed(NOW.date())
    assert len(reasoning_store.context(NOW)["conclusions"]) == 1
    reasoning_store.forget(corrected)
    assert not reasoning_store.context(NOW)["conclusions"]


def test_stale_task_proposal_cannot_overwrite_newer_plan(engine, monkeypatch):
    from services.mind import reasoning, reasoning_commands
    from services.mind.workspace import workspace
    from services.mind.reasoning_store import reasoning_store
    from providers import failover
    task = workspace.start_task("Prepare for placements")
    data = report("Please plan my interview preparation.", effect={"type": "task_plan", "task_id": task,
                                                                   "steps": ["Review arrays", "Mock interview"]})
    data["facts"] = []
    data["conclusions"][0]["evidence"] = [f"task:{task}"]
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze("Please plan my interview preparation.", "test", NOW))
    proposal = reasoning_store.context(NOW)["conclusions"][0]
    workspace.plan(task, ["My newer plan"])
    result = asyncio.run(reasoning_commands.run({"action": "apply", "id": str(proposal["id"])}))
    assert not result.success and workspace.tasks()[0]["steps"] == ["My newer plan"]


def test_reasoning_excludes_private_notifications_and_never_rolls_dates(engine):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    cognition.record("notification", "desktop", "PRIVATE_SENTINEL", status="submitted")
    asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert "PRIVATE_SENTINEL" not in str(engine)
    assert not reasoning_store.context(NOW + timedelta(days=4))["conclusions"]


def test_provider_failure_is_quiet_and_records_unavailability(engine, monkeypatch):
    from services.mind import reasoning
    from providers import failover
    async def fail(*args, **kwargs): raise RuntimeError("private-token-detail")
    monkeypatch.setattr(failover, "complete_with_failover", fail)
    result = asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert result["status"] == "unavailable"
    assert "private-token-detail" not in str(cognition.recent())


def test_expired_constraint_still_protects_historical_attendance_and_cannot_roll_forward(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.mind.reasoning_effects import class_facts
    from providers import failover
    asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert class_facts(NOW + timedelta(days=10))[0].covers(NOW.date())
    fact = reasoning_store.context(NOW)["facts"][0]
    data = report(facts=[])
    data["conclusions"][0].update(evidence=[fact["id"]], start="2026-10-24", end="2026-10-27")
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    assert asyncio.run(reasoning.analyze("", "test", NOW + timedelta(days=10)))["status"] == "unavailable"


def test_approved_task_plan_is_saved_once_and_not_executed(engine, monkeypatch):
    from services.mind import reasoning, reasoning_effects
    from services.mind.workspace import workspace
    from services.mind.reasoning_store import reasoning_store
    from providers import failover
    task = workspace.start_task("Learn gardening")
    data = report(facts=[])
    data["conclusions"][0].update(evidence=[f"task:{task}"], effect={"type": "task_plan", "task_id": task,
                                                                          "steps": ["Buy seeds", "Plant tomatoes"]})
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze("Plan my gardening task", "test", NOW))
    proposal = reasoning_store.context(NOW)["conclusions"][0]
    assert not workspace.tasks()[0]["steps"]
    reasoning_effects.apply(proposal["id"], NOW)
    assert workspace.tasks()[0]["steps"] == ["Buy seeds", "Plant tomatoes"]
    assert workspace.tasks()[0]["cursor"] == 0
    with pytest.raises(ValueError): reasoning_effects.apply(proposal["id"], NOW)
    assert cognition.latest("reasoning_action")["status"] == "verified"


def test_reminder_conflict_needs_approval_and_rechecks_delivery(engine, monkeypatch):
    from services.mind import reasoning, reasoning_effects
    from services.mind.reasoning_store import reasoning_store
    from services.reminders.service import ReminderService
    from providers import failover
    reminders = ReminderService()
    reminders.add_from_message("remind me to revise at 11am", NOW)
    original = reminders.pending()[0]
    text = "My dentist appointment clashes with revision."
    data = report(text, effect={"type": "reminder_move", "reminder_id": original.id, "due": "2026-10-14T16:00:00"})
    data["conclusions"][0]["evidence"].append(f"reminder:{original.id}")
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze(text, "test", NOW))
    assert reminders.pending()[0].due_at == original.due_at
    proposal = reasoning_store.context(NOW)["conclusions"][0]
    reasoning_effects.apply(proposal["id"], NOW)
    assert reminders.pending()[0].due_at == NOW.replace(hour=16).timestamp()
    assert cognition.latest("reasoning_action")["status"] == "verified"


def test_evidence_change_during_model_call_discards_stale_report(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.workspace import workspace
    from services.mind.reasoning_store import reasoning_store
    from providers import failover
    task = workspace.start_task("Interviews")
    data = report(facts=[])
    data["conclusions"][0].update(evidence=[f"task:{task}"], effect={"type": "task_plan", "task_id": task, "steps": ["Mock interview"]})
    async def complete(*args, **kwargs):
        workspace.plan(task, ["New owner plan"])
        return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    assert asyncio.run(reasoning.analyze("Plan my interview work", "test", NOW))["status"] == "unavailable"
    assert not reasoning_store.context(NOW)["conclusions"]


@pytest.mark.parametrize("interface", ["chat", "voice"])
def test_normal_replies_consume_reasoned_consequences_and_questions(engine, monkeypatch, interface):
    from interfaces.api.routes import chat, voice
    from providers.base_provider import ProviderResponse
    route = chat if interface == "chat" else voice
    monkeypatch.setattr(route, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    async def none(*args, **kwargs): return None
    for name in ("try_system_action", "build_file_context", "build_search_context"):
        monkeypatch.setattr(route, name, none)
    prompts = []
    async def reply(provider, messages, prompt, *args, **kwargs):
        prompts.append(prompt)
        return ProviderResponse("Your class schedule reflects the workshop replacement.", "test", "test")
    monkeypatch.setattr(route, "complete_with_failover", reply)
    if interface == "chat": asyncio.run(chat.chat(chat.ChatRequest(message=TEXT, speak=False)))
    else: asyncio.run(voice._reply(TEXT, voice.VoiceRequest(speak=False)))
    assert "Regular classes are replaced by training" in prompts[0]
    assert "applied" in prompts[0] and "Owner quotes are facts as told" in prompts[0]


def test_periodic_review_is_change_driven_and_does_not_store_synthetic_user_facts(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.workspace import workspace
    from providers import failover
    calls = []
    monkeypatch.setattr(reasoning, "_review_after", datetime.min)
    monkeypatch.setattr(reasoning, "_signature", "")
    workspace.add_goal("Learn cooking")
    async def complete(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(content='{"facts":[],"conclusions":[],"questions":[]}')
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    for minutes in (0, 1, 6): asyncio.run(reasoning.review(NOW + timedelta(minutes=minutes)))
    assert len(calls) == 1
    workspace.add_goal("Learn drawing")
    asyncio.run(reasoning.review(NOW + timedelta(minutes=12)))
    assert len(calls) == 2


def test_bad_conclusions_do_not_erase_validated_owner_facts(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.memory import schedule
    monkeypatch.setattr(reasoning, "critique", REAL_CRITIQUE)
    from providers import failover
    async def complete(provider, messages, prompt, *args, **kwargs):
        return SimpleNamespace(content=json.dumps({"checks": [{"id": 0, "supported": False, "reason": "The dates do not follow from evidence"}]} if "Check FRIDAY" in prompt else report()))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    result = asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert result["status"] == "facts_only"
    assert reasoning_store.remembered()[0][0] == TEXT
    assert not reasoning_store.context(NOW)["conclusions"] and schedule.allowed(NOW.date())
    assert cognition.latest("reasoning")["status"] == "facts_only"


def test_schema_repair_is_bounded_and_only_valid_report_is_saved(engine, monkeypatch):
    from services.mind import reasoning
    from providers import failover
    calls = []
    async def complete(provider, messages, prompt, *args, **kwargs):
        calls.append(messages)
        assert kwargs["response_schema"]["type"] == "object"
        data = report()
        if len(calls) == 1: data["conclusions"][0]["evidence"] = ["fabricated"]
        return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    result = asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    assert result["status"] == "completed" and len(calls) == 2
    assert "failed validation" in calls[-1][-1].content


def test_evidence_check_requires_a_strict_check_for_every_conclusion(engine, monkeypatch):
    from services.mind import reasoning
    from providers import failover
    async def complete(*args, **kwargs): return SimpleNamespace(content='{"checks":[]}')
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    with pytest.raises(ValueError):
        asyncio.run(REAL_CRITIQUE(reasoning.Report.model_validate_json(json.dumps(report())), {}, "test"))


def test_local_provider_uses_native_schema_without_changing_plain_completions(monkeypatch):
    from providers.ollama.client import OllamaProvider
    from providers.base_provider import Message
    from providers.ollama import client as ollama_client
    payloads = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            payloads.append(json)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": {"content": "{}"}})
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", Client)
    provider = OllamaProvider()
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    asyncio.run(provider.complete_structured(schema, messages=[Message("user", "test")], system_prompt="test"))
    asyncio.run(provider.complete(messages=[Message("user", "test")], system_prompt="test"))
    assert payloads[0]["format"] == schema and payloads[0]["options"]["num_ctx"] == 16384
    assert "format" not in payloads[1] and "num_ctx" not in payloads[1]["options"]


def test_proposal_nomination_is_once_and_actual_notification_is_still_decided(engine, monkeypatch):
    from services.mind import reasoning, notifications
    from services.mind.reasoning_store import reasoning_store
    from services.mind.workspace import workspace
    from providers import failover
    task = workspace.start_task("Interview practice")
    data = report(facts=[])
    data["conclusions"][0].update(evidence=[f"task:{task}"], effect={"type": "task_plan", "task_id": task, "steps": ["Mock interview"]})
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze("Plan interview practice", "test", NOW))
    candidate = reasoning.suggestion(NOW)
    assert "Proposed:" in candidate["text"] and reasoning.suggestion(NOW) is None
    sent = []
    async def decline(*args): return [notifications.Choice(id="0", send=False, reason="Owner is working")]
    monkeypatch.setattr(notifications, "_reason", decline)
    asyncio.run(notifications.notify(candidate["text"], kind="reasoning", subject=f"reasoning:{candidate['id']}",
                                     transport=lambda *a, **kw: sent.append(a), now=NOW))
    assert not sent and not workspace.tasks()[0]["steps"]


from services.mind.reasoning import critique as REAL_CRITIQUE


def test_forgetting_removes_duplicate_owner_quotes_and_never_reuses_proposal_ids(engine):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.memory.semantic import semantic_memory
    with semantic_memory._connect() as db:
        db.execute("INSERT INTO memories (text, vector, source, created_at) VALUES (?, ?, 'told', ?)",
                   (TEXT, b"\0" * 16, NOW.isoformat()))
    asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    old = reasoning_store.context(NOW)["conclusions"][0]["id"]
    reasoning_store.forget(TEXT)
    with semantic_memory._connect() as db:
        assert not db.execute("SELECT id FROM memories WHERE text = ?", (TEXT,)).fetchall()
    reasoning_store.forget_all()
    asyncio.run(reasoning.analyze(TEXT, "test", NOW + timedelta(minutes=1)))
    assert reasoning_store.context(NOW)["conclusions"][0]["id"] > old


def test_task_change_during_notification_decision_prevents_a_stale_proposal_notice(engine, monkeypatch):
    from services.mind import reasoning, notifications
    from services.mind.reasoning_store import reasoning_store
    from services.mind.workspace import workspace
    from providers import failover
    task = workspace.start_task("Review algorithms")
    data = report(facts=[])
    data["conclusions"][0].update(evidence=[f"task:{task}"], effect={"type": "task_plan", "task_id": task, "steps": ["Arrays"]})
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    asyncio.run(reasoning.analyze("Plan my review", "test", NOW))
    ident = reasoning_store.context(NOW)["conclusions"][0]["id"]
    sent = []
    async def approve(*args):
        workspace.plan(task, ["Different owner plan"])
        return [notifications.Choice(id="0", send=True, reason="Useful proposal")]
    monkeypatch.setattr(notifications, "_reason", approve)
    asyncio.run(notifications.notify("New plan?", kind="reasoning", subject=f"reasoning:{ident}",
                                     transport=lambda *a, **kw: sent.append(a), now=NOW))
    assert not sent


def test_first_interpretation_of_legacy_fact_uses_original_receipt_dates(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.memory import semantic, schedule
    from providers import failover
    with semantic.semantic_memory._connect() as db:
        db.execute("INSERT INTO memories (text, vector, source, created_at) VALUES (?, ?, 'told', ?)",
                   ("No classes for the next four days", b"\0" * 16, (NOW - timedelta(days=2)).isoformat()))
    data = report(facts=[])
    data["conclusions"][0]["evidence"] = ["memory:1"]
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    assert asyncio.run(reasoning.analyze("", "test", NOW))["status"] == "unavailable"
    assert schedule.allowed((NOW + timedelta(days=2)).date())
    assert not reasoning_store.context(NOW)["conclusions"]


def test_uncertain_correction_cannot_silently_restore_classes(engine, monkeypatch):
    from services.mind import reasoning
    from services.mind.reasoning_store import reasoning_store
    from services.memory import schedule
    from providers import failover
    asyncio.run(reasoning.analyze(TEXT, "test", NOW))
    old = reasoning_store.context(NOW)["facts"][0]["id"]
    text = "Maybe the workshops were postponed; I am not sure."
    data = report(text, conclusions=[])
    data["facts"][0].update(certainty="uncertain", supersedes=[old])
    async def complete(*args, **kwargs): return SimpleNamespace(content=json.dumps(data))
    monkeypatch.setattr(failover, "complete_with_failover", complete)
    assert asyncio.run(reasoning.analyze(text, "test", NOW))["status"] == "unavailable"
    assert not schedule.allowed(NOW.date())
