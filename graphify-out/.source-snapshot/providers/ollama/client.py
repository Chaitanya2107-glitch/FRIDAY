"""
providers/ollama/client.py

Ollama (local models) implementation of BaseProvider.
Runs AI models entirely on your machine — no API key, no internet needed.

REQUIRES: Ollama installed and running locally (https://ollama.com)
          A model pulled: ollama pull gemma3:4b

To use: set ACTIVE_PROVIDER=ollama in .env
        set OLLAMA_MODEL=gemma3:4b (or any model you've pulled)

PHASE 2: Full error handling — connection errors, bad responses, timeouts.
"""

import math

import httpx
from providers.base_provider import BaseProvider, Message, ProviderResponse, Tool, ToolCall
from core.config import config
from core.logger import logger
from core.errors import ProviderError
from providers.ollama.runtime import local_http_options


def response_metrics(data):
    """Only finite numeric API metrics; missing values are unknown, never measured zero."""
    def number(key):
        value = data.get(key)
        return value if type(value) in (int, float) and 0 <= value <= 1e20 and math.isfinite(value) else None
    durations = {key + '_ms': round(number(key) / 1_000_000, 2) if number(key) is not None else None
                 for key in ('total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration')}
    reason = data.get('done_reason')
    return {**durations, **{key: number(key) for key in ('prompt_eval_count', 'prompt_eval_cached_count', 'eval_count')},
            'done_reason': reason if isinstance(reason, str) and reason in {'stop', 'length', 'load', 'unload'} else None,
            'incomplete': data.get('done') is False or reason == 'length'}


class OllamaProvider(BaseProvider):
    """Connects F.R.I.D.A.Y to locally-running Ollama models."""

    def __init__(self, model: str | None = None):
        self.base_url = config.OLLAMA_BASE_URL
        self.model = model or config.OLLAMA_MODEL
        logger.info(f"OllamaProvider initialised — model: {self.model} | url: {self.base_url}")

    async def complete(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: list[Tool] | None = None,
        response_schema: dict | None = None,
    ) -> ProviderResponse:
        from providers.ollama.runtime import runtime
        async with runtime.use(self.base_url):
            return await self._complete(messages, system_prompt, max_tokens, temperature, tools, response_schema)

    async def _complete(
        self,
        messages: list[Message],
        system_prompt: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: list[Tool] | None = None,
        response_schema: dict | None = None,
    ) -> ProviderResponse:
        """
        Send messages to local Ollama instance and return the response.
        Raises ProviderError on any failure — never leaks raw exceptions.
        """

        # Build conversation in Ollama's expected format
        ollama_messages = []

        # Add system prompt first if we have one
        active_system_prompt = system_prompt or config.SYSTEM_PROMPT
        if active_system_prompt:
            ollama_messages.append({
                "role": "system",
                "content": active_system_prompt
            })

        # Add the conversation history
        for msg in messages:
            entry = {"role": msg.role, "content": msg.content}
            if msg.images:
                entry["images"] = msg.images_base64()  # needs a vision model, e.g. gemma3:4b
            ollama_messages.append(entry)

        logger.debug(f"Ollama request — model: {self.model} | messages: {len(ollama_messages)}")

        try:
            async with httpx.AsyncClient(timeout=120.0, **local_http_options(self.base_url)) as client:
                # 120s timeout — local models can be slow on first load
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": ollama_messages,
                        "stream": False,  # Get the full response at once
                        "keep_alive": max(1, config.OLLAMA_IDLE_SECONDS),
                        **({"format": response_schema} if response_schema else {}),
                        **({"tools": [t.openai_format() for t in tools]} if tools else {}),
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                            **({"num_ctx": 16384} if response_schema else {}),
                        }
                    }
                )

                # This raises httpx.HTTPStatusError if Ollama returns 4xx or 5xx
                response.raise_for_status()
                data = response.json()

        except httpx.ConnectError:
            # Ollama isn't running at all
            raise ProviderError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running: open a terminal and run 'ollama serve'"
            )

        except httpx.TimeoutException:
            # Model took too long — probably too large for the machine
            raise ProviderError(
                f"Ollama timed out after 120 seconds. "
                f"Model '{self.model}' may be too large for this machine. "
                "Try a smaller model like gemma3:4b"
            )

        except httpx.HTTPStatusError as e:
            # Ollama returned an error status (e.g. model not found, or it can't use tools)
            raise ProviderError(
                f"Ollama returned HTTP {e.response.status_code}: {e.response.text[:200]}. "
                f"If the model is missing, run: ollama pull {self.model}"
            )

        except httpx.RequestError as e:
            # Any other network-level error
            raise ProviderError(f"Ollama network error: {str(e)}")

        # Safely extract the response content
        # Wrap in try/except in case Ollama returns an unexpected response shape
        try:
            content = data["message"]["content"] or ""
            # Ollama already decodes the arguments into a dict
            tool_calls = [
                ToolCall(name=call["function"]["name"], arguments=dict(call["function"].get("arguments") or {}))
                for call in data["message"].get("tool_calls") or []
            ]
        except (KeyError, TypeError, ValueError) as e:
            raise ProviderError(
                f"Ollama returned an unexpected response format. Raw response: {data}"
            )

        tokens_used = data.get("eval_count", 0)
        logger.info(f"Ollama response received — model: {self.model} | tokens: {tokens_used}")

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            provider="ollama",
            model=self.model,
            tokens_used=tokens_used,
            metadata=response_metrics(data)
        )

    async def complete_structured(self, schema: dict, **kwargs) -> ProviderResponse:
        return await self.complete(response_schema=schema, **kwargs)

    def get_provider_name(self) -> str:
        return "ollama"

    def get_model_name(self) -> str:
        return self.model
