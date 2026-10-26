"""
providers/anthropic/client.py

Anthropic (Claude) implementation of BaseProvider.
Translates our internal Message format into Anthropic's API format,
makes the call, and translates the response back.

PHASE 1: Basic completion only.
Images attached to a message are sent as base64 image blocks.
Tools use Anthropic's native tool use; tool_use blocks come back as tool_calls.
FUTURE: streaming.
"""

import anthropic
from providers.base_provider import BaseProvider, Message, ProviderResponse, Tool, ToolCall
from core.config import config


def _content(msg: Message) -> str | list[dict]:
    if not msg.images:
        return msg.content
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
        for data in msg.images_base64()
    ] + [{"type": "text", "text": msg.content}]


class AnthropicProvider(BaseProvider):
    """Connects F.R.I.D.A.Y to Anthropic's Claude models."""

    def __init__(self, model: str | None = None):
        # AsyncAnthropic for non-blocking API calls inside FastAPI
        self.client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = model or config.ANTHROPIC_MODEL

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: list[Tool] | None = None,
    ) -> ProviderResponse:
        """Send messages to Claude and return the response."""

        # Convert our Message objects → Anthropic's dict format
        anthropic_messages = [
            {"role": msg.role, "content": _content(msg)}
            for msg in messages
        ]

        extra = {}
        if tools:
            extra["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or config.SYSTEM_PROMPT,
            messages=anthropic_messages,
            **extra,
        )

        # A reply can mix text and tool_use blocks, in any order
        return ProviderResponse(
            content="".join(block.text for block in response.content if block.type == "text"),
            tool_calls=[
                ToolCall(name=block.name, arguments=dict(block.input or {}))
                for block in response.content if block.type == "tool_use"
            ],
            provider="anthropic",
            model=self.model,
            tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            metadata={
                "stop_reason": response.stop_reason,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        )

    def get_provider_name(self) -> str:
        return "anthropic"

    def get_model_name(self) -> str:
        return self.model
