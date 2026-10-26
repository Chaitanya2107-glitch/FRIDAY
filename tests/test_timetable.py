import asyncio
from datetime import datetime

import pytest

from providers.base_provider import ProviderResponse
from services.automation.system_control import AutomationError
from services.proactive import briefing, timetable

MONDAY_9_50 = datetime(2026, 9, 28, 9, 50)  # 2026-09-28 is a Monday

AI_REPLY = """```json
[{"day": "Monday", "start": "10:00", "end": "11:00", "subject": "DBMS", "room": "204"},
 {"day": "mon", "start": "2 pm", "end": "3 pm", "subject": "OS Lab", "room": null},
 {"day": "Tuesday", "start": "09:00", "end": "10:00", "subject": "Maths", "room": ""},
 {"day": "someday", "start": "x", "end": "y", "subject": "junk"}]
```"""


@pytest.fixture
def saved(monkeypatch, tmp_path):
    sent = []

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kw):
        sent.append((provider, messages[0]))
        return ProviderResponse(content=AI_REPLY, provider=provider, model="m")

    monkeypatch.setattr("providers.failover.complete_with_failover", fake_ai)
    monkeypatch.setattr("services.vision.screen.capture_screen", lambda: b"jpeg")
    reply = asyncio.run(timetable.import_timetable("the screen", "openrouter"))
    return reply, sent


def say(text, now=MONDAY_9_50):
    parsed = timetable.match_timetable_command(text)
    assert parsed, f"not recognised: {text}"
    return timetable.run(parsed, now)


def test_reading_the_timetable_from_the_screen(saved):
    reply, sent = saved
    assert sent[0][1].images == [b"jpeg"]  # the screenshot went to the vision model
    assert reply.startswith("Saved your timetable — 3 classes. Monday: DBMS, OS Lab; Tuesday: Maths.")
    assert timetable.load()[1] == {"day": "monday", "start": "14:00", "end": "15:00", "subject": "OS Lab", "room": None}


def test_questions(saved):
    assert say("what classes do i have today") == "Classes today: 10:00 am DBMS in 204, 2:00 pm OS Lab."
    assert say("what classes do i have tomorrow") == "Classes tomorrow: 9:00 am Maths."
    assert say("show my timetable for wednesday") == "No classes on Wednesday."
    assert say("what's my next class") == "Your next class is DBMS today at 10:00 am in 204."
    assert say("what's my next class", datetime(2026, 9, 28, 16, 0)) == "Your next class is Maths tomorrow at 9:00 am."


def test_loose_questions_the_boss_actually_asked(saved):
    from services.automation.command_words import normalize_command

    def ask(text):
        return say(normalize_command(text))

    tomorrow = "Classes tomorrow: 9:00 am Maths."
    assert ask("What do I have on my timetable tomorrow?") == tomorrow
    assert ask("whats on my timetable tom?") == tomorrow
    assert ask("what's tomorrow on my timetable") == tomorrow
    assert ask("Don't u have my timetable?").startswith("Classes today: 10:00 am DBMS")
    assert ask("do u know my timetable?").startswith("Classes today:")
    assert ask("do i have class on tuesday") == tomorrow.replace("tomorrow", "on Tuesday")
    assert ask("whats my first class tmrw") == tomorrow
    assert ask("any lectures today").startswith("Classes today:")
    assert ask("any lectures on friday") == "No classes on Friday."  # the day, not her name
    assert normalize_command("open chrome, friday") == "open chrome"  # her name
    assert ask("when is my next lecture").startswith("Your next class is DBMS")
    for chat in ("what is a class in python", "The file that i sent you is my timetable",
                 "why is my timetable so packed", "i have a class today so wake me early"):
        assert timetable.match_timetable_command(normalize_command(chat)) is None, chat


def test_chat_prompt_knows_the_timetable(saved):
    line = timetable.prompt_line(MONDAY_9_50)
    assert "Today: 10:00 am DBMS in 204, 2:00 pm OS Lab. Tomorrow: 9:00 am Maths." in line


def test_warning_ten_minutes_before_once(saved):
    assert timetable.due_warnings(MONDAY_9_50) == ["DBMS starts in 10 minutes in 204."]
    assert timetable.due_warnings(datetime(2026, 9, 28, 9, 55)) == []  # already warned
    assert timetable.due_warnings(datetime(2026, 9, 28, 13, 30)) == []  # too early for OS Lab


