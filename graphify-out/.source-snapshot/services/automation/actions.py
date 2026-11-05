"""
services/automation/actions.py

Runs a parsed command ({"type": "system", "action": …}): the one place each action name
is turned into what FRIDAY does. intent.py decides WHICH action a message is (local
matchers, the cache, the AI); this file does it. Split out of intent.py, which had grown
past 1000 lines. Confirmations (_ask_first) still live in intent.py.
"""

import asyncio
import contextvars
import re
import time
from datetime import datetime
from urllib.parse import quote

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
from services.mind import brain, foresight, reflection, talk
from services.activity import study, weekly
from services.activity.log import activity_log, commands_run, foreground_app, match_activity_command
from services.automation import personality, power
from services.network.status import network
from services.proactive import attendance, college, deadlines, timetable
from services.telegram import client as telegram
from services.proactive.watcher import PROACTIVE_ACTIONS, match_proactive_command, run_proactive_command


from services.automation.results import ActionResult


def _run_action(parsed: dict, confirmed: bool = False) -> ActionResult | None:
    """
    Execute a parsed intent dict.
    success=False means the action was recognised but failed (e.g. unknown
    app name). Returns None if the action isn't recognised or its arguments
    are missing/malformed (e.g. a bad AI classifier response).
    Destructive actions only run when confirmed=True; otherwise they ask first.
    """
    from services.automation import intent  # its confirmations (_ask_first …) — imported late: no cycle
    action = parsed.get("action", "unknown")
    logger.info(f"System action detected: {action}")
    if action in intent.NOT_OVER_TELEGRAM and intent.remote_request.get():
        return ActionResult(False, intent.REMOTE_REFUSAL)

    try:
        if action.startswith("phone_"):
            from services.phone.commands import run
            return run(parsed, confirmed)
        if action.startswith("dj_"):
            from services.spotify.dj import run
            success, message = run(parsed, _open_spotify)
            return ActionResult(success, message, repeatable=False)
        if action == "open_app":
            return ActionResult(True, system.open_app(parsed["app_name"]))
        elif action == "search_chrome":
            return ActionResult(True, system.search_chrome(parsed["query"]))
        elif action == "open_url":
            return ActionResult(True, system.open_url(parsed["url"]))
        elif action in power.POWER_ACTIONS:
            if action in power.ASK_FIRST and not confirmed:
                return intent._ask_first(parsed, power.question(parsed))
            return ActionResult(True, power.run(parsed), repeatable=False)
        elif action in insights.INSIGHT_ACTIONS:
            return ActionResult(True, insights.run(parsed, activity_log), repeatable=False)
        elif action == "stop_server":
            server = devtools.server_for(parsed)
            if not confirmed:
                where = f" ({server['where']})" if server["where"] else ""
                return intent._ask_first(parsed, f"Stop {server['program']} on port {server['port']}{where}? Say yes or no.")
            return ActionResult(True, devtools.stop_server(server), repeatable=False)
        elif action in devtools.DEV_ACTIONS:
            return ActionResult(True, {"port_info": lambda: devtools.port_info(parsed["port"]),
                                       "list_servers": devtools.list_servers,
                                       "ci_status": lambda: devtools.ci_status(parsed["name"]),
                                       "outdated": lambda: devtools.outdated(parsed["name"])}[action](), repeatable=False)
        elif action == "open_folder":
            return ActionResult(True, system.open_folder(parsed["path"]))
        elif action == "organise_folder":
            if not confirmed:
                return intent._ask_to_organise(parsed)
            return ActionResult(True, system.organise_folder(parsed["path"]))
        elif action == "send_whatsapp":
            if not confirmed:  # never send without a yes
                return intent._ask_first(parsed, whatsapp.confirmation(parsed))
            return ActionResult(True, whatsapp.send(parsed, foreground_app), repeatable=False)
        elif action in whatsapp.WHATSAPP_ACTIONS:
            return ActionResult(True, whatsapp.run_contacts(parsed), repeatable=False)
        elif action == "close_app":
            return ActionResult(True, system.close_app(parsed["app_name"]))
        elif action == "set_volume":
            return ActionResult(True, system.set_volume(int(parsed["level"])))
        elif action == "change_volume":
            return ActionResult(True, system.change_volume(int(parsed["delta"])))
        elif action == "set_mute":
            return ActionResult(True, system.set_mute(str(parsed["mute"]).lower() == "true"))
        elif action == "set_brightness":
            return ActionResult(True, system.set_brightness(int(parsed["level"])))
        elif action == "change_brightness":
            return ActionResult(True, system.change_brightness(int(parsed["delta"])))
        # Clipboards often hold passwords/tokens, and chat history is resent to the
        # cloud provider on later turns — so replies showing clipboard text aren't stored.
        elif action == "read_clipboard":
            return ActionResult(
                True, system.read_clipboard(), "(Showed the clipboard contents — not saved to memory.)"
            )
        elif action == "list_clipboard_history":
            return ActionResult(
                True, clipboard_history.list_message(), "(Showed clipboard history — not saved to memory.)"
            )
        elif action == "restore_clipboard_item":
            return ActionResult(
                True,
                clipboard_history.restore(int(parsed["number"])),
                "(Copied an earlier clipboard item back — not saved to memory.)",
            )
        elif action == "clear_clipboard_history":
            return ActionResult(True, clipboard_history.clear())
        elif action == "write_clipboard":
            return ActionResult(True, system.write_clipboard(str(parsed["text"])))
        elif action == "take_screenshot":
            return ActionResult(True, system.take_screenshot())
        elif action in ("media_play", "play_music"):
            # With no player open, "play" starts Spotify rather than failing
            return ActionResult(True, media.play_music(lambda: system.open_app("spotify")), repeatable=False)
        elif action == "media_pause":
            return ActionResult(True, media.pause(), repeatable=False)
        elif action == "media_next":
            return ActionResult(True, media.next_track(), repeatable=False)
        elif action == "media_previous":
            return ActionResult(True, media.previous_track(), repeatable=False)
        elif action == "now_playing":
            return ActionResult(True, media.now_playing(), repeatable=False)
        elif action in ("type_text", "type_written"):
            return _type(parsed)
        elif action == "press_keys":
            keys, times = str(parsed["keys"]), int(parsed.get("times", 1))
            if keyboard.parse_keys(keys) is None:
                return ActionResult(False, f"I don't know the key \"{keys}\".")
            label = keyboard.describe_keys(keys) + (f" {times} times" if times > 1 else "")
            return ActionResult(True, f"Pressing {label}.", keyboard=({"keys": keys, "times": times},))
        elif action == "system_stats":
            report = system_stats.report(parsed.get("part"), top=bool(parsed.get("top")))
            return ActionResult(True, report, repeatable=False)
        elif action == "play_song":
            return ActionResult(True, _play_song(str(parsed["query"])), repeatable=False)
        elif action == "play_collection":
            return ActionResult(True, _play_collection(parsed), repeatable=False)
        elif action == "play_liked":
            return ActionResult(True, spotify.play_liked(_open_spotify, bool(parsed.get("shuffle"))), repeatable=False)
        elif action == "set_shuffle":
            return ActionResult(True, spotify.set_shuffle(_flag(parsed["on"])))
        elif action == "set_repeat":
            return ActionResult(True, spotify.set_repeat(str(parsed["mode"])))
        elif action == "queue_song":
            return ActionResult(True, spotify.add_to_queue(str(parsed["query"])), repeatable=False)
        elif action == "like_song":
            return ActionResult(True, spotify.like_current(_flag(parsed.get("like", True))), repeatable=False)
        elif action == "find_files":
            return ActionResult(True, files.find_reply(str(parsed["query"])), repeatable=False)
        elif action == "open_found_file":
            return ActionResult(True, files.open_result(int(parsed["number"]), parsed.get("context_token")), repeatable=False)
        elif action == "reveal_found_file":
            return ActionResult(True, files.reveal_result(int(parsed["number"]), parsed.get("context_token")), repeatable=False)
        elif action == "select_found_file":
            return ActionResult(True, files.select_result(int(parsed["number"]), parsed.get("context_token")), repeatable=False)
        elif action == "rescan_files":
            return ActionResult(True, files.rescan())
        elif action == "connect_spotify":
            return ActionResult(True, spotify.connect())
        elif action == "disconnect_spotify":
            return ActionResult(True, spotify.disconnect())
        elif action in routines.EDIT_ACTIONS:
            return ActionResult(True, routines.run_edit(parsed), repeatable=False)
        elif action in logins.LOGIN_ACTIONS:
            return ActionResult(True, logins.run(parsed), repeatable=False)
        elif action in modes.MODE_ACTIONS:
            return ActionResult(True, modes.run(parsed), repeatable=False)
        elif action in journal.JOURNAL_ACTIONS:
            return ActionResult(True, journal.run(parsed, activity_log), repeatable=False)
        elif action in weekly.WEEKLY_ACTIONS:
            return ActionResult(True, weekly.run(parsed, activity_log), repeatable=False)
        elif action in personality.PERSONALITY_ACTIONS:
            return ActionResult(True, personality.run(parsed), repeatable=False)
        elif action in habits.HABIT_ACTIONS:
            return ActionResult(True, habits.run(parsed, activity_log), repeatable=False)
        elif action in study.STUDY_ACTIONS:
            return ActionResult(True, study.run(parsed, activity_log), repeatable=False)
        elif action in college.COLLEGE_ACTIONS:
            return ActionResult(True, college.run(parsed, activity_log), repeatable=False)
        elif action in attendance.ATTENDANCE_ACTIONS:
            return ActionResult(True, attendance.run(parsed), repeatable=False)
        elif action in timetable.TIMETABLE_ACTIONS:
            return ActionResult(True, timetable.run(parsed), repeatable=False)
        elif action in git_status.GIT_ACTIONS:
            return ActionResult(True, git_status.run(parsed), repeatable=False)
        elif action in projects.PROJECT_ACTIONS:
            return ActionResult(True, projects.run(parsed, activity_log), repeatable=False)
        elif action in PROACTIVE_ACTIONS:
            return ActionResult(True, run_proactive_command(parsed), repeatable=False)
        elif action in MEMORY_ACTIONS:
            return ActionResult(True, run_memory_command(parsed), repeatable=False)
        elif action in {"move_deadline", "recall_deadline", "deadline_history", "link_deadline_reminder", "deadline_reminder_updates"}:
            from services.proactive import deadline_changes
            return deadline_changes.run(parsed, remote=intent.remote_request.get())
        elif action in deadlines.DEADLINE_ACTIONS:
            return ActionResult(True, deadlines.run(parsed), repeatable=False)
        elif action in talk.TALK_ACTIONS:
            return ActionResult(True, talk.run(parsed), repeatable=False)
        elif action == reflection.MIND_ACTION:
            return ActionResult(True, reflection.on_my_mind(), repeatable=False)
        elif action in foresight.FORESIGHT_ACTIONS:
            return ActionResult(True, foresight.run(parsed), repeatable=False)
        elif action in brain.BRAIN_ACTIONS:
            return ActionResult(True, brain.run(parsed, activity_log), repeatable=False)
        elif action in predict.PREDICT_ACTIONS:
            return ActionResult(True, predict.run(parsed, activity_log), repeatable=False)
        elif action in notes.NOTE_ACTIONS:
            return ActionResult(True, notes.run(parsed), repeatable=False)
        elif action in voice_commands.VOICE_ACTIONS:
            return voice_commands.run(parsed)
        elif action == clipboard_transforms.CLIPBOARD_TRANSFORM:
            return clipboard_transforms.run(parsed)
        elif action == "delete_installers":
            if not confirmed:
                ask = installers.question()
                return intent._ask_first(parsed, ask) if ask else ActionResult(True, "No old installers in Downloads.")
            return ActionResult(True, installers.delete(), repeatable=False)
        elif action in fun.FUN_ACTIONS:
            return ActionResult(True, fun.run(parsed, activity_log), repeatable=False)
        elif action == spotify_wrapped.WRAPPED_ACTION:
            return ActionResult(True, spotify_wrapped.wrapped(parsed["span"], parsed["kind"]), repeatable=False)
        elif action in reading_list.READING_ACTIONS:
            return ActionResult(True, reading_list.run(parsed), repeatable=False)
        elif action in system_health.HEALTH_ACTIONS:
            return ActionResult(True, system_health.run(parsed), repeatable=False)
        elif action in limits.LIMIT_ACTIONS:
            return ActionResult(True, limits.run(parsed), repeatable=False)
        elif action == "list_installers":
            return ActionResult(True, installers.list_message(), repeatable=False)
        elif action in watches.WATCH_ACTIONS:
            return ActionResult(True, watches.run(parsed), repeatable=False)
        elif action == activity_ask.ACTIVITY_QUESTION:
            return ActionResult(True, activity_ask.answer(parsed["question"], activity_log), repeatable=False)
        elif action == "activity_summary":
            return ActionResult(True, activity_log.day_summary(), repeatable=False)
        elif action == "clear_activity":
            return ActionResult(True, activity_log.clear(), repeatable=False)
        elif action == "set_reminder":
            return ActionResult(True, reminders.add_from_message(parsed["message"]))
        elif action == "list_reminders":
            return ActionResult(True, reminders.list_message())
        elif action == "cancel_reminder":
            return ActionResult(True, reminders.cancel(int(parsed["number"])))
        elif action == "cancel_all_reminders":
            return ActionResult(True, reminders.cancel_all())
        else:
            logger.warning(f"Unknown system action: {action}")
            return None
    except (AutomationError, ReminderError) as e:
        logger.warning(f"System action failed: {e}")
        return ActionResult(False, str(e))
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"Malformed system action {parsed}: {e}")
        return None


