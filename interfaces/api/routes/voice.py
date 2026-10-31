"""
interfaces/api/routes/voice.py

The voice endpoint — listens, thinks, speaks.

FLOW:
  1. POST /voice starts listening. FRIDAY stops talking first, so it doesn't talk
     over the user (or record itself). Listening ends when the user presses the
     voice hotkey again (POST /voice/stop), goes quiet after speaking, or hits
     the time limit
  2. Transcribe with faster-whisper
  3. Screen question, web search request, system command, or normal AI chat —
     same as typed chat
  4. Return the reply straight away; FRIDAY speaks it in the background.
     AI chat replies are streamed: the first sentence is spoken while the rest
     is still being written (services/voice/speech_stream.py)

To hear the answer to a yes/no question, the client listens again with
after_speech=true, which waits for FRIDAY to finish asking before recording.

POST /voice/wake replaces step 1 while "Hey Friday" is switched on: it waits for
the wake phrase (services/voice/wake.py) and uses what followed it as the command.
POST /voice/wake/stop ends the wait when the user switches it off.

Listening, transcription and speech all run off the event loop, so reminders,
clipboard history and other requests keep working while FRIDAY listens or talks.

This file stays thin. Recording/STT/TTS live in services/voice/,
system control lives in services/automation/.
"""

import asyncio
import contextvars
import re
import threading

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.config import config
from core.logger import logger
from core.errors import MemoryError, FridayError
from providers.base_provider import Message
from providers.failover import complete_with_failover, is_quick_chat
from services.memory.sqlite_memory import MemoryService
from services.memory.semantic import semantic_memory
from services.voice.recorder import recorder
from services.voice.conversation import END_REPLY, START_REPLY, match_conversation
from services.automation.command_words import rephrase_command
from services.voice.stt import stt
from services.voice.speech_stream import FirstSentenceSpeaker
from services.voice.tts import tts
from services.voice import wake as wake_log
from services.voice.conversation_input import conversation_input
from services.voice.wake import wake_listener
from services.automation.intent import (
    cancel_pending_confirmation,
    is_awaiting_confirmation,
    try_system_action,
    remote_request,
)
from services.search.web_search import build_search_context
from services.files.assistant import build_file_context
from services.vision.screen import ask_about_screen, extract_screen_question
from services.memory.notes import is_note
from services.mind import humour, talk
from services.telegram import commands as telegram_commands
from services.mind import cognition as cognition_service, cognition_commands

router = APIRouter()

# Shared memory instance — same one used by chat.py
_memory = MemoryService()

# asyncio only keeps weak references to tasks, so hold background speech until it's done.
_speech_tasks: set[asyncio.Task] = set()
_speech_generation = contextvars.ContextVar("voice_speech_generation", default=None)
_conversation_request = asyncio.Lock()

# Set by POST /voice/stop, so a listen still waiting for FRIDAY to finish speaking can be cancelled.
_listen_cancelled = threading.Event()
_listen_discarded = threading.Event()  # stopped because the answer was typed instead: drop the audio
# "Hey Friday" sessions the user switched off (POST /voice/wake/stop). One id per
# time it's switched on, so a stop that lands just before the next wait still counts.
_stopped_wake_sessions: set[str] = set()


# ── Request / Response schemas ────────────────────────────────────────────────

class VoiceRequest(BaseModel):
    barge_in: bool = Field(False, description="Conversation mode: retain spoken interruptions during reply playback.")
    provider: str | None = Field(
        None,
        description="Override the active provider for this request only."
    )
    max_tokens: int = Field(500, ge=1, le=4000)
    speak: bool = Field(
        True,
        description="Whether FRIDAY should speak the response out loud (default: True)"
    )
    after_speech: bool = Field(
        False,
        description="Wait for FRIDAY to finish speaking before listening (to hear the answer to "
                    "its question). Otherwise FRIDAY stops talking so the user can speak."
    )


class WakeRequest(VoiceRequest):
    session: str = Field(..., min_length=1, max_length=64,
                         description="Id of this switch-on of \"Hey Friday\"; /voice/wake/stop ends it.")


class WakeStopRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=64)


