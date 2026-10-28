"""
services/automation/intent.py

Shared intent classification service for F.R.I.D.A.Y.
Used by both chat.py and voice.py to detect system commands.

FLOW:
  0. A yes/no reply to an action waiting for confirmation
  1. Literal shortcuts ("\\o chrome")
  2a. Typing: "type <exact words>", "write <something>" (the AI writes it),
      key presses (services/automation/typing_commands.py). The text itself is
      typed by the client that has the user's focus, from ActionResult.keyboard
  Then, with wake words and politeness stripped ("hey friday, can you… please"):
  1a. Notes and watches: "note buy a charger", "read my notes", "journal: …" (services/memory/notes.py);
      "read this", "talk faster" (services/voice/voice_commands.py); "make my clipboard
      uppercase", "paste as plain text" (services/automation/clipboard_transforms.py);
      "delete my installers" (services/files/installers.py); "limit valorant to 2 hours a day"
      (services/activity/limits.py); "battery health", "do I need to restart", "what's taking up
      space" (services/automation/system_health.py); "add this to my reading list"
      (services/memory/reading_list.py);
      "tell me when blender closes / it's charged / <url> changes", "what are you watching"
      (services/watch/asked.py)
  1b. Routines: "create a routine called work mode to …", "start work mode",
      "list my routines" (services/automation/routines.py). Running one sends
      each saved step back through this whole flow
  2. Reminders ("remind me at 5pm to …", "set a reminder…", "list reminders")
  2e. Briefing and nudges: "brief me", "pause nudges for an hour", "turn off nudges"
      (services/proactive/watcher.py)
  2c. Activity: "what have I been doing today", "clear my activity log"
      (services/activity/log.py — every command run is logged there too)
  2d. Memory: "remember that …", "forget that …", "what do you remember about me"
      (services/memory/semantic.py)
  2b. Your files: "find my resume", then "open 2" (services/files/assistant.py).
      Questions about the files ("what does my lease say…") never get here:
      chat.py/voice.py answer them with the AI and excerpts from the files
  3. Several commands in one message ("mute and open chrome") → validate and run locally;
     unfamiliar combinations can use step 6 when AI command routing is enabled
  4. Device matcher — close app, volume, brightness, mute, clipboard, screenshot
     (services/automation/device_commands.py)
  5. App matcher — open app/folder/website, Chrome/YouTube search, play music,
     organise (services/automation/app_commands.py)
  6. Unmatched language in assist-only mode: AI proposes canonical text, then
     the local router validates and executes it. Legacy mode uses native tools.

All the words the local matchers know are in services/automation/command_words.py.

Actions that change files (organise_folder) never run straight away: FRIDAY
asks first, and only an explicit "yes" as the very next message runs them.
"""

import asyncio
import contextvars
import re
import time
from datetime import datetime
from urllib.parse import quote
from typing import NamedTuple

from core.config import config
from core.errors import ProviderError
from core.logger import logger
from providers.registry import get_provider
from providers.base_provider import Message
from services.automation.command_tools import COMMAND_ROUTER_PROMPT, build_tools, tool_call_to_action
from services.automation.clipboard_history import clipboard_history
from services.automation import command_cache, command_words as words, routines
from services.automation import keyboard, logins, media_control as media, modes, whatsapp, writer
from services.automation.app_commands import (
    APP_STARTERS, URL_PATTERN, match_app_command, match_bare_url, match_media_command,
)
from services.automation.command_words import FOLDER_MAP, first_word, normalize_command
from services.automation import system_stats
from services.automation.typing_commands import match_typing_command
from services.automation.device_commands import DEVICE_STARTERS, match_device_command, match_stats_command
from services.automation.system_control import system, AutomationError, folder_display_name
from services.reminders.parser import is_reminder_request
from services.reminders.service import ReminderError, reminders
from services.spotify import auth as spotify_auth, player as spotify
from services.files import assistant as files
from services.memory.semantic import MEMORY_ACTIONS, match_memory_command, run_memory_command
from services.memory import notes
from services.voice import voice_commands
from services.automation import clipboard_transforms
from services.files import installers
from services.activity import limits
from services.automation import system_health
from services.memory import reading_list
from services.spotify import wrapped as spotify_wrapped
from services.activity import fun
from services.watch import asked as watches
from services.activity import ask as activity_ask, devtools, git_status, habits, insights, journal, predict, projects
from services.activity import study, weekly
from services.activity.log import activity_log, commands_run, foreground_app, match_activity_command
from services.automation import personality, power
from services.mind import brain, corrections, evening, foresight, life, reflection, talk, wording
from services.network.status import network
from services.proactive import attendance, college, deadlines, timetable
from services.telegram import client as telegram
from services.telegram import commands as telegram_commands
from services.mind import cognition_commands
from services.mind.cognition import cognition, mark_introspection
from services.proactive.watcher import PROACTIVE_ACTIONS, match_proactive_command, run_proactive_command
from services.automation.results import ActionResult  # noqa: F401 — others import it from here
from services.automation.actions import _run_action, _type  # noqa: F401 — the doing half (actions.py)

# ── Literal shortcuts — bypass keyword/AI guessing entirely ──────────────────
# "\o <target>" opens an app, folder, or URL directly — no ambiguity, no
# fuzzy keyword guessing. Same targets as the regular "open" keyword covers.
SHORTCUT_OPEN = "\\o"

# True for messages the Telegram bot passes in (services/telegram/bot.py): these can't read
# the clipboard or use saved logins, since the reply would leave the laptop
remote_request: contextvars.ContextVar[bool] = contextvars.ContextVar("remote_request", default=False)
# Set only inside the authenticated owner's Telegram turn; never persisted.
telegram_owner: contextvars.ContextVar[bool] = contextvars.ContextVar("telegram_owner", default=False)
skip_confirmation: contextvars.ContextVar[bool] = contextvars.ContextVar("skip_confirmation", default=False)
_language_proposal: contextvars.ContextVar[bool] = contextvars.ContextVar("language_proposal", default=False)
_language_source: contextvars.ContextVar[str | None] = contextvars.ContextVar("language_source", default=None)
NOT_OVER_TELEGRAM = {"read_clipboard", "list_clipboard_history", "restore_clipboard_item", "save_login", "log_in"}
REMOTE_REFUSAL = "I don't do that over Telegram — ask me at the laptop."
_UNLOCK_TELEGRAM = re.compile(r"^(?:unlock|turn on|enable)\s+(?:the\s+)?(?:telegram(?:\s+bot)?|remote control)$", re.I)

# "what time is it", "what's the date today", "what day is it" — answered from the PC clock, never the AI
# (models often insist they can't know the time, even with it in the system prompt)
_CLOCK_ITEM = r"(?:the |today's )?(?:current )?(?:time|date|day)"
_CLOCK = re.compile(
    rf"^(?:tell me |what(?:'s| is)? )?(?P<what>{_CLOCK_ITEM}"
    rf"(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*){_CLOCK_ITEM})*)"
    r"(?: is it| is today| is it today| today| now| right now)?$", re.I,
)


