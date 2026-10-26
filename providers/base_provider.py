"""
providers/base_provider.py

The abstract contract that every AI provider must implement.
This is what makes F.R.I.D.A.Y provider-agnostic.

HOW IT WORKS:
  - The rest of the system only ever talks to BaseProvider.
  - It never imports AnthropicProvider or OpenAIProvider directly.
  - To swap providers: change one env var. Nothing else.

HOW TO ADD A NEW PROVIDER:
  1. Create providers/yourprovider/client.py
  2. Inherit from BaseProvider
  3. Implement all @abstractmethod methods
  4. Register it in providers/registry.py
  5. Done — the rest of the system works automatically
"""

import base64
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Message:
    """A single message in a conversation."""
    role: str      # "user" or "assistant"
    content: str
    images: list[bytes] = field(default_factory=list)  # JPEG images sent with the message (vision)

    def images_base64(self) -> list[str]:
        return [base64.b64encode(image).decode("ascii") for image in self.images]

    def openai_content(self) -> str | list[dict]:
        """Content in the OpenAI chat format (also used by OpenRouter): text, plus any images."""
        if not self.images:
            return self.content
        return [{"type": "text", "text": self.content}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}
            for data in self.images_base64()
        ]


@dataclass
class Tool:
    """A function the model may call instead of (or as well as) replying with text."""
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})  # JSON Schema

    def openai_format(self) -> dict:
        """Tool definition in the OpenAI format (also used by OpenRouter and Ollama)."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


@dataclass
class ToolCall:
    """A tool the model chose to call, with its arguments."""
    name: str
    arguments: dict


def parse_openai_tool_calls(raw_calls) -> list[ToolCall]:
    """
    Tool calls from an OpenAI-format reply (OpenAI, OpenRouter). The arguments
    arrive as a JSON string; calls whose arguments don't decode are dropped.
    """
    calls = []
    for raw in raw_calls or []:
        try:
            arguments = json.loads(raw.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(arguments, dict):
            calls.append(ToolCall(name=raw.function.name, arguments=arguments))
    return calls


@dataclass
class ProviderResponse:
    """
    Standard response returned by every provider.
    No matter which AI answered, the response always looks the same.
    """
    content: str         # The actual text response ("" if the model only called tools)
    provider: str        # Which provider answered e.g. "anthropic"
    model: str           # Which model e.g. "claude-sonnet-4-20250514"
    tokens_used: int = 0 # Total tokens consumed (for monitoring costs)
    metadata: dict = field(default_factory=dict)  # Any extra provider-specific info
    tool_calls: list[ToolCall] = field(default_factory=list)  # in the order the model made them


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """
    Every AI provider inherits from this.
    If a method isn't defined here, the system doesn't know it exists.
    This is intentional — it forces a clean, consistent interface.
    """

    async def complete_structured(self, schema: dict, **kwargs) -> ProviderResponse:
        """Optional native JSON constraints; callers still validate semantics.
        Unsupported providers use the prompt without altering ordinary replies."""
        return await self.complete(**kwargs)

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: list[Tool] | None = None,
    ) -> ProviderResponse:
        """
        Core method: send a conversation, get a response.
        This is the only method the orchestrator calls.

        Args:
            messages:      Full conversation history as a list of Messages
            system_prompt: Optional instructions that shape the AI's behaviour
            max_tokens:    Maximum length of the response
            temperature:   Creativity level (0.0 = deterministic, 1.0 = creative)
            tools:         Functions the model may call; its calls come back in tool_calls

        Returns:
            ProviderResponse with the AI's reply and metadata
        """
        pass

    async def stream(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        Yield the reply's text as it arrives (no tools). Providers without real
        streaming yield the whole reply at once, so every provider supports this.
        """
        response = await self.complete(messages, system_prompt, max_tokens, temperature)
        if response.content:
            yield response.content

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the provider identifier e.g. 'anthropic'"""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the active model name e.g. 'claude-sonnet-4-20250514'"""
        pass

    def get_info(self) -> dict:
        """Convenience method — returns provider info as a dict."""
        return {
            "provider": self.get_provider_name(),
            "model": self.get_model_name(),
        }
