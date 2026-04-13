"""
Inference Pipeline
==================

Chains RAG retrieval -> prompt construction -> LLM call -> response parsing.
Used by Coach and Puzzle Master agents for knowledge-grounded generation.

Pipeline Steps:
  1. Retrieve: Query RAG collections for relevant documents
  2. Construct: Build prompt from template + RAG context + game state
  3. Generate: Send prompt to LLM via LLMClient
  4. Parse: Extract structured information from LLM response (if needed)
  5. Validate: Check response quality / safety

Features:
  - Configurable pipeline stages (skip RAG, skip LLM, etc.)
  - Fallback chains (if RAG fails, use template-only prompt)
  - Response caching for repeated queries
  - Timing / metrics for each stage
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("inference.pipeline")


# ========================
#    PIPELINE RESULT
# ========================

@dataclass
class PipelineResult:
    """Output of the inference pipeline."""
    text: str                              # Final generated text
    rag_documents: list[dict] = field(default_factory=list)  # Retrieved docs
    prompt_used: str = ""                  # The full prompt sent to LLM
    provider: str = "mock"                 # Which LLM provider was used
    cached: bool = False                   # Whether result was from cache
    timings: dict[str, float] = field(default_factory=dict)  # Stage timings (ms)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "rag_document_count": len(self.rag_documents),
            "provider": self.provider,
            "cached": self.cached,
            "timings": self.timings,
            "error": self.error,
        }


# ========================
#   PIPELINE CONFIG
# ========================

@dataclass
class PipelineConfig:
    """Configuration for pipeline behavior."""
    enable_rag: bool = True           # Whether to retrieve RAG documents
    enable_llm: bool = True           # Whether to call LLM (False = template only)
    rag_top_k: int = 3                # Number of RAG documents to retrieve
    rag_collections: list[str] = field(
        default_factory=lambda: ["tactics", "beginner_principles"]
    )
    llm_temperature: float = 0.7
    llm_max_tokens: int = 256
    llm_provider: Optional[str] = None  # Override default provider
    cache_enabled: bool = True


# ========================
#   INFERENCE PIPELINE
# ========================

class InferencePipeline:
    """RAG + LLM inference pipeline for knowledge-grounded generation.

    Usage:
        pipeline = InferencePipeline(rag_retriever=retriever, llm_client=client)
        result = await pipeline.run(
            query="Why is the cannon powerful?",
            prompt_template=coach_explain_move_prompt,
            template_kwargs={"move_str": "b2e2", "side": "computer"},
        )
    """

    def __init__(
        self,
        rag_retriever: Any = None,
        llm_client: Any = None,
        config: Optional[PipelineConfig] = None,
    ):
        self._rag = rag_retriever      # tools.rag_retriever.RAGRetriever
        self._llm = llm_client         # tools.llm_client.LLMClient
        self._config = config or PipelineConfig()
        self._cache: dict[str, PipelineResult] = {}

    async def run(
        self,
        query: str,
        prompt_template: Any = None,
        template_kwargs: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        config_override: Optional[PipelineConfig] = None,
    ) -> PipelineResult:
        """Execute the full inference pipeline.

        Args:
            query: The retrieval query / user question.
            prompt_template: A callable(rag_context=..., **kwargs) -> str.
                             If None, query is used as the raw prompt.
            template_kwargs: Additional kwargs for the prompt template.
            system_prompt: System-level instruction for the LLM.
            config_override: Override the default pipeline config.

        Returns:
            PipelineResult with the generated text and metadata.
        """
        config = config_override or self._config
        template_kwargs = template_kwargs or {}
        timings: dict[str, float] = {}

        # Check cache
        cache_key = f"{query}:{hash(str(template_kwargs))}"
        if config.cache_enabled and cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.cached = True
            logger.debug(f"Pipeline cache hit for: {query[:50]}")
            return cached

        # Step 1: RAG Retrieval
        rag_context = ""
        rag_documents: list[dict] = []

        if config.enable_rag and self._rag:
            t0 = time.perf_counter()
            try:
                for collection in config.rag_collections:
                    docs = await self._rag.retrieve(
                        query=query,
                        collection=collection,
                        top_k=max(1, config.rag_top_k // len(config.rag_collections)),
                    )
                    rag_documents.extend(docs)

                # Sort by score, take top_k
                rag_documents.sort(key=lambda d: d.get("score", 0), reverse=True)
                rag_documents = rag_documents[:config.rag_top_k]

                # Build context string
                rag_context = "\n\n".join(
                    d.get("content", "") for d in rag_documents
                )
            except Exception as e:
                logger.error(f"RAG retrieval failed: {e}")

            timings["rag_ms"] = (time.perf_counter() - t0) * 1000

        # Step 2: Prompt Construction
        t0 = time.perf_counter()

        if prompt_template and callable(prompt_template):
            try:
                prompt = prompt_template(
                    rag_context=rag_context,
                    **template_kwargs,
                )
            except TypeError:
                # Template doesn't accept rag_context -- pass it separately
                prompt = prompt_template(**template_kwargs)
                if rag_context:
                    prompt = f"Reference knowledge:\n{rag_context}\n\n{prompt}"
        else:
            prompt = query
            if rag_context:
                prompt = f"Reference knowledge:\n{rag_context}\n\n{prompt}"

        timings["prompt_ms"] = (time.perf_counter() - t0) * 1000

        # Step 3: LLM Generation
        generated_text = ""

        if config.enable_llm and self._llm:
            t0 = time.perf_counter()
            try:
                generated_text = await self._llm.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=config.llm_temperature,
                    max_tokens=config.llm_max_tokens,
                    provider=config.llm_provider,
                )
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                generated_text = self._fallback_response(query)

            timings["llm_ms"] = (time.perf_counter() - t0) * 1000
        else:
            # No LLM: return the prompt itself or a fallback
            generated_text = self._fallback_response(query)
            timings["llm_ms"] = 0

        # Step 4: Build result
        result = PipelineResult(
            text=generated_text,
            rag_documents=rag_documents,
            prompt_used=prompt[:500],  # Truncate for storage
            provider=config.llm_provider or "default",
            timings=timings,
        )

        # Cache result
        if config.cache_enabled:
            self._cache[cache_key] = result

        logger.info(
            f"Pipeline complete: rag_docs={len(rag_documents)}, "
            f"text_len={len(generated_text)}, "
            f"timings={timings}"
        )

        return result

    def _fallback_response(self, query: str) -> str:
        """Generate a fallback response when LLM is unavailable."""
        query_lower = query.lower()

        if "blunder" in query_lower or "mistake" in query_lower:
            return (
                "That move may not have been the best choice. "
                "Consider looking for moves that protect your pieces "
                "while creating threats."
            )
        elif "why" in query_lower or "explain" in query_lower:
            return (
                "This involves a tactical pattern common in Xiangqi. "
                "Detailed explanations will be available once the "
                "language model is connected."
            )
        elif "hint" in query_lower:
            return "Look for the most active piece on the board."
        else:
            return (
                "I'll be able to provide more detailed coaching once "
                "the language model is configured."
            )

    def clear_cache(self) -> None:
        """Clear the pipeline result cache."""
        self._cache.clear()
        logger.debug("Pipeline cache cleared")

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @config.setter
    def config(self, new_config: PipelineConfig) -> None:
        self._config = new_config
