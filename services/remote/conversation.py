"""The usual provider/failover pipeline, without private context or command routing."""
import asyncio

from core.config import config, PERSONAL_ASSISTANT_ROLE
from providers.base_provider import Message
from providers.failover import complete_with_failover
from .security import Denied

PROMPT = (PERSONAL_ASSISTANT_ROLE + '\nThis is an isolated remote conversation. Answer the submitted question only. '
          'You have no tools, private laptop context, notifications or command authority. '
          'Never claim to have performed an action. Actions require the phone command controls.')


async def answer(text):
    async with asyncio.timeout(35):
        result = await complete_with_failover(config.ACTIVE_PROVIDER, [Message('user', text)], PROMPT,
                                              500, purpose='conversation', attempt_timeout=10)
    if result.tool_calls or not result.content.strip():
        raise Denied('conversation_refused')
    return result