class VoiceResponse(BaseModel):
    private: bool = False
    transcription: str   # What Whisper heard you say
    response:      str   # What FRIDAY replied or did
    provider:      str   # the provider that actually answered (may be a fallback)
    model:         str
    tokens_used:   int
    action:        str = "chat"  # "chat" or the system action taken
    action_success: bool | None = None  # None for normal chat replies
    awaiting_reply: bool = False  # FRIDAY asked a yes/no question and is waiting for the answer
    keyboard: list[dict] = []  # text/keys for the client to type into the focused app
    conversation: str | None = None  # "start" / "end": conversation mode (services/voice/conversation.py)


def _speak_in_background(text: str, cache: bool = False, *, local_only: bool = False) -> None:
    generation = _speech_generation.get()
    if generation is None:
        generation = tts.generation
    async def speak():
        try:
            if tts.generation != generation:
                return
            if local_only:
                await tts.speak(text, cache=False, expected_generation=generation, local_only=True)
            else:
                await tts.speak(text, cache=cache, expected_generation=generation)
        except Exception as e:
            logger.warning(f"Couldn't speak the reply: {e}")

    task = asyncio.create_task(speak())
    _speech_tasks.add(task)
    task.add_done_callback(_speech_tasks.discard)


async def _wait_until_done_speaking() -> bool:
    """Wait for FRIDAY to finish speaking. Returns False if the listen was cancelled meanwhile."""
    while _speech_tasks and not _listen_cancelled.is_set():
        await asyncio.wait(list(_speech_tasks), timeout=0.1)
    return not _listen_cancelled.is_set()


# ── Voice endpoints ───────────────────────────────────────────────────────────

@router.post("/voice", response_model=VoiceResponse)
async def voice(request: VoiceRequest):
    """
    Listen until the user stops (voice hotkey again, or silence), then reply.
    The reply is returned immediately and spoken in the background.
    """
    if request.barge_in:
        return await _conversation_voice(request)
    await asyncio.to_thread(conversation_input.stop)
    logger.info(f"Voice request — listening | speak: {request.speak} | after speech: {request.after_speech}")
    _listen_cancelled.clear()
    _listen_discarded.clear()

    if request.after_speech:
        if not await _wait_until_done_speaking():
            raise FridayError("Stopped listening.", status_code=409)
    else:
        tts.stop()  # the user wants to talk — don't talk over them, or record FRIDAY's own voice

    # ── Step 1: Record and transcribe ────────────────────────────────────────
    transcription = await _record_command()
    if _listen_discarded.is_set():
        raise FridayError("Stopped listening.", status_code=409)
    return await _reply(transcription, request)


async def _conversation_voice(request):
    if _conversation_request.locked():
        raise FridayError("Another conversation turn is already listening.", status_code=409)
    async with _conversation_request:
        _listen_cancelled.clear()
        _listen_discarded.clear()
        token, monitor = None, None
        try:
            captured = await asyncio.to_thread(conversation_input.take)
            if _listen_cancelled.is_set() or _listen_discarded.is_set():
                raise FridayError("Stopped listening.", status_code=409)
            if captured.interrupted and not captured.text:
                return _quick_reply("wait", "Listening.", request)
            token = _speech_generation.set(tts.generation)
            monitor = conversation_input.start(replying=True, expected_epoch=captured.epoch)
            result = await _reply(captured.text, request)
            if result.conversation == "end":
                await asyncio.to_thread(conversation_input.stop)
            return result
        except BaseException:
            await asyncio.to_thread(conversation_input.stop)
            raise
        finally:
            if monitor:
                monitor.replying.clear()
            if token is not None:
                _speech_generation.reset(token)


@router.post("/voice/conversation/stop")
async def stop_conversation_input(silence: bool = True):
    if silence:
        _listen_cancelled.set()
        tts.stop()
    await asyncio.to_thread(conversation_input.stop)
    return {"stopped": True}


@router.post("/voice/wake", response_model=VoiceResponse)
async def voice_wake(request: WakeRequest):
    """
    Wait until someone says "Hey Friday" (only while the user has it switched on),
    then answer like /voice. "Hey Friday, work mode" answers straight away; a bare
    "Hey Friday" beeps and listens for the command.
    408 = nobody said it for WAKE_AUTO_OFF_MINUTES; 409 = switched off meanwhile.
    """
    logger.info("Listening for the wake phrase")
    wake = await asyncio.to_thread(
        wake_listener.wait, lambda: request.session in _stopped_wake_sessions, config.WAKE_AUTO_OFF_MINUTES * 60,
        lambda: recorder.is_recording, lambda: tts.saying, tts.stop,
    )
    if wake is None:
        raise FridayError("Stopped listening for 'Hey Friday'.", status_code=409)
    if wake.interrupted and _means_stop_talking(wake.command):
        # FRIDAY has already gone quiet — that was all the user wanted
        wake_log.record(mistake=False, interrupted=True)
        return _quick_reply(wake.command, "Okay.", request)
    command = wake.command
    if not command:
        try:
            command = await _record_command()
        except FridayError:
            wake_log.record(mistake=True, interrupted=wake.interrupted)  # woke, then nobody said anything
            raise
    if _words(command) in FALSE_WAKE:
        wake_log.record(mistake=True, interrupted=wake.interrupted)
        return _quick_reply(command, "Sorry — my mistake.", request)
    wake_log.record(mistake=False, interrupted=wake.interrupted)
    return await _reply(command, request)


def _quick_reply(transcription: str, text: str, request: VoiceRequest) -> VoiceResponse:
    return VoiceResponse(
        transcription=transcription, response=text, provider=request.provider or config.ACTIVE_PROVIDER,
        model="system_control", tokens_used=0, action="system", action_success=True,
    )


# Said over FRIDAY ("Hey Friday, stop"): just stop talking. At other times these go
# through the normal command flow ("stop" can mean pause the music).
STOP_TALKING = {
    "stop", "stop it", "stop talking", "ok stop", "okay stop", "shut up", "be quiet", "quiet", "hush",
    "silence", "enough", "that's enough", "thats enough", "never mind", "nevermind", "cancel",
    "thank you", "thanks", "got it", "ok", "okay",
}


# Said right after a wake: it wasn't meant for FRIDAY (logged as a false wake, services/voice/wake.py)
FALSE_WAKE = {
    "false alarm", "not you", "not you friday", "sorry not you", "i wasn't talking to you", "wasn't talking to you",
    "i'm not talking to you", "not talking to you", "i was not talking to you", "wrong person", "my mistake",
}


def _words(command: str) -> str:
    return " ".join(re.findall(r"[a-z']+", command.lower().replace("’", "'")))


def _means_stop_talking(command: str) -> bool:
    return _words(command) in STOP_TALKING


@router.post("/voice/wake/stop")
async def stop_wake(request: WakeStopRequest):
    """The wake-word switch turned off: stop listening for "Hey Friday"."""
    _stopped_wake_sessions.add(request.session)
    return {"stopped": True}


async def _record_command() -> str:
    audio = await asyncio.to_thread(recorder.record)
    transcription = await asyncio.to_thread(stt.transcribe, audio, log=False)
    if not transcription:
        raise FridayError("No speech detected. Please try again.", status_code=422)  # conversation mode counts these
    return transcription


