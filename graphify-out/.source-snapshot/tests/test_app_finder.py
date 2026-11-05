from services.automation import app_finder, app_commands
from services.automation.system_control import AutomationError, system

import os
import pytest

REAL_EVERYTHING = app_finder._everything  # before conftest swaps it for a fake
START = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"


def everything(by_name, by_path=()):
    """A fake Everything: file-name results first, folder-path (-p) results second."""
    return lambda args: list(by_path if "-p" in args else by_name)


def test_picks_the_start_menu_shortcut_over_installers_and_junk(monkeypatch):
    monkeypatch.setattr(app_finder, "_everything", everything([
        r"C:\Users\me\Downloads\arduino-ide_setup.exe",                                   # installer in Downloads
        r"C:\Users\me\AppData\Roaming\Microsoft\Windows\Recent\arduino notes.txt.lnk",    # a recent file
        r"C:\Program Files\Arduino IDE\Uninstall Arduino IDE.exe",
        r"C:\Program Files\Arduino IDE\resources\arduino-cli.exe",
        START + r"\Arduino IDE.lnk",
    ]))
    assert app_finder.find_app("Arduino IDE") == START + r"\Arduino IDE.lnk"


def test_an_exact_name_beats_a_word_inside_another_name(monkeypatch):
    monkeypatch.setattr(app_finder, "_everything", everything([
        START + r"\MySQL\MySQL Command Line Client - Unicode.lnk",   # "code" inside "Unicode"
        r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    ]))
    assert app_finder.find_app("code").endswith(r"Microsoft VS Code\Code.exe")


def test_games_are_found_by_their_folder(monkeypatch):
    monkeypatch.setattr(app_finder, "_everything", everything([], by_path=[
        r"C:\games\Black Myth Wukong\b1\Binaries\Win64\b1-Win64-Shipping.exe",
        r"C:\games\Black Myth Wukong\Engine\Binaries\Win64\CrashReportClient.exe",
        r"C:\games\Black Myth Wukong\b1.exe",
    ]))
    assert app_finder.find_app("black myth") == r"C:\games\Black Myth Wukong\b1.exe"


def test_nothing_found(monkeypatch):
    assert app_finder.find_app("xyzzy") is None
    assert app_finder.find_app("  ") is None


def test_open_app_launches_what_everything_found(monkeypatch):
    launched = []
    monkeypatch.setattr(app_finder, "_everything", everything([START + r"\Canva.lnk"]))
    monkeypatch.setattr(os, "startfile", launched.append)
    assert system.open_app("canva") == "Opening Canva."
    assert launched == [START + r"\Canva.lnk"]


def test_opened_app_is_brought_to_the_front(monkeypatch):
    from services.automation import system_control
    focused = []
    monkeypatch.setattr(system_control.time, "sleep", lambda s: None)
    monkeypatch.setattr(app_finder, "app_windows", lambda is_app: [42] if is_app(
        type("P", (), {"name": lambda self: "Notepad.exe"})()) else [])
    monkeypatch.setattr(app_finder, "bring_to_front", lambda hwnd: focused.append(hwnd) or True)
    system._focus_when_open("notepad", "notepad")
    assert focused == [42]


def test_open_app_says_when_nothing_is_found():
    with pytest.raises(AutomationError, match="couldn't find an app called 'xyzzy'"):
        system.open_app("xyzzy")


def test_open_command_goes_to_everything_before_the_ai(monkeypatch):
    assert app_commands.match_app_command("open arduino") is None  # not listed, not installed: the AI decides
    monkeypatch.setattr(app_finder, "_everything", everything([START + r"\Arduino IDE.lnk"]))
    assert app_commands.match_app_command("open arduino") == {"type": "system", "action": "open_app", "app_name": "arduino"}
    assert app_commands.match_app_command("open chrome")["app_name"] == "chrome"  # listed apps don't need Everything


def test_downloads_is_a_last_resort(monkeypatch):
    game = r"C:\Users\me\Downloads\God-Of-War-AnkerGames\God of War\Launch God of War.lnk"
    monkeypatch.setattr(app_finder, "_everything", everything([game]))
    assert app_finder.find_app("god of war") == game  # games get unpacked there
    installed = START + r"\God of War.lnk"
    monkeypatch.setattr(app_finder, "_everything", everything([game, installed]))
    assert app_finder.find_app("god of war") == installed


def test_everything_is_started_when_it_isnt_running(monkeypatch):
    from types import SimpleNamespace
    answers = [SimpleNamespace(returncode=8, stdout="", stderr="Everything IPC not found"),
               SimpleNamespace(returncode=0, stdout="C:\Code.exe\n", stderr="")]
    started = []
    monkeypatch.setattr(app_finder, "es_path", lambda: "es.exe")
    monkeypatch.setattr(app_finder.subprocess, "run", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(app_finder, "_start_everything", lambda: started.append(True) or True)
    monkeypatch.setattr(app_finder.time, "sleep", lambda s: None)
    monkeypatch.setattr(app_finder, "_everything", REAL_EVERYTHING)  # it calls itself again after the start
    assert REAL_EVERYTHING(["code"]) == ["C:\Code.exe"] and started == [True]
