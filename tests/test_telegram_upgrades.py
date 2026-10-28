"""Owner-authorized commands through the real Telegram -> chat -> intent path."""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import config
from interfaces.api.routes import chat
from services.automation import intent, keyboard
from services.files.search import FileHit
from services.mind.cognition import cognition
from services.telegram import bot, client, inbox, summaries


def update(text, ident=1, age=0, user=42, **extra):
    return {"update_id": ident, "message": {"text": text, "from": {"id": user},
            "chat": {"id": user}, "date": int(time.time() - age), **extra}}


def send(text, **kwargs):
    asyncio.run(bot.handle(update(text, **kwargs)))


@pytest.fixture
def owner(monkeypatch):
    sent, files, keys, typed, power = [], [], [], [], []
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(config, "AI_WORDING_ENABLED", False)
    monkeypatch.setattr(config, "AI_KNOWLEDGE_ENABLED", False)
    monkeypatch.setattr(config, "WEATHER_CITY", "")
    monkeypatch.setattr(bot, "_pending", None)
    monkeypatch.setattr(bot, "started_at", time.time() - 60)
    monkeypatch.setattr(chat, "_memory", SimpleNamespace(get_recent_history=lambda: [], save_message=lambda *a: None))
    monkeypatch.setattr(client, "send", lambda chat_id, text, links=None: sent.append(text))
    monkeypatch.setattr(client, "send_file", lambda chat_id, path, *a: files.append(Path(path)))
    monkeypatch.setattr(keyboard, "press_keys", lambda key, times=1: keys.append((key, times)))
    monkeypatch.setattr(keyboard, "run_steps", typed.extend)
    monkeypatch.setattr(intent.power, "run", lambda parsed: power.append(parsed) or "Power command executed.")
    return SimpleNamespace(sent=sent, files=files, keys=keys, typed=typed, power=power)


@pytest.mark.parametrize("command", ["/h", "/help", "/start", "/H", "/h@FridayBot", "/! /h"])
def test_help_aliases_deliver_the_complete_guide_without_running_commands(owner, monkeypatch, command):
    async def unexpected(request):
        pytest.fail("Help must not call the chat or command executor")
    monkeypatch.setattr(chat, "chat", unexpected)
    send(command)
    assert "".join(owner.sent) == bot.HELP
    assert all(len(part) <= client.TEXT_LIMIT for part in owner.sent)
    assert not owner.power and not owner.keys and not owner.typed and not owner.files


def test_h_is_available_during_lockdown_and_lists_regular_commands(owner):
    send("/lockdown")
    owner.sent.clear()
    send("/h")
    text = "".join(owner.sent)
    for example in ("/h", "/! <command>", "/cc <keys>", "/send <file>", "brain status",
                    "brief me", "weekly summary", "remind me", "find my resume", "play music",
                    "start task", "what are my habits"):
        assert example in text
    assert text == bot.HELP


@pytest.mark.parametrize("command,action", [("/sleep", "sleep_pc"), ("/restart", "restart_pc"),
                                           ("/shutdown 5", "shutdown_pc")])
def test_no_confirmation_executes_power_for_one_message_only(owner, command, action):
    intent._ask_first({"action": "restart_pc"}, "Laptop confirmation")
    send("/! " + command)
    assert [p["action"] for p in owner.power] == [action]
    assert all("yes or no" not in text.lower() for text in owner.sent)
    assert intent.is_awaiting_confirmation()  # the laptop's separate question survives
    assert not intent.skip_confirmation.get() and not intent.telegram_owner.get()
    send(command)
    assert len(owner.power) == 1 and "yes" in owner.sent[-1].lower()
    send("no")
    assert len(owner.power) == 1


def test_no_confirmation_uploads_and_types_without_prompts(owner, monkeypatch, tmp_path):
    file = tmp_path / "notes.txt"
    file.write_text("synthetic notes")
    monkeypatch.setattr(bot, "_find_file", lambda query: FileHit(str(file), file.name))
    send("/! /send notes.txt")
    send("/! type hello")
    assert owner.files == [file] and owner.typed == [{"text": "hello"}]
    assert bot._pending is None and owner.sent[-1] == "Done."
    send("type hello again")
    assert owner.typed == [{"text": "hello"}] and "Reply yes or no" in owner.sent[-1]


