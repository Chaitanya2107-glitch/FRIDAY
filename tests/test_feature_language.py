"""Check paraphrases against real feature parsers, without running PC actions."""
import asyncio

import pytest

from services.automation import intent
from services.automation.command_phrases import PHRASE_GROUPS
from services.automation.command_words import normalize_command, rephrase_command
from services.mind import workspace_commands, execution_commands, reasoning_commands
from services.voice.conversation import match_conversation
from services.vision.screen import extract_screen_question
from services.learning import reports
from services.proactive import class_changes
from services.mind import followup_commands

MATCHERS = {
    "apps": intent.match_app_command,
    "device": intent.match_device_command,
    "transforms": intent.clipboard_transforms.match_clipboard_transform,
    "typing": intent.match_typing_command,
    "stats": intent.match_stats_command,
    "reminders": intent._match_reminder_command,
    "media": lambda text: intent.match_media_command(text, lambda: True),
    "spotify": lambda text: intent.match_media_command(text, lambda: True),
    "conversation": match_conversation,
    "screen": extract_screen_question,
    "learning": lambda text: bool(reports._REQUEST.fullmatch(text)),
    "routines": intent.routines.match_routine_command,
    "modes": intent.modes.match_mode_command,
    "voice": intent.voice_commands.match_voice_command,
    "notes": intent.notes.match_note_command,
    "reading": intent.reading_list.match_reading_command,
    "files": intent.files.match_file_command,
    "installers": intent.installers.match_installer_command,
    "health": intent.system_health.match_health_command,
    "limits": intent.limits.match_limit_command,
    "watches": intent.watches.match_watch_command,
    "deadlines": intent.deadlines.match_deadline_command,
    "timetable": intent.timetable.match_timetable_command,
    "class_changes": class_changes.match_command,
    "task_followups": followup_commands.match_command,
    "college": intent.college.match_college_command,
    "attendance": intent.attendance.match_attendance_command,
    "personality": intent.personality.match_personality_command,
    "power": intent.power.match_power_command,
    "insights": intent.insights.match_insight_command,
    "devtools": intent.devtools.match_dev_command,
    "habits": intent.habits.match_habit_command,
    "projects": intent.projects.match_project_command,
    "journal": intent.journal.match_journal_command,
    "weekly": intent.weekly.match_weekly_command,
    "study": intent.study.match_study_command,
    "git": intent.git_status.match_git_command,
    "logins": intent.logins.match_login_command,
    "whatsapp": intent.whatsapp.match_whatsapp_command,
    "telegram": intent.telegram_commands.match_command,
    "proactive": intent.match_proactive_command,
    "talk": intent.talk.match_talk_command,
    "reflection": intent.reflection.match_mind_command,
    "life": intent.life.match_life_command,
    "evening": intent.evening.match_evening_command,
    "foresight": intent.foresight.match_foresight_command,
    "brain": intent.brain.match_brain_command,
    "predict": intent.predict.match_predict_command,
    "activity": intent.match_activity_command,
    "memory": intent.match_memory_command,
    "wrapped": intent.spotify_wrapped.match_wrapped_command,
    "fun": intent.fun.match_fun_command,
    "cognition": intent.cognition_commands.match_command,
    "workspace": workspace_commands.match_command,
    "execution": execution_commands.match_command,
    "reasoning": reasoning_commands.match_command,
}
CASES = [
    pytest.param(family, canonical, alias, id=f"{family}: {alias}")
    for family, commands in PHRASE_GROUPS.items()
    for canonical, aliases in commands.items()
    for alias in aliases
]


@pytest.mark.parametrize("family,canonical,alias", CASES)
@pytest.mark.parametrize("prefix", ["", "Could you please ", "Would you be able to "])
def test_feature_paraphrase_matches_the_same_task(family, canonical, alias, prefix):
    expected = MATCHERS[family](canonical)
    assert expected, f"Canonical example is not recognized: {family}: {canonical}"
    actual = normalize_command(rephrase_command(prefix + alias))
    assert MATCHERS[family](actual) == expected


@pytest.mark.parametrize("family,canonical,alias", CASES)
def test_paraphrases_do_not_rewrite_payloads_or_negated_requests(family, canonical, alias):
    for message in (f"don't {alias}", f"never {alias}", f"type {alias}",
                    f"note {alias}", f"search for {alias}", f"how do i {alias}",
                    f"remind me tomorrow to {alias}", f'"{alias}"'):
        assert rephrase_command(message) == message


def test_each_phrase_has_only_one_meaning():
    pairs = [(alias, canonical) for commands in PHRASE_GROUPS.values()
             for canonical, aliases in commands.items() for alias in aliases]
    assert len(pairs) == len({normalize_command(alias).casefold() for alias, _ in pairs})
    assert set(PHRASE_GROUPS) == set(MATCHERS)


DIRECT_FAMILIES = set(MATCHERS) - {
    "modes", "college", "telegram", "talk", "life", "evening", "cognition",
    "workspace", "execution", "reasoning", "conversation", "screen", "learning",
    "class_changes",  # Scoped early routing is exercised with real saved classes in test_class_changes.
    "task_followups",  # Scoped controls and replies use real state in test_task_followups.
}


