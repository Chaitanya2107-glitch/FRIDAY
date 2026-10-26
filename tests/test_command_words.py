import asyncio

import pytest

from services.automation import intent
from services.automation.command_words import is_multi_step, normalize_command
from services.automation.intent import ActionResult, try_system_action

YT = "https://www.youtube.com/results?search_query="


@pytest.fixture
def routed(monkeypatch):
    """Records what try_system_action would run (nothing really runs) and every AI call."""
    state = type("State", (), {"actions": [], "ai_messages": []})()

    def fake_execute(parsed, confirmed=False):
        state.actions.append({k: v for k, v in parsed.items() if k != "type"})
        return ActionResult(True, "done")

    async def fake_ai(message, provider_name):
        state.ai_messages.append(message)
        return None

    intent.cancel_pending_confirmation()
    monkeypatch.setattr(intent.media, "has_player", lambda: False)
    monkeypatch.setattr(intent, "_execute", fake_execute)
    monkeypatch.setattr(intent, "_classify_with_ai", fake_ai)
    return state


def route(message):
    return asyncio.run(try_system_action(message, "openrouter"))


# ── Filler ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("hey friday, can you please open chrome for me?", "open chrome"),
    ("Friday: could you launch Spotify now", "launch Spotify"),
    ("I want you to mute", "mute"),
    ("please just take a screenshot thanks", "take a screenshot"),
    ("let's organise downloads!", "organise downloads"),
    ("What's the weather?", "What's the weather"),
])
def test_filler_is_stripped(message, expected):
    assert normalize_command(message) == expected


# ── Wordings that now run locally, without the AI ─────────────────────────────

APPS = [
    ("hey friday, can you please open chrome for me?", {"action": "open_app", "app_name": "chrome"}),
    ("launch the spotify app", {"action": "open_app", "app_name": "spotify"}),
    ("fire up black myth wukong", {"action": "open_app", "app_name": "black myth wukong"}),
    ("open the browser", {"action": "open_app", "app_name": "chrome"}),
    ("start calc", {"action": "open_app", "app_name": "calculator"}),
    ("open file explorer", {"action": "open_app", "app_name": "explorer"}),
    ("kill spotify", {"action": "close_app", "app_name": "spotify"}),
    ("terminate the chrome browser", {"action": "close_app", "app_name": "chrome"}),
    ("could you quit whatsapp please", {"action": "close_app", "app_name": "whatsapp"}),
]
WEB = [
    ("open youtube", {"action": "open_url", "url": "youtube.com"}),
    ("go to github", {"action": "open_url", "url": "github.com"}),
    ("take me to gmail", {"action": "open_url", "url": "mail.google.com"}),
    ("visit reddit.com", {"action": "open_url", "url": "reddit.com"}),
    ("youtube.com", {"action": "open_url", "url": "youtube.com"}),
    ("search lofi beats on youtube", {"action": "open_url", "url": YT + "lofi%20beats"}),
    ("youtube minecraft tutorials", {"action": "open_url", "url": YT + "minecraft%20tutorials"}),
    ("google best pizza near me", {"action": "search_chrome", "query": "best pizza near me"}),
    ("search on google for rtx 5090 price", {"action": "search_chrome", "query": "rtx 5090 price"}),
    ("find me cheap flights to goa", {"action": "search_chrome", "query": "cheap flights to goa"}),
    ("search for cat videos online", {"action": "search_chrome", "query": "cat videos"}),
]
FOLDERS = [
    ("open my downloads folder", {"action": "open_folder", "path": intent.FOLDER_MAP["downloads"]}),
    ("show my photos", {"action": "open_folder", "path": intent.FOLDER_MAP["pictures"]}),
    ("go to documents", {"action": "open_folder", "path": intent.FOLDER_MAP["documents"]}),
    ("pull up the movies folder", {"action": "open_folder", "path": intent.FOLDER_MAP["videos"]}),
    ("sort out my downloads", {"action": "organise_folder", "path": intent.FOLDER_MAP["downloads"]}),
    ("declutter the desktop", {"action": "organise_folder", "path": intent.FOLDER_MAP["desktop"]}),
]
DEVICE = [
    ("crank up the volume", {"action": "change_volume", "delta": 10}),
    ("volume max", {"action": "set_volume", "level": 100}),
    ("make it a lot louder", {"action": "change_volume", "delta": 30}),
    ("a bit quieter", {"action": "change_volume", "delta": -10}),
    ("half volume", {"action": "set_volume", "level": 50}),
    ("sound to 25", {"action": "set_volume", "level": 25}),
    ("turn the sound off", {"action": "set_mute", "mute": True}),
    ("silence", {"action": "set_mute", "mute": True}),
    ("mute the laptop please", {"action": "set_mute", "mute": True}),
    ("sound on", {"action": "set_mute", "mute": False}),
    ("brighten the screen", {"action": "change_brightness", "delta": 10}),
    ("make the display darker", {"action": "change_brightness", "delta": -10}),
    ("max brightness", {"action": "set_brightness", "level": 100}),
    ("screen brightness to 40", {"action": "set_brightness", "level": 40}),
    ("grab a screenshot", {"action": "take_screenshot"}),
    ("print screen", {"action": "take_screenshot"}),
    ("what's in my clipboard", {"action": "read_clipboard"}),
    ("what did I copy", {"action": "read_clipboard"}),
    ("put Hello There on the clipboard", {"action": "write_clipboard", "text": "Hello There"}),
    ("copy salt and pepper to clipboard", {"action": "write_clipboard", "text": "salt and pepper"}),
    ("wipe clipboard history", {"action": "clear_clipboard_history"}),
]
REMINDERS = [
    ("set a reminder for 5pm to call mom", {"action": "set_reminder", "message": "remind me at 5pm to call mom"}),
    ("create a reminder in 10 minutes to stretch",
     {"action": "set_reminder", "message": "remind me in 10 minutes to stretch"}),
    ("set a reminder for tomorrow at 9am to pay rent",
     {"action": "set_reminder", "message": "remind me tomorrow at 9am to pay rent"}),
    ("can you remind me in 10 minutes to stretch",
     {"action": "set_reminder", "message": "remind me in 10 minutes to stretch"}),
    ("any reminders?", {"action": "list_reminders"}),
    ("what are my reminders", {"action": "list_reminders"}),
    ("delete all reminders", {"action": "cancel_all_reminders"}),
    ("remove reminder 3", {"action": "cancel_reminder", "number": 3}),
]


