"""Classify scoped follow-ups before search, learning and multi-command parsing."""

import re
import sqlite3

from core.logger import logger
from services.automation.results import ActionResult
from services.automation.command_words import strip_leading_filler
from services.files import assistant as files
from services.mind import followup_commands, handoff_context, project_session_context, reference_context as context
from services.mind.workspace import workspace
from services.telegram import commands as telegram_commands
from services.proactive import class_changes, deadline_changes


def observe(text, *, remote=False):
    from services.mind.dialogue import dialogue
    from services.mind.commitment_topics import topics
    from services.mind.execution_commands import match_command
    execution_turn = (match_command(text) or {}).get("workflow") == "project_execution"
    brief = project_session_context.observe(text, remote=remote)
    try:
        dialogue_turn = dialogue.match_turn(text, remote=remote)
        deadline_turn = deadline_changes.match_turn(text, remote=remote)
        class_turn = class_changes.match_turn(text, remote=remote)
        followup_turn = followup_commands.match_turn(text, remote=remote)
        handoff = handoff_context.match_turn(text, remote=remote)
        file_command = files.match_file_command(text)
        # Sending a selected file uses the same results; it does not change the target.
        file_send = (telegram_commands.match_command(text) or {}).get("action") == "telegram_file"
        topic_turn = None
        if not remote:
            if not (dialogue_turn or execution_turn or brief or deadline_turn or class_turn or followup_turn or handoff or file_command or file_send):
                try:
                    topic_turn = topics.match_turn(text)
                except (OSError, ValueError, sqlite3.Error):
                    # A recognized question with unavailable context must reach the
                    # guarded handler, never recency guessing in search/model chat.
                    topic_turn = True
            if not topic_turn:
                try:
                    topics.clear()
                except (OSError, ValueError, sqlite3.Error):
                    logger.debug('Optional commitment topic could not be retired')
        if not file_command and not file_send:
            files.last_results.clear()
        if not remote and not handoff:
            with workspace._db() as conn:
                context.clear(conn, "handoff")
        if not deadline_turn:
            with workspace._db() as conn:
                context.clear(conn, "deadline", "telegram" if remote else "local")
        if not class_turn:
            with workspace._db() as conn:
                context.clear(conn, "class_session", "telegram" if remote else "local")
        if not followup_turn:
            with workspace._db() as conn:
                context.clear(conn, "task_followup", "telegram" if remote else "local")
        return bool(dialogue_turn or topic_turn or execution_turn or brief or handoff or file_command or file_send or deadline_turn or class_turn or followup_turn)
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Conversation reference unavailable: %s", type(error).__name__)
        reference_words = re.match(r"(?:open|show|reveal) (?:it|that(?: one)?|this(?: one)?|\d+)\b|"
                                   r"(?:actually|no)[, ]+(?:use|switch to)\b", strip_leading_filler(text), re.I)
        return bool(brief or reference_words)


async def try_handle(text, *, remote=False):
    import asyncio
    from services.automation import intent

    try:
        from services.mind.dialogue import dialogue
        if parsed := await asyncio.to_thread(dialogue.match_turn, text, remote=remote):
            intent.cancel_pending_confirmation()
            return await dialogue.run(parsed)
        from services.mind import execution_commands
        parsed = execution_commands.match_command(text)
        if parsed and parsed.get("workflow") == "project_execution":
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(execution_commands.run, parsed, remote=remote)
        if parsed := await asyncio.to_thread(followup_commands.match_turn, text, remote=remote):
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(followup_commands.run, parsed, remote=remote)
        if parsed := await asyncio.to_thread(class_changes.match_turn, text, remote=remote):
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(class_changes.run, parsed, remote=remote)
        if parsed := await asyncio.to_thread(deadline_changes.match_turn, text, remote=remote):
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(deadline_changes.run, parsed, remote=remote)
        if parsed := await asyncio.to_thread(handoff_context.match_turn, text, remote=remote):
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(handoff_context.run, parsed, remote=remote)
        parsed = await asyncio.to_thread(files.match_file_command, text)
        if parsed and parsed["action"] not in {"find_files", "rescan_files"}:
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(intent._execute, parsed)
        from services.mind.commitment_topics import topics
        if parsed := await asyncio.to_thread(topics.match_turn, text, remote=remote):
            intent.cancel_pending_confirmation()
            return await asyncio.to_thread(topics.run, parsed)
    except (OSError, ValueError, sqlite3.Error) as error:
        logger.warning("Conversation reference action unavailable: %s", type(error).__name__)
        return ActionResult(False, "The reference is unavailable or changed. Repeat the request with its name.", repeatable=False)
    return None


def clear():
    from services.mind.dialogue import dialogue
    dialogue.cancel()
    with workspace._db() as conn:
        for scope in ("local", "telegram"):
            context.clear(conn, scope=scope)
    project_session_context.clear()


def awaiting_reply(*, remote=False):
    from services.mind.dialogue import dialogue
    return False if remote else dialogue.awaiting()


def retire_dialogue(*, remote=False):
    if not remote:
        from services.mind.dialogue import dialogue
        from services.mind.commitment_topics import topics
        try:
            dialogue.cancel()
        except (OSError, ValueError, sqlite3.Error):
            logger.debug('Conversation clarification could not be retired')
        try:
            topics.clear()
        except (OSError, ValueError, sqlite3.Error):
            logger.debug('Optional commitment topic could not be retired')
