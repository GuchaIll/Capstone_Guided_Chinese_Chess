"""
Retrieval Request
=================

Structured request object for RAG retrieval, used by CoachAgent to express
*what* to retrieve and *why* without coupling coach logic to collection names.

The helper functions ``select_collections`` and ``build_metadata_filters``
translate the high-level request into concrete RAG parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ========================
#   RETRIEVAL REQUEST
# ========================

@dataclass
class RetrievalRequest:
    """Structured retrieval parameters for RAGManagerAgent.

    Attributes:
        query_text:   Natural-language search query.
        user_intent:  Coaching action that triggered this retrieval
                      (e.g. "blunder_warning", "explain_move", "teach").
        game_phase:   Current phase of the game ("opening", "middlegame",
                      "endgame"). Used to focus collection selection.
        player_skill: Player skill level from MemoryAgent / CoachingMode.
                      Used to filter documents by difficulty metadata.
        top_k:        Maximum number of documents to return.
        collections:  Explicit collection override. When non-empty,
                      ``select_collections`` will use this list directly.
        filters:      Explicit metadata filter override. When non-None,
                      ``build_metadata_filters`` will use this dict directly.
    """

    query_text: str
    user_intent: str = ""
    game_phase: str = ""
    player_skill: str = ""
    top_k: int = 3
    collections: List[str] = field(default_factory=list)
    filters: Optional[dict] = None


# ========================
#   COLLECTION SELECTION
# ========================

# Map intent → preferred collections (order matters: first = highest priority)
_INTENT_COLLECTIONS: dict[str, List[str]] = {
    "blunder_warning": ["tactics", "beginner_principles"],
    "explain_move":    ["tactics", "openings"],
    "why_question":    ["tactics", "openings", "endgames", "beginner_principles"],
    "hint":            ["tactics"],
    "teach":           ["openings", "tactics", "endgames", "beginner_principles"],
    "chat":            ["openings", "tactics", "endgames", "beginner_principles"],
}

# Map game_phase → collection that should be prepended
_PHASE_COLLECTION: dict[str, str] = {
    "opening":    "openings",
    "middlegame": "tactics",
    "endgame":    "endgames",
}

_ALL_COLLECTIONS = list(_INTENT_COLLECTIONS["teach"])  # all four


def select_collections(request: RetrievalRequest) -> List[str]:
    """Return an ordered list of collection names for *request*.

    Priority:
      1. Explicit ``request.collections`` override.
      2. Intent-based default, promoted with the game-phase collection.
      3. All collections as a safe fallback.
    """
    if request.collections:
        return request.collections

    base = list(_INTENT_COLLECTIONS.get(request.user_intent, _ALL_COLLECTIONS))

    # Promote the phase-appropriate collection to the front
    phase_coll = _PHASE_COLLECTION.get(request.game_phase, "")
    if phase_coll and phase_coll in base and base[0] != phase_coll:
        base.remove(phase_coll)
        base.insert(0, phase_coll)
    elif phase_coll and phase_coll not in base:
        base.insert(0, phase_coll)

    return base


# ========================
#   METADATA FILTERS
# ========================

def build_metadata_filters(request: RetrievalRequest) -> Optional[dict]:
    """Return a metadata filter dict for the retriever, or None for no filter.

    Priority:
      1. Explicit ``request.filters`` override.
      2. Skill-level difficulty filter (beginner/intermediate/advanced).
         Advanced players can see all documents (no filter applied).
    """
    if request.filters is not None:
        return request.filters

    skill = (request.player_skill or "").lower()
    if skill in ("beginner",):
        return {"difficulty": ["beginner", "all"]}
    if skill in ("intermediate",):
        return {"difficulty": ["beginner", "intermediate", "all"]}
    # advanced or unknown: no filter — retrieve everything
    return None