def clock_answer(text: str, now: datetime | None = None) -> str | None:
    """`text` has already been through normalize_command()."""
    match = _CLOCK.match(text)
    if not match:
        return None
    now = now or datetime.now()
    requested = set(re.findall(r"\b(time|date|day)\b", match["what"].lower()))
    if "time" in requested and requested & {"date", "day"}:
        return f"It's {now:%A, %B} {now.day}, {now.year} at {now:%I:%M %p}.".replace("at 0", "at ")
    if requested == {"time"}:
        return f"It's {now:%I:%M %p}.".replace("It's 0", "It's ")
    return f"It's {now:%A, %B} {now.day}, {now.year}."

# ── Confirmation for destructive actions ──────────────────────────────────────
CONFIRM_TIMEOUT_SECONDS = 120
AFFIRMATIVE_REPLIES = {
    "yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "proceed",
    "do it", "go ahead", "yes please", "yes do it", "yes go ahead",
}
NEGATIVE_REPLIES = {
    "no", "n", "nope", "nah", "cancel", "stop", "abort", "don't", "dont",
    "no thanks", "never mind", "nevermind", "don't do it",
}


class PendingAction(NamedTuple):
    parsed: dict
    expires_at: float
    asked_at: float = 0


# Laptop chat/voice share a conversation; Telegram has its own pending action.
_pending: dict[bool, PendingAction] = {}


def cancel_pending_confirmation() -> None:
    """Drop this conversation's action waiting for a yes/no."""
    _pending.pop(remote_request.get(), None)


def is_awaiting_confirmation() -> bool:
    """True while this conversation is waiting for the user's yes/no."""
    return remote_request.get() in _pending


async def _handle_pending_reply(message: str, provider_name: str) -> ActionResult | None:
    """
    Treat this conversation's next message as the pending action's answer.
    Consume it before execution, so another reply cannot run the action twice.
    """
    pending = _pending.pop(remote_request.get(), None)
    if pending is None:
        return None

    if pending.parsed.get("action") == "resume_project":
        message = normalize_command(message)

    reply = " ".join(re.findall(r"[a-z']+", message.lower().replace("’", "'")))
    is_yes, is_no = reply in AFFIRMATIVE_REPLIES, reply in NEGATIVE_REPLIES
    if not (is_yes or is_no):
        logger.info("Pending confirmation dropped — user moved on")
        return None

    if time.monotonic() > pending.expires_at:
        return ActionResult(
            False,
            "That request timed out, so I didn't do anything. Ask again if you still want it.",
        )
    if is_no:
        logger.info(f"User cancelled pending action: {pending.parsed.get('action')}")
        return ActionResult(True, "Okay, cancelled. Nothing was changed.")

    logger.info(f"User confirmed pending action: {pending.parsed.get('action')}")
    if pending.parsed.get("action") == "resume_project":
        return await _resume_project(pending.parsed["name"], provider_name,
                                     expected=pending.parsed.get('_project_snapshot', ...))
    if pending.parsed.get("action") == "phone_reply":
        return await asyncio.to_thread(_execute, pending.parsed, True)
    return _execute(pending.parsed, confirmed=True)


def _ask_to_organise(parsed: dict) -> ActionResult:
    path = parsed["path"]
    folder = folder_display_name(path)
    count = system.count_files_to_organise(path)
    if count == 0:
        return ActionResult(True, f"There's nothing to organise in {folder}.")

    _pending[remote_request.get()] = PendingAction(parsed, time.monotonic() + CONFIRM_TIMEOUT_SECONDS, time.time())
    files = "file" if count == 1 else "files"
    return ActionResult(
        True,
        f'Organise {folder}? This moves {count} {files} into subfolders. '
        'Reply "yes" to go ahead or "no" to cancel.',
    )


def _ask_first(parsed: dict, question: str) -> ActionResult:
    """Hold the action until the user's yes (see _handle_pending_reply)."""
    if parsed.get('action') == 'resume_project':
        import copy
        from services import settings_store
        with settings_store.lock:
            parsed = {**parsed, '_project_snapshot': copy.deepcopy(projects.load().get(parsed['name']))}
    _pending[remote_request.get()] = PendingAction(parsed, time.monotonic() + CONFIRM_TIMEOUT_SECONDS, time.time())
    return ActionResult(True, question, repeatable=False)


def _match_reminder_command(message: str) -> dict | None:
    """Reminder commands. `message` has already been through normalize_command()."""
    set_reminder = words.SET_REMINDER.match(message.lower())
    if set_reminder:
        # "set a reminder for 5pm to X" → "remind me at 5pm to X"
        rest = message[set_reminder.end():]
        at = "at " if set_reminder.group().endswith("for ") and rest[:1].isdigit() else ""
        message = f"remind me {at}{rest}"
    if is_reminder_request(message):
        return {"type": "system", "action": "set_reminder", "message": message.strip()}

    msg = message.strip().lower()
    tokens = set(re.findall(r"[a-z]+", msg))
    if not tokens & {"reminder", "reminders"}:
        return None

    if words.REMINDER_LIST_PHRASES.match(msg):
        return {"type": "system", "action": "list_reminders"}
    if first_word(msg) in words.REMINDER_CANCEL_STARTERS:
        if first_word(msg) == "clear" or tokens & {"all", "every", "everything"}:
            return {"type": "system", "action": "cancel_all_reminders"}
        number = re.search(r"\b(\d+)\b", msg)
        if number:
            return {"type": "system", "action": "cancel_reminder", "number": int(number.group(1))}
    return None


def _try_shortcut(message: str) -> dict | None:
    """
    Literal command shortcuts (e.g. "\\o whatsapp", "\\o downloads",
    "\\o youtube.com"). Checked before anything else — deterministic,
    no keyword guessing.
    """
    stripped = message.strip()
    lowered = stripped.lower()

    if lowered.startswith(SHORTCUT_OPEN + " "):
        target = stripped[len(SHORTCUT_OPEN):].strip()
        if not target:
            return None
        target_lower = target.lower()

        # Registered app? (exact name or a known app name mentioned in the target)
        for app_name in system.list_apps():
            if app_name == target_lower or app_name in target_lower:
                return {"type": "system", "action": "open_app", "app_name": app_name}

        # A known folder?
        for folder_name, folder_path in FOLDER_MAP.items():
            if folder_name in target_lower:
                return {"type": "system", "action": "open_folder", "path": folder_path}

        # A URL?
        url_match = URL_PATTERN.search(target_lower)
        if url_match:
            return {"type": "system", "action": "open_url", "url": url_match.group()}

        # Nothing matched — treat it as an app name anyway so the user gets
        # a helpful "I don't know how to open X" with the full app list.
        return {"type": "system", "action": "open_app", "app_name": target}

    return None


