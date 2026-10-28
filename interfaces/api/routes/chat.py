"""
interfaces/api/routes/chat.py

The chat endpoint — the core of Phase 1.

FLOW FOR EVERY REQUEST:
  1. Receive user message
  2. Load recent conversation history from memory
  3. Call the active AI provider
  4. Save both messages (user + assistant) to memory
  5. Return the response

This file stays thin. Business logic belongs in services, not here.
"""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.config import config
from core.logger import logger
from core.errors import MemoryError
from providers.base_provider import Message
from providers.failover import complete_with_failover, is_quick_chat
from providers.registry import list_providers
from services.memory.sqlite_memory import MemoryService
from services.memory.semantic import semantic_memory
from services.memory.notes import is_note
from services.mind import humour, talk
from services.automation.intent import (
    cancel_pending_confirmation,
    is_awaiting_confirmation,
    try_system_action,
)
from services.search.web_search import build_search_context
from services.files.assistant import build_file_context
from services.automation import command_cache
from services.voice.tts import tts
from interfaces.api.routes.voice import _speak_in_background
from services.vision.screen import ask_about_screen, extract_screen_question
from services.computer.agent import computer_agent, is_computer_command
from services.automation.intent import remote_request
from services.automation.command_words import rephrase_command
from services.telegram import commands as telegram_commands
from services.mind import cognition as cognition_service, cognition_commands


router = APIRouter()

# One memory instance shared across all requests in this process
_memory = MemoryService()


@router.get("/automation/status")
async def automation_status():
    from services.browser.service import automation
    if remote_request.get():
        return {"active": False, "state": "unavailable", "response": "Laptop only.", "awaiting_reply": False}
    reply = automation.status()
    return {"active": automation.active, "job_id": automation.job.id if automation.job else None,
            "state": automation.job.state if automation.job else "idle",
            "response": reply.message, "awaiting_reply": reply.awaiting_reply}


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="The user's message")
    provider: str | None = Field(
        None,
        description="Override the active provider for this request only. "
                    "Options: openrouter | anthropic | openai | ollama"
    )
    max_tokens: int = Field(500, ge=1, le=4000)
    speak: bool = Field(False, description="Say the reply out loud too (the tray's \"Speak typed replies\" option)")


class ChatResponse(BaseModel):
    private: bool = False  # desktop must not persist/mirror private phone replies
    response: str
    provider: str  # the provider that actually answered (may be a fallback)
    model: str
    tokens_used: int
    action_success: bool | None = None  # None = normal chat reply, not a system action
    awaiting_reply: bool = False  # FRIDAY asked a yes/no question and is waiting for the answer
    # Text/keys for the client to type into the app the user is using (see services/automation/keyboard.py)
    keyboard: list[dict] = []
    automation_job: str | None = None


class HistoryItem(BaseModel):
    role: str
    content: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
