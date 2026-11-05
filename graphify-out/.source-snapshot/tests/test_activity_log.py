import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.activity import log as activity
from services.activity.log import ActivityLog, match_activity_command
from services.automation import intent

T0 = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)


def rows(log, kind):
    with log._connect() as conn:
        return conn.execute(
            "SELECT app, action, target, success, duration_s FROM activity WHERE kind = ? ORDER BY id", (kind,)
        ).fetchall()


@pytest.fixture
def log(tmp_path, monkeypatch):
    fresh = ActivityLog(str(tmp_path / "a.db"))
    monkeypatch.setattr(activity, "activity_log", fresh)
    monkeypatch.setattr(intent, "activity_log", fresh)
    return fresh


def test_app_sessions_are_recorded_on_each_switch(log):
    log.observe("code", T0)
    log.observe("code", T0 + timedelta(minutes=5))       # same app: nothing new
    log.observe("chrome", T0 + timedelta(minutes=30))
    log.observe(None, T0 + timedelta(minutes=40))          # went idle
    log.observe("chrome", T0 + timedelta(minutes=41, seconds=2))
    log.observe("spotify", T0 + timedelta(minutes=41, seconds=4))  # too short to count

    assert [(app, secs) for app, _, _, _, secs in rows(log, "app")] == [("code", 1800), ("chrome", 600)]
    assert log.last_app == "spotify"


def test_title_changes_split_rows_but_not_the_app_stretch(log):
    log.observe("chrome", T0, title="Inbox - Gmail")
    log.observe("chrome", T0 + timedelta(minutes=10), title="YouTube")
    with log._connect() as conn:
        assert conn.execute("SELECT app, title, duration_s FROM activity").fetchall() == [("chrome", "Inbox - Gmail", 600)]
    assert log.app_since == T0  # the long-stretch nudge still sees one continuous stretch in chrome


def test_launches(log, monkeypatch):
    seen = iter([{"code"}, {"code", "spotify"}])
    monkeypatch.setattr(activity, "running_apps", lambda: next(seen))
    log._launches()  # seeds
    log._launches()
    assert [r[0] for r in rows(log, "launch")] == ["spotify"]


def test_private_titles_are_dropped():
    assert activity.PRIVATE_TITLE.search("New Incognito tab - Google Chrome")
    assert activity.PRIVATE_TITLE.search("HDFC Bank NetBanking")
    assert not activity.PRIVATE_TITLE.search("main.py - FRIDAY - Visual Studio Code")


def test_commands_are_logged_with_the_app_the_user_was_in(log):
    log.observe("code", T0)
    intent._execute({"action": "list_reminders"})
    log.log_command({"action": "open_url", "url": "https://mail.google.com/mail/u/0/#inbox?token=x"}, True)
    log.log_command({"action": "write_clipboard", "text": "my password"}, True)

    assert rows(log, "command") == [
        ("code", "list_reminders", None, 1, None),
        ("code", "open_url", "mail.google.com", 1, None),  # site only
        ("code", "write_clipboard", None, 1, None),        # never the text
    ]


def test_confirmation_questions_are_not_logged_until_confirmed(log, tmp_path):
    (tmp_path / "notes.txt").write_text("x")
    asked = intent._execute({"action": "organise_folder", "path": str(tmp_path)})
    assert asked and intent.is_awaiting_confirmation() and rows(log, "command") == []
    intent.cancel_pending_confirmation()


def test_nothing_is_logged_when_disabled(log, monkeypatch):
    monkeypatch.setattr(config, "ACTIVITY_LOG_ENABLED", False)
    log.log_command({"action": "open_app", "app_name": "chrome"}, True)
    assert rows(log, "command") == []


def test_day_summary(log, monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 12, tzinfo=tz)

    monkeypatch.setattr(activity, "datetime", FixedClock)
    assert log.day_summary() == "I haven't recorded any activity today yet."
    now = FixedClock.now()
    log.observe("code", now - timedelta(hours=2))
    log.observe("chrome", now - timedelta(minutes=30))  # code: 1h 30m saved; chrome still open
    log.log_command({"action": "open_app", "app_name": "chrome"}, True)
    log.log_command({"action": "open_app", "app_name": "spotify"}, True)

    summary = log.day_summary()
    assert "2h 0m" in summary and "code 1h 30m, chrome 30m" in summary
    assert "2 commands, mostly open app (2)" in summary