def _execute(parsed: dict, confirmed: bool = False) -> ActionResult | None:
    """Run a parsed intent (see _run_action) and log it for FRIDAY to learn habits from."""
    if _language_source.get() and not _close_target_was_named(parsed, _language_source.get()):
        return ActionResult(False, "Which app do you want me to close, Boss?")
    intention = cognition.record('action_intent', 'system', str(parsed.get('action', 'system action')),
                                 status='started', public=True)
    try:
        result = _run_action(parsed, confirmed or (telegram_owner.get() and skip_confirmation.get()))
    except BaseException:
        cognition.finish(intention, 'failed')
        raise
    cognition.finish(intention, 'awaiting_confirmation' if is_awaiting_confirmation() else
                     'completed' if result and result.success else 'failed' if result else 'unsupported')
    if result is not None:
        cognition.record("action", "system", str(parsed.get("action", "system action")),
                         status="awaiting_confirmation" if is_awaiting_confirmation() else
                         "completed" if result.success else "failed", public=True)
    if result is not None and not is_awaiting_confirmation():  # "are you sure?" isn't done yet
        activity_log.log_command({"action": parsed["action"]} if parsed.get("action", "").startswith("phone_")
                                 else parsed, result.success)
    return result


async def try_system_action(message: str, provider_name: str) -> ActionResult | None:
    """
    Try to interpret a message as a system command.
    Returns an ActionResult if it was a system command, None otherwise.
    The reply may get one of FRIDAY's quips (personality.py) — once, not for each step of a routine.
    """
    if commands_run.get() is not None:  # a routine / mode step inside a request: seasoned at the top
        return await _try_system_action(message, provider_name)
    from services.phone import commands as phone_commands
    if phone_commands.private_turn(message):
        return await phone_commands.handle(message, provider_name)
    from services.screen_watch import commands as screen_commands
    if seen := await screen_commands.handle(message, remote=remote_request.get()):
        return seen
    from services.mind import app_verification
    if aware := await app_verification.handle(message, activity_log, remote=remote_request.get()):
        app_verification.mark_returned(aware.message, remote=remote_request.get())
        return aware
    token = commands_run.set([])
    try:
        cognition.record('intent', 'telegram' if remote_request.get() else 'system',
                         'Interpreting an owner request with current local controls.', public=False)
        from services.mind import project_session_context, conversation_context
        brief_turn = await asyncio.to_thread(conversation_context.observe, message, remote=remote_request.get())
        if brief_turn:
            if reference_answer := await conversation_context.try_handle(message, remote=remote_request.get()):
                return reference_answer
            if brief_answer := await asyncio.to_thread(project_session_context.try_answer, message, remote=remote_request.get()):
                return brief_answer
        result = await _try_correction(message, provider_name) or await _try_system_action(message, provider_name)
        corrections.note(message, bool(result and result.success and commands_run.get()))
        return personality.season(result, commands_run.get())
    finally:
        commands_run.reset(token)


async def _try_correction(message: str, provider_name: str) -> ActionResult | None:
    """"No, I meant X" right after a miss: do X, and remember that the missed message means it (services/mind/corrections.py)."""
    found = corrections.correction(message)
    if not found:
        return None
    missed, meant = found
    result = await _try_system_action(meant, provider_name)
    if result is None:  # X isn't a command either: let the message go on as usual
        return None
    if result.success and corrections.learn(missed, meant, [parsed for parsed, ok in commands_run.get() if ok]):
        result = result._replace(message=f"{result.message} Noted — next time \"{missed}\" means that.")
    return result