def test_briefing_mentions_todays_classes(saved):
    assert briefing._classes_today(MONDAY_9_50) == "Classes today: 10:00 am DBMS in 204, 2:00 pm OS Lab."


def test_add_and_remove_by_voice(saved):
    assert say("add class Networks on Wednesday 11 to 12 in room 101") == "Added Wednesday 11:00 am Networks in 101."
    assert say("add class Lab on friday 2 pm to 4 pm") == "Added Friday 2:00 pm Lab."
    assert say("remove class DBMS on monday") == "Removed 1 DBMS class."
    with pytest.raises(AutomationError, match="don't have a class called Physics"):
        say("remove class Physics")
    assert say("clear my timetable") == "Cleared your timetable."


def test_no_timetable_yet():
    assert "read my timetable from the screen" in say("what classes do i have today")
    assert briefing._classes_today(MONDAY_9_50) == ""


def test_import_command_sources():
    assert timetable.match_timetable_command("read my timetable from the screen")["source"] == "the screen"
    assert timetable.match_timetable_command("import timetable from sem3 timetable.pdf")["source"] == "sem3 timetable.pdf"
    parsed = timetable.match_timetable_command("read my timetable from the screen for section ii-a")
    assert (parsed["source"], parsed["section"]) == ("the screen", "II-A")
    assert timetable.match_timetable_command("this is my timetable")["source"] == "screen"
    assert timetable.match_timetable_command("this is my new timetable for section II-A")["section"] == "II-A"
    assert timetable.match_timetable_command("what's the weather") is None


def test_only_my_section_is_asked_for(monkeypatch):
    prompts = []

    async def fake_ai(provider, messages, system_prompt, max_tokens, **kw):
        prompts.append(system_prompt)
        return ProviderResponse(content=AI_REPLY, provider=provider, model="m")

    monkeypatch.setattr("providers.failover.complete_with_failover", fake_ai)
    monkeypatch.setattr("services.vision.screen.capture_screen", lambda: b"jpeg")
    monkeypatch.setattr(timetable.config, "TIMETABLE_SECTION", "II-A")
    asyncio.run(timetable.import_timetable("the screen", "openrouter"))
    assert "ONLY the classes of section II-A" in prompts[0]


def test_replies_with_thinking_before_the_json():
    reply = ('The user has a timetable for sections II-A to II-E. Here it is:\n'
             '[{"day": "monday", "start": "08:00", "end": "09:00", "subject": "Maths", "room": "R12"}]')
    assert timetable.parse_classes(reply) == [
        {"day": "monday", "start": "08:00", "end": "09:00", "subject": "Maths", "room": "R12"}]
    assert timetable.parse_classes("I can't tell which subject is which.") == []


def test_several_sections_without_mine_asks_which(monkeypatch):
    async def fake_ai(*a, **kw):
        return ProviderResponse(content="This timetable has sections II-A, II-B and II-C.", provider="x", model="m")

    monkeypatch.setattr("providers.failover.complete_with_failover", fake_ai)
    monkeypatch.setattr("services.vision.screen.capture_screen", lambda: b"jpeg")
    monkeypatch.setattr(timetable.config, "TIMETABLE_SECTION", "")
    with pytest.raises(AutomationError, match="say which is yours"):
        asyncio.run(timetable.import_timetable("the screen", "openrouter"))


def test_images_never_go_to_a_model_that_cannot_see(monkeypatch):
    from core.errors import ProviderError
    from providers import failover
    from providers.base_provider import Message
    from services.network import status

    monkeypatch.setattr(failover.config, "OLLAMA_MODEL", "qwen2.5:3b-instruct-q5_K_M")
    monkeypatch.setattr(status.network, "online", False)  # offline: only the (blind) local model is left
    monkeypatch.setattr(failover, "get_provider", lambda *a, **k: pytest.fail("the blind model was asked"))
    with pytest.raises(ProviderError, match="needs a vision AI"):
        asyncio.run(failover.complete_with_failover(
            "openrouter", [Message(role="user", content="x", images=[b"jpeg"])], "p", 10))


@pytest.mark.parametrize("said, expected", [("10", "10:00"), ("2", "14:00"), ("2 pm", "14:00"), ("9:30 am", "09:30"),
                                            ("12", "12:00"), ("14:15", "14:15")])
def test_times(said, expected):
    assert timetable.parse_time(said) == expected
