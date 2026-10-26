"""
providers/openrouter/client.py

OpenRouter implementation of BaseProvider.

OpenRouter is a unified API that gives you access to 200+ models
(Claude, GPT, Llama, Mistral, Gemini, etc.) through ONE API key.

HOW IT WORKS:
  OpenRouter is OpenAI-compatible — same SDK, just a different base URL.
  You pick the model using OpenRouter's model string format:
    "anthropic/claude-haiku-4-5"
    "anthropic/claude-sonnet-4-5"
    "openai/gpt-4o"
    "openai/gpt-4o-mini"
    "meta-llama/llama-3.1-8b-instruct"
    "google/gemini-flash-1.5"

Get your free API key at: https://openrouter.ai
Browse all models at:     https://openrouter.ai/models

PHASE 1: Basic completion.
Tools use the OpenAI function-calling format, which OpenRouter passes on.
FUTURE: streaming.
"""

import openai
from openai import AsyncOpenAI
from providers.base_provider import BaseProvider, Message, ProviderResponse, Tool, parse_openai_tool_calls
from core.config import config
from core.logger import logger
from core.errors import ProviderError


THINKING_BUDGET = 4000  # tokens for a retry when a thinking model used them all up before answering

class OpenRouterProvider(BaseProvider):
    """
    Connects F.R.I.D.A.Y to OpenRouter's unified model API.
    Uses the OpenAI SDK because OpenRouter is OpenAI-compatible.
    """

    def __init__(self, model: str | None = None):
        # OpenRouter is OpenAI-compatible — we just point the SDK at their URL
        self.client = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                # These headers are optional but recommended by OpenRouter
                # They help them track usage and show your app in their dashboard
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "F.R.I.D.A.Y Personal Assistant",
            },
            timeout=90,
            max_retries=0,  # a busy model moves on to the next backup model instead of retrying
        )
        self.model = model or config.OPENROUTER_MODEL
        logger.info(f"OpenRouterProvider initialised — model: {self.model}")

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: list[Tool] | None = None,
    ) -> ProviderResponse:
        """
        Send messages to OpenRouter and return the response.
        Raises ProviderError on any failure — never leaks raw exceptions.
        """

        # Build message list — system prompt goes first
        openrouter_messages = []

        active_system_prompt = system_prompt or config.SYSTEM_PROMPT
        if active_system_prompt:
            openrouter_messages.append({
                "role": "system",
                "content": active_system_prompt
            })

        # Add conversation history + new message
        openrouter_messages += [
            {"role": msg.role, "content": msg.openai_content()}
            for msg in messages
        ]

        # Image requests have their own backups: chat models may be text-only.
        backups = (config.OPENROUTER_VISION_BACKUP_MODELS if any(msg.images for msg in messages)
                   else config.OPENROUTER_BACKUP_MODELS)
        models = list(dict.fromkeys([self.model, *backups]))
        failures = []
        for model in models:
            try:
                return await self._complete_with(model, openrouter_messages, max_tokens, temperature, tools)
            except ProviderError as e:
                if "API key" in str(e):
                    raise  # a bad key fails every model the same way
                logger.warning(f"OpenRouter model {model} failed, trying the next: {e}")
                failures.append(f"{model}: {e}")
        raise ProviderError("Every OpenRouter model failed — " + " | ".join(failures))

    async def _complete_with(self, model, openrouter_messages, max_tokens, temperature, tools,
                             retried: bool = False) -> ProviderResponse:
        logger.debug(f"OpenRouter request — model: {model} | messages: {len(openrouter_messages)}")

        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=openrouter_messages,
                **({"tools": [t.openai_format() for t in tools]} if tools else {}),
            )

        except openai.AuthenticationError:
            # Bad or missing API key
            raise ProviderError(
                "OpenRouter API key is invalid or missing. "
                "Check OPENROUTER_API_KEY in your .env file."
            )

        except openai.RateLimitError:
            # Hit OpenRouter's rate limit or ran out of credits
            raise ProviderError(
                "OpenRouter rate limit hit or insufficient credits. "
                "Check your usage at openrouter.ai/activity"
            )

        except openai.APIConnectionError:
            # No internet or OpenRouter is down
            raise ProviderError(
                "Cannot connect to OpenRouter. "
                "Check your internet connection or try again shortly."
            )

        except openai.APIStatusError as e:
            # OpenRouter returned a 4xx or 5xx error
            raise ProviderError(
                f"OpenRouter returned an error: HTTP {e.status_code}. "
                f"Message: {e.message}"
            )

        except openai.APIError as e:
            # Catch-all for any other OpenAI SDK error
            raise ProviderError(f"OpenRouter API error: {str(e)}")

        # Safely extract the response content
        # Wrap in try/except in case the response shape is unexpected
        if not response.choices:
            # Free models sometimes answer HTTP 200 with {"error": {...}} instead of choices (upstream overloaded)
            error = (response.model_extra or {}).get("error") or {}
            raise ProviderError(f"OpenRouter returned no answer: {error.get('message', 'empty response')}")
        try:
            message = response.choices[0].message
            content = message.content or ""
            tool_calls = parse_openai_tool_calls(message.tool_calls)
        except (IndexError, AttributeError) as e:
            raise ProviderError(
                f"OpenRouter returned an unexpected response format: {str(e)}"
            )

        # A thinking model that runs out of tokens mid-thought: OpenRouter copies the unfinished reasoning into
        # the answer ("Okay, the user is asking to…"). Never show that — retry once with room to finish.
        reasoning = str((getattr(message, "model_extra", None) or {}).get("reasoning") or "").strip()
        if response.choices[0].finish_reason == "length" and not tool_calls and (
                not content.strip() or (reasoning and content.strip() == reasoning)):
            if retried or max_tokens >= THINKING_BUDGET:
                raise ProviderError("The model ran out of room while thinking and gave no answer")
            logger.info(f"OpenRouter {model} was still thinking at {max_tokens} tokens — retrying with {THINKING_BUDGET}")
            return await self._complete_with(model, openrouter_messages, THINKING_BUDGET, temperature, tools, retried=True)

        tokens_used = response.usage.total_tokens if response.usage else 0
        logger.info(f"OpenRouter response received — model: {model} | tokens: {tokens_used}")

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            provider="openrouter",
            model=getattr(response, "model", None) or model,
            tokens_used=tokens_used,
            metadata={
                "finish_reason": response.choices[0].finish_reason,
            }
        )

    def get_provider_name(self) -> str:
        return "openrouter"

    def get_model_name(self) -> str:
        return self.model
