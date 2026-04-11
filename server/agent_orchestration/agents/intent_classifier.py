"""
Intent Classifier Agent
=======================

Classifies user input into one of the predefined intents.
Routes to the appropriate downstream agent via the orchestrator.

Intents:
  MOVE          - Player submits a move (e.g., "e3e4", "move knight to c5")
  WHY_QUESTION  - Player asks why something happened ("why did you move there?")
  HINT_REQUEST  - Player asks for a hint ("give me a hint", "what should I do?")
  TEACH_ME      - Player requests a lesson ("teach me about cannons")
  GENERAL_CHAT  - General conversation not fitting other categories
  UNDO          - Player wants to undo last move
  RESIGN        - Player resigns the game

Approach:
  Phase 1: Keyword/regex-based classification (no LLM dependency)
  Phase 2: LLM-based router with few-shot examples for ambiguous inputs
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#     INTENT ENUM
# ========================

class Intent(str, Enum):
    MOVE = "move"
    WHY_QUESTION = "why_question"
    HINT_REQUEST = "hint_request"
    TEACH_ME = "teach_me"
    GENERAL_CHAT = "general_chat"
    UNDO = "undo"
    RESIGN = "resign"
    UNKNOWN = "unknown"


# ========================
#   INTENT AGENT -> AGENT MAPPING
# ========================

# Maps each intent to the agent name that should handle it
INTENT_ROUTING = {
    Intent.MOVE: "GameEngineAgent",
    Intent.WHY_QUESTION: "CoachAgent",
    Intent.HINT_REQUEST: "CoachAgent",
    Intent.TEACH_ME: "CoachAgent",
    Intent.GENERAL_CHAT: "CoachAgent",
    Intent.UNDO: "GameEngineAgent",
    Intent.RESIGN: "GameEngineAgent",
    Intent.UNKNOWN: "CoachAgent",
}


# ========================
#     KEYWORD PATTERNS
# ========================

# Ordered by priority: first match wins
_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    # Direct address to coach by name (Kimbo)
    (Intent.GENERAL_CHAT, re.compile(
        r"\bkimbo\b", re.IGNORECASE)),

    # Resign
    (Intent.RESIGN, re.compile(
        r"\b(resign|give up|i lose|surrender|quit game)\b", re.IGNORECASE)),

    # Undo
    (Intent.UNDO, re.compile(
        r"\b(undo|take back|go back|reverse|unmove)\b", re.IGNORECASE)),

    # Move: coordinate notation like "e3e4" or "a0a1"
    (Intent.MOVE, re.compile(
        r"^[a-i]\d[a-i]\d$")),

    # Move: natural language move requests
    (Intent.MOVE, re.compile(
        r"\b(move|play|place|put)\b.*\b(to|at|on)\b", re.IGNORECASE)),

    # Why question (also covers "explain" requests like "explain the flying elephant")
    (Intent.WHY_QUESTION, re.compile(
        r"\b(why|explain|reason|how come|what makes|what is|what are)\b", re.IGNORECASE)),

    # Hint request
    (Intent.HINT_REQUEST, re.compile(
        r"\b(hint|suggest|help|what should|best move|recommend|advice)\b",
        re.IGNORECASE)),

    # Teach me
    (Intent.TEACH_ME, re.compile(
        r"\b(teach|learn|lesson|tutorial|show me|tell me about|how (do|does|to))\b",
        re.IGNORECASE)),
]


# ========================
#     INTENT CLASSIFIER
# ========================

class IntentClassifierAgent(AgentBase):
    """Classifies user text input into a structured Intent.

    Phase 1 implementation uses keyword/regex matching.
    When an LLM client is provided, ambiguous inputs can be routed
    through the LLM for more accurate classification.
    """

    def __init__(self, llm_client: Any = None, enabled: bool = True):
        super().__init__(name="IntentClassifierAgent", enabled=enabled)
        self._llm_client = llm_client  # Optional: for Phase 2 LLM-based routing

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Classify the user's input text.

        Expected kwargs:
            user_input (str): The raw text from the user.

        Returns:
            AgentResponse with:
                data.intent: The classified Intent value
                data.confidence: Confidence score (1.0 for keyword match)
                data.raw_input: The original user input
                follow_up_agent: The agent that should handle this intent
        """
        user_input: str = kwargs.get("user_input", "")

        if not user_input.strip():
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.STATE_UPDATE,
                data={"intent": Intent.UNKNOWN, "confidence": 0.0,
                      "raw_input": user_input},
            )

        intent, confidence = self._classify_keywords(user_input)

        # Phase 2: If confidence is low and LLM is available, use LLM
        if confidence < 0.5 and self._llm_client is not None:
            intent, confidence = await self._classify_llm(user_input)

        target_agent = INTENT_ROUTING.get(intent, "CoachAgent")

        self.logger.info(
            f"Classified '{user_input[:50]}' -> {intent.value} "
            f"(confidence={confidence:.2f}, target={target_agent})"
        )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={
                "intent": intent,
                "confidence": confidence,
                "raw_input": user_input,
            },
            follow_up_agent=target_agent,
        )

    def _classify_keywords(self, text: str) -> tuple[Intent, float]:
        """Rule-based classification using regex patterns."""
        text_stripped = text.strip()

        for intent, pattern in _PATTERNS:
            if pattern.search(text_stripped):
                return intent, 1.0

        return Intent.GENERAL_CHAT, 0.3

    async def _classify_llm(self, text: str) -> tuple[Intent, float]:
        """LLM-based classification for ambiguous inputs.

        TODO: Implement when LLM client is integrated.
        Uses few-shot prompt with intent definitions and examples.
        """
        self.logger.debug(f"LLM classification not yet implemented for: {text}")
        return Intent.GENERAL_CHAT, 0.4