async def _try_system_action(message: str, provider_name: str, *, _allow_typo: bool = True) -> ActionResult | None:
    pending_reply = await _handle_pending_reply(message, provider_name)
    if pending_reply is not None:
        return pending_reply

    taught = corrections.lookup(message)  # the Boss corrected this one before ("no, I meant …")
    if taught and (result := _execute_all(taught)) is not None:
        return result

    shortcut = _try_shortcut(message)
    if shortcut:
        logger.info(f"Shortcut match: {shortcut['action']}")
        return _execute(shortcut)

    message = words.rephrase_command(message)
    from services.spotify.dj import match_command as match_dj
    if dj_command := match_dj(message):
        return await asyncio.to_thread(_execute, dj_command)
    # Preserve short stop controls before normalization drops filler such as "now".
    control = talk.match_talk_command(words.strip_leading_filler(message))
    if control and control['action'] in {'talk_off', 'talk_pause'}:
        return _execute(control)
    plan = _local_multi_plan(message)
    if plan is not None:
        if not plan:
            if config.AI_ASSIST_ONLY and config.AI_LANGUAGE_ENABLED and not _language_proposal.get():
                return await _understand_command(message, provider_name)
            return ActionResult(False, 'I could not recognise every step, Boss. Try each command separately.')
        logger.info("Running %s locally recognized command steps", len(plan))
        if _language_source.get() and any(isinstance(step, dict) and
                not _close_target_was_named(step, _language_source.get()) for step in plan):
            return ActionResult(False, "Which app do you want me to close, Boss?")
        return await _run_multi_plan(plan)

    typing_match = match_typing_command(message)
    if typing_match:
        if config.AI_ASSIST_ONLY and typing_match["action"] == "write_text":
            return ActionResult(False, 'Give me the exact text, Boss: "type <text>". Drafting new content is disabled.')
        logger.info(f"Typing command match: {typing_match['action']}")
        return _execute_all(await writer.resolve_writing([typing_match], provider_name))

    from services.mind import workspace_commands
    from services.mind import reasoning_commands
    from services.mind import execution_commands
    if execution_command := execution_commands.match_command(message):
        return await asyncio.to_thread(execution_commands.run, execution_command, remote=remote_request.get())
    if reasoning_command := reasoning_commands.match_command(message):
        return await reasoning_commands.run(reasoning_command)
    if workspace_command := workspace_commands.match_command(message):
        return await asyncio.to_thread(workspace_commands.run, workspace_command, remote=remote_request.get())

    text = normalize_command(message)

    from services.memory import schedule
    if saved_schedule := await asyncio.to_thread(schedule.capture, text):
        from services.mind import reasoning
        await reasoning.analyze(message, provider_name)
        return ActionResult(True, saved_schedule, repeatable=False)

    if cognition_command := cognition_commands.match_command(text):
        mark_introspection()  # set in this task; thread ContextVar changes don't flow back
        return await asyncio.to_thread(cognition_commands.run, cognition_command, remote=remote_request.get())

    if telegram_result := await telegram_commands.try_handle(message):
        return telegram_result

    from services.learning import reports as learning_reports
    if learning_result := await learning_reports.try_handle(text):
        return learning_result

    clock = clock_answer(text)
    if clock:
        return ActionResult(True, clock, repeatable=False)

    if _UNLOCK_TELEGRAM.match(text):  # "/lockdown" from Telegram is undone only here, at the laptop
        if remote_request.get():
            return ActionResult(False, "Remote control can only be unlocked at the laptop.")
        telegram.set_locked(False)
        return ActionResult(True, "Telegram remote control is back on.")

    note_match = notes.match_note_command(words.strip_leading_filler(message)) or notes.match_note_command(text)
    if note_match:
        logger.info(f"Note command match: {note_match['action']}")  # never the note itself
        return await asyncio.to_thread(_execute, note_match)

    voice_match = voice_commands.match_voice_command(text)
    if voice_match:
        logger.info(f"Voice command match: {voice_match['action']}")
        if voice_match["action"] == "read_aloud" and remote_request.get():
            return ActionResult(False, "Reading aloud only works at the laptop.")
        return await asyncio.to_thread(_execute, voice_match)  # "read this" waits for the copy

    transform_match = clipboard_transforms.match_clipboard_transform(text)
    if transform_match:
        logger.info(f"Clipboard transform match: {transform_match['kind']}")
        return _execute(transform_match)

    installer_match = installers.match_installer_command(text)
    if installer_match:
        logger.info(f"Installer command match: {installer_match['action']}")
        return await asyncio.to_thread(_execute, installer_match)  # looks through Downloads

    fun_match = fun.match_fun_command(text)
    if fun_match:
        logger.info(f"Fun command match: {fun_match['action']}")
        return await asyncio.to_thread(_execute, fun_match)  # reads the activity log

    wrapped_match = spotify_wrapped.match_wrapped_command(text)
    if wrapped_match:
        logger.info(f"Spotify wrapped match: {wrapped_match['span']}")
        return await asyncio.to_thread(_execute, wrapped_match)  # asks Spotify

    reading_match = reading_list.match_reading_command(text, message)
    if reading_match:
        logger.info(f"Reading list match: {reading_match['action']}")
        return await asyncio.to_thread(_execute, reading_match)  # "add this" reads the browser history

    health_match = system_health.match_health_command(text)
    if health_match:
        logger.info(f"System health match: {health_match['action']}")
        return await asyncio.to_thread(_execute, health_match)  # powercfg / Everything take a moment

    limit_match = limits.match_limit_command(text)
    if limit_match:
        logger.info(f"App limit command match: {limit_match['action']}")
        return _execute(limit_match)

    try:
        deadline_match = deadlines.match_deadline_command(text)
    except AutomationError as e:  # "add deadline X due <something unreadable>"
        return ActionResult(False, str(e))
    if deadline_match:
        logger.info(f"Deadline command match: {deadline_match['action']}")
        return await asyncio.to_thread(_execute, deadline_match)

    watch_match = watches.match_watch_command(words.strip_leading_filler(message)) or watches.match_watch_command(text)
    if watch_match:
        logger.info(f"Watch command match: {watch_match['action']}")
        return await asyncio.to_thread(_execute, watch_match)  # a web watch loads the page once

    routine_match = routines.match_routine_command(words.strip_leading_filler(message))
    if routine_match:
        logger.info(f"Routine command match: {routine_match['action']}")
        if routine_match["action"] == "run_routine":
            return await _run_routine(routine_match["routine"], provider_name)
        return _execute(routine_match)

    mode_match = modes.match_mode_command(text)
    if mode_match:
        logger.info(f"Mode command match: {mode_match['action']}")
        if mode_match["action"] == "start_mode":
            return await _start_mode(mode_match["mode"], provider_name, mode_match["subject"])
        if mode_match["action"] == "end_mode":
            return await asyncio.to_thread(_end_mode, mode_match["mode"])
        return _execute(mode_match)

    personality_match = personality.match_personality_command(text)
    if personality_match:
        logger.info(f"Personality command match: {personality_match['action']}")
        if personality_match["action"] == "roast_me":
            return ActionResult(True, await personality.roast_me(provider_name, week=personality_match["week"]),
                                repeatable=False)
        return _execute(personality_match)

    power_match = power.match_power_command(text)  # before app commands: "shut down" alone is the laptop
    if power_match:
        logger.info(f"Power command match: {power_match['action']}")
        return _execute(power_match)

    insight_match = insights.match_insight_command(text)
    if insight_match:
        logger.info(f"Insight command match: {insight_match['action']}")
        return await asyncio.to_thread(_execute, insight_match)  # reads weeks of activity

    dev_match = devtools.match_dev_command(text)
    if dev_match:
        logger.info(f"Dev command match: {dev_match['action']}")
        return await asyncio.to_thread(_execute, dev_match)  # lists ports / runs gh or npm

    college_match = college.match_college_command(text)
    if college_match:
        logger.info(f"College command match: {college_match['action']}")
        if college_match["action"] == "revision_pack":
            return await asyncio.to_thread(_execute, college_match)  # reads the activity log and files
        return _execute(college_match)

    habit_match = habits.match_habit_command(text)  # before projects: "resume habit suggestions" isn't a project
    if habit_match:
        logger.info(f"Habit command match: {habit_match['action']}")
        return await asyncio.to_thread(_execute, habit_match)  # reads two weeks of activity

    project_match = projects.match_project_command(text)
    if project_match:
        logger.info(f"Project command match: {project_match['action']}")
        if project_match["action"] == "suggest_resume_project":
            name = project_match["name"]
            if telegram_owner.get() and skip_confirmation.get():
                return await _resume_project(name, provider_name)
            return _ask_first(
                {"type": "system", "action": "resume_project", "name": name},
                f"Do you want me to resume {name}? Say yes to open the project, or no to cancel.",
            )
        if project_match["action"] == "resume_project":
            return await _resume_project(project_match["name"], provider_name)
        return await asyncio.to_thread(_execute, project_match)  # may look up folders (Everything)

    attendance_match = attendance.match_attendance_command(text)
    if attendance_match:
        logger.info(f"Attendance command match: {attendance_match['action']}")
        return _execute(attendance_match)

    timetable_match = timetable.match_timetable_command(text)
    if timetable_match:
        logger.info(f"Timetable command match: {timetable_match['action']}")
        if timetable_match["action"] == "import_timetable":
            if config.AI_ASSIST_ONLY:
                return ActionResult(False, 'Image timetable import needs AI interpretation. Add classes with "add class <subject> on <day> at <time>" instead.')
            try:
                return ActionResult(True, await timetable.import_timetable(
                    timetable_match["source"], provider_name, timetable_match["section"]), repeatable=False)
            except (AutomationError, ProviderError) as e:
                return ActionResult(False, str(e))
        return _execute(timetable_match)

    journal_match = journal.match_journal_command(text)
    if journal_match:
        logger.info(f"Journal command match: {journal_match['action']}")
        return await asyncio.to_thread(_execute, journal_match)  # reads the day's activity and git logs

    weekly_match = weekly.match_weekly_command(text)
    if weekly_match:
        logger.info(f"Weekly summary command match: {weekly_match['action']}")
        return await asyncio.to_thread(_execute, weekly_match)  # reads the week's activity and git logs

    study_match = study.match_study_command(text)
    if study_match:
        logger.info(f"Study hours command match: {study_match['subject'] or 'all subjects'}")
        return await asyncio.to_thread(_execute, study_match)  # reads the activity log

    git_match = git_status.match_git_command(text)
    if git_match:
        logger.info(f"Git command match: {git_match['action']}")
        if git_match["action"] == "commit_message":
            try:
                return ActionResult(True, await git_status.commit_message(git_match["name"]), repeatable=False)
            except AutomationError as e:
                return ActionResult(False, str(e))
        return await asyncio.to_thread(_execute, git_match)  # runs git

    reminder_match = _match_reminder_command(words.strip_leading_filler(message)) or _match_reminder_command(text)
    if reminder_match:
        logger.info(f"Reminder command match: {reminder_match['action']}")
        return _execute(reminder_match)

    login_match = logins.match_login_command(text)
    if login_match:
        logger.info(f"Login command match: {login_match['action']}")  # never the password: it isn't in the message
        if login_match["action"] in NOT_OVER_TELEGRAM and remote_request.get():
            return ActionResult(False, REMOTE_REFUSAL)
        try:
            if login_match["action"] == "save_login":  # a small window asks for the password, privately
                return ActionResult(True, await asyncio.to_thread(logins.ask_and_save, login_match["name"]), repeatable=False)
            if login_match["action"] == "log_in":
                message_ = await asyncio.to_thread(logins.log_in, login_match["name"], system.open_url)
                activity_log.log_command({"action": "log_in", "url": logins.load()[login_match["name"]]["url"]}, True)
                return ActionResult(True, message_, repeatable=False)
        except AutomationError as e:
            return ActionResult(False, str(e))
        return _execute(login_match)

    whatsapp_match = whatsapp.match_whatsapp_command(text, message)
    if whatsapp_match:
        logger.info(f"WhatsApp command match: {whatsapp_match['action']}")
        return await asyncio.to_thread(_execute, whatsapp_match)  # sending waits for WhatsApp to open

    proactive_match = match_proactive_command(text)
    if proactive_match:
        logger.info(f"Briefing/nudge command match: {proactive_match['action']}")
        return await asyncio.to_thread(_execute, proactive_match)  # the briefing reads the weather

    talk_match = talk.match_talk_command(text)
    if talk_match and talk_match["action"] == "talk_ask":  # "ask me something": she asks from her list
        return ActionResult(True, await talk.ask_now(activity_log, datetime.now()), repeatable=False)
    if talk_match:
        return _execute(talk_match)

    mind_match = reflection.match_mind_command(text)
    if mind_match:
        return _execute(mind_match)

    if life.match_life_command(text):  # "how are you feeling": her mood and her day, worded like anything she says
        now = datetime.now()
        return ActionResult(True, await wording.say(life.feeling(now, brain.away_minutes(now))), repeatable=False)
    if evening_command := evening.match_evening_command(text):
        first = await evening.start(activity_log, datetime.now(), extended=evening_command.get("extended", False))
        return ActionResult(True, first or "I don't have a useful new question right now, Boss. You can inspect brain status for the reason.", repeatable=False)
    foresight_match = foresight.match_foresight_command(text)
    if foresight_match:
        return _execute(foresight_match)
    brain_match = brain.match_brain_command(text)
    if brain_match:
        return await asyncio.to_thread(_execute, brain_match)  # reads the day back from the activity log

    predict_match = predict.match_predict_command(text)
    if predict_match:
        logger.info(f"Prediction command match: {predict_match['action']}")
        return await asyncio.to_thread(_execute, predict_match)  # replays the activity log

    activity_match = match_activity_command(text) or activity_ask.match_activity_question(text)
    if activity_match:
        logger.info(f"Activity command match: {activity_match['action']}")
        return _execute(activity_match)

    memory_match = match_memory_command(text)
    if memory_match:
        logger.info(f"Memory command match: {memory_match['action']}")
        result = await asyncio.to_thread(_execute, memory_match)
        if result and result.success and memory_match["action"] == "remember":
            from services.mind import reasoning
            await reasoning.analyze(message, provider_name)
        return result

    file_match = files.match_file_command(message)
    if file_match:
        logger.info(f"File command match: {file_match['action']}")
        return await asyncio.to_thread(_execute, file_match)  # searching takes a moment

    # Named media owns ambiguous conjunctions in its title. Explicit batches
    # were already validated above, before any single-command handler ran.
    media_match = match_media_command(message, media.has_player)
    if media_match:
        logger.info(f"Music command match: {media_match['action']}")
        return _remember(message, await asyncio.to_thread(_execute, media_match), media_match)

    if words.is_multi_step(text):
        if config.AI_ASSIST_ONLY:
            if config.AI_LANGUAGE_ENABLED and not _language_proposal.get():
                return await _understand_command(message, provider_name)
            return ActionResult(False, 'I could not recognise every step, Boss. Try each command separately.')
        logger.info("Several commands in one message — asking the AI which tools to call")
        return await _run_ai_tools(message, provider_name)

    stats_match = match_stats_command(text)
    if stats_match:
        logger.info(f"System stats match: {stats_match.get('part', 'everything')}")
        return await asyncio.to_thread(_execute, stats_match)  # sampling takes a moment

    first = first_word(text)

    if first in DEVICE_STARTERS:
        device_match = match_device_command(text)
        if device_match:
            logger.info(f"Device command match: {device_match['action']}")
            return _remember(message, _execute(device_match), device_match)

    local_match = (match_app_command(text) if first in APP_STARTERS else None) or match_bare_url(text)
    if local_match:
        local_match = _preserve_search_query(local_match, words.strip_leading_filler(message))
        logger.info(f"Local command match: {local_match['action']}")
        return _remember(message, _execute(local_match), local_match)

    if _allow_typo:
        if candidate := _correct_local_typo(message):
            return await _try_system_action(candidate, provider_name, _allow_typo=False)

    # Natural language need not begin with a known command verb.
    if config.AI_ASSIST_ONLY and config.AI_LANGUAGE_ENABLED and not _language_proposal.get():
        return await _understand_command(message, provider_name)
    if _language_proposal.get():
        return None
    # The legacy native-tool classifier keeps its command-starter/cache heuristic.
    if first not in words.AI_COMMAND_STARTERS:
        same = await asyncio.to_thread(command_cache.similar, message, _cache_fp(), False)
        return await asyncio.to_thread(_execute_all, same) if same else None

    if config.AI_ASSIST_ONLY:
        return None
    logger.info("No local match — asking the AI which tools to call")
    return await _run_ai_tools(message, provider_name)


