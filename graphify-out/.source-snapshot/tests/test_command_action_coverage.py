"""Frozen examples for every inventoried parser outcome, with source drift checks."""
import json
from pathlib import Path

import pytest

from command_action_support import MATCHERS, inventory, outcome
from services.automation import intent
from services.automation.command_words import normalize_command, rephrase_command
from services.files.search import FileHit

CORPUS_PATH = Path(__file__).with_name("command_action_examples.json")
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def action_state(tmp_path, monkeypatch):
    intent.cancel_pending_confirmation()
    intent.routines._save({"desk": ["mute"], "work mode": ["open chrome"]})
    folder = tmp_path / "catjang"
    folder.mkdir()
    intent.projects.path.write_text(json.dumps({"catjang": {"path": str(folder), "resume": ["mute"]}}))
    intent.whatsapp._save({"mom": "919876543210", "rahul sharma": "447700900123"})
    intent.deadlines._save([{"what": "DBMS assignment", "due": "2030-01-01T17:00", "alerted": []}])
    monkeypatch.setattr(intent.timetable, "subjects", lambda: ["DBMS", "DS", "EVS", "DSP", "PE"])
    monkeypatch.setattr(intent.logins, "load", lambda: {"github": {}, "reva": {}, "college": {}})
    monkeypatch.setattr(intent.brain.knowledge, "find", lambda name: True if name.lower() == "catjang" else None)
    intent.files.last_results.set([FileHit(str(tmp_path / "resume.pdf"), "resume.pdf"),
                                   FileHit(str(tmp_path / "notes.txt"), "notes.txt")])


def test_corpus_covers_every_inventoried_parser_action():
    expected = set()
    for family in MATCHERS:
        actions, unknown = inventory(family)
        assert not unknown, f"Review computed action domains for {family}: {unknown}"
        assert actions, f"No actions inventoried for {family}"
        expected.update((family, action) for action in actions)
    actual = {(row["family"], row["action"]) for row in CORPUS}
    assert expected == actual, f"Missing: {sorted(expected - actual)}; stale: {sorted(actual - expected)}"
    assert len(actual) == len(CORPUS), "Duplicate family/action rows"


@pytest.mark.parametrize("family,action,phrase", [
    pytest.param(row["family"], row["action"], phrase,
                 id=f'{row["family"]}:{row["action"]}: {phrase}')
    for row in CORPUS for phrase in row["phrases"]
])
def test_frozen_phrase_selects_the_expected_action(action_state, family, action, phrase):
    text = rephrase_command(phrase)
    if family not in {"typing", "telegram", "workspace", "execution"}:
        text = normalize_command(text)
    parsed = MATCHERS[family](text)
    assert outcome(family, parsed) == action


def test_every_action_has_multiple_phrases():
    assert all(len(set(row["phrases"])) >= 2 for row in CORPUS)


def test_media_youtube_helper_is_routed_by_apps_instead():
    for phrase in ("play cats on youtube", "search cats on youtube"):
        assert intent.match_media_command(phrase, lambda: True) is None
        assert intent.match_app_command(phrase)["action"] == "open_url"