@pytest.mark.parametrize("message, expected", APPS + WEB + FOLDERS + DEVICE + REMINDERS)
def test_command_runs_locally(routed, message, expected):
    assert route(message) == ActionResult(True, "done")
    assert routed.actions == [expected]
    assert routed.ai_messages == []


# ── Chat that must not become a command ───────────────────────────────────────

@pytest.mark.parametrize("message", [
    "can you tell me about chrome extensions",
    "what's the sound of a cat",
    "the sound is off in this video",
    "a sound at 50 hz is too low",
    "reminders are useful",
    "set up my project plan",
    "take me through fastapi basics",
    "how do I take a screenshot",
    "config.py",
    "I love this song",
    "make it make sense",
    "turn left at the light",
])
def test_chat_stays_chat_without_asking_the_ai(routed, message):
    assert route(message) is None
    assert routed.actions == []
    assert routed.ai_messages == []


@pytest.mark.parametrize("message", [
    "show me pictures of cats",
    "open chrome so I can check my mail",
    "find out why the sky is blue",
    "close the door behind you",
])
def test_unclear_wordings_go_to_the_ai(routed, message):
    assert route(message) is None
    assert routed.actions == []
    assert routed.ai_messages == [message]


# ── Several commands in one message ───────────────────────────────────────────

@pytest.mark.parametrize("message, expected", [
    ("mute and open chrome", True),
    ("turn the volume up, then take a screenshot", True),
    ("search cats and dogs", False),
    ("copy salt and pepper to clipboard", False),
    ("open chrome", False),
])
def test_multi_step_detection(message, expected):
    assert is_multi_step(message) is expected


def test_recognized_multi_step_messages_run_locally(routed):
    route("please mute and open chrome")
    assert [a["action"] for a in routed.actions] == ["set_mute", "open_app"]
    assert routed.ai_messages == []


def test_reminders_that_mention_other_commands_stay_reminders(routed):
    route("remind me in 5 minutes to open chrome and close spotify")
    assert routed.actions == [{
        "action": "set_reminder", "message": "remind me in 5 minutes to open chrome and close spotify",
    }]
    assert routed.ai_messages == []


@pytest.mark.parametrize("message, expected", [
    ("hey friday, what time is it?", "It's 9:05 PM."),
    ("What's the time", "It's 9:05 PM."),
    ("tell me the time", "It's 9:05 PM."),
    ("what's the date today", "It's Monday, September 28, 2026."),
    ("what day is it", "It's Monday, September 28, 2026."),
    ("what time is it in london", None),
    ("time to go", None),
])
def test_clock_questions_are_answered_from_the_pc_clock(message, expected):
    from datetime import datetime
    assert intent.clock_answer(normalize_command(message), datetime(2026, 9, 28, 21, 5)) == expected