class _WorkspaceStep(NamedTuple):
    parsed: dict


async def _understand_command(message: str, provider_name: str) -> ActionResult | None:
    """Translate once, then pass the proposal through every existing local guard."""
    from services.mind.language import understand

    command = await understand(message, provider_name)
    if not command:
        return None
    if normalize_command(command) in AFFIRMATIVE_REPLIES | NEGATIVE_REPLIES:
        return ActionResult(False, "Please confirm or cancel the original request yourself, Boss.")
    # A language model cannot name additional apps to close.
    parsed = _match_local_step(command)
    if isinstance(parsed, dict) and not _close_target_was_named(parsed, message):
        return ActionResult(False, "Which app do you want me to close, Boss?")
    token = _language_proposal.set(True)
    source_token = _language_source.set(message)
    try:
        result = await _try_system_action(command, provider_name)
    finally:
        _language_source.reset(source_token)
        _language_proposal.reset(token)
    return result or ActionResult(False, "I couldn't map that request to a supported command, Boss. "
                                  "Tell me the app or task you want me to work on.")


def _match_local_deadline(text: str) -> dict | None:
    try:
        return deadlines.match_deadline_command(text)
    except AutomationError:
        return None  # The dedicated route reports invalid dates for single requests.


def _match_local_step(message: str) -> dict | _WorkspaceStep | None:
    """Parse direct native actions without executing, learning or asking a model.

    Async orchestration (running modes/projects/routines, login entry and image
    import) stays with its dedicated single-command route.
    """
    from services.mind import workspace_commands

    raw = words.strip_leading_filler(message)
    if parsed := workspace_commands.match_command(raw):
        return _WorkspaceStep(parsed)
    text = normalize_command(raw)
    parsed = (match_typing_command(raw) or notes.match_note_command(raw) or notes.match_note_command(text)
              or _match_reminder_command(raw) or _match_reminder_command(text)
              or watches.match_watch_command(raw) or watches.match_watch_command(text)
              or voice_commands.match_voice_command(text)
              or system_health.match_health_command(text) or limits.match_limit_command(text)
              or _match_local_deadline(text)
              or reading_list.match_reading_command(text, raw)
              or power.match_power_command(text) or attendance.match_attendance_command(text)
              or timetable.match_timetable_command(text) or routines.match_routine_command(raw)
              or modes.match_mode_command(text) or projects.match_project_command(text)
              or whatsapp.match_whatsapp_command(text, raw)
              or logins.match_login_command(text) or files.match_file_command(raw)
              or journal.match_journal_command(text) or match_memory_command(text)
              or match_device_command(raw) or match_stats_command(text)
              or match_media_command(raw, media.has_player) or match_app_command(raw))
    if parsed and parsed["action"] in {
        "write_text", "run_routine", "start_mode", "end_mode", "resume_project", "suggest_resume_project",
        "import_timetable", "save_login", "log_in",
    }:
        return None
    return _preserve_search_query(parsed, raw)


