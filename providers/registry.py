"""
providers/registry.py

Provider registry — maps provider names to their implementations.

This is the ONLY file that knows which provider classes exist.
The rest of the system calls get_provider() and doesn't care what's behind it.

TO ADD A NEW PROVIDER:
  1. Create providers/yourprovider/client.py with a class inheriting BaseProvider
  2. Add an elif branch here
  3. That's all — nothing else needs to change

CURRENT PROVIDERS:
  openrouter  ← DEFAULT (one key, 200+ models)
  anthropic   ← direct Anthropic API
  openai      ← direct OpenAI API
  ollama      ← local models, no API key needed
"""

from providers.base_provider import BaseProvider
from core.errors import ConfigError


def get_provider(name: str, model: str | None = None) -> BaseProvider:
    """
    Factory function. Returns a ready-to-use provider instance.

    Args:
        name:  Provider identifier — "openrouter" | "anthropic" | "openai" | "ollama"
        model: Optional model override. Defaults to that provider's model from .env.

    Returns:
        An instance of the requested provider

    Raises:
        ConfigError: If the provider name isn't recognised (bad .env value)
    """

    # Imports are inside the if-branches intentionally.
    # This means we only load (and require) the libraries for the provider
    # that's actually being used. You don't need openai installed to use anthropic.

    from providers.policy import check_allowed
    check_allowed()
    if name == "openrouter":
        from providers.openrouter.client import OpenRouterProvider
        return OpenRouterProvider(model)

    elif name == "anthropic":
        from providers.anthropic.client import AnthropicProvider
        return AnthropicProvider(model)

    elif name == "openai":
        from providers.openai.client import OpenAIProvider
        return OpenAIProvider(model)

    elif name == "ollama":
        from providers.ollama.client import OllamaProvider
        return OllamaProvider(model)

    else:
        # ConfigError — not a code bug, it's a bad ACTIVE_PROVIDER value in .env
        raise ConfigError(
            f"Unknown provider: '{name}'. "
            f"Valid options: openrouter | anthropic | openai | ollama. "
            f"Check ACTIVE_PROVIDER in your .env file."
        )


def list_providers() -> list[str]:
    """Return all registered provider names."""
    return ["openrouter", "anthropic", "openai", "ollama"]
