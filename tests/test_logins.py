import asyncio

import pytest

from services.automation import intent, logins
from services.automation.system_control import AutomationError


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setattr(logins, "_login_window", lambda name, url, user, two: ("github.com/login", "me", "s3cret!", False))
    assert logins.ask_and_save("github") == 'Saved your github login. Say "log me in to github" to use it.'
    return logins


@pytest.fixture
def typed(monkeypatch):
    out = []
    monkeypatch.setattr(logins.keyboard, "type_secret", lambda text: out.append(("type", text)))
    monkeypatch.setattr(logins.keyboard, "press_keys", lambda keys: out.append(("key", keys)))
    monkeypatch.setattr(logins.time, "sleep", lambda s: None)
    monkeypatch.setattr(logins, "_bring_browser_forward", lambda: None)
    clock = iter(range(0, 10_000))
    monkeypatch.setattr(logins.time, "monotonic", lambda: next(clock))
    return out


def front(*windows):
    """A foreground-window stand-in that shows these (app, title) in turn, then keeps the last."""
    seq = list(windows)
    return lambda: seq.pop(0) if len(seq) > 1 else seq[0]


def test_saved_without_the_password_in_any_file(github, tmp_path):
    assert logins.load() == {"github": {"url": "https://github.com/login", "two_step": False}}
    assert "s3cret" not in logins.path.read_text()
    assert logins.read_secret("github") == ("me", "s3cret!")  # in (the stand-in for) Credential Manager


def test_log_in(github, typed):
    opened = []
    reply = logins.log_in("github", opened.append, front(("chrome", "Sign in to GitHub · GitHub - Google Chrome")))
    assert opened == ["https://github.com/login"] and reply == "Signing you in to github."
    assert typed == [("type", "me"), ("key", "tab"), ("type", "s3cret!"), ("key", "enter")]


def test_no_password_typed_when_already_signed_in(github, typed):
    reply = logins.log_in("github", lambda url: None, front(("chrome", "GitHub - Google Chrome")))
    assert "doesn't look like a login page" in reply and typed == []


def test_stops_if_the_browser_leaves_the_front(github, typed):
    def windows():  # the user clicks into a terminal right after the username is typed
        return ("windowsterminal", "bash") if ("type", "me") in typed else ("chrome", "Sign in to GitHub - Google Chrome")
    reply = logins.log_in("github", lambda url: None, windows)
    assert "stopped before typing" in reply and ("type", "s3cret!") not in typed


def test_two_page_login(monkeypatch, typed):
    monkeypatch.setattr(logins, "_login_window", lambda *a: ("accounts.google.com", "me@gmail.com", "pw", True))
    logins.ask_and_save("google")
    logins.log_in("google", lambda url: None, front(("chrome", "Sign in - Google Accounts - Google Chrome")))
    assert typed == [("type", "me@gmail.com"), ("key", "enter"), ("type", "pw"), ("key", "enter")]


def test_page_never_comes_up(github, typed):
    reply = logins.log_in("github", lambda url: None, front(("windowsterminal", "bash")))
    assert "didn't come up in front in time" in reply and typed == []


def test_list_and_remove(github):
    assert logins.run({"action": "list_logins"}) == "Saved logins: github."
    assert logins.run({"action": "remove_login", "name": "github"}).startswith("Removed your github login")
    assert logins.read_secret("github") is None and logins.load() == {}


def test_cancelled_window_saves_nothing(monkeypatch):
    monkeypatch.setattr(logins, "_login_window", lambda *a: None)
    assert logins.ask_and_save("reva") == "Okay, nothing saved."
    with pytest.raises(AutomationError, match="need the login page"):
        monkeypatch.setattr(logins, "_login_window", lambda *a: ("reva.edu.in", "me", "", False))
        logins.ask_and_save("reva")


def test_commands(github):
    assert logins.match_login_command("log me in to github")["action"] == "log_in"
    assert logins.match_login_command("sign in to github")["action"] == "log_in"
    assert logins.match_login_command("login to github")["action"] == "log_in"
    assert logins.match_login_command("log into github")["action"] == "log_in"
    assert logins.match_login_command("log me in to instagram") is None  # nothing saved for it
    assert logins.match_login_command("save my reva login") == {"type": "system", "action": "save_login", "name": "reva"}
    assert logins.match_login_command("add a login for the reva portal")["name"] == "reva"
    assert logins.match_login_command("remove my github login")["action"] == "remove_login"
    assert logins.match_login_command("list my logins")["action"] == "list_logins"


def test_through_friday(github, monkeypatch):
    monkeypatch.setattr(logins, "log_in", lambda name, open_url: f"Signing you in to {name}.")
    reply = asyncio.run(intent.try_system_action("log me in to github", "openrouter"))
    assert reply.message == "Signing you in to github."
