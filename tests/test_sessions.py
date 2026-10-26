import asyncio
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from services.activity import journal, sessions, weekly
from services.activity.log import ActivityLog
from services.automation import intent, modes
from services.proactive import buttons, watcher

DAY = date(2026, 9, 28)  # a Monday


def t(hour, minute=0, day=DAY):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)


def row(hour, minute, minutes, category, project=None, day=DAY):
    return (t(hour, minute, day).isoformat(), minutes * 60, category, project)


# ── Building sessions ─────────────────────────────────────────────────────────

def test_related_categories_merge_and_neutral_ones_dont_break_a_session():
    found = sessions.build([
        row(14, 0, 20, "coding", "friday"),
        row(14, 20, 5, "communication"),       # a WhatsApp reply: neutral
        row(14, 25, 15, "ai"),                  # same group as coding
        row(14, 40, 30, "project", "friday"),
    ])
    assert len(found) == 1
    s = found[0]
    assert (s.group, s.start, s.end, s.active_s) == ("work", t(14), t(15, 10), 65 * 60)
    assert s.projects == {"friday": 50 * 60}


def test_a_gap_over_ten_minutes_splits_and_short_stretches_are_not_sessions():
    found = sessions.build([
        row(9, 0, 30, "study"),
        row(9, 41, 20, "study"),                # 11 min after the last one ended
        row(12, 0, 5, "coding"),                # too short on its own
    ])
    assert [(s.group, s.start) for s in found] == [("study", t(9)), ("study", t(9, 41))]


def test_groups_can_overlap():
    found = sessions.build([row(14, 0, 8, "coding"), row(14, 8, 6, "entertainment"), row(14, 14, 8, "coding"),
                            row(14, 22, 6, "entertainment"), row(14, 28, 8, "coding")])
    assert [(s.group, s.start, s.end) for s in found] == [("work", t(14), t(14, 36)), ("chill", t(14, 8), t(14, 28))]
    # a break longer than the gap splits the session instead
    found = sessions.build([row(14, 0, 30, "coding"), row(14, 30, 20, "entertainment"), row(14, 50, 30, "coding")])
    assert [s.group for s in found] == ["work", "chill", "work"]


def test_the_app_in_front_right_now_counts(tmp_path):
    log = ActivityLog(str(tmp_path / "a.db"))
    log._insert(at=t(14).isoformat(), kind="app", app="code", title="main.py", duration_s=6 * 60)
    log.app, log.title, log.title_since = "code", "app.py", t(14, 6)
    found = sessions.recent(log, t(14, 12))
    assert [(s.group, s.active_s) for s in found] == [("work", 12 * 60)]


# ── Suggestions and summaries ─────────────────────────────────────────────────

WORK = sessions.Session("work", t(14), t(14, 15), active_s=15 * 60)


def test_suggest_a_running_session_once_then_wait_or_stop_on_no():
    now = t(14, 16)
    assert sessions.to_suggest([WORK], {}, {"work"}, now) is WORK
    assert sessions.to_suggest([WORK], {}, {"study"}, now) is None       # no mode with that name
    offered = {"work": {"day": "2026-09-28", "at": now.timestamp()}}
    assert sessions.to_suggest([WORK], offered, {"work"}, now) is None
    later = sessions.Session("work", t(14), t(16, 15), active_s=100 * 60)
    assert sessions.to_suggest([later], offered, {"work"}, t(16, 17)) is later
    declined = {"work": {"day": "2026-09-28", "at": 0, "declined": True}}
    assert sessions.to_suggest([WORK], declined, {"work"}, now + timedelta(hours=5)) is None
    assert sessions.to_suggest([WORK], {}, {"work"}, t(14, 26)) is None  # it's over


def test_just_ended_needs_twenty_minutes_and_a_recent_end():
    long = sessions.Session("work", t(13), t(14), active_s=50 * 60)
    assert sessions.just_ended([long, WORK], t(14, 5)) == []             # might still go on
    assert sessions.just_ended([long, WORK], t(14, 11)) == [long]        # WORK is too short
    assert sessions.just_ended([long], t(14, 41)) == []                  # too long ago (a restart)


