import asyncio
from datetime import datetime, timedelta

import pytest

from core.config import config
from services.activity.log import activity_log
from services.automation import intent, modes, personality
from services.automation.intent import ActionResult
from services.proactive import deadlines, timetable

TUESDAY = datetime(2026, 9, 29, 10, 0)
OK = ActionResult(True, "Opening Steam.")


@pytest.fixture
def sarcastic(monkeypatch):
    personality.path.write_text('{"off": false}')
    # only the obvious openings joke (learned humour pinned so tests are exact)
    monkeypatch.setattr(personality.humour, "should_joke", lambda where, weight=1.0: weight >= personality.OPENING)
    monkeypatch.setattr(personality.random, "choice", lambda options: options[0])


def season(parsed, now=TUESDAY, result=OK):
    return personality.season(result, [(parsed, True)], now).message


def test_gaming_in_study_mode_gets_roasted(sarcastic):
    modes.begin("study", None, "")
    assert season({"action": "open_app", "app_name": "steam"}) == "Opening Steam. Bold choice, with study mode on."


def test_videos_during_class_and_before_a_deadline(sarcastic):
    timetable._save([{"day": "tuesday", "start": "09:30", "end": "10:30", "subject": "DBMS", "room": None}])
    assert season({"action": "open_url", "url": "https://www.youtube.com"}) == "Opening Steam. Isn't DBMS on right now?"
    timetable._save([])
    deadlines._save([{"what": "DBMS assignment", "due": (TUESDAY + timedelta(hours=5)).isoformat(), "alerted": []}])
    assert season({"action": "open_app", "app_name": "instagram"}).startswith(
        "Opening Steam. DBMS assignment is due today at 3:00 PM")


def test_the_third_time_in_an_hour(sarcastic):
    for _ in range(3):
        activity_log.log_command({"action": "open_app", "app_name": "instagram"}, True)
    assert season({"action": "open_app", "app_name": "instagram"}, now=datetime.now()).endswith(
        "That's 3 times this hour. instagram must be really important.")


def test_short_study_session_and_useful_things_stay_plain(sarcastic):
    assert season({"action": "end_mode", "routine": "study", "minutes": 12}).endswith(
        "12 minutes of studying. A new personal record.")
    assert season({"action": "open_app", "app_name": "notepad"}) == "Opening Steam."


def test_serious_mode_and_failures_have_no_jokes(sarcastic):
    modes.begin("study", None, "")
    assert personality.run({"action": "sarcasm_off"}) == "Fine. Serious mode. No jokes."
    assert season({"action": "open_app", "app_name": "steam"}) == "Opening Steam."
    personality.run({"action": "sarcasm_on"})
    assert personality.season(ActionResult(False, "Couldn't."), [({"action": "open_app", "app_name": "steam"}, False)],
                              TUESDAY).message == "Couldn't."


def test_game_toast_once_per_session(sarcastic):
    modes.begin("study", None, "")
    assert personality.game_toast("steam", TUESDAY) == "study mode is on… and so is steam. Interesting study technique."
    assert personality.game_toast("steam", TUESDAY) is None
    assert personality.game_toast("notepad", TUESDAY) is None


def test_prompt_has_persona_and_the_moment(sarcastic):
    modes.begin("study", None, "")
    assert 'call the user "Boss"' in config.SYSTEM_PROMPT and "study mode is on" in config.SYSTEM_PROMPT
    personality.run({"action": "sarcasm_off"})
    assert "Boss" not in config.SYSTEM_PROMPT and "Right now" not in config.SYSTEM_PROMPT


@pytest.mark.parametrize("text, action", [("be serious", "sarcasm_off"), ("sarcasm on", "sarcasm_on"),
                                          ("roast me", "roast_me"), ("no more jokes", "sarcasm_off")])
def test_commands(text, action):
    assert personality.match_personality_command(text)["action"] == action


def test_routine_steps_are_seasoned_once_at_the_top(sarcastic, monkeypatch):
    seen = []
    monkeypatch.setattr(personality, "season", lambda result, ran, now=None: seen.append(len(ran)) or result)
    asyncio.run(intent.try_system_action("be serious", "ollama"))
    assert seen == [1]


def test_personal_assistant_role_survives_custom_prompt_and_serious_mode(monkeypatch):
    monkeypatch.setenv("SYSTEM_PROMPT", "Keep replies very brief.")
    personality.run({"action": "sarcasm_off"})
    prompt = config.SYSTEM_PROMPT
    assert "Keep replies very brief." in prompt
    assert "primary role is the user's personal assistant" in prompt
    assert "schedule, commitments" in prompt
    assert "when the user asks" in prompt and "unverified interpretations" in prompt
    assert "Boss" not in prompt


def test_timetable_is_a_plan_not_observed_attendance(sarcastic):
    timetable._save([{"day": "tuesday", "start": "09:30", "end": "10:30", "subject": "DBMS", "room": None}])
    prompt = personality.now_line(TUESDAY)
    assert "DBMS is scheduled until" in prompt
    assert "attendance is unobserved" in prompt
    assert "they're in DBMS" not in prompt
