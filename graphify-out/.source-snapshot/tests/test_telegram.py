import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import config
from interfaces.api.routes import chat as chat_route
from services.activity import habits
from services.automation import intent
from services.files.search import FileHit
from services.proactive import buttons, watcher
from services.telegram import bot, client

ME = 42


@pytest.fixture
def tg(monkeypatch):
    """A fake Telegram: what FRIDAY sends is recorded in `sent` / `files`, and the user asked is ME."""
    sent, files, asked = [], [], []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", ME)
    monkeypatch.setattr(client, "send", lambda chat_id, text, links=None: sent.append((text, links)))
    monkeypatch.setattr(client, "send_file", lambda chat_id, path, photo=False, caption="": files.append((Path(path).name, photo)))
    monkeypatch.setattr(client, "call", lambda method, **kw: None)
    monkeypatch.setattr(bot, "started_at", time.time() - 60)
    monkeypatch.setattr(bot, "_pending", None)

    async def fake_chat(request):
        asked.append((request.message, intent.remote_request.get()))
        return SimpleNamespace(response=f"did: {request.message}", keyboard=[])
    monkeypatch.setattr(chat_route, "chat", fake_chat)
    return SimpleNamespace(sent=sent, files=files, asked=asked, texts=lambda: [t for t, _ in sent])


def message(text=None, user=ME, age=0, **extra):
    msg = {"from": {"id": user}, "chat": {"id": user}, "date": int(time.time() - age), **extra}
    if text is not None:
        msg["text"] = text
    return {"message": msg}


def run(update):
    asyncio.run(bot.handle(update))


def test_messages_go_through_the_command_path_marked_remote(tg):
    run(message("turn the volume up"))
    assert tg.asked == [("turn the volume up", True)]
    assert tg.texts() == ["did: turn the volume up"]
    assert intent.remote_request.get() is False  # only for that message


def test_setup_reply_tells_the_user_their_id(tg, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 0)
    run(message("hi", user=777))
    assert tg.texts() == ["Your Telegram ID is 777. Add TELEGRAM_USER_ID=777 to FRIDAY's .env and restart FRIDAY."]
    assert tg.asked == []


def test_strangers_are_ignored_silently(tg):
    run(message("open chrome", user=999))
    assert tg.sent == [] and tg.asked == []


def test_offline_commands_run_but_forwarded_messages_are_refused(tg):
    run(message("open chrome", age=600))
    run(message("open chrome", forward_date=int(time.time())))
    assert tg.asked == [("open chrome", True)]
    assert "forwarded" in tg.texts()[1]


def test_clipboard_and_logins_are_refused_remotely():
    token = intent.remote_request.set(True)
    try:
        result = asyncio.run(intent.try_system_action("read my clipboard", "openai"))
    finally:
        intent.remote_request.reset(token)
    assert result.message == intent.REMOTE_REFUSAL and not result.success


def test_lockdown_blocks_commands_until_unlocked_at_the_laptop(tg):
    run(message("/lockdown"))
    run(message("open chrome"))
    assert tg.asked == [] and "locked" in tg.texts()[1]

    token = intent.remote_request.set(True)  # "unlock telegram" from Telegram doesn't count
    try:
        assert not asyncio.run(intent.try_system_action("unlock telegram", "openai")).success
    finally:
        intent.remote_request.reset(token)
    assert client.locked()

    assert asyncio.run(intent.try_system_action("unlock telegram", "openai")).success  # at the laptop
    run(message("open chrome"))
    assert tg.asked == [("open chrome", True)]


def test_typing_asks_first(tg, monkeypatch):
    typed = []
    monkeypatch.setattr(bot.keyboard, "run_steps", typed.extend)
    monkeypatch.setattr("services.activity.log.foreground_window", lambda: ("notepad", "notes.txt - Notepad"))

    async def typing_chat(request):
        return SimpleNamespace(response="Typing it.", keyboard=[{"text": "hello"}])
    monkeypatch.setattr(chat_route, "chat", typing_chat)

    run(message("type hello"))
    assert tg.texts()[-1] == 'Type "hello" into notes.txt - Notepad? Reply yes or no.' and typed == []
    run(message("yes"))
    assert typed == [{"text": "hello"}] and tg.texts()[-1] == "Done."


def test_send_file_asks_then_uploads(tg, tmp_path, monkeypatch):
    notes = tmp_path / "DBMS notes.pdf"
    notes.write_bytes(b"x" * 2048)
    monkeypatch.setattr(bot, "_find_file", lambda query: FileHit(str(notes), notes.name) if query == "dbms notes" else None)

    run(message("send me my dbms notes"))
    assert tg.texts()[-1] == "Send DBMS notes.pdf (2 KB)? Reply yes or no." and tg.files == []
    run(message("no"))
    assert tg.files == []

    run(message("/send dbms notes"))
    run(message("yes"))
    assert tg.files == [("DBMS notes.pdf", False)] and tg.texts()[-1] == "Sent DBMS notes.pdf."

    run(message("send me the weather"))  # no such file: an ordinary message
    assert tg.asked[-1] == ("send me the weather", True)


