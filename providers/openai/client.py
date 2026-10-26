"""
providers/openai/client.py

OpenAI (GPT) implementation of BaseProvider.

PHASE 1: Basic completion.
Images attached to a message are sent as data URLs.
Tools use OpenAI's native function calling.
stream() yields the reply as it arrives (voice starts speaking early).
"""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from providers.base_provider import BaseProvider, Message, ProviderResponse, Tool, parse_openai_tool_calls
from core.config import config


class OpenAIProvider(BaseProvider):
    """Connects F.R.I.D.A.Y to OpenAI's GPT models."""

    def __init__(self, model: str | None = None):
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = model or config.OPENAI_MODEL

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: list[Tool] | None = None,
    ) -> ProviderResponse:
        """Send messages to GPT and return the response."""
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=self._openai_messages(messages, system_prompt),
            **({"tools": [t.openai_format() for t in tools]} if tools else {}),
        )

        message = response.choices[0].message
        return ProviderResponse(
            content=message.content or "",
            tool_calls=parse_openai_tool_calls(message.tool_calls),
            provider="openai",
            model=self.model,
            tokens_used=response.usage.total_tokens,
            metadata={
                "finish_reason": response.choices[0].finish_reason,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
        )

    async def stream(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=self._openai_messages(messages, system_prompt),
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @staticmethod
    def _openai_messages(messages: list[Message], system_prompt: str) -> list[dict]:
        # OpenAI puts the system prompt as the first message with role "system"
        openai_messages = []
        if system_prompt or config.SYSTEM_PROMPT:
            openai_messages.append({"role": "system", "content": system_prompt or config.SYSTEM_PROMPT})
        return openai_messages + [{"role": msg.role, "content": msg.openai_content()} for msg in messages]

    def get_provider_name(self) -> str:
        return "openai"

    def get_model_name(self) -> str:
        return self.model
