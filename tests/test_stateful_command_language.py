"""Exercise saved-state changes through FRIDAY's real local command router."""
import asyncio
import time
from pathlib import Path

import pytest

from core.config import config
from services.automation import intent
from services.files.search import FileHit


def say(message):
    return asyncio.run(intent.try_system_action(message, "openrouter"))


@pytest.fixture
def pc(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    state = {"apps": [], "urls": [], "files": [], "revealed": [], "muted": [], "sent": []}
    monkeypatch.setattr(intent.system, "open_app", lambda name: state["apps"].append(name) or "Opened.")
    monkeypatch.setattr(intent.system, "close_app", lambda name: "Closed.")
    monkeypatch.setattr(intent.system, "volume_level", lambda: 60)
    monkeypatch.setattr(intent.system, "set_volume", lambda level: "Volume restored.")
    monkeypatch.setattr(intent.system, "set_mute", lambda value: state["muted"].append(value) or "Muted.")
    monkeypatch.setattr(intent.system, "open_url", lambda url: state["urls"].append(url) or "Opened.")
    monkeypatch.setattr(intent.files.os, "startfile", state["files"].append)
    monkeypatch.setattr(intent.files.subprocess, "Popen", lambda args, **kw: state["revealed"].append(args))
    monkeypatch.setattr(intent.whatsapp, "send", lambda parsed, *args: state["sent"].append(parsed) or "Sent.")
    folder = tmp_path / "Atlas"
    folder.mkdir()
    monkeypatch.setattr(intent.projects, "find_folder", lambda name: folder if name.lower() == "atlas" else None)
    monkeypatch.setattr(intent.projects, "repo_of", lambda folder: None)
    monkeypatch.setattr(intent.activity_log, "resort", lambda: None)
    intent.cancel_pending_confirmation()
    yield state
    intent.cancel_pending_confirmation()


def test_edit_run_and_delete_saved_workflow(pc):
    assert say("define a workflow called Desk: mute").success
    assert say("replace steps in workflow Desk with open chrome and mute").success
    assert intent.routines.load()["desk"] == ["open chrome", "mute"]
    assert say("execute my workflow Desk").success
    assert pc["apps"] == ["chrome"] and pc["muted"] == [True]
    assert say("remove workflow Desk").success
    assert "desk" not in intent.routines.load()
    assert say("execute my workflow Desk") is None
    assert pc["apps"] == ["chrome"]


def test_edit_activate_deactivate_and_delete_saved_mode(pc):
    assert say("change actions in Focus mode to open chrome and mute").success
    assert say("keep Focus mode silent").success
    assert intent.modes.load()["focus"] == {"steps": ["open chrome", "mute"], "quiet": True}
    assert say("activate saved mode Focus").success
    assert intent.modes.active()["name"] == "focus" and intent.modes.is_quiet_mode()
    assert pc["apps"] == ["chrome"]
    assert say("end saved mode Focus").success
    assert intent.modes.active() is None
    assert say("allow notifications in Focus mode").success
    assert intent.modes.load()["focus"]["quiet"] is False
    assert say("remove saved mode Focus").success
    assert "focus" not in intent.modes.load()
    assert say("activate saved mode Focus") is None


def test_register_edit_resume_and_unregister_project(pc):
    assert say("register project Atlas").success
    assert "atlas" in intent.projects.load()
    assert say("change launch steps for project Atlas to open chrome and mute").success
    assert intent.projects.load()["atlas"]["resume"] == ["open chrome", "mute"]
    assert "open chrome" in say("show startup steps for project Atlas").message
    assert say("reopen saved project Atlas").success
    assert pc["apps"] == ["chrome"] and pc["muted"] == [True]
    assert say("restore default startup steps for project Atlas").success
    assert "resume" not in intent.projects.load()["atlas"]
    folder = Path(intent.projects.load()["atlas"]["path"])
    assert say("unregister project Atlas").success
    assert "atlas" not in intent.projects.load()
    assert folder.is_dir()  # unregistering never deletes project files
    assert say("reopen saved project Atlas") is None


def test_search_result_aliases_select_the_right_file(pc, tmp_path):
    hits = [FileHit(str(tmp_path / "one.txt"), "one.txt"), FileHit(str(tmp_path / "two.txt"), "two.txt")]
    for hit in hits:
        Path(hit.path).write_text("temporary result")
    intent.files.last_results.set(hits)
    assert say("open search result 2").success
    assert pc["files"] == [hits[1].path]
    assert intent.files.last_results.selected == hits[1]
    assert say("show search result 1 in its folder").success
    assert hits[0].path in " ".join(pc["revealed"][0])


def test_expired_or_invalid_search_result_does_not_open_a_file(pc, tmp_path):
    intent.files.last_results.set([FileHit(str(tmp_path / "one.txt"), "one.txt")])
    result = say("open search result 99")
    assert result and not result.success and not pc["files"]
    intent.files.last_results.at = time.monotonic() - intent.files.RESULTS_VALID_SECONDS - 1
    assert say("open search result 1") is None
    assert not pc["files"]


def test_contact_aliases_update_the_saved_recipient_and_still_confirm(pc):
    assert say("store contact Mom with number 9876543210").success
    assert say("update contact Mom with number 9876543211").success
    assert intent.whatsapp.load()["mom"] == "919876543211"
    assert say("message saved contact Mom: Keep CAPS, please!").success
    assert intent.is_awaiting_confirmation() and not pc["sent"]
    assert say("yes").success
    assert pc["sent"][0]["contact"] == "mom"
    assert pc["sent"][0]["text"] == "Keep CAPS, please!"
    assert say("forget whatsapp contact Mom").success
    assert "mom" not in intent.whatsapp.load()
    result = say("message saved contact Mom: Hello!")
    assert result and not result.success and len(pc["sent"]) == 1


def test_reading_item_aliases_open_and_remove_the_selected_item(pc):
    assert say("save https://example.com/KeepCase to read later").success
    assert say("save https://example.com/Second to read later").success
    assert say("open saved reading item 2").success
    assert pc["urls"] == ["https://example.com/Second"]
    assert say("mark reading item 1 as read").success
    assert [item["url"] for item in intent.reading_list.load()] == ["https://example.com/Second"]
    result = say("open saved reading item 99")
    assert result and not result.success and pc["urls"] == ["https://example.com/Second"]


@pytest.mark.parametrize("phrase", [
    "don't remove workflow Desk", "type remove workflow Desk", "note remove workflow Desk",
    "don't unregister project Atlas", "how do I unregister project Atlas",
    "don't mark reading item 1 as read", "don't forget whatsapp contact Mom",
])
def test_stateful_aliases_do_not_rewrite_negation_or_other_task_payloads(phrase):
    assert intent.words.rephrase_command(phrase) == phrase