def test_summary_and_journal_line():
    s = sessions.Session("work", t(14, 5), t(15, 40), active_s=95 * 60, projects={"FRIDAY": 70 * 60, "x": 30})
    assert sessions.summary(s, 3) == "Work session done: 1h 35m (14:05–15:40) — FRIDAY 1h 10m, 3 commits."
    assert sessions.summary(sessions.Session("chill", t(20), t(20, 30), 30 * 60)) == \
        "Chill session done: 30m (20:00–20:30)."
    assert sessions.line(s) == "14:05–15:40 work — 1h 35m (FRIDAY)"


# ── The watcher ───────────────────────────────────────────────────────────────

@pytest.fixture
def log(tmp_path, monkeypatch):
    log = ActivityLog(str(tmp_path / "a.db"))
    import services.activity.log as log_module
    monkeypatch.setattr(log_module, "activity_log", log)
    monkeypatch.setattr(watcher, "activity_log", log)
    return log


def link(links, answer):
    for _, url in links:
        query = parse_qs(urlsplit(url).query)
        if query["answer"][0] == answer:
            return query["token"][0]


def test_watcher_offers_the_mode_and_yes_starts_it(log, monkeypatch):
    shown = []
    monkeypatch.setattr(watcher, "show_toast", lambda title, text, links=None, **kw: shown.append((text, links)))
    log._insert(at=t(14).isoformat(), kind="app", app="code", title="main.py", duration_s=12 * 60)
    started = []

    async def start(name, provider, subject=""):
        started.append(name)
        return intent.ActionResult(True, f"{name.title()} mode on.")

    monkeypatch.setattr(intent, "_start_mode", start)

    async def scenario():
        await watcher._check_sessions(t(14, 13))
        await watcher._check_sessions(t(14, 14))  # not asked twice
        text, links = shown[0]
        return text, await asyncio.to_thread(buttons.respond, link(links, "start"), "start")

    text, reply = asyncio.run(scenario())
    assert len(shown) == 1 and text == "Looks like you're working. Start work mode?"
    assert reply == "Work mode on." and started == ["work"]
    with log._connect() as conn:
        assert conn.execute("SELECT app, action FROM activity WHERE kind = 'feedback' ORDER BY id").fetchall() == \
            [("mode:work", "suggested"), ("mode:work", "start")]


def test_no_stops_suggestions_for_the_day(log, monkeypatch):
    shown = []
    monkeypatch.setattr(watcher, "show_toast", lambda title, text, links=None, **kw: shown.append((text, links)))
    log._insert(at=t(14).isoformat(), kind="app", app="code", title="main.py", duration_s=12 * 60)
    asyncio.run(watcher._check_sessions(t(14, 13)))
    assert buttons.respond(link(shown[0][1], "no"), "no") == "Okay, no more work mode suggestions today."
    log._insert(at=t(18).isoformat(), kind="app", app="code", title="main.py", duration_s=12 * 60)
    asyncio.run(watcher._check_sessions(t(18, 13)))
    assert len(shown) == 1


def test_summary_when_a_session_ends_with_end_mode_button_while_it_is_on(log, monkeypatch):
    shown = []
    monkeypatch.setattr(watcher, "show_toast", lambda title, text, links=None, **kw: shown.append((text, links)))
    log._insert(at=t(14).isoformat(), kind="app", app="code", title="main.py", duration_s=30 * 60)
    modes._set_active({"name": "work", "opened": [], "volume": None, "quiet": True})
    asyncio.run(watcher._check_sessions(t(14, 45)))
    asyncio.run(watcher._check_sessions(t(14, 46)))  # once only
    assert len(shown) == 1
    text, links = shown[0]
    assert text == "Work session done: 30m (14:00–14:30)."
    assert buttons.respond(link(links, "end"), "end") == "Work mode off."
    assert modes.active() is None