@pytest.mark.parametrize("family,canonical,alias", [
    case for case in CASES if case.values[0] in DIRECT_FAMILIES
])
def test_alias_reaches_its_feature_through_the_real_router(monkeypatch, family, canonical, alias):
    from core.config import config
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    executed = []
    def capture(parsed, confirmed=False):
        executed.append(parsed)
        return intent.ActionResult(True, "captured")
    monkeypatch.setattr(intent, "_execute", capture)
    intent.cancel_pending_confirmation()
    result = asyncio.run(intent.try_system_action("Could you please " + alias, "openrouter"))
    assert result and result.success
    assert executed == [MATCHERS[family](canonical)]


PARAMETER_CASES = [
    ("routines", "define a workflow called Desk: open chrome and mute", "create a routine called Desk: open chrome and mute"),
    ("whatsapp", "whatsapp message to Ravi: Keep CAPS, don't change this!", "message Ravi on whatsapp: Keep CAPS, don't change this!"),
    ("telegram", 'forward the message "Keep CAPS, please!" via telegram', 'send the message "Keep CAPS, please!" through telegram'),
    ("files", "track down my Embedded Systems PDF", "find my Embedded Systems PDF"),
    ("deadlines", "set a due date for DSP Assignment to tomorrow at 5pm", "add deadline DSP Assignment due tomorrow at 5pm"),
    ("attendance", "record attendance for DSP as present today", "attended DSP today"),
    ("attendance", "record attendance for EVS as absent yesterday", "missed EVS yesterday"),
    ("college", "join my EVS online lecture", "join EVS class"),
    ("college", "prepare EVS revision notes", "make a revision pack for EVS"),
    ("logins", "use my saved login for College Portal", "log in to College Portal"),
    ("execution", "prepare a handover for Project Friday", "prepare a handoff for Project Friday"),
    ("workspace", "create a task: Review Code, Please!", "start task: Review Code, Please!"),
    ("workspace", "create a goal: Finish Project Friday", "add goal: Finish Project Friday"),
]


@pytest.mark.parametrize("family,phrase,canonical", PARAMETER_CASES)
def test_parameterized_phrases_keep_names_and_payloads(monkeypatch, family, phrase, canonical):
    if family == "attendance":
        monkeypatch.setattr(intent.timetable, "subjects", lambda: ["DSP", "EVS"])
    if family == "logins":
        monkeypatch.setattr(intent.logins, "load", lambda: {"college": {}})
    rewritten = rephrase_command("Could you please " + phrase)
    assert rewritten == canonical
    # Raw literals are passed to parsers that own their punctuation; other parsers
    # receive ordinary normalized command syntax just as they do in intent.py.
    raw = family in {"whatsapp", "telegram", "workspace", "execution"}
    source = rewritten if raw else normalize_command(rewritten)
    expected = canonical if raw else normalize_command(canonical)
    assert MATCHERS[family](source) == MATCHERS[family](expected)
    assert MATCHERS[family](source)


@pytest.mark.parametrize("family,phrase,canonical", PARAMETER_CASES)
def test_parameterized_phrases_are_not_applied_inside_other_tasks(family, phrase, canonical):
    for prefix in ("type ", "note ", "don't ", "how do i ", "search for "):
        assert rephrase_command(prefix + phrase) == prefix + phrase


@pytest.mark.parametrize("phrase", ["suspend my laptop", "restart this device", "power down my laptop"])
def test_power_paraphrases_keep_confirmation(monkeypatch, phrase):
    from core.config import config
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", True)
    monkeypatch.setattr(intent.power, "_later", lambda *a: pytest.fail("power action ran before confirmation"))
    monkeypatch.setattr(intent.power, "_shutdown", lambda *a: pytest.fail("shutdown ran before confirmation"))
    intent.cancel_pending_confirmation()
    try:
        result = asyncio.run(intent.try_system_action(phrase, "openrouter"))
        assert result.success and intent.is_awaiting_confirmation()
        assert "yes or no" in result.message.lower()
        asyncio.run(intent.try_system_action("no", "openrouter"))
        assert not intent.is_awaiting_confirmation()
    finally:
        intent.cancel_pending_confirmation()


def test_saved_login_paraphrase_keeps_remote_restriction(monkeypatch):
    monkeypatch.setattr(intent.logins, "load", lambda: {"college": {}})
    monkeypatch.setattr(intent.logins, "log_in", lambda *a: pytest.fail("remote login was attempted"))
    token = intent.remote_request.set(True)
    try:
        result = asyncio.run(intent.try_system_action("use my saved login for College Portal", "openrouter"))
        assert not result.success and result.message == intent.REMOTE_REFUSAL
    finally:
        intent.remote_request.reset(token)


def test_saved_routine_name_is_preserved(monkeypatch):
    monkeypatch.setattr(intent.routines, "load", lambda: {"desk": ["mute"]})
    text = normalize_command(rephrase_command("execute my workflow Desk"))
    assert intent.routines.match_routine_command(text) == {
        "type": "system", "action": "run_routine", "routine": "desk",
    }


@pytest.mark.parametrize("phrase,query", [
    ("Could you please look up Python releases", "Python releases"),
    ("research online: USB-C DisplayPort Support", "USB-C DisplayPort Support"),
])
def test_web_search_phrases_keep_the_query(phrase, query):
    from services.search.web_search import extract_search_query
    assert extract_search_query(phrase) == query


def test_file_question_and_diary_payloads_keep_their_words():
    question = "What does My Report say about FPGA Timing?"
    text = "Don't rewrite my day, Please!"
    assert intent.files.extract_file_question("answer from my files: " + question) == question
    rewritten = rephrase_command("add a diary entry: " + text)
    assert intent.notes.match_note_command(rewritten)["text"] == text
