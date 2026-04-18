"""
RAG Manager Agent
=================

Coordinates retrieval-augmented generation across Xiangqi knowledge collections.

Collections:
  - openings:           Opening theory, named openings, first-move principles
  - tactics:            Tactical patterns (forks, pins, discovered attacks, cannon screens)
  - endgames:           Endgame theory (K+R vs K, basic checkmates, fortress)
  - beginner_principles: General Xiangqi rules, piece movement, palace/river constraints

Responsibilities:
  - Route retrieval queries to the appropriate collection
  - Apply metadata filters (difficulty, piece type, game phase)
  - Cache frequently retrieved documents for reuse within a session
  - Provide a unified retrieve() interface for other agents
  - Support hybrid search (dense + sparse) when backend supports it

.. deprecated::
    Replaced by ChromaDB Retriever tool in the Go coaching service (server/chess_coach/).
    Retained as fallback only. See AGENTS.md.
"""
from __future__ import annotations

import warnings as _warnings
_warnings.warn(
    "RAGManagerAgent is deprecated — use Go ChromaDB Retriever tool instead.",
    DeprecationWarning, stacklevel=2,
)

from dataclasses import dataclass, field
from typing import Any, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#     RAG COLLECTIONS
# ========================

COLLECTIONS = {
    "openings": "Xiangqi opening theory and named opening systems",
    "tactics": "Tactical patterns, combinations, and forcing sequences",
    "endgames": "Endgame technique, basic checkmates, and fortress positions",
    "beginner_principles": "Rules, piece movement, palace and river constraints",
}


# ========================
#     DOCUMENT MODEL
# ========================

@dataclass
class Document:
    """A retrieved document from the knowledge base."""
    content: str
    collection: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "collection": self.collection,
            "score": self.score,
            "metadata": self.metadata,
        }


# ========================
#   RAG MANAGER AGENT
# ========================

