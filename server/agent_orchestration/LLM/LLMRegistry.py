"""
LLM Registry
=============

Registry for managing LLM provider configurations.
Supports multiple providers (OpenAI, Anthropic, Ollama, Mock)
and allows switching between them at runtime.

Usage:
    registry = LLMRegistry()
    registry.register("openai", api_key="sk-...", model="gpt-4")
    registry.register("ollama", url="http://localhost:11434", model="llama3")
    config = registry.get_provider("openai")
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("llm.registry")


# ========================
#     PROVIDER CONFIG
# ========================

class ProviderConfig:
    """Configuration for a single LLM provider."""

    def __init__(
        self,
        name: str,
        api_key: str = "",
        model: str = "",
        url: str = "",
        max_tokens: int = 512,
        temperature: float = 0.7,
        **extra: Any,
    ):
        self.name = name
        self.api_key = api_key
        self.model = model
        self.url = url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra = extra

    def to_dict(self, redact: bool = False) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "url": self.url,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "api_key": ("***" if self.api_key else "") if redact else self.api_key,
            **self.extra,
        }


# ========================
#     LLM REGISTRY
# ========================

class LLMRegistry:
    """Central registry for LLM provider configurations.

    Manages provider registration, lookup, and default selection.
    Supports environment variable loading for API keys.
    """

    def __init__(self):
        self._providers: dict[str, ProviderConfig] = {}
        self._default_provider: str = "mock"

        # Register the mock provider by default
        self.register(
            name="mock",
            model="mock-v1",
            url="",
            api_key="",
        )

    def register(
        self,
        name: str,
        api_key: str = "",
        model: str = "",
        url: str = "",
        max_tokens: int = 512,
        temperature: float = 0.7,
        **extra: Any,
    ) -> None:
        """Register an LLM provider configuration.

        Args:
            name: Provider identifier (e.g., "openai", "anthropic", "ollama")
            api_key: API key for authentication
            model: Model name/identifier
            url: API endpoint URL (for self-hosted models)
            max_tokens: Default max tokens for this provider
            temperature: Default temperature for this provider
            **extra: Additional provider-specific settings
        """
        config = ProviderConfig(
            name=name,
            api_key=api_key,
            model=model,
            url=url,
            max_tokens=max_tokens,
            temperature=temperature,
            **extra,
        )
        self._providers[name] = config
        logger.info(f"Registered LLM provider: {name} (model={model})")

    def get_provider(self, name: Optional[str] = None) -> Optional[dict]:
        """Get a provider configuration by name.

        Args:
            name: Provider name. If None, returns the default provider.

        Returns:
            Provider config dict, or None if not found.
        """
        name = name or self._default_provider
        config = self._providers.get(name)
        if config is None:
            logger.warning(f"Provider '{name}' not found in registry")
            return None
        return config.to_dict()

    def set_default(self, name: str) -> bool:
        """Set the default provider.

        Returns True if the provider exists and was set as default.
        """
        if name in self._providers:
            self._default_provider = name
            logger.info(f"Default provider set to: {name}")
            return True
        logger.warning(f"Cannot set default: provider '{name}' not registered")
        return False

    def list_providers(self) -> list[str]:
        """List all registered provider names."""
        return list(self._providers.keys())

    def remove(self, name: str) -> bool:
        """Remove a provider from the registry."""
        if name in self._providers:
            del self._providers[name]
            if self._default_provider == name:
                self._default_provider = "mock"
            logger.info(f"Removed provider: {name}")
            return True
        return False

    @staticmethod
    def from_env() -> "LLMRegistry":
        """Create a registry pre-populated from environment variables.

        Looks for (in priority order):
            LLM_PROVIDER             - Explicit default provider name
            OPENROUTER_API_KEY       - OpenRouter (200+ models via one key)
            OPENAI_API_KEY           - OpenAI direct
            ANTHROPIC_API_KEY        - Anthropic / Claude
            OLLAMA_URL               - Local Ollama server
        """
        import os
        from dotenv import load_dotenv
        load_dotenv()

        registry = LLMRegistry()
        explicit_default = os.environ.get("LLM_PROVIDER", "").strip().lower()
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "256"))
        temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))

        # ---- OpenRouter ----
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if openrouter_key:
            registry.register(
                name="openrouter",
                api_key=openrouter_key,
                model=os.environ.get(
                    "OPENROUTER_MODEL",
                    "google/gemma-3-12b-it:free",
                ),
                url=os.environ.get(
                    "OPENROUTER_BASE_URL",
                    "https://openrouter.ai/api/v1",
                ),
                max_tokens=max_tokens,
                temperature=temperature,
                # OpenRouter extra headers for analytics
                app_name=os.environ.get("OPENROUTER_APP_NAME", "GuidedChineseChess"),
                app_url=os.environ.get("OPENROUTER_APP_URL", "http://localhost:5000"),
            )

        # ---- OpenAI ----
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            registry.register(
                name="openai",
                api_key=openai_key,
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                max_tokens=max_tokens,
                temperature=temperature,
            )

        # ---- Anthropic ----
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            registry.register(
                name="anthropic",
                api_key=anthropic_key,
                model=os.environ.get(
                    "ANTHROPIC_MODEL", "claude-3-haiku-20240307"
                ),
                max_tokens=max_tokens,
                temperature=temperature,
            )

        # ---- Ollama (local) ----
        ollama_url = os.environ.get("OLLAMA_URL", "").strip()
        if ollama_url:
            registry.register(
                name="ollama",
                url=ollama_url,
                model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
                max_tokens=max_tokens,
                temperature=temperature,
            )

        # ---- Set default provider ----
        # Explicit LLM_PROVIDER env var overrides auto-detection
        if explicit_default and explicit_default != "mock":
            registry.set_default(explicit_default)
        elif openrouter_key:
            registry.set_default("openrouter")
        elif openai_key:
            registry.set_default("openai")
        elif anthropic_key:
            registry.set_default("anthropic")
        elif ollama_url:
            registry.set_default("ollama")
        # else: stays "mock" (default)

        logger.info(
            f"LLMRegistry loaded: providers={registry.list_providers()}, "
            f"default={registry._default_provider}"
        )
        return registry