def test_bare_prefix_does_not_enable_a_mode(owner):
    send("/!")
    assert "one command" in owner.sent[-1]
    send("/restart")
    assert not owner.power and "yes" in owner.sent[-1].lower()


def test_prefix_accepts_newline_separator(owner):
    send("/!\n/restart")
    assert len(owner.power) == 1


@pytest.mark.parametrize("text", ["/! /restart", "/cc enter", "brain status"])
def test_strangers_and_forwarded_commands_cannot_use_owner_features(owner, text):
    send(text, user=999)
    assert not owner.sent
    send(text, forward_origin={"type": "user"})
    assert "forwarded" in owner.sent[-1]
    assert not owner.power and not owner.keys


@pytest.mark.parametrize("text", ["/! /restart", "/cc enter", "/! brain status"])
def test_lockdown_blocks_new_controls(owner, text):
    send("/lockdown")
    send(text)
    assert "locked" in owner.sent[-1]
    assert not owner.power and not owner.keys


def test_no_confirmation_still_refuses_remote_clipboard_and_saved_logins(owner, monkeypatch):
    from services.automation import logins
    monkeypatch.setattr(logins, "load", lambda: {"github": {}})
    send("/! read my clipboard")
    assert owner.sent[-1] == intent.REMOTE_REFUSAL
    send("/! log me in to github")
    assert owner.sent[-1] == intent.REMOTE_REFUSAL


