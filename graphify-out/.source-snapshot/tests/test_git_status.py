import asyncio
import shutil
import subprocess

import pytest

from services.activity import git_status, projects
from services.automation.system_control import AutomationError

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git isn't installed")


def git(folder, *args):
    subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "catjang"
    folder.mkdir()
    git(folder, "init", "-q")
    (folder / "main.py").write_text("print('hi')\n")
    git(folder, "add", ".")
    git(folder, "commit", "-q", "-m", "First version")
    projects._save({"catjang": {"path": str(folder), "repo": None, "sites": []}})
    return folder


def test_all_committed(repo):
    assert git_status.check() == "catjang: all committed."


def test_uncommitted_work(repo):
    (repo / "main.py").write_text("print('hello')\n")
    (repo / "game.py").write_text("x = 1\n")
    assert git_status.check("catjang") == "catjang: 2 uncommitted changes (main.py, game.py)."
    assert git_status.uncommitted_summary() == "catjang has 2 uncommitted changes. Commit before you stop?"


def test_what_changed_today(repo):
    (repo / "main.py").write_text("print('hello')\nprint('again')\n")
    reply = git_status.changes("catjang", "today")
    assert reply.startswith("In catjang, 1 commit today: First version. Not committed yet: 1 file changed")
    assert "(main.py)" in reply


def test_clean_projects_mean_no_evening_notification(repo):
    assert git_status.uncommitted_summary() is None


def test_commit_message_uses_only_the_local_model(repo, monkeypatch):
    (repo / "main.py").write_text("print('hello')\n")
    used = []

    class Local:
        async def complete(self, messages, system_prompt, **kw):
            used.append(messages[0].content)
            return type("R", (), {"content": "Say hello instead of hi"})()

    monkeypatch.setattr("providers.registry.get_provider", lambda name: used.append(name) or Local())
    monkeypatch.setattr("services.automation.clipboard.set_text", lambda text: used.append(("copied", text)))
    reply = asyncio.run(git_status.commit_message("catjang"))
    assert used[0] == "ollama" and "-print('hi')" in used[1] and used[2] == ("copied", "Say hello instead of hi")
    assert reply == "Commit message for catjang (copied to your clipboard):\nSay hello instead of hi"


def test_nothing_to_commit(repo):
    assert asyncio.run(git_status.commit_message("catjang")) == "There's nothing to commit in catjang."


def test_no_projects_saved():
    with pytest.raises(AutomationError, match="haven't saved any projects"):
        git_status.check()


@pytest.mark.parametrize("text, expected", [
    ("any uncommitted work", {"action": "git_check", "name": ""}),
    ("do i have any uncommitted changes in catjang", {"action": "git_check", "name": "catjang"}),
    ("check my projects", {"action": "git_check", "name": ""}),
    ("what did i change in catjang today", {"action": "git_changes", "name": "catjang", "when": "today"}),
    ("what did i commit to catjang this week", {"action": "git_changes", "name": "catjang", "when": "this week"}),
    ("write a commit message for catjang", {"action": "commit_message", "name": "catjang"}),
    ("what did i do in class today", None),   # not a saved project
    ("check the weather", None),
])
def test_commands(repo, text, expected):
    match = git_status.match_git_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected
