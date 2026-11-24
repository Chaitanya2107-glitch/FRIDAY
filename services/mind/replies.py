"""FRIDAY's own replies. Models can teach a fact, never handle an arbitrary turn."""
import asyncio
import re
from datetime import datetime

from core.config import config
from core.logger import logger
from providers.base_provider import ProviderResponse
from services.automation.command_words import normalize_command
from services.mind import knowledge, wording
from services.mind import training
from services.mind.lessons import personal_question

REMARKS = {
    "greeting": "I'm here, Boss. What are we doing today?",
    "thanks": "Anytime, Boss.",
    "goodbye": "Talk later, Boss.",
    "help": 'I help you keep track of your day, schedule, reminders, notes and recorded activity, plus phone notifications and music. Try "what am I doing", "read my phone notifications", "play something chill" or "remind me in 10 minutes to stretch". For local math, science and procedural stories, try "engine help".',
    "unknown": 'I haven\'t learned that yet, Boss. You can tell me what it is, or ask again when knowledge lookup is available.',
    "unmatched": 'I don\'t recognise that yet, Boss. Which of my commands did you mean? Try "help" for examples.',
    "screen": 'Screen interpretation is unavailable in this mode, Boss. Tell me what you see, or use a local command.',
    "computer": 'I can run local commands, Boss. Try "open <app>" or "type <exact text>" for this task.',
}
_QUESTION = re.compile(r"^(?:what (?:is|are)|what's|who is|tell me about|explain)\s+(.+)$", re.I)
_SMALL_TALK = {
    **dict.fromkeys(("hi", "hello", "hey", "yo", "hi friday", "hello friday"), "greeting"),
    **dict.fromkeys(("thanks", "thank you", "thanks friday"), "thanks"),
    **dict.fromkeys(("bye", "goodbye", "see you", "goodnight", "good night"), "goodbye"),
    **dict.fromkeys(("tell me a joke", "joke"), "joke"),
}


def remark_kind(message: str) -> str | None:
    return _SMALL_TALK.get(normalize_command(message).strip(" .!?").lower())


def speech_allowed(result: ProviderResponse) -> bool:
    return result.provider == "local" and getattr(result, "metadata", {}).get("allow_speech", True) is True


def tone_instruction() -> str:
    from services.automation.intent import remote_request
    from services.mind import character, emotion, humour
    from services.remote.context import remote_origin

    if remote_request.get() or remote_origin.get():
        return ""
    if emotion.snapshot()["owner_stressed"]:
        return "\nUse gentle, direct wording. Keep it to one short sentence when the facts fit. Skip jokes."
    traits = character.snapshot()["traits"]
    phrases = ["Use warm wording" if traits["warmth"] >= .5 else "Use matter-of-fact wording",
               "keep it brief" if traits["verbosity"] < .55 else "include useful detail",
               "use a formal register" if traits["formality"] >= .55 else "use a conversational register"]
    if not humour.allowed():
        phrases.append("skip jokes")
    return "\nReply style: " + ", ".join(phrases) + "."


async def answer(message: str, provider_name: str | None = None, context: str | None = None,
                 screen: bool = False, *, model_assist: bool = True) -> ProviderResponse:
    text = normalize_command(message).strip(" .!?")
    lowered = text.lower()
    # Applied replies are literal owner text. They bypass polishing and never run actions.
    learned = await asyncio.to_thread(training.local_reply, text) if not screen and not context else None
    if learned:
        return ProviderResponse(content=learned, provider="local", model="friday", tokens_used=0)
    if not screen and not context and personal_question(text):
        return ProviderResponse(content="I don't have a reviewed memory for that yet, Boss. Tell me what you'd like me to remember.",
                                provider="local", model="friday", tokens_used=0)
    if screen:
        reply = REMARKS["screen"]
    elif context:
        # Already retrieved facts/excerpts remain useful without generated answers.
        reply = "Here's what I found, Boss:\n" + context
    elif kind := remark_kind(text):
        reply = await asyncio.to_thread(wording.render, {"kind": kind})
        if kind == "joke" and reply != wording.plain({"kind": kind}):
            from services.mind import humour

            humour.told(humour.situation(), "requested")
    elif lowered in {"help", "what can you do", "show commands", "commands"}:
        reply = REMARKS["help"]
    elif match := _QUESTION.fullmatch(text):
        name = match[1].strip()
        now = datetime.now()
        thing = await asyncio.to_thread(knowledge.requested_thing, name, None, now)
        from services.mind.app_learning import pending
        if thing and not thing.placed:
            try:
                thing = await asyncio.wait_for(knowledge.look_up(thing, now, requested=True, model_assist=model_assist),
                                               timeout=17 + max(1, config.OLLAMA_START_TIMEOUT_SECONDS)) or thing
            except Exception as error:
                logger.debug("Knowledge unavailable (%s)", type(error).__name__)
        proposed = await asyncio.to_thread(pending, thing.key) if thing and not thing.placed else []
        if thing and not thing.about and proposed and proposed[0]["description"]:
            return ProviderResponse(f"Unverified model explanation of {thing.name}: {proposed[0]['description']} "
                                    f"({proposed[0]['provider']}). Say verify {thing.name} to review it.",
                                    "local", "friday", metadata={"allow_speech": False})
        reply = f"{thing.name}: {thing.about}" if thing and thing.about else REMARKS["unknown"]
    else:
        reply = REMARKS["unmatched"]
    return ProviderResponse(content=reply, provider="local", model="friday", tokens_used=0)
