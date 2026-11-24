"""The usual provider/failover pipeline, without private context or command routing."""
import asyncio

from core.config import config, PERSONAL_ASSISTANT_ROLE
from core.errors import ModelUnavailable
from providers.base_provider import Message, ProviderResponse
from providers.failover import complete_with_failover
from .security import Denied

PROMPT = (PERSONAL_ASSISTANT_ROLE + '\nThis is an isolated remote conversation. Answer the submitted question only. '
          'You have no tools, private laptop context, notifications or command authority. '
          'Never claim to have performed an action. Actions require the phone command controls.')


async def answer(text):
    from services.mind.coaching_commands import try_command
    private = await try_command(text, conversation=True)
    if private is not None:
        return ProviderResponse(private.message, 'local', 'coaching', metadata={'allow_speech': False})
    try:
        async with asyncio.timeout(35):
            result = await complete_with_failover(config.ACTIVE_PROVIDER, [Message('user', text)], PROMPT,
                                                  500, purpose='conversation', attempt_timeout=10)
    except (ModelUnavailable, TimeoutError):
        from services.mind.replies import REMARKS
        reply = (REMARKS['greeting'] if text.strip(' .!?').casefold() in {'hi', 'hello', 'hey'} else
                 "Which phone command do you want, Boss? Use the phone command controls.")
        return ProviderResponse(reply, 'local', 'friday')
    if result.tool_calls or not result.content.strip():
        raise Denied('conversation_refused')
    return result