@cognition_service.turn("chat")
async def chat(request: ChatRequest):
    """
    Main chat endpoint.
    Send a message, get a response. Memory is handled automatically.
    """
    logger.info(f"Chat request received — provider override: {request.provider or 'none'}")
    from services.phone import commands as phone_commands
    if phone_commands.private_turn(request.message):
        result = await phone_commands.handle(request.message, request.provider or config.ACTIVE_PROVIDER)
        cognition_service.reply(result.message, safe_text=result.memory_message)
        if request.speak:
            _speak_in_background(result.message, cache=False)
        return ChatResponse(response=result.message, provider="local", model="system_control", tokens_used=0, private=True,
                            action_success=result.success, awaiting_reply=is_awaiting_confirmation())
    from services.screen_watch import commands as screen_commands
    result = await screen_commands.handle(request.message, remote=remote_request.get())
    if result is not None:
        cognition_service.reply(result.message, safe_text=screen_commands.PRIVATE_MEMORY)
        if request.speak:
            _speak_in_background(result.message, cache=False, local_only=True)
        return ChatResponse(response=result.message, provider="local", model="system_control", tokens_used=0, private=True,
                            action_success=result.success)
    from services.mind import app_verification
    from services.activity.log import activity_log
    result = await app_verification.handle(request.message, activity_log, remote=remote_request.get())
    if result is not None:
        app_verification.mark_returned(result.message, remote=remote_request.get())
        cognition_service.reply(result.message)
        if request.speak:
            _speak_in_background(result.message, cache=False)
        return ChatResponse(response=result.message, provider="local", model="system_control", tokens_used=0,
                            action_success=result.success, awaiting_reply=app_verification.awaiting())
    from services.browser.commands import match_command as automation_command
    if automation_command(request.message):
        from services.browser.service import automation
        from services.mind import conversation_context
        await asyncio.to_thread(conversation_context.retire_dialogue, remote=remote_request.get())
        if not remote_request.get():
            cancel_pending_confirmation()
        if not remote_request.get() and computer_agent.session is not None:
            computer_agent.cancel()
        reply = await automation.handle(request.message, request.provider or config.ACTIVE_PROVIDER)
        cognition_service.reply("Automation task response")
        return ChatResponse(response=reply.message, provider="local", model="automation_task",
                            tokens_used=0, action_success=reply.success, awaiting_reply=reply.awaiting_reply,
                            automation_job=automation.job.id if reply.success and automation.job else None)
    if not remote_request.get():
        from services.browser.service import automation
        automation.abandon_pending()
    from services.mind import conversation_context
    brief_turn = await asyncio.to_thread(conversation_context.observe, request.message, remote=remote_request.get())

    # Computer tasks have their own ephemeral context. Keep their screen data,
    # proposed typing and user task out of history, learning, search and TTS caches.
    if is_computer_command(request.message):
        provider_name = request.provider or config.ACTIVE_PROVIDER
        if config.AI_ASSIST_ONLY:
            from services.mind.replies import REMARKS
            return ChatResponse(response=REMARKS["computer"], provider="local", model="friday",
                                tokens_used=0, action_success=False)
        if remote_request.get():
            return ChatResponse(response="Computer tasks are available at the laptop's command bar only.",
                                provider=provider_name, model="computer_agent", tokens_used=0, action_success=False)
        cancel_pending_confirmation()
        reply = await computer_agent.handle(request.message, provider_name)
        return ChatResponse(response=reply.message, provider=reply.provider or provider_name, model="computer_agent",
                            tokens_used=reply.tokens_used, action_success=reply.success, awaiting_reply=reply.awaiting_reply)
    # Switching to another command cancels any old desktop proposal. A later yes
    # cannot apply to something the user is no longer reviewing.
    if not remote_request.get() and computer_agent.session is not None:
        computer_agent.cancel()

    # 1. Load recent history from memory
    try:
        history_dicts = _memory.get_recent_history()
    except Exception as e:
        raise MemoryError(f"Could not load conversation history: {e}")

    # 2. Build message list: history + new user message
    messages = [
        Message(role=m["role"], content=m["content"])
        for m in history_dicts
    ]
    messages.append(Message(role="user", content=request.message))

    # 3. Pick provider
    provider_name = request.provider or config.ACTIVE_PROVIDER

    # Checked first: "look up X" would otherwise be classified as a Chrome search,
    # and "look at my screen" as a command.
    from services.mind import workspace_commands, reasoning_commands
    command_message = rephrase_command(request.message)
    cognition_command = (cognition_commands.match_command(command_message) or workspace_commands.match_command(command_message)
                         or reasoning_commands.match_command(command_message) or brief_turn)
    if not cognition_command:  # asking what she said is not an answer to her pending question
        humour.hear(request.message)
    note = is_note(command_message)  # "note look up flights" is saved, not searched
    telegram_command = telegram_commands.match_command(command_message)
    screen_question = None if note or telegram_command or cognition_command else extract_screen_question(request.message)
    # Excerpts from the user's files or web results, for the AI to answer from
    search_context = None if screen_question or note or telegram_command or cognition_command else (
        await build_file_context(request.message) or await build_search_context(request.message)
    )
    if screen_question or search_context:
        cancel_pending_confirmation()

    system_result = None
    if not (screen_question or search_context):
        system_result = await try_system_action(request.message, provider_name)
    if system_result is not None:
        app_verification.mark_returned(system_result.message, remote=remote_request.get())
        success, message = system_result.success, system_result.message
        if (config.AI_ASSIST_ONLY and success and not is_awaiting_confirmation()
                and system_result.memory_message is None and not system_result.keyboard
                and system_result.speech is None and system_result.repeatable):
            from services.mind.wording import enhance
            message = await enhance(message, provider_name)
        cognition_service.reply(message, safe_text=system_result.memory_message)
        # Forwarding is a delivery operation: its confirmation must not replace
        # the answer that a repeated request should send. Voice does not save
        # system confirmations either.
        if not telegram_command or telegram_command["action"] != "telegram_answer":
            try:
                _memory.save_message("user", request.message)
                _memory.save_message("assistant", system_result.memory_message or message)
            except Exception as e:
                logger.warning(f"Could not save system action to memory: {e}")
        if system_result.speech:  # "read this" is read aloud even when typed
            _speak_in_background(system_result.speech)
        elif request.speak and system_result.speech is None:
            _speak_in_background(message, cache=system_result.memory_message is None and system_result.repeatable)
        return ChatResponse(
            response=message,
            provider=provider_name,
            model="system_control",
            tokens_used=0,
            action_success=success,
            awaiting_reply=is_awaiting_confirmation() or conversation_context.awaiting_reply(remote=remote_request.get()),
            keyboard=list(system_result.keyboard),
        )

    if not remote_request.get() and not (cognition_command or screen_question or search_context):
        talk.hear(request.message)
    # 4. Call the AI — other configured providers are tried if this one fails
    if config.AI_ASSIST_ONLY:
        if config.AI_LANGUAGE_ENABLED and not screen_question:
            from services.mind.language import answer
            result = await answer(request.message, provider_name, messages[:-1], request.max_tokens, search_context)
        else:
            from services.mind.replies import answer
            result = await answer(request.message, provider_name, search_context, bool(screen_question))
    elif screen_question:
        result = await ask_about_screen(screen_question, messages[:-1], provider_name, request.max_tokens)
    else:
        from services.mind import reasoning
        reasoned = await reasoning.analyze(request.message, provider_name)
        system_prompt = config.SYSTEM_PROMPT + await semantic_memory.prompt_section(request.message)
        system_prompt += reasoning.questions_section(reasoned)
        if search_context:
            system_prompt += "\n\n" + search_context
        result = await complete_with_failover(
            provider_name, messages, system_prompt, request.max_tokens,
            prefer_local=is_quick_chat(request.message, provider_name, bool(search_context)),
        )
        semantic_memory.learn_in_background(request.message, provider_name)
        humour.after_chat_reply()
    logger.info(
        f"Response received — provider: {result.provider} | model: {result.model} | tokens: {result.tokens_used}"
    )
    cognition_service.reply(result.content, public=True)

    # 5. Save both sides to memory
    try:
        _memory.save_message("user", request.message)
        _memory.save_message("assistant", result.content)
    except Exception as e:
        # Don't fail the whole request if memory save fails — just log it
        logger.warning(f"Could not save messages to memory: {e}")

    if request.speak:
        _speak_in_background(result.content)
    return ChatResponse(
        response=result.content,
        provider=result.provider,
        model=result.model,
        tokens_used=result.tokens_used,
    )


