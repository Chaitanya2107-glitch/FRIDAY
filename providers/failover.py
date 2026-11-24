"""
providers/failover.py

Runs a chat completion on the requested provider and, if it fails (outage,
rate limit, bad key, Ollama not running), retries on the fallback providers
from config — so one provider having a bad moment doesn't break FRIDAY.
While the laptop is offline it goes straight to the local Ollama model.
Configure with FALLBACK_PROVIDERS in .env (see core/config.py).
"""

import json
import re
from collections.abc import Callable

from core.config import config
from core.errors import ModelUnavailable, ProviderError
from core.logger import logger
from providers import execution
from providers.base_provider import Message, ProviderResponse
from services.network.status import network

require_enabled = execution.require_enabled
run_embedding = execution.run_embedding
DEFAULT_ATTEMPT_SECONDS = 25


def get_provider(name, model=None):
    require_enabled()
    from providers.registry import get_provider as create_provider
    return create_provider(name, model=model) if model else create_provider(name)


def model_state():
    from providers.ollama.runtime import runtime
    status = execution.status("ollama") | runtime.health()
    if status["needs_restart"] and status["status"] in {"idle", "ready"}:
        status["status"] = "unavailable"
    return status


def set_mode(mode):
    """Persist an owner setting and fence pending model responses when switched off."""
    if mode not in ("on", "off"):
        raise ValueError("Choose on or off for model assistance.")
    from services import settings_store
    with settings_store.lock:
        settings_store.save(config.MEMORY_DIR / "model-settings.json", {"mode": mode})
        changed = mode != config.FRIDAY_LLM
        config.FRIDAY_LLM = mode
        if changed:
            execution.reset()
            if mode == "off":
                execution.cancel_pending()
    return mode


async def prepare_local_model(*, timeout=25):
    require_enabled()
    from providers.ollama.runtime import runtime
    try:
        return await execution.run_async("ollama", runtime.prepare_model, timeout=timeout)
    except ModelUnavailable:
        raise
    except ProviderError as error:
        raise ModelUnavailable(error.message) from error


async def close_local_model():
    from providers.ollama.runtime import runtime
    await runtime.close()


async def run_local_model(operation, *, timeout=55):
    """Isolate private local-only protocols from configured provider failover."""
    return await execution.run_async("ollama", operation, timeout=timeout)


async def local_model_session(base_url, operation, *, timeout=55):
    """Run a private or maintenance operation against the single local endpoint."""
    require_enabled()
    from providers.ollama.runtime import runtime

    async def use():
        async with runtime.use(base_url):
            return await operation()

    return await run_local_model(use, timeout=timeout)


async def recover_local_model():
    """Watchdog recovery is limited to a previously started FRIDAY-owned server."""
    require_enabled()
    from providers.ollama.runtime import runtime
    return await run_local_model(runtime.recover_owned, timeout=max(2, config.OLLAMA_START_TIMEOUT_SECONDS + 2))


async def complete_provider(name, provider, *, attempt_timeout=None, response_schema=None,
                            pinned_model=None, on_text=None, **params):
    """Apply the same capacity, deadline and validation to a single provider attempt."""
    require_enabled()
    from providers.policy import check_allowed
    check_allowed()

    async def invoke():
        if pinned_model and name == "openrouter":
            messages = params["messages"]
            wire = [{"role": "system", "content": params["system_prompt"]},
                    *(dict(role=message.role, content=message.openai_content()) for message in messages)]
            result = await provider._complete_with(pinned_model, wire, params["max_tokens"], 0.7, None)
        elif on_text is not None:
            streamed = []
            async for piece in provider.stream(**params):
                if not isinstance(piece, str):
                    raise ModelUnavailable("The model returned invalid text.")
                require_enabled()
                streamed.append(piece)
                on_text(piece)
            result = ProviderResponse("".join(streamed), name, provider.get_model_name())
        else:
            structured = getattr(provider, "complete_structured", None)
            result = await (structured(response_schema, **params) if response_schema is not None and structured
                            else provider.complete(**params))
        content = getattr(result, "content", None)
        tools = getattr(result, "tool_calls", None)
        if not isinstance(content, str) or not content.strip() and not tools:
            raise ModelUnavailable("The model returned no usable response.")
        if tools and not params.get("tools"):
            raise ModelUnavailable("The model returned unexpected actions.")
        if response_schema is not None:
            try:
                raw = content.strip()
                if raw.startswith("```json\n") and raw.endswith("```"):
                    raw = raw[8:-3].strip()
                value = json.loads(raw)
                if (not isinstance(value, (dict, list)) or
                        (response_schema.get("type") == "object" and not isinstance(value, dict)) or
                        (isinstance(value, dict) and set(response_schema.get("required", ())) - value.keys())):
                    raise ValueError
            except ValueError as error:
                raise ModelUnavailable("The model returned invalid structured output.") from error
        return result

    timeout = attempt_timeout if attempt_timeout is not None else DEFAULT_ATTEMPT_SECONDS
    if name == "ollama":
        timeout += max(1, config.OLLAMA_START_TIMEOUT_SECONDS)
    return await execution.run_async(name, invoke, timeout=timeout)


async def complete_exact(name, messages, system_prompt, max_tokens, *, model=None, attempt_timeout=None,
                         pin_model=False, **kwargs):
    """No provider fallback. Approved vision uses one exact provider and model."""
    require_enabled()
    return await complete_provider(name, get_provider(name, model), messages=messages, system_prompt=system_prompt,
                                   max_tokens=max_tokens, pinned_model=model if pin_model else None,
                                   attempt_timeout=attempt_timeout, **kwargs)


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
    require_enabled()
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
        require_enabled()
        streamed: list[str] = []
        try:
            model = model_for(name) if model_for else None
            provider = get_provider(name, model=model) if model else get_provider(name)
            def feed(piece):
                streamed.append(piece)
                on_text(piece)

            response = await complete_provider(name, provider, messages=messages, system_prompt=system_prompt,
                                               max_tokens=max_tokens, attempt_timeout=attempt_timeout,
                                               response_schema=response_schema, on_text=feed if on_text else None,
                                               **complete_kwargs)
        except Exception as e:
            require_enabled()
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

    if isinstance(last_error, ModelUnavailable):
        raise last_error
    if has_images:
        raise ModelUnavailable("The vision AI is busy or unavailable right now (free models get rate-limited) — "
                            f"try again in a minute. Details — {'; '.join(failures)}")
    raise ModelUnavailable(
        "The AI provider failed to respond. Check your API keys and internet connection. "
        f"Details — {'; '.join(failures)}"
    ) from last_error
