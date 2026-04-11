"""
LLM Client
===========

Wraps LLM API calls for the coaching system.
Supports multiple providers via the LLMRegistry.

Providers:
  - OpenAI (GPT-4, GPT-3.5-turbo)
  - Anthropic (Claude)
  - Local (Ollama, llama.cpp)
  - Mock (for testing without API keys)

Features:
  - Provider-agnostic interface: generate(prompt) -> str
  - Context injection (RAG snippets, game state)
  - Token counting and budget management
  - Response caching for repeated queries
  - Temperature and parameter control per request
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..LLM.LLMRegistry import LLMRegistry

logger = logging.getLogger("tools.llm_client")


# ========================
#      LLM CLIENT
# ========================

class LLMClient:
    """Provider-agnostic LLM client for the coaching system.

    Usage:
        registry = LLMRegistry()
        registry.register("openai", api_key="sk-...", model="gpt-4")
        client = LLMClient(registry=registry, default_provider="openai")
        response = await client.generate("Explain the cannon capture rule")
    """

    def __init__(
        self,
        registry: Optional[LLMRegistry] = None,
        default_provider: str = "mock",
        max_tokens: int = 512,
        temperature: float = 0.7,
    ):
        self._registry = registry or LLMRegistry()
        self._default_provider = default_provider
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._cache: dict[str, str] = {}
        self._total_tokens_used: int = 0

    # ---- Core Interface ----

    async def generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Generate a response from the LLM.

        Args:
            prompt: The user/task prompt.
            context: Additional context to prepend (RAG snippets, game state).
            temperature: Override default temperature.
            max_tokens: Override default max tokens.
            provider: Override default provider.
            system_prompt: System-level instruction for the LLM.

        Returns:
            Generated text string.
        """
        provider = provider or self._default_provider
        temp = temperature if temperature is not None else self._temperature
        tokens = max_tokens or self._max_tokens

        # Build full prompt with context
        full_prompt = self._build_prompt(prompt, context, system_prompt)

        # Check cache
        cache_key = f"{provider}:{hash(full_prompt)}:{temp}:{tokens}"
        if cache_key in self._cache:
            logger.debug("LLM cache hit")
            return self._cache[cache_key]

        # Get provider config
        config = self._registry.get_provider(provider)
        if config is None:
            logger.warning(
                f"Provider '{provider}' not registered, using mock"
            )
            return self._mock_generate(prompt)

        # Dispatch to provider
        try:
            if provider == "openrouter":
                response = await self._generate_openrouter(
                    full_prompt, config, temp, tokens, system_prompt
                )
            elif provider == "openai":
                response = await self._generate_openai(
                    full_prompt, config, temp, tokens, system_prompt
                )
            elif provider == "anthropic":
                response = await self._generate_anthropic(
                    full_prompt, config, temp, tokens, system_prompt
                )
            elif provider == "ollama":
                response = await self._generate_ollama(
                    full_prompt, config, temp, tokens, system_prompt
                )
            else:
                response = self._mock_generate(prompt)

            # Cache and track
            self._cache[cache_key] = response
            self._total_tokens_used += len(response.split())  # Rough estimate
            return response

        except Exception as e:
            logger.error(f"LLM generation failed ({provider}): {e}", exc_info=True)
            raise

    # ---- Provider Implementations ----

    async def _generate_openrouter(
        self,
        prompt: str,
        config: dict,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate using OpenRouter API (OpenAI-compatible).

        Retries once on 429/5xx. Timeout is 60s for free-tier models.
        """
        import asyncio
        import aiohttp

        base_url = config.get("url", "https://openrouter.ai/api/v1")
        endpoint = f"{base_url.rstrip('/')}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": config.get("model", "google/gemma-3-12b-it:free"),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {config.get('api_key', '')}",
            "Content-Type": "application/json",
            "HTTP-Referer": config.get("app_url", "http://localhost:5000"),
            "X-Title": config.get("app_name", "GuidedChineseChess"),
        }

        last_error: Exception | None = None
        for attempt in range(2):  # 1 initial + 1 retry
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        endpoint, json=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = (
                                data.get("choices", [{}])[0]
                                .get("message", {})
                                .get("content", "")
                            )
                            logger.info(
                                f"OpenRouter OK: model={data.get('model', '?')}, "
                                f"tokens={data.get('usage', {}).get('total_tokens', '?')}"
                            )
                            return content

                        error_text = await resp.text()
                        last_error = RuntimeError(
                            f"OpenRouter HTTP {resp.status}: {error_text[:200]}"
                        )
                        # Retry on rate-limit or server errors
                        if resp.status in (429, 500, 502, 503) and attempt == 0:
                            wait = 3
                            logger.warning(
                                f"OpenRouter {resp.status}, retrying in {wait}s..."
                            )
                            await asyncio.sleep(wait)
                            continue
                        raise last_error
            except aiohttp.ClientError as e:
                last_error = RuntimeError(f"OpenRouter connection error: {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                raise last_error from e

        raise last_error  # type: ignore[misc]

    async def _generate_openai(
        self,
        prompt: str,
        config: dict,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate using OpenAI API.

        Requires: pip install openai
        """
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=config.get("api_key"))

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await client.chat.completions.create(
                model=config.get("model", "gpt-4"),
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except ImportError:
            logger.error("openai package not installed")
            return self._mock_generate(prompt)

    async def _generate_anthropic(
        self,
        prompt: str,
        config: dict,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate using Anthropic API.

        Requires: pip install anthropic
        """
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=config.get("api_key"))

            response = await client.messages.create(
                model=config.get("model", "claude-3-sonnet-20240229"),
                max_tokens=max_tokens,
                system=system_prompt or "You are a helpful Xiangqi coach.",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return response.content[0].text
        except ImportError:
            logger.error("anthropic package not installed")
            return self._mock_generate(prompt)

    async def _generate_ollama(
        self,
        prompt: str,
        config: dict,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate using local Ollama server.

        Requires: Ollama running at http://localhost:11434
        """
        try:
            import aiohttp

            url = config.get("url", "http://localhost:11434/api/generate")
            payload = {
                "model": config.get("model", "llama3"),
                "prompt": prompt,
                "system": system_prompt or "",
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
                "stream": False,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("response", "")
                    else:
                        logger.error(f"Ollama returned status {resp.status}")
                        return self._mock_generate(prompt)
        except ImportError:
            logger.error("aiohttp package not installed")
            return self._mock_generate(prompt)
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            return self._mock_generate(prompt)

    def _mock_generate(self, prompt: str) -> str:
        """Return a mock response for testing.

        Provides context-aware stub responses based on keywords in the prompt.
        """
        prompt_lower = prompt.lower()

        if "blunder" in prompt_lower or "mistake" in prompt_lower:
            return (
                "That move loses material. Consider protecting your pieces "
                "before attacking. Look for moves that both defend and create "
                "threats at the same time."
            )
        elif "explain" in prompt_lower or "why" in prompt_lower:
            return (
                "This move improves the position by controlling key squares "
                "and developing pieces toward the center. In Xiangqi, "
                "controlling the center and activating rooks early "
                "are fundamental principles."
            )
        elif "hint" in prompt_lower:
            return (
                "Look at your strongest piece and think about "
                "where it can create the most pressure."
            )
        elif "teach" in prompt_lower or "learn" in prompt_lower:
            return (
                "In Xiangqi, each piece has unique movement rules. "
                "The Rook is the most powerful piece, moving any distance "
                "along ranks and files. The Cannon is unique: it moves "
                "like a Rook but captures by jumping over exactly one piece."
            )
        else:
            return (
                "I'm your Xiangqi coach. I can explain moves, "
                "warn about mistakes, give hints, and teach you "
                "concepts. What would you like to learn about?"
            )

    # ---- Prompt Construction ----

    def _build_prompt(
        self,
        prompt: str,
        context: Optional[str],
        system_prompt: Optional[str],
    ) -> str:
        """Build the full prompt with context injection."""
        parts = []
        if context:
            parts.append(f"Reference knowledge:\n{context}\n")
        parts.append(prompt)
        return "\n".join(parts)

    # ---- Stats ----

    @property
    def total_tokens_used(self) -> int:
        return self._total_tokens_used

    def clear_cache(self) -> None:
        """Clear the response cache."""
        self._cache.clear()
        logger.debug("LLM cache cleared")
