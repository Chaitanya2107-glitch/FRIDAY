from datetime import datetime, timedelta

import pytest

from services.activity import projects
from services.activity.log import ActivityLog
from services.automation.system_control import AutomationError

T0 = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)


@pytest.fixture
def folder(tmp_path):
    """A git project folder, catjang, with a GitHub remote."""
    root = tmp_path / "home" / "Documents" / "catjang"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / ".git" / "config").write_text('[remote "origin"]\n\turl = https://github.com/me/catjang.git\n')
    return root


@pytest.fixture
def log(tmp_path, monkeypatch, folder):
    monkeypatch.setattr(projects, "HOME", tmp_path / "home")
    return ActivityLog(str(tmp_path / "a.db"))


def rows(log):
    with log._connect() as conn:
        return conn.execute("SELECT kind, app, target, category, project FROM activity ORDER BY at").fetchall()


def save(log, folder, monkeypatch):
    monkeypatch.setattr(projects, "find_folder", lambda name: folder)
    return projects.run({"action": "save_project", "name": "catjang", "this": False}, log)


def test_saving_a_project_by_name_labels_the_time_already_spent(log, folder, monkeypatch):
    log._insert(at=T0.isoformat(), kind="app", app="electron", title="Catjang", duration_s=600)
    log._insert(at=T0.isoformat(), kind="app", app="chrome", title="me/catjang: a game - Google Chrome", duration_s=60)
    log._insert(at=T0.isoformat(), kind="app", app="chrome", title="catjang tips - Google Search", duration_s=60)
    log._insert(at=T0.isoformat(), kind="app", app="code", title="main.py - other - Visual Studio Code", duration_s=60)
    assert rows(log)[0][3:] == ("other", None)

    assert save(log, folder, monkeypatch) == (
        f'Saved "catjang" as a project: {folder} (GitHub: me/catjang). Say "resume catjang" to pick it up later.'
    )
    assert [r[3:] for r in rows(log)] == [
        ("project", "catjang"),    # the app window named after it
        ("project", "catjang"),    # its GitHub repo tab
        ("search", None),          # a browser tab that only mentions the name isn't the project
        ("coding", None),
    ]


def test_this_is_a_project_uses_the_folder_of_the_last_window(log, folder, monkeypatch):
    monkeypatch.setattr(projects, "window_folders", lambda hwnd, pid: {folder})
    reply = projects.run({"action": "save_project", "name": "", "this": True}, log)
    assert reply.startswith('Saved "catjang" as a project')
    assert projects.load()["catjang"] == {"path": str(folder), "repo": "me/catjang", "sites": []}


def test_this_is_a_project_asks_when_it_cannot_tell(log, folder, monkeypatch):
    monkeypatch.setattr(projects, "window_folders", lambda hwnd, pid: {folder, folder.parent / "friday"})
    with pytest.raises(AutomationError, match="several folders open"):
        projects.run({"action": "save_project", "name": "", "this": True}, log)


def test_subfolders_belong_to_their_git_project(folder):
    assert projects.git_root(folder / "src") == folder


def test_programs_running_in_the_folder_are_the_project(log, folder, monkeypatch):
    save(log, folder, monkeypatch)
    monkeypatch.setattr(projects, "process_folders", lambda pid: {folder})
    assert projects.project_of_process(1234) == "catjang"
    monkeypatch.setattr(projects, "process_folders", lambda pid: {folder, folder.parent})
    assert projects.project_of_process(1234) == "catjang"  # Documents isn't a project
    other = {"catjang": projects.load()["catjang"], "friday": {"path": str(folder.parent / "friday")}}
    monkeypatch.setattr(projects, "process_folders", lambda pid: {folder, folder.parent / "friday"})
    assert projects.project_of_process(1234, other) is None  # tabs in two projects: can't tell which is showing

    log.observe("windowsterminal", T0, title="✳ Build next", project="catjang")
    log.observe("chrome", T0 + timedelta(minutes=20))
    assert rows(log) == [("app", "windowsterminal", None, "project", "catjang")]
    log.resort()  # found while recording: kept on the next start
    assert rows(log) == [("app", "windowsterminal", None, "project", "catjang")]


def test_localhost_pages_belong_to_the_project_serving_them(log, folder, monkeypatch):
    save(log, folder, monkeypatch)

    class Conn:
        status, pid = projects.psutil.CONN_LISTEN, 7
        laddr = type("addr", (), {"port": 3000})

    class Proc:
        def __init__(self, pid):
            pass

        def cwd(self):
            return str(folder / "src")  # its dev server, started in a subfolder

    monkeypatch.setattr(projects.psutil, "net_connections", lambda kind: [Conn()])
    monkeypatch.setattr(projects.psutil, "Process", Proc)
    assert projects.local_servers() == {3000: "catjang"}
    assert projects.port_of("localhost:3000") == 3000 and projects.port_of("github.com") is None

    log._insert(at=T0.isoformat(), kind="web", target="localhost:3000", title="AICTE IDEA Lab",
                project=projects.local_servers().get(projects.port_of("localhost:3000")))
    log._insert(at=T0.isoformat(), kind="web", target="localhost:5173", title="ipl-book")  # another app's server
    log._insert(at=T0.isoformat(), kind="web", target="localhost:8080", title="Catjang")    # titled with its name
    assert [r[4] for r in rows(log)] == ["catjang", None, "catjang"]