def test_flags_are_restored_even_when_the_route_fails(owner, monkeypatch):
    async def fail(request):
        assert intent.remote_request.get() and intent.telegram_owner.get() and intent.skip_confirmation.get()
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(chat, "chat", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        send("/! do something")
    assert not intent.remote_request.get() and not intent.telegram_owner.get() and not intent.skip_confirmation.get()


@pytest.mark.parametrize("key,normalized", [("right-arrow", "right arrow"), ("left-arrow", "left arrow"),
                                          ("up-arrow", "up arrow"), ("down-arrow", "down arrow"),
                                          ("enter", "enter"), ("ctrl+s", "ctrl+s"),
                                          ("ctrl+right-arrow", "ctrl+right arrow")])
def test_cc_presses_valid_keys_immediately(owner, key, normalized):
    send("/cc " + key)
    assert owner.keys == [(normalized, 1)] and bot._pending is None
    assert owner.sent[-1].startswith("Pressed ")


@pytest.mark.parametrize("key", ["", "not-a-key", "enter+ctrl", "a+b", "ctrl+"])
def test_invalid_cc_never_reaches_windows(owner, key):
    send("/cc " + key)
    assert not owner.keys and "Use /cc" in owner.sent[-1]


def test_cc_cancels_older_remote_confirmation(owner):
    send("/restart")
    send("/cc enter")
    token = intent.remote_request.set(True)
    try:
        assert not intent.is_awaiting_confirmation()
    finally:
        intent.remote_request.reset(token)
    assert not owner.power


def test_windows_key_failure_returns_a_reply(owner, monkeypatch):
    def blocked(*args):
        raise keyboard.KeyboardError("Windows blocked the key press.")
    monkeypatch.setattr(keyboard, "press_keys", blocked)
    send("/cc enter")
    assert "Windows blocked" in owner.sent[-1]


def test_brain_status_works_for_authenticated_owner(owner):
    send("brain status")
    assert "Local brain reasoning:" in "".join(owner.sent)
    assert "local-only" not in "".join(owner.sent)


@pytest.mark.parametrize("text", ["executive status", "notification status", "reasoning status"])
def test_other_local_status_commands_reply_over_telegram(owner, text):
    send(text)
    assert owner.sent and "local-only" not in owner.sent[-1]


def test_owner_can_recall_a_local_private_question(owner):
    cognition.record("question", "brain", "Synthetic local question about tomorrow", public=False)
    send("what did you ask me")
    assert "Synthetic local question about tomorrow" in owner.sent[-1]


@pytest.mark.parametrize("text", ["brain status", "what did you ask me", "/! /restart"])
def test_owner_features_do_not_expose_local_data_in_a_group(owner, text):
    cognition.record("question", "brain", "Synthetic private question", public=False)
    group_update = update(text)
    group_update["message"]["chat"] = {"id": -100, "type": "group"}
    asyncio.run(bot.handle(group_update))
    assert "Synthetic private question" not in owner.sent[-1]
    assert "Local brain reasoning:" not in owner.sent[-1]
    assert "local-only" in owner.sent[-1] or "private chat" in owner.sent[-1]
    assert not owner.power


def test_long_local_reply_keeps_all_text(owner, monkeypatch):
    text = "🧠 Status\n" + ("• synthetic diagnostic line\n" * 400)
    async def reply(request):
        return SimpleNamespace(response=text, keyboard=[])
    monkeypatch.setattr(chat, "chat", reply)
    send("brain status")
    assert "".join(owner.sent) == text
    assert all(len(part) <= client.TEXT_LIMIT for part in owner.sent)


def test_offline_messages_are_executed_in_order_and_never_replayed(owner):
    updates = [update("/! /restart", 12, age=600), update("/cc right-arrow", 11, age=900)]
    inbox.enqueue(updates)
    inbox.enqueue(updates)  # duplicate getUpdates result
    assert inbox.offset() == 13
    assert [item[0]["update_id"] for item in inbox.pending()] == [11, 12]
    asyncio.run(bot._drain_inbox())
    assert owner.keys == [("right arrow", 1)] and len(owner.power) == 1
    assert owner.sent[0].startswith("Pressed ")
    assert not inbox.pending()
    inbox.enqueue(updates)  # a fresh process rereads the durable cursor
    asyncio.run(bot._drain_inbox())
    assert owner.keys == [("right arrow", 1)] and len(owner.power) == 1


def test_interrupted_execution_is_reported_instead_of_repeated(owner):
    inbox.enqueue([update("/cc enter", 3)])
    inbox.start(3)  # process died after claiming, before a completion receipt
    asyncio.run(bot._drain_inbox())
    assert not owner.keys and "interrupted" in owner.sent[-1]
    assert inbox.offset() == 4 and not inbox.pending()


def test_queue_is_bound_to_the_bot_and_owner(owner, monkeypatch):
    inbox.enqueue([update("/cc enter", 5), update("/cc enter", 6, user=999)])
    assert len(inbox.pending()) == 1 and inbox.offset() == 7
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 777)
    assert not inbox.pending() and inbox.offset() == 0
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 42)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "different-synthetic-token")
    assert not inbox.pending() and inbox.offset() == 0


def test_inbox_batch_and_cursor_are_atomic(owner):
    with pytest.raises(KeyError):
        inbox.enqueue([update("/cc enter", 1), {}])
    assert not inbox.pending() and inbox.offset() == 0


def test_old_cursor_expires_so_telegrams_randomized_ids_can_restart(owner, monkeypatch):
    inbox.enqueue([update("/cc enter", 9000)])
    inbox.finish(9000)
    clock = time.time()
    monkeypatch.setattr(inbox.time, "time", lambda: clock + 8 * 24 * 60 * 60)
    inbox.enqueue([])  # Empty polls do not refresh a stale offset.
    assert inbox.offset() == 0
    inbox.enqueue([update("/cc right-arrow", 10)])
    assert inbox.offset() == 11
    asyncio.run(bot._drain_inbox())
    assert owner.keys == [("right arrow", 1)]