# Equivalent requests must work in the default local-only action mode too.
@pytest.mark.parametrize("prefix", [
    "", "Could you please ", "Would you be able to ",
    "Is it possible for you to ", "I was wondering if you could ",
])
@pytest.mark.parametrize("phrase, expected", [
    ("pop open Chrome", {"action": "open_app", "app_name": "chrome"}),
    ("get Spotify running", {"action": "open_app", "app_name": "spotify"}),
    ("bring Chrome to the front", {"action": "open_app", "app_name": "chrome"}),
    ("shut Spotify down", {"action": "close_app", "app_name": "spotify"}),
    ("make the volume less loud", {"action": "change_volume", "delta": -10}),
    ("make the sound more quiet", {"action": "change_volume", "delta": -10}),
    ("make the display less bright", {"action": "change_brightness", "delta": -10}),
    ("make the screen less dim", {"action": "change_brightness", "delta": 10}),
    ("set the volume to twenty five percent", {"action": "set_volume", "level": 25}),
    ("set brightness to seventy-five percent", {"action": "set_brightness", "level": 75}),
    ("take a picture of my screen", {"action": "take_screenshot"}),
    ("put the music on hold", {"action": "media_pause"}),
    ("carry on playing", {"action": "media_play"}),
    ("move to the next track", {"action": "media_next"}),
    ("go back to the previous track", {"action": "media_previous"}),
    ("listen to Believer", {"action": "play_song", "query": "believer"}),
    ("schedule a notification in 10 minutes to stretch",
     {"action": "set_reminder", "message": "remind me in 10 minutes to stretch"}),
    ("save a note Buy USB-C Cable", {"action": "add_note", "text": "Buy USB-C Cable"}),
])
def test_equivalent_requests_work_without_ai(routed, monkeypatch, prefix, phrase, expected):
    from core.config import config
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    assert route(prefix + phrase) == ActionResult(True, "done")
    assert routed.actions == [expected]
    assert routed.ai_messages == []


@pytest.mark.parametrize("message", [
    "don't get Spotify running", "never pop open Chrome",
    "how do I get Spotify running", "what does make the screen less bright mean",
    "if I say shut Spotify down what happens", "the movie is less bright than before",
    "I was wondering if you could explain how to open Chrome",
    "take a picture of my cat", "make the screen less bright tomorrow",
])
def test_paraphrases_do_not_turn_negation_or_discussion_into_actions(routed, monkeypatch, message):
    from core.config import config
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    assert route(message) is None
    assert routed.actions == []
    assert routed.ai_messages == []


def test_equivalent_steps_are_recognized_together(routed, monkeypatch):
    from core.config import config
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    assert route("get Chrome running and make the display less bright").success
    assert routed.actions == [
        {"action": "open_app", "app_name": "chrome"},
        {"action": "change_brightness", "delta": -10},
    ]


def test_sentence_patterns_leave_dictation_unchanged(routed):
    route("type Get Spotify running and make the screen less bright, please!")
    assert routed.actions == [{
        "action": "type_text", "text": "Get Spotify running and make the screen less bright, please!",
    }]


@pytest.mark.parametrize("spoken, level", [
    ("zero", 0), ("one", 1), ("nineteen", 19), ("twenty", 20),
    ("twenty-one", 21), ("ninety nine", 99), ("one hundred", 100), ("a hundred", 100),
])
@pytest.mark.parametrize("noun", ["volume", "brightness"])
def test_spoken_percentage_boundaries(routed, noun, spoken, level):
    route(f"set {noun} to {spoken} percent")
    assert routed.actions == [{"action": f"set_{noun}", "level": level}]


@pytest.mark.parametrize("phrase, expected", [
    ("increase volume by twenty", {"action": "change_volume", "delta": 20}),
    ("reduce brightness by thirty-five", {"action": "change_brightness", "delta": -35}),
    ("make the sound less quiet", {"action": "change_volume", "delta": 10}),
    ("make the volume more loud", {"action": "change_volume", "delta": 10}),
    ("make the display more bright", {"action": "change_brightness", "delta": 10}),
    ("make the screen more dim", {"action": "change_brightness", "delta": -10}),
    ("save a note Make the screen less bright", {"action": "add_note", "text": "Make the screen less bright"}),
    ("remind me in 5 minutes to get Chrome running",
     {"action": "set_reminder", "message": "remind me in 5 minutes to get Chrome running"}),
    ("search for ways to get Chrome running",
     {"action": "search_chrome", "query": "ways to get Chrome running"}),
    ("copy Get Chrome running to clipboard", {"action": "write_clipboard", "text": "Get Chrome running"}),
])
def test_paraphrases_preserve_direction_amount_and_task_contents(routed, phrase, expected):
    route(phrase)
    assert routed.actions == [expected]


def test_app_sentence_patterns_do_not_swallow_other_steps(routed):
    route("get Chrome running and get Spotify running")
    assert routed.actions == [
        {"action": "open_app", "app_name": "chrome"},
        {"action": "open_app", "app_name": "spotify"},
    ]


@pytest.mark.parametrize("phrase", [
    "shut my computer down", "shut the laptop down", "shut Windows down",
])
def test_app_sentence_patterns_leave_power_commands_alone(phrase):
    assert intent.words.rephrase_command(phrase) == phrase