def _type(parsed: dict) -> ActionResult | None:
    text = str(parsed["text"])
    if not text.strip():
        return None
    steps: tuple = ({"text": text},)
    then_keys = parsed.get("then_keys")
    if then_keys and keyboard.parse_keys(str(then_keys)):
        steps += ({"keys": str(then_keys), "times": 1},)
    if parsed["action"] == "type_text":
        # Dictation can be anything (passwords, addresses), so it stays out of chat memory
        return ActionResult(
            True, "Typing it.", "(Typed dictated text into the active app — not saved to memory.)", keyboard=steps,
        )
    count = len(text.split())
    return ActionResult(
        True, f"Typing it now — {count} word{'s' if count != 1 else ''}.",
        f"(Wrote this and typed it into the active app:)\n{text}", repeatable=False, keyboard=steps,
    )


def _open_spotify() -> None:
    system.open_app("spotify")


def _flag(value) -> bool:
    # Tool calls send real booleans; be forgiving about "false" strings
    return str(value).lower() not in ("false", "0", "no", "off")


def _play_collection(parsed: dict) -> str:
    kind, query = str(parsed["kind"]), str(parsed["query"])
    if kind not in ("artist", "album", "playlist"):
        raise ValueError(f"Unknown kind: {kind}")
    if not spotify_auth.is_connected():
        return _play_song(query)  # opens a search instead
    return spotify.play_named(kind, query, _open_spotify, _flag(parsed.get("shuffle", False)))


def _play_song(query: str) -> str:
    if spotify_auth.is_connected():
        return spotify.play_search(query, _open_spotify)
    if "spotify" in system.list_apps():
        return media.search_spotify(query)
    system.open_url(f"https://www.youtube.com/results?search_query={quote(query)}")
    return f"Opened YouTube results for \"{query}\". Pick the video to play it."
