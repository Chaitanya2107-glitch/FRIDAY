"""
providers/failover.py

Runs a chat completion on the requested provider and, if it fails (outage,
rate limit, bad key, Ollama not running), retries on the fallback providers
from config — so one provider having a bad moment doesn't break FRIDAY.
While the laptop is offline it goes straight to the local Ollama model.
Configure with FALLBACK_PROVIDERS in .env (see core/config.py).
"""

import asyncio
import re
from collections.abc import Callable

from core.config import config
from core.errors import ProviderError
from core.logger import logger
from providers.base_provider import Message, ProviderResponse
from providers.registry import get_provider
from services.network.status import network


# Local (Ollama) models that can see images; others are skipped for image requests
OLLAMA_VISION_MODEL = re.compile(r"llava|vision|[-.]vl\b|vl:|minicpm-v|moondream|gemma3|gemma4|bakllava|granite.*vision", re.I)

# Words that mean the message needs the main (stronger) model
_NEEDS_STRONG_MODEL = re.compile(
    r"\b(code|coding|script|program|function|bug|debug|error|explain|why|analy[sz]e|compare|"
    r"plan|essay|write|draft|summari[sz]e|translate|calculate|solve|math|prove|step by step|"
    r"pros and cons|difference between|how (?:does|do|to|can))\b",
    re.IGNORECASE,
)
QUICK_CHAT_MAX_WORDS = 15


def is_quick_chat(message: str, provider_name: str, has_context: bool = False) -> bool:
    """
    Short, simple chat ("how are you", "capital of Australia") that the local model answers in
    under a second, instead of the main model's 5–12 s (QUICK_CHAT_LOCAL; see complete_with_failover).
    ponytail: keyword + length heuristic; ask a classifier model if it misroutes too often.
    """
    return (
        config.QUICK_CHAT_LOCAL
        and provider_name == config.ACTIVE_PROVIDER  # a provider picked for this request is kept
        and not has_context                          # answering from files/web results
        and len(message.split()) <= QUICK_CHAT_MAX_WORDS
        and not _NEEDS_STRONG_MODEL.search(message)
    )


def provider_chain(primary: str) -> list[str]:
    """
    The requested provider first, then the configured fallbacks, without repeats.
    Offline (services/network/status.py), only the local model: API calls would just time out.
    """
    from providers.policy import purpose
    if purpose.get() in {"cognitive_review", "notification_review", "inquiry"}:
        # Background judgement stays on this machine, even if Ollama fails.
        return ["ollama"] if config.provider_is_configured("ollama") else []
    if config.AI_ASSIST_ONLY:
        # Only these two providers are used for the optional assistance layer.
        chain = ["ollama"] if primary == "ollama" else ["openrouter", "ollama"]
        return network.usable([name for name in chain if config.provider_is_configured(name)])
    chain = [primary]
    for name in config.fallback_providers():
        if name not in chain:
            chain.append(name)
    return network.usable(chain)


async def complete_with_failover(*args, **kwargs) -> ProviderResponse:
    """_complete_with_failover, with FRIDAY's body showing thinking dots meanwhile (services/body_state.py)."""
    from services import body_state  # late: providers load before services

    from providers.policy import check_allowed, purpose
    task = kwargs.pop("purpose", None)
    check_allowed(task)
    if (config.AI_ASSIST_ONLY or task in {"cognitive_review", "notification_review", "inquiry", "understanding", "conversation", "automation_proposal"}) and kwargs.get("tools"):
        raise ProviderError("Models cannot choose or run FRIDAY's actions.")
    token = purpose.set(task)
    try:
        with body_state.thinking():
            return await _complete_with_failover(*args, **kwargs)
    finally:
        purpose.reset(token)


async def _complete_with_failover(
    provider_name: str,
    messages: list[Message],
    system_prompt: str,
    max_tokens: int,
    model_for: Callable[[str], str | None] | None = None,
    on_text: Callable[[str], None] | None = None,
    prefer_local: bool = False,
    response_schema: dict | None = None,
    attempt_timeout: float | None = None,
    **complete_kwargs,
) -> ProviderResponse:
    """
    Return the first successful response along the provider chain.
    prefer_local tries the local Ollama model first (quick chat), then the usual chain.
    model_for(provider) can pick a model per provider (None = its .env model).
    on_text streams the reply: it's called with each piece of text as it arrives.
    Once any text has arrived there's no switching provider (it may already be
    spoken) — a failure then returns what came so far, marked "incomplete".
    Raises ProviderError, listing each provider's error, only if all of them fail.
    """
    failures = []
    last_error = None
    chain = provider_chain(provider_name)
    if prefer_local and config.provider_is_configured("ollama"):
        chain = ["ollama"] + [name for name in chain if name != "ollama"]
    has_images = any(m.images for m in messages)
    if has_images:  # a model that can't see would answer anyway — making up what's in the picture
        local = (model_for("ollama") if model_for else None) or config.OLLAMA_MODEL
        chain = [name for name in chain if name != "ollama" or OLLAMA_VISION_MODEL.search(local)]
        if not chain:
            raise ProviderError("Reading images needs a vision AI, and the local model can't see "
                                f"({local}). Try again when you're online.")
    for name in chain:
        streamed: list[str] = []
        try:
            model = model_for(name) if model_for else None
            provider = get_provider(name, model=model) if model else get_provider(name)
            if on_text is None:
                structured = getattr(provider, "complete_structured", None)
                params = dict(messages=messages, system_prompt=system_prompt, max_tokens=max_tokens, **complete_kwargs)
                completion = structured(response_schema, **params) if response_schema is not None and structured else provider.complete(**params)
                timeout = attempt_timeout + max(1, config.OLLAMA_START_TIMEOUT_SECONDS) if attempt_timeout and name == "ollama" else attempt_timeout
                response = await asyncio.wait_for(completion, timeout=timeout) if timeout else await completion
            else:
                async for text in provider.stream(
                    messages=messages, system_prompt=system_prompt, max_tokens=max_tokens, **complete_kwargs,
                ):
                    streamed.append(text)
                    on_text(text)
                # ponytail: no token counts while streaming; ask for stream usage if cost tracking needs it
                response = ProviderResponse(
                    content="".join(streamed), provider=name, model=provider.get_model_name(),
                )
        except Exception as e:
            last_error = e
            if streamed:
                logger.warning(f"AI provider {name} failed part-way through a reply: {e}")
                return ProviderResponse(
                    content="".join(streamed), provider=name, model=provider.get_model_name(),
                    metadata={"incomplete": True},
                )
            # Providers raise their SDKs' own exception types, so catch broadly.
            logger.warning(f"AI provider {name} failed: {e}")
            failures.append(f"{name}: {str(e) or type(e).__name__}")
            continue

        if failures:
            logger.warning(f"Answered by fallback provider {name} after: {'; '.join(failures)}")
        return response

    if has_images:
        raise ProviderError("The vision AI is busy or unavailable right now (free models get rate-limited) — "
                            f"try again in a minute. Details — {'; '.join(failures)}")
    raise ProviderError(
        "The AI provider failed to respond. Check your API keys and internet connection. "
        f"Details — {'; '.join(failures)}"
    ) from last_error