def test_clear(log):
    log.log_command({"action": "open_app", "app_name": "chrome"}, True)
    assert "1 entries" in log.clear()
    assert rows(log, "command") == []


@pytest.mark.parametrize("text, action", [
    ("what have I been doing today", "activity_summary"),
    ("what did I do today", "activity_summary"),
    ("how did I spend my day", "activity_summary"),
    ("show my activity", "activity_summary"),
    ("clear my activity log", "clear_activity"),
    ("what did I do wrong in this code", None),
])
def test_activity_commands(text, action):
    match = match_activity_command(text)
    assert (match and match["action"]) == action


def test_summary_command_through_the_command_flow(log):
    result = asyncio.run(intent.try_system_action("hey friday, what have I been doing today?", "openai"))
    assert result.message == "I haven't recorded any activity today yet."


def test_foreground_app_reads_this_pc():
    # Smoke test of the Windows calls: a name or None, never an exception
    assert activity.foreground_app() is None or isinstance(activity.foreground_app(), str)
    assert activity.idle_seconds() >= 0


def test_rows_are_sorted_into_categories():
    from services.activity.categories import categorize
    assert categorize("app", "code") == "coding"
    assert categorize("app", "chrome", title="Object Oriented Programming Lab | REVA - Google Chrome") == "study"
    assert categorize("app", "chrome", title="Installed GitHub App - Claude - Google Chrome") == "ai"
    assert categorize("app", "chrome", title="New Tab - Google Chrome") == "browsing"
    assert categorize("launch", "lenovovantage-(batterywidgetaddin)") == "system"
    assert categorize("launch", "someunknownapp") == "other"
    assert categorize("web", target="rulms.reva.edu.in") == "study"            # subdomain of a listed site
    assert categorize("web", target="music.youtube.com") == "music"            # the longer domain wins
    assert categorize("web", target="www.youtube.com") == "entertainment"
    assert categorize("web", target="localhost:3000") == "coding"
    assert categorize("web", target="unknown.site", title="npm error - Google Search") == "search"  # falls back to the title
    assert categorize("file", target="style.css (2)") == "coding"
    assert categorize("file", target="notes.pdf") == "documents"
    assert categorize("file", target="IDEA-LAB-WEB") == "files"                # a folder
    assert categorize("command", action="open_app", target="spotify") == "music"
    assert categorize("command", action="play_song", target="believer") == "music"
    assert categorize("command", action="list_reminders") == "friday"


def test_categories_are_saved_and_old_rows_resorted(log, monkeypatch):
    log.observe("code", T0)
    log.observe("spotify", T0 + timedelta(minutes=30))
    log.observe(None, T0 + timedelta(minutes=45))
    with log._connect() as conn:
        assert conn.execute("SELECT app, category FROM activity").fetchall() == [("code", "coding"), ("spotify", "music")]
        conn.execute("UPDATE activity SET category = NULL")  # like rows saved before categories existed

    log._ready_for = None  # next start
    with log._connect() as conn:
        assert [c for (c,) in conn.execute("SELECT category FROM activity")] == ["coding", "music"]
    assert "By kind: coding 30m, music 15m." in log.day_summary(T0)


def test_games_are_found_by_their_install_folder(tmp_path, monkeypatch):
    from services.activity import categories
    game = tmp_path / "Games" / "Some Game" / "bin"
    game.mkdir(parents=True)
    (game / "SomeGame.exe").touch()
    monkeypatch.setattr(categories, "GAME_FOLDERS", [str(tmp_path / "Games")])  # an absolute path wins over the drive
    categories.game_programs.cache_clear()
    try:
        assert categories.categorize("app", "somegame") == "gaming"
        assert categories.categorize("launch", "anotherthing-win64-shipping") == "gaming"  # Unreal games anywhere
        assert categories.categorize("app", "notagame") == "other"
    finally:
        categories.game_programs.cache_clear()