def test_a_screenshot_comes_back_as_a_photo(tg, monkeypatch):
    async def screenshot_chat(request):
        bot.system.last_screenshot = Path("FRIDAY_shot.png")
        return SimpleNamespace(response="Screenshot saved.", keyboard=[])
    monkeypatch.setattr(chat_route, "chat", screenshot_chat)
    monkeypatch.setattr(bot.system, "last_screenshot", None)
    run(message("take a screenshot"))
    assert tg.files == [("FRIDAY_shot.png", True)]


def test_notification_buttons_work_from_telegram(tg, monkeypatch):
    monkeypatch.setattr("services.activity.log.idle_seconds", lambda: 3600)  # away
    key = "chain:app:code>app:spotify"
    client.mirror("F.R.I.D.A.Y", "You usually open spotify after code. Open it?", buttons.offer("habit", habit=key, id="s1"))
    text, links = tg.sent[-1]
    assert text == "F.R.I.D.A.Y\nYou usually open spotify after code. Open it?"
    assert [label for label, _ in links] == ["Open it", "Not now", "Stop suggesting"]

    never = links[2][1]
    asyncio.run(bot.handle({"callback_query": {"id": "1", "from": {"id": ME}, "message": {"chat": {"id": ME}}, "data": never}}))
    assert tg.texts()[-1] == "Okay, I won't suggest that again."
    assert habits.load_state()["habits"][key]["muted"] is True


def test_notifications_only_go_to_telegram_when_away(tg, monkeypatch):
    monkeypatch.setattr("services.activity.log.idle_seconds", lambda: 30)
    client.mirror("F.R.I.D.A.Y", "FRIDAY ONLINE")
    assert tg.sent == []
    monkeypatch.setattr("services.activity.log.idle_seconds", lambda: config.TELEGRAM_AWAY_MINUTES * 60)
    client.mirror("F.R.I.D.A.Y", "FRIDAY ONLINE")
    assert tg.texts() == ["F.R.I.D.A.Y\nFRIDAY ONLINE"]


def test_button_links_fit_telegram():
    link = buttons.offer("habit", habit="time:app:code:weekday", id="s1")[2][1]
    data = client.button_data(link)
    assert data.startswith("b|") and data.endswith("|never") and len(data.encode()) <= 64


# ── Send-to-laptop ────────────────────────────────────────────────────────────

def test_a_link_opens_on_the_laptop(tg, monkeypatch):
    opened = []
    monkeypatch.setattr(bot.system, "open_url", opened.append)
    run(message("https://youtu.be/AbC123xyz"))
    run(message("Great talk on RAG\nhttps://www.youtube.com/watch?v=Zx9Q"))  # a phone's share
    assert opened == ["https://youtu.be/AbC123xyz", "https://www.youtube.com/watch?v=Zx9Q"]  # letter case kept
    assert tg.texts() == ["Opened it on the laptop."] * 2
    run(message("summarise https://example.com for me"))  # a link inside a request: an ordinary message
    assert tg.asked == [("summarise https://example.com for me", True)]


def test_copy_puts_text_on_the_laptops_clipboard(tg, monkeypatch):
    copied = []
    monkeypatch.setattr(bot.system, "write_clipboard", lambda text: copied.append(text) or f"Copied to clipboard: {text}")
    run(message("copy WiFi pass: Tr1cky!"))
    run(message("copy hello to the clipboard"))
    assert copied == ["WiFi pass: Tr1cky!", "hello"] and tg.asked == []


def test_a_file_is_saved_and_shown_never_opened(tg, monkeypatch):
    shown = []
    monkeypatch.setattr(bot, "_reveal", shown.append)
    monkeypatch.setattr(client, "download", lambda file_id: b"%PDF-1.7 " + file_id.encode())
    doc = {"file_id": "f1", "file_name": "notes.pdf", "file_size": 20}
    run(message(document=doc))
    run(message(document=doc, forward_date=int(time.time())))  # forwarded files are fine: only saved
    run(message(photo=[{"file_id": "small", "file_size": 5}, {"file_id": "big", "file_size": 50}]))
    names = [p.name for p in shown]
    assert names[:2] == ["notes.pdf", "notes (1).pdf"] and names[2].startswith("photo ") and names[2].endswith(".jpg")
    assert shown[2].read_bytes() == b"%PDF-1.7 big" and shown[0].parent == bot.RECEIVED_DIR
    assert tg.texts()[0] == "Saved notes.pdf to Downloads\\FRIDAY." and tg.asked == []


def test_files_over_telegrams_limit_are_refused(tg, monkeypatch):
    monkeypatch.setattr(client, "download", lambda file_id: pytest.fail("downloaded a file that's too big"))
    run(message(document={"file_id": "f", "file_name": "movie.mkv", "file_size": 700 * 1024 * 1024}))
    assert "up to 20 MB" in tg.texts()[0]


def test_dangerous_names_stay_in_the_folder(tmp_path):
    target = bot._unique(tmp_path, r"..\..\Windows\evil:name?.exe")
    assert target.parent == tmp_path and target.name == "evil_name_.exe"