def test_polling_persists_before_advancing_the_telegram_offset(owner, monkeypatch):
    offsets = []
    def poll(method, **kwargs):
        assert method == "getUpdates"
        offsets.append(kwargs["offset"])
        if len(offsets) == 1:
            return [update("/cc enter", 8, age=600)]
        raise asyncio.CancelledError
    monkeypatch.setattr(client, "call", poll)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bot.run_bot())
    assert offsets == [0, 9] and owner.keys == [("enter", 1)]
    assert inbox.offset() == 9 and not inbox.pending()


def test_old_yes_cannot_confirm_a_newly_replayed_command(owner):
    send("/restart", age=600)
    send("yes", age=590)
    assert not owner.power and "queued" in owner.sent[-1]
    send("yes")
    assert len(owner.power) == 1


def test_same_poll_yes_cannot_approve_a_question_issued_after_receipt(owner):
    inbox.enqueue([update("/restart", 1), update("yes", 2)])
    asyncio.run(bot._drain_inbox())
    assert not owner.power and "queued" in owner.sent[-1]
    inbox.enqueue([update("yes", 3)])
    asyncio.run(bot._drain_inbox())
    assert len(owner.power) == 1


def test_daily_and_nightly_reports_have_emoji_sections_and_individual_items(owner, monkeypatch):
    from services.proactive import briefing, deadlines, timetable
    now = datetime(2026, 10, 27, 9)
    monkeypatch.setattr(briefing, "weather", lambda: "Clear, 24°.")
    monkeypatch.setattr(briefing, "_system", lambda **kw: "Battery 80%.")
    monkeypatch.setattr(briefing.reminders, "pending", lambda: [
        SimpleNamespace(text="Send notes, slides and code", due_at=now.replace(hour=17).timestamp())])
    monkeypatch.setattr(timetable, "load", lambda: [{"subject": "DBMS"}])
    monkeypatch.setattr(timetable, "classes_for_date", lambda day: [
        {"subject": "DBMS, lab", "start": "10:00", "day": "tue", "room": "A"}])
    monkeypatch.setattr(deadlines, "load", lambda: [{"what": "Review v1.2, draft", "due": now.replace(hour=19).isoformat()}])
    monkeypatch.setattr(briefing.activity_log, "day_summary", lambda day:
                        "Today you've been active for 2h 0m: code 2h 0m. By kind: coding 2h 0m. Projects: Dr. Smith, v1.2 2h 0m.")
    daily = summaries.build("morning", now)
    assert "\n\n🌤️ Weather\n• Clear, 24°." in daily
    assert "📚 Classes\n• 10:00 am DBMS, lab in A" in daily
    assert "🔔 Reminders\n• 05:00 PM — Send notes, slides and code" in daily
    assert "⏰ Due soon\n• Review v1.2, draft" in daily
    nightly = summaries.build("nightly", now)
    assert "🌙 FRIDAY" in nightly and "📊 Activity\n• Today" in nightly
    assert "\n• By kind:" in nightly and "\n• Projects: Dr. Smith, v1.2" in nightly


def test_weekly_report_keeps_heading_hierarchy_and_separates_days(owner, monkeypatch):
    from services.activity import weekly
    monkeypatch.setattr(weekly, "build", lambda *a: "# Week of Monday, 26 October 2026\n\n**Active:** 5h 0m (+1h 0m)\n\n## Time\n- coding 5h 0m\n\n## Days\n- Mon 2h 0m, Tue 3h 0m\n")
    text = summaries.build("weekly", datetime(2026, 10, 27))
    assert "⏱️ Time by activity\n• coding" in text
    assert "📆 Day by day\n• Mon 2h 0m\n• Tue 3h 0m" in text
    assert "previous week" in text and "##" not in text and "**" not in text


def test_direct_telegram_briefing_uses_the_structured_renderer(owner, monkeypatch):
    from services.proactive import briefing
    monkeypatch.setattr(briefing, "weather", lambda: "Clear, 24°.")
    monkeypatch.setattr(briefing, "_system", lambda **kw: "Battery 80%.")
    send("brief me")
    assert "☀️ FRIDAY — Daily briefing" in "".join(owner.sent)
    assert "\n\n🌤️ Weather\n• Clear, 24°." in "".join(owner.sent)