def test_resume_opens_terminal_folder_and_sites(log, folder, monkeypatch):
    save(log, folder, monkeypatch)
    log._insert(at=T0.isoformat(), kind="web", target="catjang.vercel.app", title="Catjang")  # named after it
    log._insert(at=T0.isoformat(), kind="web", target="localhost:3000", title="x")
    opened = []
    monkeypatch.setattr(projects.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(projects.system, "open_folder", lambda p: opened.append(("folder", p)))
    monkeypatch.setattr(projects.system, "open_url", lambda u: opened.append(("url", u)))

    reply, other_steps = projects.start_resume("", log)  # "pick up where I left off"

    assert opened == [
        ("folder", str(folder)),
        ("url", "https://github.com/me/catjang"),
        ("url", "https://catjang.vercel.app"),  # never localhost
        ["wt.exe", "-d", str(folder)],
    ]
    assert reply == ("Resuming catjang: opened a terminal, the folder and 2 sites "
                     "(github.com/me/catjang, catjang.vercel.app).")
    assert other_steps == []


def test_custom_resume_steps(log, folder, monkeypatch):
    save(log, folder, monkeypatch)
    parsed = projects.match_project_command(
        "When I resume catjang, run npm run dev, run claude --continue, open VS Code and play lofi")
    assert parsed == {"type": "system", "action": "set_resume", "name": "catjang",
                      "steps": ["run npm run dev", "run claude --continue", "open VS Code", "play lofi"]}
    assert projects.run(parsed, log) == (
        'Done. "resume catjang" will now: 1. run npm run dev, 2. run claude --continue, 3. open VS Code, 4. play lofi.')

    opened = []
    monkeypatch.setattr(projects.subprocess, "Popen", lambda args: opened.append(args))
    monkeypatch.setattr(projects.system, "open_folder", lambda p: pytest.fail("the folder wasn't asked for"))
    reply, other_steps = projects.start_resume("catjang", log)
    assert opened == [["wt.exe", "-d", str(folder), "powershell", "-NoExit", "-Command", "npm run dev",
                       ";", "new-tab", "-d", str(folder), "powershell", "-NoExit", "-Command", "claude --continue"]]
    assert reply == "Resuming catjang: opened a terminal running npm run dev and claude --continue."
    assert other_steps == ["open VS Code", "play lofi"]  # normal FRIDAY commands, run by intent.py

    show = projects.match_project_command("what does resume catjang do")
    assert projects.run(show, log).startswith('"resume catjang" will: 1. run npm run dev')
    reset = projects.match_project_command("reset resume for catjang")
    assert projects.run(reset, log) == (
        '"resume catjang" is back to the default: 1. open the terminal, 2. open the folder, 3. open the sites.')


def test_set_resume_needs_a_saved_project_and_steps(log, folder, monkeypatch):
    assert projects.match_project_command("when i resume ipl, run npm start") is None  # not saved: not a project command
    save(log, folder, monkeypatch)
    with pytest.raises(AutomationError, match="Tell me the steps"):
        projects.run({"action": "set_resume", "name": "catjang", "steps": []}, log)


def test_semicolons_in_a_command_stay_in_its_tab(log, folder, monkeypatch):
    opened = []
    monkeypatch.setattr(projects.subprocess, "Popen", lambda args: opened.append(args))
    projects._open_terminal(folder, ["npm i; npm run dev"])
    assert opened[0][-1] == "npm i\\; npm run dev"


def test_resume_runs_the_other_steps_as_commands(log, folder, monkeypatch):
    import asyncio
    from services.automation import intent

    save(log, folder, monkeypatch)
    projects.run({"action": "set_resume", "name": "catjang", "steps": ["open the folder", "mute"]}, log)
    monkeypatch.setattr(intent, "activity_log", log)
    monkeypatch.setattr(projects.system, "open_folder", lambda p: None)
    ran = []

    async def fake_steps(steps, provider):
        ran.extend(steps)
        return [intent.ActionResult(True, "Muted.")]

    monkeypatch.setattr(intent, "_run_steps", fake_steps)
    result = asyncio.run(intent.try_system_action("resume catjang", "openrouter"))
    assert ran == ["mute"] and result.message == "Resuming catjang: opened the folder. Muted."


def test_time_spent_and_the_day_summary(log, folder, monkeypatch):
    save(log, folder, monkeypatch)
    log._insert(at=datetime.now().replace(minute=0).isoformat(), kind="app", app="electron", title="Catjang", duration_s=4200)
    assert log.project_time("catjang", "today") == "You've spent 1h 10m on catjang today."
    assert log.project_time("catjang", "yesterday") == "You haven't worked on catjang yesterday."
    assert "Projects: catjang 1h 10m." in log.day_summary()


def test_removing_a_project_puts_its_time_back(log, folder, monkeypatch):
    save(log, folder, monkeypatch)
    log._insert(at=T0.isoformat(), kind="app", app="electron", title="Catjang", duration_s=60)
    projects.run({"action": "remove_project", "name": "catjang"}, log)
    assert rows(log)[0][3:] == ("other", None)


@pytest.mark.parametrize("text, expected", [
    ("this is a project", {"action": "save_project", "name": "", "this": True}),
    ("save this as a project called idea lab", {"action": "save_project", "name": "idea lab", "this": True}),
    ("save catjang as a project", {"action": "save_project", "name": "catjang", "this": False}),
    ("list my projects", {"action": "list_projects"}),
    ("catjang is not a project", {"action": "remove_project", "name": "catjang"}),
    ("pick up where i left off", {"action": "resume_project", "name": ""}),
    ("resume catjang", {"action": "resume_project", "name": "catjang"}),
    ("continue working on catjang", {"action": "resume_project", "name": "catjang"}),
    ("how long did i work on catjang this week", {"action": "project_time", "name": "catjang", "when": "this week"}),
    ("continue the song", None),   # not a saved project
    ("resume ipl", None),
])
def test_commands(log, folder, monkeypatch, text, expected):
    save(log, folder, monkeypatch)
    match = projects.match_project_command(text)
    assert (match and {k: v for k, v in match.items() if k != "type"}) == expected