def _preserve_search_query(parsed: dict | None, raw: str) -> dict | None:
    if parsed and parsed["action"] == "search_chrome":
        # The native app matcher normalizes the query. Keep its grammar while
        # taking the actual payload from the original request.
        from services.automation.app_commands import _SEARCH_PREFIX, _SEARCH_SUFFIX

        verbs = "|".join(map(re.escape, sorted(words.SEARCH_VERBS, key=len, reverse=True)))
        if prefix := re.match(rf"(?:{verbs})\s+", raw, re.I):
            query = raw[prefix.end():]
            if engine := _SEARCH_PREFIX.match(query.lower()):
                query = query[engine.end():]
            if engine := _SEARCH_SUFFIX.search(query.lower()):
                query = query[:engine.start()]
            parsed = {**parsed, "query": query.strip()}
    return parsed


def _correct_local_typo(message: str) -> str | None:
    from services.automation.command_typos import correct_command_typo

    if candidate := correct_command_typo(words.strip_leading_filler(message)):
        candidate = words.rephrase_command(candidate)
        if _match_local_step(candidate):
            return candidate
    return None


def _literal_local_step(message: str) -> dict | _WorkspaceStep | None:
    """An explicit free-text body consumes the remaining sentence as user data."""
    parsed = _match_local_step(message)
    if isinstance(parsed, _WorkspaceStep):
        if parsed.parsed["action"] in {"add_goal", "start_task", "plan", "step"} or parsed.parsed.get("note"):
            return parsed
    elif parsed and parsed["action"] in {
        "type_text", "add_note", "add_diary", "set_reminder", "search_chrome", "write_clipboard",
        "create_routine", "set_resume", "set_mode_steps", "watch_log", "send_whatsapp", "find_files",
        "search_journal", "remember",
    }:
        return parsed
    elif parsed and parsed["action"] in {"play_song", "play_collection", "queue_song"}:
        return None if _music_step_boundary(message) else parsed
    return None


def _music_step_boundary(text: str) -> re.Match | None:
    """Music titles own ambiguous 'and'; explicit then/semicolon separates actions."""
    quoted = [(m.start(), m.end()) for m in words._QUOTED_STEP_TEXT.finditer(text)]
    for found in re.finditer(r"\s*;\s*|\s+\b(?:and\s+then|then)\b\s+", text, re.I):
        if not any(left <= found.start() < right for left, right in quoted):
            return found
    return None


def _owns_routed_payload(text: str) -> bool:
    """Keep literal requests handled by dedicated asynchronous routes whole."""
    from services.mind import execution_commands, reasoning_commands

    typed = match_typing_command(text)
    memory = match_memory_command(text)
    return bool((typed and typed["action"] == "write_text")
                or telegram_commands._SEND.fullmatch(text) or telegram_commands._MESSAGE_AFTER.fullmatch(text)
                or execution_commands.match_command(text) or reasoning_commands.match_command(text)
                or (memory and memory["action"] in {"remember", "forget_memory"}))


