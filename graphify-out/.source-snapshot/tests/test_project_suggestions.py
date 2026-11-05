import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from interfaces.api.routes import chat, voice
from services.activity import projects
from services.automation import intent


def ask(message):
    return asyncio.run(intent.try_system_action(message, "openrouter"))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    folder = tmp_path / "FRIDAY"
    folder.mkdir()
    projects._save({"friday": {"path": str(folder), "sites": [],
                               "resume": ["open the terminal", "open the folder"]}})
    intent.cancel_pending_confirmation()
    opened = []
    monkeypatch.setattr(projects.subprocess, "Popen", lambda args: opened.append(("terminal", args)))
    monkeypatch.setattr(projects.system, "open_folder", lambda path: opened.append(("folder", path)))
    monkeypatch.setattr(intent, "get_provider", lambda name: pytest.fail("project suggestions need no AI"))
    yield folder, opened
    intent.cancel_pending_confirmation()


@pytest.mark.parametrize("message", [
    "I want to work on Friday",
    "Hey Friday, I wanna work on Friday",
    "Friday, I'd like to work on the Friday project please",
    "I need to work on my project Friday",
    "Let's work on Friday",
    "work on friday",
    "I'm going to work on Friday",
    "I feel like working on Friday",
    "start working on Friday",
    "I wanna work on F.R.I.D.A.Y.",
])
def test_work_request_offers_saved_project_without_opening(workspace, message):
    _, opened = workspace
    result = ask(message)
    assert result is not None and result.success
    assert result.message == 'Do you want me to resume friday? Say yes to open the project, or no to cancel.'
    assert intent.is_awaiting_confirmation()
    assert not result.repeatable
    assert opened == []


@pytest.mark.parametrize("reply", ["yes", "yeah", "go ahead", "Yes, please!", "Friday, yes"])
def test_yes_opens_saved_workspace_once(workspace, reply):
    folder, opened = workspace
    ask("I wanna work on Friday")
    result = ask(reply)
    assert result is not None and result.success
    assert result.message.startswith("Resuming friday:")
    assert opened == [("folder", str(folder)), ("terminal", ["wt.exe", "-d", str(folder)])]
    assert not intent.is_awaiting_confirmation()
    assert ask("yes") is None
    assert len(opened) == 2


@pytest.mark.parametrize("reply", ["no", "nah", "cancel", "never mind"])
def test_declining_dismisses_suggestion(workspace, reply):
    _, opened = workspace
    ask("work on friday")
    assert ask(reply).success
    assert not intent.is_awaiting_confirmation()
    assert ask("yes") is None
    assert opened == []


def test_unrelated_message_cancels_project_suggestion(workspace):
    _, opened = workspace
    ask("work on friday")
    assert ask("what time is it").success
    assert not intent.is_awaiting_confirmation()
    assert ask("yes") is None
    assert opened == []


def test_expired_suggestion_does_not_open(workspace, monkeypatch):
    _, opened = workspace
    monkeypatch.setattr(intent, "CONFIRM_TIMEOUT_SECONDS", -1)
    ask("work on friday")
    result = ask("yes")
    assert result is not None and not result.success and "timed out" in result.message
    assert opened == []


@pytest.mark.parametrize("message", [
    "I don't want to work on friday", "I worked on friday yesterday",
    "what should I work on friday", "work on something else",
    "work on friday and open chrome", "work on friday's voice recognition",
])
def test_unrelated_topics_do_not_offer_a_project(workspace, message):
    assert projects.match_project_command(intent.normalize_command(message)) is None
    assert not intent.is_awaiting_confirmation()


def test_explicit_resume_still_opens_immediately(workspace):
    _, opened = workspace
    assert ask("resume friday").success
    assert len(opened) == 2 and not intent.is_awaiting_confirmation()


@pytest.mark.parametrize("message", ["resume friday", "continue friday", "work on my project friday"])
def test_project_name_friday_survives_wake_word_cleanup(message):
    assert intent.normalize_command(message) == message


def test_confirmed_resume_runs_custom_steps(workspace, monkeypatch):
    folder, opened = workspace
    projects._save({"friday": {"path": str(folder), "resume": ["open the folder", "mute"]}})
    ran = []

    async def steps(commands, provider):
        ran.extend(commands)
        return [intent.ActionResult(True, "Muted.")]

    monkeypatch.setattr(intent, "_run_steps", steps)
    ask("work on friday")
    assert not ran and not opened
    assert ask("yes").message == "Resuming friday: opened the folder. Muted."
    assert ran == ["mute"]


def test_missing_project_folder_reports_failure_after_confirmation(workspace):
    folder, opened = workspace
    ask("work on friday")
    folder.rmdir()
    result = ask("yes")
    assert not result.success and "isn't at" in result.message
    assert not intent.is_awaiting_confirmation() and not opened


def test_suggested_project_is_not_logged_as_opened_until_yes(workspace):
    ask("work on friday")
    with intent.activity_log._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity WHERE kind='command'").fetchone()[0] == 0
    ask("yes")
    with intent.activity_log._connect() as conn:
        assert conn.execute("SELECT action FROM activity WHERE kind='command'").fetchall() == [("resume_project",)]


def test_other_saved_names_can_be_spoken_without_punctuation(workspace):
    folder, _ = workspace
    projects._save({"idea-lab-web": {"path": str(folder)}})
    result = ask("I want to work on Idea Lab Web")
    assert result.success and "resume idea-lab-web?" in result.message


def test_ambiguous_normalized_names_are_not_guessed(workspace):
    folder, _ = workspace
    projects._save({"idea-lab": {"path": str(folder)}, "idea_lab": {"path": str(folder)}})
    assert projects.match_project_command("work on idea lab") is None
    assert projects.match_project_command("work on idea-lab")["name"] == "idea-lab"


def test_chat_signals_followup_then_opens_on_yes(workspace, monkeypatch):
    _, opened = workspace
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(
        get_recent_history=lambda: [], save_message=lambda *a: None))
    client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
    first = client.post("/api/v1/chat", json={"message": "I wanna work on Friday"})
    assert first.status_code == 200
    assert first.json()["awaiting_reply"] is True and not opened
    second = client.post("/api/v1/chat", json={"message": "yes"})
    assert second.status_code == 200
    assert second.json()["awaiting_reply"] is False
    assert second.json()["action_success"] is True and len(opened) == 2


def test_voice_speaks_suggestion_and_waits_for_confirmation(workspace, monkeypatch):
    _, opened = workspace
    spoken = []
    monkeypatch.setattr(voice, "_speak_in_background", lambda text, **kwargs: spoken.append(text))
    request = voice.VoiceRequest(provider="openrouter", speak=True)
    first = asyncio.run(voice._reply("Hey Friday, I wanna work on Friday", request))
    assert first.awaiting_reply is True and opened == []
    assert spoken == [first.response]
    second = asyncio.run(voice._reply("yes", request))
    assert second.awaiting_reply is False and second.action_success is True
    assert len(opened) == 2 and spoken[-1].startswith("Resuming friday:")
