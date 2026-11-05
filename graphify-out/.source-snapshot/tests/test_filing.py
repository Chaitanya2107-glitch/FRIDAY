import json

import pytest

from core.errors import FridayError
from services.activity import projects
from services.files import filing
from services.proactive import buttons, timetable
from services.watch import auto


@pytest.fixture
def subjects():
    timetable._save_subjects(["Finance", "Management", "Operating Systems", "DBMS"])


def downloaded(tmp_path, name, text="x"):
    path = tmp_path / "Downloads" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_subject_in_the_name_wins(subjects, tmp_path):
    assert filing.suggest(downloaded(tmp_path, "Finance_Unit3_notes.txt")) == filing.COLLEGE_DIR / "Finance"
    assert filing.suggest(downloaded(tmp_path, "OS lab manual.txt")) == filing.COLLEGE_DIR / "Operating Systems"
    assert filing.suggest(downloaded(tmp_path, "DBMS-assignment-2.md")) == filing.COLLEGE_DIR / "DBMS"


def test_the_first_page_counts_when_the_name_says_nothing(subjects, tmp_path):
    path = downloaded(tmp_path, "scan0042.txt", "Unit 4: Management by objectives …")
    assert filing.suggest(path) == filing.COLLEGE_DIR / "Management"


def test_no_guess_for_ties_other_files_or_unknown_subjects(subjects, tmp_path):
    assert filing.suggest(downloaded(tmp_path, "finance and management model paper.txt")) is None  # a tie
    assert filing.suggest(downloaded(tmp_path, "setup_finance.exe")) is None  # not a document
    assert filing.suggest(downloaded(tmp_path, "holiday photos.txt")) is None
    assert filing.suggest(downloaded(tmp_path, "refinance.txt")) is None  # whole words only


def test_a_project_named_in_the_file(tmp_path, monkeypatch):
    folder = tmp_path / "catjang"
    projects._save({"catjang": {"path": str(folder)}})
    assert filing.suggest(downloaded(tmp_path, "catjang_design_spec.md")) == folder


def test_move_makes_the_folder_and_never_overwrites(subjects, tmp_path):
    first = downloaded(tmp_path, "Finance notes.txt", "one")
    assert filing.move(str(first), str(filing.COLLEGE_DIR / "Finance")) == "Moved Finance notes.txt to College\\Finance."
    second = downloaded(tmp_path, "Finance notes.txt", "two")
    filing.move(str(second), str(filing.COLLEGE_DIR / "Finance"))
    assert sorted(p.name for p in (filing.COLLEGE_DIR / "Finance").iterdir()) == ["Finance notes (1).txt", "Finance notes.txt"]
    assert not second.exists()


def test_the_notification_buttons(subjects, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda title, body, links=None, **kwargs: shown.append((body, links)) or True)
    path = downloaded(tmp_path, "DBMS unit 2.txt")
    assert auto.announce(path, slow=False) is None
    body, links = shown[0]
    assert body == "New download: DBMS unit 2.txt. Move it to College\\DBMS?"
    assert [label for label, _ in links] == ["Move it", "Move & rename", "Leave it"]

    token = links[0][1].split("token=")[1].split("&")[0]
    assert buttons.respond(token, "move") == "Moved DBMS unit 2.txt to College\\DBMS."
    assert (filing.COLLEGE_DIR / "DBMS" / "DBMS unit 2.txt").exists()
    with pytest.raises(FridayError):
        buttons.respond(token, "move")  # each notification answers once


def test_leave_it(subjects, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda title, body, links=None, **kwargs: shown.append(links) or True)
    path = downloaded(tmp_path, "finance.txt")
    auto.announce(path, slow=True)
    token = shown[0][1][1].split("token=")[1].split("&")[0]
    assert buttons.respond(token, "leave") == "Okay, left it in Downloads."
    assert path.exists()


def test_subject_commands():
    assert timetable.run(timetable.match_timetable_command("my subjects are Finance, Management and Marketing")) == \
        "Got it: Finance, Management, Marketing."
    assert timetable.run(timetable.match_timetable_command("add subject OS")) == "Added OS to your subjects."
    assert timetable.run(timetable.match_timetable_command("what are my subjects")) == \
        "Your subjects: Finance, Management, Marketing, OS."
    assert json.loads(timetable.subjects_path.read_text(encoding="utf-8"))[-1] == "OS"


@pytest.mark.parametrize("approved", [False, True])
def test_filing_suggestion_requires_brain_approval(subjects, tmp_path, monkeypatch, approved):
    from services.mind import notifications
    from services.mind.cognition import cognition

    shown, candidates = [], []
    monkeypatch.setattr("services.reminders.service.show_toast", lambda *args, **kwargs: shown.append(args) or True)
    async def decide(items, now, observations):
        candidates.extend(items)
        return [notifications.Choice(id="0", send=approved, reason="Owner context checked.")]
    monkeypatch.setattr(notifications, "_reason", decide)
    path = downloaded(tmp_path, "DBMS notes.txt")

    auto.announce(path, slow=False)

    assert len(candidates) == 1 and candidates[0].kind == "filing"
    assert len(shown) == int(approved)
    assert path.exists()  # A decision never moves a file without its button being accepted.
    assert cognition.latest("notification_decision")["status"] == ("submitted" if approved else "suppressed")