def _local_multi_plan(text: str) -> list[dict | _WorkspaceStep | ActionResult] | None:
    """Recognize every step first; [] rejects partially recognized batches."""
    text = words.strip_leading_filler(text)
    if clock_answer(normalize_command(text)) or _owns_routed_payload(text) or _literal_local_step(text):
        return None
    parts = words.split_steps(text)
    if len(parts) < 2:
        return None
    located, search_from = [], 0
    for part in parts:
        start = text.find(part, search_from)
        located.append((part, start))
        search_from = start + len(part)
    plan, target_verb, cursor, unknown = [], "", 0, False
    now = datetime.now()
    for part, start in located:
        if start < cursor:
            continue
        cursor = start + len(part)
        tail = words.rephrase_command(text[start:])
        if literal := _literal_local_step(tail):
            return [] if unknown else plan + [literal]
        if boundary := _music_step_boundary(tail):
            music = match_media_command(tail[:boundary.start()], media.has_player)
            if music and music["action"] in {"play_song", "play_collection", "queue_song"}:
                plan.append(music)
                cursor = start + boundary.end()
                target_verb = ""
                continue
        part = words.rephrase_command(part)
        clock = clock_answer(normalize_command(part), now)
        if clock:
            plan.append(ActionResult(True, clock, repeatable=False))
            target_verb = ""
            continue
        action = _match_local_step(part)
        if not action and (candidate := _correct_local_typo(part)):
            # A corrected search/reminder can own conjunctions in its tail too.
            if corrected_tail := _correct_local_typo(tail):
                if literal := _literal_local_step(corrected_tail):
                    return [] if unknown else plan + [literal]
            action = _match_local_step(candidate)
        if not action and target_verb:
            expanded = f"{target_verb} {part}"
            action = match_device_command(expanded) or match_app_command(expanded)
        if not action:
            unknown = True
            target_verb = ""
            continue
        plan.append(action)
        # "open chrome and notepad": only opening/closing targets inherit the verb.
        if isinstance(action, dict) and action["action"] in {"open_app", "open_folder", "open_url", "close_app"}:
            target_verb = "close" if action["action"] == "close_app" else "open"
        else:
            target_verb = ""
    return ([] if unknown else plan) if plan else None


async def _run_multi_plan(plan: list[dict | _WorkspaceStep | ActionResult]) -> ActionResult:
    from services.mind import workspace_commands

    if remote_request.get():
        if any(isinstance(step, dict) and step["action"] in NOT_OVER_TELEGRAM | {"read_aloud"} for step in plan):
            return ActionResult(False, REMOTE_REFUSAL)
    results = []
    for index, step in enumerate(plan):
        if isinstance(step, _WorkspaceStep):
            result = await asyncio.to_thread(workspace_commands.run, step.parsed, remote=remote_request.get())
        else:
            result = step if isinstance(step, ActionResult) else await asyncio.to_thread(_execute, step)
        results.append(result or ActionResult(False, "I couldn't run that command."))
        if is_awaiting_confirmation():
            if index + 1 < len(plan):
                results.append(ActionResult(False, "The remaining commands were not run. Ask for them again after confirming."))
            break
    return _combine(results)


def _cache_fp() -> str:
    """What cached command decisions depend on: the tools and the router prompt (not the model)."""
    return command_cache.fingerprint(build_tools(system.list_apps(), list(FOLDER_MAP)), COMMAND_ROUTER_PROMPT)


def _remember(message: str, result: ActionResult | None, parsed: dict) -> ActionResult | None:
    """Save a command FRIDAY understood by itself, so its rephrasings hit the cache later."""
    if result is not None and result.success:
        command_cache.put(message, _cache_fp(), [parsed])
    return result


async def _run_ai_tools(message: str, provider_name: str) -> ActionResult | None:
    actions = await _classify_with_ai(message, provider_name)
    if not actions:
        return None
    return await asyncio.to_thread(_execute_all, await writer.resolve_writing(actions, provider_name))


# A routine's steps can't start another routine (no loops, no surprises)
_running_routine = False


async def _run_routine(name: str, provider_name: str) -> ActionResult:
    """Run each saved step through the normal command flow; one failed step doesn't stop the rest."""
    global _running_routine
    if _running_routine:
        return ActionResult(False, f"Skipped \"{name}\": a routine can't start another routine.")
    try:
        steps = routines.steps(name)
    except AutomationError as e:
        return ActionResult(False, str(e))
    if not steps:
        return ActionResult(False, f'The "{name}" routine has no steps yet.')

    _running_routine = True
    try:
        results = await _run_steps(steps, provider_name)
    finally:
        _running_routine = False

    combined = _combine(results)
    activity_log.log_command({"action": "run_routine", "routine": name}, combined.success)
    return combined._replace(message=f"{name[:1].upper()}{name[1:]}: {combined.message}", repeatable=False)


async def _run_steps(steps: list[str], provider_name: str) -> list[ActionResult]:
    """Each step through the normal command flow, in order; one failed step doesn't stop the rest."""
    results = []
    for step in steps:
        pause = routines.pause_seconds(step)
        if pause is not None:  # "wait 5 seconds": nothing to report
            await asyncio.sleep(pause)
            continue
        result = await try_system_action(step, provider_name)
        if is_awaiting_confirmation():  # a list of steps can't stop and wait for a yes
            cancel_pending_confirmation()
            result = ActionResult(False, f'Skipped "{step}": it needs a yes first, so ask me for it on its own.')
        results.append(result or ActionResult(False, f"I couldn't do \"{step}\"."))
    return results


_switching_mode = False  # a mode's steps can't start another mode (no loops)


async def _start_mode(name: str, provider_name: str, subject: str = "") -> ActionResult:
    from services.mind.outcome_learning import outcome_learning, verified_result
    expected = {'mode': name}
    job = await asyncio.to_thread(outcome_learning.begin, 'start_mode', expected)
    try:
        result = await _start_mode_impl(name, provider_name, subject)
        return await asyncio.to_thread(verified_result, job, 'start_mode', expected, result, _observed_mode)
    except BaseException as error:
        outcome_learning.finish(job, None, False if isinstance(error, Exception) else None)
        raise


def _observed_mode():
    state = modes.active(strict=True)
    return {'mode': state['name'] if state else 'normal'}


async def _start_mode_impl(name: str, provider_name: str, subject: str = "") -> ActionResult:
    """End the current mode (if any), then turn this one on ("… for DBMS": studying that) and run its steps."""
    global _switching_mode
    if _switching_mode:
        return ActionResult(False, "Skipped: a mode's steps can't start another mode.")
    current = modes.active()
    if current and current['name'] == name and (not subject or subject == current.get('subject')):
        return ActionResult(True, f"{name.title()} mode is already on.", repeatable=False)
    ended = await asyncio.to_thread(_end_mode, "") if current else None
    try:
        volume = await asyncio.to_thread(system.volume_level)
    except AutomationError:
        volume = None
    activity_log.flush()  # save the stretch so far first: the time before this doesn't count for the subject
    try:
        mode, steps = modes.begin(name, volume, subject)
    except AutomationError as e:
        return ActionResult(False, str(e))
    quiet = " — nudges will wait and I'll stay quiet until you end it" if mode["quiet"] else ""
    studying = f" for {modes.active()['subject']}" if subject else ""
    results = [ActionResult(True, f"{name.title()} mode on{studying}{quiet}.")] + ([ended] if ended else [])
    _switching_mode = True
    try:
        results += await _run_steps(steps, provider_name)
    finally:
        _switching_mode = False
    combined = _combine(results)
    if not combined.success:
        combined = combined._replace(message=f"{results[0].message} Some setup steps failed. " +
                                     " ".join(result.message for result in results[1:]))
    activity_log.log_command({"action": "start_mode", "routine": name}, combined.success)
    return combined._replace(repeatable=False)