@cognition_service.turn("voice")
async def _reply(transcription: str, request: VoiceRequest) -> VoiceResponse:
    """Steps 2–5 for a transcribed voice command."""
    provider_name = request.provider or config.ACTIVE_PROVIDER

    from services.phone import commands as phone_commands
    if phone_commands.private_turn(transcription):
        result = await phone_commands.handle(transcription, provider_name)
        cognition_service.reply(result.message, safe_text=result.memory_message)
        if request.speak:
            _speak_in_background(result.message, cache=False)
        return VoiceResponse(transcription=transcription, response=result.message, provider="local", private=True,
                             model="system_control", tokens_used=0, action="system", action_success=result.success,
                             awaiting_reply=is_awaiting_confirmation())

    from services.screen_watch import commands as screen_commands
    result = await screen_commands.handle(transcription, remote=remote_request.get())
    if result is not None:
        cognition_service.reply(result.message, safe_text=screen_commands.PRIVATE_MEMORY)
        if request.speak:
            _speak_in_background(result.message, cache=False, local_only=True)
        return VoiceResponse(transcription=transcription, response=result.message, provider="local", private=True,
                             model="system_control", tokens_used=0, action="system", action_success=result.success)
    from services.mind import app_verification
    from services.activity.log import activity_log
    result = await app_verification.handle(transcription, activity_log, remote=remote_request.get())
    if result is not None:
        app_verification.mark_returned(result.message, remote=remote_request.get())
        cognition_service.reply(result.message)
        if request.speak:
            _speak_in_background(result.message, cache=False)
        return VoiceResponse(transcription=transcription, response=result.message, provider="local", model="system_control",
                             tokens_used=0, action="system", action_success=result.success,
                             awaiting_reply=app_verification.awaiting())
    from services.browser.commands import match_command as automation_command
    if command := automation_command(transcription):
        from services.browser.service import automation
        from services.mind import conversation_context
        await asyncio.to_thread(conversation_context.retire_dialogue, remote=remote_request.get())
        if not remote_request.get():
            cancel_pending_confirmation()
        reply = await automation.handle(transcription, provider_name)
        cognition_service.reply("Automation task response")
        if request.speak:
            spoken = "The research report is ready in the command bar." if command.kind == "report" and reply.success else reply.message
            _speak_in_background(spoken, cache=False)
        return VoiceResponse(transcription=transcription, response=reply.message, provider="local",
                             model="automation_task", tokens_used=0, action="system",
                             action_success=reply.success, awaiting_reply=reply.awaiting_reply)
    if not remote_request.get():
        from services.browser.service import automation
        automation.abandon_pending()

    from services.mind import conversation_context
    brief_turn = await asyncio.to_thread(conversation_context.observe, transcription, remote=remote_request.get())

    if mode := match_conversation(transcription):  # "let's talk" / "bye": the tray starts or ends the loop
        reply = START_REPLY if mode == "start" else END_REPLY
        if request.speak:
            _speak_in_background(reply, cache=True)
        return _quick_reply(transcription, reply, request).model_copy(update={"conversation": mode})

    # ── Step 2: Check if it's a system command ───────────────────────────────
    from services.mind import workspace_commands, reasoning_commands
    command_message = rephrase_command(transcription)
    cognition_command = (cognition_commands.match_command(command_message) or workspace_commands.match_command(command_message)
                         or reasoning_commands.match_command(command_message) or brief_turn)
    if not cognition_command:
        humour.hear(transcription)
    note = is_note(command_message)  # "note look up flights" is saved, not searched
    telegram_command = telegram_commands.match_command(command_message)
    screen_question = None if note or telegram_command or cognition_command else extract_screen_question(transcription)
    # Excerpts from the user's files or web results, for the AI to answer from
    search_context = None if screen_question or note or telegram_command or cognition_command else (
        await build_file_context(transcription, cite=False)
        or await build_search_context(transcription, cite=False)
    )
    if screen_question or search_context:
        cancel_pending_confirmation()

    system_result = None
    if not (screen_question or search_context):
        system_result = await try_system_action(transcription, provider_name)

    if system_result is not None:
        app_verification.mark_returned(system_result.message, remote=remote_request.get())
        if (config.AI_ASSIST_ONLY and system_result.success and not is_awaiting_confirmation()
                and system_result.memory_message is None and not system_result.keyboard
                and system_result.speech is None and system_result.repeatable):
            from services.mind.wording import enhance
            system_result = system_result._replace(message=await enhance(system_result.message, provider_name))
        cognition_service.reply(system_result.message, safe_text=system_result.memory_message)
        logger.info(f"System action completed: {system_result.message}")
        if system_result.speech is not None:  # "read this": say the text itself, not "Reading it out"
            if system_result.speech:
                _speak_in_background(system_result.speech)
        elif request.speak:
            # Command confirmations are short and repeat, so their audio is reused —
            # except replies that show private content (they set memory_message) or
            # change every time (stats, track names).
            cache = system_result.memory_message is None and system_result.repeatable
            _speak_in_background(system_result.message, cache=cache)
        return VoiceResponse(
            transcription=transcription,
            response=system_result.message,
            provider=provider_name,
            model="system_control",
            tokens_used=0,
            action="system",
            action_success=system_result.success,
            awaiting_reply=is_awaiting_confirmation() or conversation_context.awaiting_reply(remote=remote_request.get()),
            keyboard=list(system_result.keyboard),
        )

    # ── Step 3: Normal chat flow ──────────────────────────────────────────────
    try:
        history_dicts = _memory.get_recent_history()
    except Exception as e:
        raise MemoryError(f"Could not load conversation history: {e}")

    messages = [
        Message(role=m["role"], content=m["content"])
        for m in history_dicts
    ]
    if not (cognition_command or screen_question or search_context):
        from services.screen_watch import companion
        private_reply = await companion.answer(transcription, messages, remote=remote_request.get(),
                                                max_tokens=request.max_tokens)
        if private_reply is not None:
            cognition_service.reply(private_reply.content, safe_text=companion.PRIVATE_MEMORY)
            if request.speak:
                _speak_in_background(private_reply.content, cache=False, local_only=True)
            return VoiceResponse(transcription=transcription, response=private_reply.content,
                                 provider=private_reply.provider, model=private_reply.model,
                                 tokens_used=private_reply.tokens_used, action="chat", private=True)
    if not remote_request.get() and not (cognition_command or screen_question or search_context):
        talk.hear(transcription)
    # Other configured providers are tried if this one fails
    speaker = None
    if config.AI_ASSIST_ONLY:
        if config.AI_LANGUAGE_ENABLED and not screen_question:
            from services.mind.language import answer
            result = await answer(transcription, provider_name, messages, request.max_tokens, search_context)
        else:
            from services.mind.replies import answer
            result = await answer(transcription, provider_name, search_context, bool(screen_question))
    elif screen_question:
        result = await ask_about_screen(
            screen_question, messages, provider_name, request.max_tokens, spoken=True
        )
    else:
        messages.append(Message(role="user", content=transcription))
        from services.mind import reasoning
        reasoned = await reasoning.analyze(transcription, provider_name)
        system_prompt = config.SYSTEM_PROMPT + await semantic_memory.prompt_section(transcription)
        system_prompt += reasoning.questions_section(reasoned)
        if search_context:
            system_prompt += "\n\n" + search_context
        if request.speak:
            generation = _speech_generation.get()
            if generation is None:
                generation = tts.generation
            speaker = FirstSentenceSpeaker(_speak_in_background, stopped=lambda: tts.generation != generation)
        result = await complete_with_failover(
            provider_name, messages, system_prompt, request.max_tokens,
            prefer_local=is_quick_chat(transcription, provider_name, bool(search_context)),
            on_text=speaker.feed if speaker else None,
        )
        semantic_memory.learn_in_background(transcription, provider_name)
        humour.after_chat_reply()
    logger.info(f"Response received — provider: {result.provider} | model: {result.model} | tokens: {result.tokens_used}")
    cognition_service.reply(result.content, public=True)

    # ── Step 4: Save to memory ────────────────────────────────────────────────
    try:
        _memory.save_message("user", transcription)
        _memory.save_message("assistant", result.content)
    except Exception as e:
        logger.warning(f"Could not save voice messages to memory: {e}")

    # ── Step 5: Reply now, speak in the background ────────────────────────────
    if speaker:
        speaker.finish()  # the first sentence may already be playing
    elif request.speak:
        _speak_in_background(result.content)

    return VoiceResponse(
        transcription=transcription,
        response=result.content,
        provider=result.provider,
        model=result.model,
        tokens_used=result.tokens_used,
        action="chat",
    )


@router.post("/voice/stop")
async def stop_listening(discard: bool = False):
    """
    The voice hotkey pressed again: stop listening now — or cancel a listen that's
    still waiting for FRIDAY to finish speaking — and stop any speech.
    discard=True: the answer was typed instead, so what was recorded is thrown away.
    """
    if discard:
        _listen_discarded.set()
    _listen_cancelled.set()
    tts.stop()
    await asyncio.to_thread(conversation_input.stop)
    return {"stopped": recorder.stop()}