# ── Journal and weekly ────────────────────────────────────────────────────────

def test_journal_has_a_sessions_section(log, monkeypatch):
    monkeypatch.setattr(journal, "_commits", lambda day: {})
    log._insert(at=t(14).isoformat(), kind="app", app="code", title="main.py", duration_s=40 * 60)
    assert "## Sessions\n- 14:00–14:40 work — 40m" in journal.build(DAY, log)


def test_weekly_summary(log, monkeypatch):
    monkeypatch.setattr(journal, "commits_between", lambda since, until: {"friday": ["a", "b"]})
    last_week = DAY - timedelta(days=7)
    log._insert(at=t(10, day=last_week).isoformat(), kind="app", app="code", title="x", duration_s=3600)
    log._insert(at=t(10).isoformat(), kind="app", app="code", title="x", duration_s=2 * 3600, project="friday")
    log._insert(at=t(9, day=DAY + timedelta(days=2)).isoformat(), kind="app", app="code", title="y", duration_s=3600)
    text = weekly.build(DAY, log)
    assert text.startswith("# Week of Monday, 28 September 2026\n\n**Active:** 3h 0m (+2h 0m)")
    for part in ["## Time\n- project 2h 0m (+2h 0m)\n- coding 1h 0m\n",
                 "## Projects\n- friday — 2h 0m (2 commits)",
                 "## Sessions\n- work: 2 sessions, longest 2h 0m (Mon 10:00)",
                 "## Days\n- Mon 2h 0m, Wed 1h 0m"]:
        assert part in text
    assert weekly.note(DAY, log) == ("Your week: 3h 0m active — project 2h 0m (+2h 0m), coding 1h 0m · top project "
                                     'friday · 2 commits. Say "open my weekly summary" to read it.')


def test_weekly_open_writes_and_opens(log, monkeypatch):
    monkeypatch.setattr(journal, "commits_between", lambda since, until: {})
    opened = []
    monkeypatch.setattr(weekly.os, "startfile", opened.append)
    assert weekly.run({"action": "open_weekly", "which": "last"}, log, today=DAY + timedelta(days=3)) == \
        "Nothing recorded for the week of 21 September."
    assert opened == [weekly.summary_path(DAY - timedelta(days=7))]


@pytest.mark.parametrize("text, expected", [
    ("how was my week", {"action": "open_weekly", "which": "this"}),
    ("open my weekly summary", {"action": "open_weekly", "which": "this"}),
    ("open last week's summary", {"action": "open_weekly", "which": "last"}),
    ("show me last week's weekly review", {"action": "open_weekly", "which": "last"}),
    ("open my journal", None),
])
def test_weekly_commands(text, expected):
    found = weekly.match_weekly_command(text)
    assert (found and {k: v for k, v in found.items() if k != "type"}) == expected


def test_sunday_evening_writes_the_week(log, monkeypatch):
    monkeypatch.setattr(journal, "commits_between", lambda since, until: {})
    monkeypatch.setattr(watcher.config, "JOURNAL_HOUR", "22")
    monkeypatch.setattr(watcher.config, "BRIEFING_ENABLED", False)
    monkeypatch.setattr(watcher.config, "GIT_REMINDER_HOUR", "")
    monkeypatch.setattr(watcher, "nudges_active", lambda now_ts=None: False)
    delivered = []

    async def deliver(text, habit=None):
        delivered.append(text)

    monkeypatch.setattr(watcher, "_deliver", deliver)
    sunday = DAY + timedelta(days=6)
    log._insert(at=t(10, day=sunday).isoformat(), kind="app", app="code", title="x", duration_s=3600)
    asyncio.run(watcher.tick(t(22, 5, sunday)))
    assert any(d.startswith("Your week: 1h 0m active") for d in delivered)
    assert weekly.summary_path(DAY).exists()