@router.get("/history", response_model=list[HistoryItem])
async def get_history(limit: int = 20):
    """Return recent conversation history."""
    try:
        return _memory.get_recent_history(limit=limit)
    except Exception as e:
        raise MemoryError(f"Could not retrieve history: {e}")


@router.delete("/history")
async def clear_history():
    """Wipe conversation history and the command/speech caches. User facts are preserved."""
    try:
        _memory.clear_history()
        from services.mind import conversation_context
        await asyncio.to_thread(conversation_context.clear)
        cognition_service.cognition.clear()
        # The caches hold wording from past messages too
        command_cache.clear()
        tts.clear_cache()
        logger.info("Conversation history cleared")
        return {"message": "Conversation history cleared."}
    except Exception as e:
        raise MemoryError(f"Could not clear history: {e}")


@router.get("/memory/facts")
async def get_facts():
    """Return all stored user facts."""
    try:
        return _memory.get_all_facts()
    except Exception as e:
        raise MemoryError(f"Could not retrieve facts: {e}")


@router.post("/memory/facts")
async def save_fact(key: str, value: str):
    """Store a user fact manually."""
    try:
        _memory.save_fact(key, value)
        logger.info(f"Fact saved: {key} = {value}")
        return {"message": f"Saved: {key} = {value}"}
    except Exception as e:
        raise MemoryError(f"Could not save fact: {e}")


@router.get("/providers")
async def get_providers():
    """Return available providers and which one is currently active."""
    return {
        "active": config.ACTIVE_PROVIDER,
        "available": list_providers(),
    }
