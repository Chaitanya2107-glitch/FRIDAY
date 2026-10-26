import asyncio
import json
from pathlib import Path

import pytest

from services.activity import projects
from services.automation import intent
from services.memory import notes
from services.mind.workspace import workspace
from test_project_session import session


def say(message):
    return asyncio.run(intent.try_system_action(message, "openrouter"))


def prepare():
    assert say("prepare my project work session for friday").success


def test_note_instructions_create_new_verified_briefs_and_preserve_old_output(session):
    runner, _ = session
    notes.add("FRIDAY private note")
    prepare()
    first = runner.get(1)
    result = say("leave out the notes")
    assert result.success and "Verified brief" in result.message
    second = runner.get(2)
    assert second["payload"]["include_notes"] is False
    assert "private note" not in Path(second["artifact"]).read_text(encoding="utf-8")
    assert "private note" in Path(first["artifact"]).read_text(encoding="utf-8")
    assert say("include the notes again").success
    assert "private note" in Path(runner.get(3)["artifact"]).read_text(encoding="utf-8")


def test_refresh_uses_current_sources_instead_of_replaying_old_snapshot(session):
    runner, root = session
    prepare()
    (root / "new.py").write_text("new content", encoding="utf-8")
    notes.add("FRIDAY new context")
    assert say("refresh that brief").success
    row = runner.get(2)
    assert row["verified"] and row["payload"]["supersedes"] == 1
    assert "new.py" in Path(row["artifact"]).read_text(encoding="utf-8")


def test_project_correction_preserves_note_preference_and_leaves_old_artifact(session, tmp_path):
    runner, root = session
    college = tmp_path / "college"
    college.mkdir()
    (college / "syllabus.txt").write_text("private", encoding="utf-8")
    projects.path.write_text(json.dumps({"friday": {"path": str(root)}, "college": {"path": str(college)}}))
    prepare()
    assert say("leave out the notes").success
    assert say("actually, use the college project").success
    row = runner.get(3)
    assert row["payload"]["project"]["name"] == "college" and row["verified"]
    assert row["payload"]["include_notes"] is False
    assert "syllabus.txt" in Path(row["artifact"]).read_text(encoding="utf-8")
    assert runner.get(1)["verified"]


def test_ambiguous_switch_waits_for_name_and_remote_cannot_consume_answer(session, tmp_path):
    runner, root = session
    projects.path.write_text(json.dumps({name: {"path": str(root)} for name in ["friday", "college web", "college app"]}))
    prepare()
    answer = say("actually use the college project")
    assert not answer.success and "Which project" in answer.message and "Reply with" in answer.message
    with workspace._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspace_executions").fetchone()[0] == 1
    token = intent.remote_request.set(True)
    try:
        # A generic short answer on Telegram cannot inspect or consume laptop clarification.
        assert not say("refresh that brief").success
    finally:
        intent.remote_request.reset(token)
    assert say("college app").success
    assert runner.get(2)["payload"]["project"]["name"] == "college app"


def test_unrelated_turn_expires_short_followups_but_explicit_status_restores_context(session):
    runner, _ = session
    prepare()
    assert say("what is the date and time").success
    result = say("refresh that brief")
    assert not result.success and "current" in result.message.lower()
    assert say("check my work session").success
    assert say("refresh that brief").success
    assert runner.get(2)["verified"]


def test_cancelled_session_cannot_be_revived_by_short_instructions(session):
    runner, _ = session
    ident = runner.create("friday")
    workspace.focus("project_session", ident)
    assert say("cancel my work session").success
    assert not say("refresh that brief").success
    assert runner.get(ident)["state"] == "cancelled"


def test_excluded_notes_are_not_read_and_blocked_old_job_cannot_resume(session, monkeypatch):
    runner, _ = session
    notes.path.write_text("invalid JSON", encoding="utf-8")
    assert not say("prepare my project work session for friday").success
    assert runner.get(1)["state"] == "blocked"
    monkeypatch.setattr(runner, "_read_notes", lambda: pytest.fail("Excluded notes were read"))
    assert say("leave out the notes").success
    assert runner.get(1)["state"] == "cancelled"
    assert runner.run(1, resume=True)["state"] == "cancelled"
    assert runner.get(2)["verified"]


def test_followup_context_survives_restart_and_stale_tokens_cannot_retarget(session, monkeypatch):
    from services.mind import project_session, project_session_context as continuity
    from services.mind.cognition import Cognition, cognition
    from services.mind.workspace import Workspace
    runner, _ = session
    prepare()
    stale = continuity.current(runner)
    restarted = project_session.ProjectSessionEngine(Workspace(Cognition(cognition.path)), runner.output_dir)
    monkeypatch.setattr(project_session, "sessions", restarted)
    assert say("leave out the notes").success
    with pytest.raises(ValueError, match="changed or expired"):
        restarted.revise(stale)
    assert continuity.current(restarted)["target"] == 2
    assert say("refresh that brief").success
    assert not restarted.get(3)["payload"]["include_notes"]


def test_expired_context_does_not_guess_from_persisted_focus(session):
    runner, _ = session
    prepare()
    with workspace._db() as conn:
        conn.execute("UPDATE workspace_brief_context SET expires=0")
    result = say("leave out the notes")
    assert not result.success and "No current brief context" in result.message
    assert say("check my work session").success
    assert say("leave out the notes").success


def test_ordinal_answer_selects_only_an_offered_project(session):
    runner, root = session
    names = ["friday", "college web", "college app"]
    projects.path.write_text(json.dumps({name: {"path": str(root)} for name in names}))
    prepare()
    assert not say("use the other project").success
    assert say("the second one").success
    assert runner.get(2)["payload"]["project"]["name"] == "college app"