class RAGManagerAgent(AgentBase):
    """Manages RAG retrieval across all Xiangqi knowledge collections.

    Uses a pluggable retriever backend (tools/rag_retriever.py).
    Falls back to mock/empty results when no backend is configured.
    """

    def __init__(
        self,
        retriever: Any = None,
        enabled: bool = True,
    ):
        super().__init__(name="RAGManagerAgent", enabled=enabled)
        self._retriever = retriever  # tools.rag_retriever.RAGRetriever instance
        self._cache: dict[str, list[Document]] = {}
        self._cache_ttl: int = 50  # Cache up to N unique queries per session

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Retrieve documents from the knowledge base.

        Expected kwargs:
            query (str): The search query (natural language or keywords)
            collection (str): Target collection name (or "all" for cross-collection)
            top_k (int): Number of documents to retrieve (default 3)
            filters (dict): Metadata filters (e.g., {"difficulty": "beginner"})
            retrieval_request (RetrievalRequest): Structured request (overrides above)

        Returns:
            AgentResponse with:
                data.documents: List of document content strings
                data.sources: List of Document dicts with scores and metadata
        """
        # Support structured RetrievalRequest
        from .retrieval_request import (
            RetrievalRequest,
            select_collections,
            build_metadata_filters,
        )

        request = kwargs.get("retrieval_request")
        if isinstance(request, RetrievalRequest):
            query = request.query_text
            collections = select_collections(request)
            top_k = request.top_k
            filters = build_metadata_filters(request) or {}
        else:
            query = kwargs.get("query", "")
            collection = kwargs.get("collection", "all")
            collections = [collection] if collection != "all" else list(COLLECTIONS.keys())
            top_k = kwargs.get("top_k", 3)
            filters = kwargs.get("filters", {})

        if not query:
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.STATE_UPDATE,
                data={"documents": [], "sources": []},
            )

        # Check cache
        colls_key = ",".join(sorted(collections))
        cache_key = f"{colls_key}:{query}:{top_k}"
        if cache_key in self._cache:
            self.logger.debug(f"Cache hit for: {cache_key[:60]}")
            docs = self._cache[cache_key]
            return self._build_response(docs)

        # Retrieve from backend
        docs = await self._retrieve_multi(query, collections, top_k, filters)

        # Update cache
        if len(self._cache) < self._cache_ttl:
            self._cache[cache_key] = docs

        return self._build_response(docs)

    async def _retrieve_multi(
        self,
        query: str,
        collections: list[str],
        top_k: int,
        filters: dict,
    ) -> list[Document]:
        """Retrieve from multiple collections and merge results."""
        if not self._retriever:
            self.logger.debug(
                f"No retriever configured. Returning mock for: {query[:50]}"
            )
            return self._mock_retrieve(query, collections[0] if collections else "all")

        try:
            all_docs = []
            per_coll_k = max(1, top_k // len(collections)) if collections else top_k

            for coll_name in collections:
                results = await self._retriever.retrieve(
                    query=query,
                    collection=coll_name,
                    top_k=per_coll_k,
                    filters=filters if filters else None,
                )
                all_docs.extend([
                    Document(
                        content=r["content"],
                        collection=coll_name,
                        score=r.get("score", 0.0),
                        metadata=r.get("metadata", {}),
                    )
                    for r in results
                ])

            # Sort by score descending and return top_k
            all_docs.sort(key=lambda d: d.score, reverse=True)
            return all_docs[:top_k]
        except Exception as e:
            self.logger.error(f"Retrieval failed: {e}")
            return []

    async def _retrieve(
        self,
        query: str,
        collection: str,
        top_k: int,
        filters: dict,
    ) -> list[Document]:
        """Execute retrieval against the backend.

        If retriever is not configured, returns mock results.
        """
        if not self._retriever:
            self.logger.debug(
                f"No retriever configured. Returning mock for: {query[:50]}"
            )
            return self._mock_retrieve(query, collection)

        try:
            if collection == "all":
                # Cross-collection search
                all_docs = []
                for coll_name in COLLECTIONS:
                    results = await self._retriever.retrieve(
                        query=query,
                        collection=coll_name,
                        top_k=max(1, top_k // len(COLLECTIONS)),
                        filters=filters,
                    )
                    all_docs.extend([
                        Document(
                            content=r["content"],
                            collection=coll_name,
                            score=r.get("score", 0.0),
                            metadata=r.get("metadata", {}),
                        )
                        for r in results
                    ])
                # Sort by score and return top_k
                all_docs.sort(key=lambda d: d.score, reverse=True)
                return all_docs[:top_k]
            else:
                results = await self._retriever.retrieve(
                    query=query,
                    collection=collection,
                    top_k=top_k,
                    filters=filters,
                )
                return [
                    Document(
                        content=r["content"],
                        collection=collection,
                        score=r.get("score", 0.0),
                        metadata=r.get("metadata", {}),
                    )
                    for r in results
                ]
        except Exception as e:
            self.logger.error(f"Retrieval failed: {e}")
            return []

    def _mock_retrieve(self, query: str, collection: str) -> list[Document]:
        """Return placeholder documents for development/testing."""
        mock_data = {
            "openings": Document(
                content=(
                    "The Central Cannon Opening (Zhong Pao) is the most popular "
                    "opening in Xiangqi. Red moves the cannon to the central file "
                    "to attack the opponent's central pawn and exert pressure."
                ),
                collection="openings",
                score=0.8,
                metadata={"topic": "central_cannon", "difficulty": "beginner"},
            ),
            "tactics": Document(
                content=(
                    "A double cannon checkmate (Shuang Pao) uses two cannons on "
                    "the same file or rank with a screen piece between them. "
                    "This is one of the most powerful tactical patterns."
                ),
                collection="tactics",
                score=0.8,
                metadata={"topic": "double_cannon", "difficulty": "intermediate"},
            ),
            "endgames": Document(
                content=(
                    "In Rook vs King endgames, the side with the rook should use "
                    "the rook to cut off the opponent's king to the edge of the "
                    "board, then deliver checkmate with king support."
                ),
                collection="endgames",
                score=0.8,
                metadata={"topic": "rook_vs_king", "difficulty": "beginner"},
            ),
            "beginner_principles": Document(
                content=(
                    "In Xiangqi, the Elephant (Xiang) can only move diagonally "
                    "two points and cannot cross the river. It is blocked if a "
                    "piece occupies the diagonal intersection (elephant eye)."
                ),
                collection="beginner_principles",
                score=0.8,
                metadata={"topic": "elephant_movement", "difficulty": "beginner"},
            ),
        }
        if collection in mock_data:
            return [mock_data[collection]]
        return list(mock_data.values())

    def _build_response(self, docs: list[Document]) -> AgentResponse:
        """Build a standardized response from retrieved documents."""
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={
                "documents": [d.content for d in docs],
                "sources": [d.to_dict() for d in docs],
                "count": len(docs),
            },
        )

    def clear_cache(self) -> None:
        """Clear the retrieval cache (e.g., on new game)."""
        self._cache.clear()
        self.logger.debug("RAG cache cleared")

    async def on_game_start(self) -> None:
        """Clear cache at the start of each game."""
        self.clear_cache()
        await super().on_game_start()
