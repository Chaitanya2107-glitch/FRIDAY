"""FRIDAY's own replies. Models can teach a fact, never handle an arbitrary turn."""
import asyncio
import json
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
    "help": 'I help you keep track of your day, schedule, reminders, notes and recorded activity, plus phone notifications and music. Try "what am I doing", "read my phone notifications", "play something chill" or "remind me in 10 minutes to stretch".',
    "unknown": 'I haven\'t learned that yet, Boss. You can tell me what it is, or ask again when knowledge lookup is available.',
    "unmatched": 'I don\'t recognise that yet, Boss. I can help with local commands; try "help" for examples.',
    "screen": 'Screen interpretation is unavailable in this mode, Boss. Tell me what you see, or use a local command.',
    "computer": 'I can run local commands, Boss. Try "open <app>" or "type <exact text>" for this task.',
}
_QUESTION = re.compile(r"^(?:what (?:is|are)|what's|who is|tell me about|explain)\s+(.+)$", re.I)


async def answer(message: str, provider_name: str | None = None, context: str | None = None,
                 screen: bool = False) -> ProviderResponse:
    text = normalize_command(message).strip(" .!?")
    lowered = text.lower()
    # Applied replies are literal owner text. They bypass polishing and never run actions.
    learned = await asyncio.to_thread(training.local_reply, text) if not screen and not context else None
    if learned:
        return ProviderResponse(content=learned, provider="local", model="friday", tokens_used=0)
    if not screen and not context and personal_question(text):
        return ProviderResponse(content="I don't have a reviewed memory for that yet, Boss. Teach me through train_friday.",
                                provider="local", model="friday", tokens_used=0)
    if screen:
        reply = REMARKS["screen"]
    elif context:
        # Already retrieved facts/excerpts remain useful without generated answers.
        reply = "Here's what I found, Boss:\n" + context
    elif lowered in {"hi", "hello", "hey", "yo", "hi friday", "hello friday"}:
        reply = REMARKS["greeting"]
    elif lowered in {"thanks", "thank you", "thanks friday"}:
        reply = REMARKS["thanks"]
    elif lowered in {"bye", "goodbye", "see you", "goodnight", "good night"}:
        reply = REMARKS["goodbye"]
    elif lowered in {"help", "what can you do", "show commands", "commands"}:
        reply = REMARKS["help"]
    elif lowered in {"tell me a joke", "joke"}:
        reply = "I tried to organise my thoughts, Boss. They asked for another folder."
    elif match := _QUESTION.fullmatch(text):
        name = match[1].strip()
        thing = await asyncio.to_thread(knowledge.find, name)
        if not thing and len(name) <= knowledge.MAX_NAME:
            # Requested knowledge is not an observed app: do not fabricate usage statistics.
            def remember_topic():
                now = datetime.now().isoformat(timespec="seconds")
                with knowledge.db() as conn:
                    conn.execute("INSERT OR IGNORE INTO things (key,kind,name,category,first_seen,last_seen,hours,last_day,last_slot) "
                                 "VALUES (?, 'topic', ?, 'browsing', ?, ?, ?, '', '')",
                                 (knowledge.key_for("topic", name), name, now, now, json.dumps([0] * 24)))
                return knowledge.find(name)
            thing = await asyncio.to_thread(remember_topic)
        from services.mind.app_learning import pending
        proposed = await asyncio.to_thread(pending, thing.key) if thing else []
        if thing and not thing.about and not proposed and config.AI_KNOWLEDGE_ENABLED:
            try:
                thing = await asyncio.wait_for(knowledge.look_up(thing, datetime.now(), requested=True),
                                               timeout=17 + max(1, config.OLLAMA_START_TIMEOUT_SECONDS)) or thing
            except Exception as error:
                logger.debug("Knowledge unavailable (%s)", type(error).__name__)
            proposed = await asyncio.to_thread(pending, thing.key)
        reply = (f"{thing.name}: {thing.about}" if thing and thing.about else
                 f"Unverified model explanation of {thing.name}: {proposed[0]['description']}"
                 if proposed and proposed[0]["description"] else REMARKS["unknown"])
    else:
        reply = REMARKS["unmatched"]
    reply = await wording.enhance(reply, provider_name)
    return ProviderResponse(content=reply, provider="local", model="friday", tokens_used=0)