def _end_mode(name: str) -> ActionResult:
    from services.mind.outcome_learning import outcome_learning, verified_result
    expected = {'mode': 'normal'}
    job = outcome_learning.begin('end_mode', expected)
    try:
        result = _end_mode_impl(name)
        return verified_result(job, 'end_mode', expected, result, _observed_mode)
    except BaseException as error:
        outcome_learning.finish(job, None, False if isinstance(error, Exception) else None)
        raise


def _end_mode_impl(name: str) -> ActionResult:
    """Turn the mode off: close the apps its steps opened and put the volume back."""
    state = modes.active()
    if not state:
        return ActionResult(True, "Normal mode is active; no mode is on.", repeatable=False)
    if name and name != state["name"]:
        return ActionResult(False, f"You're in {state['name']} mode, not {name} mode.")
    activity_log.flush()  # the stretch so far still counts for the mode's subject
    modes.finish()
    errors = []
    undone = []
    for app in state.get("opened", []):
        try:
            if system.close_app(app).startswith("Closing"):
                undone.append(f"closed {app}")
        except AutomationError as e:
            logger.info(f"Ending {state['name']} mode: couldn't close {app}: {e}")
            errors.append(f"could not close {app}")
    if state.get("volume") is not None:
        try:
            system.set_volume(state["volume"])
            undone.append(f"volume back to {state['volume']}%")
        except AutomationError:
            errors.append('previous volume could not be verified')
    minutes = round((time.time() - state["since"]) / 60) if state.get("since") else None
    activity_log.log_command({"action": "end_mode", "routine": state["name"], "minutes": minutes}, not errors)
    return ActionResult(not errors, f"{state['name'].title()} mode off" + (": " + ", ".join(undone) if undone else "") + "." +
                        (' Some cleanup steps failed: ' + '; '.join(errors) + '.' if errors else ''),
                        repeatable=False)


_resuming = False  # a resume step can't resume another project (no loops)


async def _resume_project(name: str, provider_name: str, *, expected=...) -> ActionResult:
    """Open the project (terminal, folder, sites — projects.py), then run its other resume steps as commands."""
    global _resuming
    if _resuming:
        return ActionResult(False, "Skipped: resuming a project can't resume another one.")
    from services.learning import origin
    origin.note_open()
    try:
        opened, steps = await asyncio.to_thread(projects.start_resume, name, activity_log,
                                                **({'expected': expected} if expected is not ... else {}))
    except AutomationError as e:
        return ActionResult(False, str(e))
    _resuming = True
    try:
        results = [ActionResult(True, opened), *await _run_steps(steps, provider_name)]
    finally:
        _resuming = False
    combined = _combine(results)
    activity_log.log_command({"action": "resume_project", "project": name or activity_log.last_project()},
                             combined.success)
    return combined._replace(repeatable=False)


def _execute_all(actions: list[dict]) -> ActionResult | None:
    """Run the actions in order and report them as one reply. None if none were valid."""
    results = [result for result in map(_execute, actions) if result is not None]
    return _combine(results) if results else None


def _combine(results: list[ActionResult]) -> ActionResult:
    if len(results) == 1:
        return results[0]
    private = any(r.memory_message for r in results)
    return ActionResult(
        all(r.success for r in results),
        " ".join(r.message for r in results),
        " ".join(r.memory_message or r.message for r in results) if private else None,
        all(r.repeatable for r in results),
        sum((r.keyboard for r in results), ()),
    )


def _classifier_attempts(chat_provider_name: str) -> list[tuple[str, str | None]]:
    """
    (provider, model) pairs to try in order: the cheap classifier model first,
    then the chat provider's own model as a fallback. None = provider's .env model.
    """
    if config.INTENT_PROVIDER:
        cheap = (config.INTENT_PROVIDER, config.INTENT_MODEL or None)
    else:
        cheap = (chat_provider_name, config.INTENT_DEFAULT_MODELS.get(chat_provider_name))
    fallbacks = [(name, config.INTENT_DEFAULT_MODELS.get(name)) for name in config.fallback_providers()]
    attempts = [cheap, (chat_provider_name, None), *fallbacks]
    if not network.online:  # offline: only the local model, API calls would just time out
        usable = network.usable([name for name, _ in attempts])
        attempts = [a for a in attempts if a[0] in usable] or [(name, None) for name in usable]
    return attempts


async def _classify_with_ai(message: str, chat_provider_name: str) -> list[dict] | None:
    """
    Ask the cheap model which tools, if any, the message calls for. If that model
    fails (error, or tools not supported), retry once on the chat model.
    Returns the actions to run in order; None means "treat as chat".
    Decisions are cached, so a message the AI has seen before is answered instantly.
    """
    if config.AI_ASSIST_ONLY:
        return None
    tools = build_tools(system.list_apps(), list(FOLDER_MAP))
    attempts = _classifier_attempts(chat_provider_name)
    cache_fp = _cache_fp()
    cached = command_cache.get(message, cache_fp)
    if cached is None:  # not this exact message: one that means the same? (loads the small model if needed)
        cached = await asyncio.to_thread(command_cache.similar, message, cache_fp)
    if cached is not None:
        logger.info(f"Command cache hit: {[a.get('action') for a in cached] or 'chat'}")
        return cached or None

    tried = set()
    for name, model in attempts:
        provider = get_provider(name, model=model)
        attempt = (name, provider.get_model_name())
        if attempt in tried:
            continue
        tried.add(attempt)

        try:
            result = await provider.complete(
                messages=[Message(role="user", content=message)],
                system_prompt=COMMAND_ROUTER_PROMPT,
                max_tokens=300,
                temperature=0.1,
                tools=tools,
            )
        except Exception as e:
            logger.warning(f"Intent classifier {name}/{attempt[1]} failed: {e}")
            continue

        # No tool call means the model decided it's chat — no need to ask again
        logger.info(f"Intent classifier {name}/{attempt[1]} called: {[c.name for c in result.tool_calls] or 'nothing'}")
        actions = [tool_call_to_action(call, FOLDER_MAP) for call in result.tool_calls]
        actions = [a for a in actions if _close_target_was_named(a, message)]
        command_cache.put(message, cache_fp, actions)
        return actions or None

    logger.warning("Intent classification failed on every model, treating as chat")
    return None


def _close_target_was_named(action: dict, message: str) -> bool:
    """Models sometimes add apps to close that the user never mentioned — never close those."""
    if action.get("action") != "close_app":
        return True
    app_name = str(action.get("app_name", "")).lower()
    if app_name and re.search(rf"\b{re.escape(app_name)}\b", message.lower()):
        return True
    logger.warning(f"Ignoring AI request to close '{app_name}' — the user didn't name it")
    return False