def test_changed_project_choice_is_rejected_before_any_new_job(session, tmp_path):
    runner, root = session
    names = ["friday", "college web", "college app"]
    catalog = {name: {"path": str(root)} for name in names}
    projects.path.write_text(json.dumps(catalog))
    prepare()
    assert not say("use the other project").success
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    catalog["college app"]["path"] = str(replacement)
    projects.path.write_text(json.dumps(catalog))
    answer = say("college app")
    assert not answer.success and "registered project changed" in answer.message
    with workspace._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspace_executions").fetchone()[0] == 1


def test_refresh_cannot_silently_follow_a_changed_registration(session, tmp_path):
    runner, _ = session
    prepare()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    projects.path.write_text(json.dumps({"friday": {"path": str(replacement)}}))
    assert not say("refresh that brief").success
    assert say("prepare my work session for friday").success
    assert runner.get(2)["payload"]["project"]["path"] == str(replacement.resolve())


def test_workspace_reset_removes_context_but_keeps_published_brief(session):
    from services.mind import project_session_context as continuity
    runner, _ = session
    prepare()
    artifact = Path(runner.get(1)["artifact"])
    workspace.clear()
    with pytest.raises(ValueError, match="No current brief context"):
        continuity.current(runner)
    assert artifact.is_file()


def test_chat_and_voice_followups_bypass_search_and_pending_question_learning(session, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from interfaces.api.app import create_app
    from interfaces.api.routes import chat, voice
    runner, root = session
    projects.path.write_text(json.dumps({name: {"path": str(root)} for name in ["friday", "college web", "college app"]}))
    stored = []
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [],
                        save_message=lambda *a: stored.append(a)))
    def forbidden(*a, **kw):
        pytest.fail("Brief turn entered search or pending-question learning")
    for route in [chat, voice]:
        monkeypatch.setattr(route, "build_file_context", forbidden)
        monkeypatch.setattr(route, "build_search_context", forbidden)
        monkeypatch.setattr(route, "extract_screen_question", forbidden)
    monkeypatch.setattr(chat.talk, "hear", forbidden)
    monkeypatch.setattr(chat.humour, "hear", forbidden)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    result = client.post("/api/v1/chat", json={"message": "prepare my work session for friday"})
    assert result.status_code == 200 and result.json()["action_success"]
    answer = asyncio.run(voice._reply("leave out the notes", voice.VoiceRequest(speak=False)))
    assert answer.action_success
    answer = client.post("/api/v1/chat", json={"message": "actually use the college project"})
    assert answer.status_code == 200 and not answer.json()["action_success"]
    answer = asyncio.run(voice._reply("college app", voice.VoiceRequest(speak=False)))
    assert answer.action_success and runner.get(3)["payload"]["project"]["name"] == "college app"
    assert str(runner.output_dir) not in str(stored)


def test_chat_history_clear_retires_short_references_and_keeps_named_session(session, monkeypatch):
    from types import SimpleNamespace
    from interfaces.api.routes import chat
    from services.mind import project_session_context as continuity
    runner, _ = session
    prepare()
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(clear_history=lambda: None))
    asyncio.run(chat.clear_history())
    with pytest.raises(ValueError, match="No current brief context"):
        continuity.current(runner)
    assert runner.get(1)["verified"]
    assert say("check my work session").success


def test_existing_note_commands_and_literal_payloads_keep_their_meaning(session):
    from services.mind.execution_commands import match_command
    prepare()
    notes.add("FRIDAY source note")
    for phrase in ["remove my notes", "clear the notes", "note refresh that brief", "type leave out the notes"]:
        assert match_command(phrase) is None
    assert say("remove my notes").success
    assert notes.load() == []


def test_repeated_ambiguous_answer_never_guesses_a_project(session):
    runner, root = session
    names = ["friday", "college web", "college app"]
    projects.path.write_text(json.dumps({name: {"path": str(root)} for name in names}))
    prepare()
    assert not say("use the other project").success
    assert not say("college").success
    assert say("college web").success
    assert runner.get(2)["payload"]["project"]["name"] == "college web"


def test_durable_clarification_can_continue_in_another_process(session):
    import subprocess
    import sys
    from services.mind.cognition import cognition
    runner, root = session
    names = ["friday", "college web", "college app"]
    projects.path.write_text(json.dumps({name: {"path": str(root)} for name in names}))
    prepare()
    assert not say("use the other project").success
    script = """import logging, sys
logging.disable(logging.CRITICAL)
from pathlib import Path
from services.activity import projects
from services.memory import notes
from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.mind import project_session, project_session_context
projects.path = Path(sys.argv[3])
notes.path = Path(sys.argv[4])
project_session.sessions = project_session.ProjectSessionEngine(Workspace(Cognition(Path(sys.argv[1]))), Path(sys.argv[2]))
assert project_session_context.try_answer('college app').success
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(cognition.path), str(runner.output_dir),
                             str(projects.path), str(notes.path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert runner.get(2)["payload"]["project"]["name"] == "college app"


@pytest.mark.parametrize("phrase,change", [
    ("refresh that brief", "refresh"),
    ("update my project brief", "refresh"),
    ("leave out the notes", "notes"),
    ("exclude saved notes from that brief", "notes"),
    ("include the notes again", "notes"),
    ("actually, use the college project", "project"),
    ("switch to the other project instead", "project"),
])
def test_bounded_followup_phrases_preserve_project_names(phrase, change):
    from services.mind.execution_commands import match_command
    parsed = match_command(phrase)
    assert parsed["action"] == "revise" and parsed["change"] == change
