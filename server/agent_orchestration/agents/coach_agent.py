"""
Coach Agent
===========

Core teaching agent for the Guided Chinese Chess system.

Responsibilities:
  - Detect blunders by comparing player eval vs engine eval (eval delta)
  - Generate warnings with alternative move suggestions
  - Explain moves using RAG-retrieved Xiangqi knowledge
  - Answer "why" questions about positions and moves
  - Provide hints on request (without giving away the answer directly)
  - Deliver proactive tips based on player skill level (from MemoryAgent)
  - Offer mini-lessons when triggered by MemoryAgent skill gap detection

Uses:
  - RAGManagerAgent for retrieving domain knowledge
  - LLM client for generating natural language explanations
  - MemoryAgent for player history and skill tracking

.. deprecated::
    Replaced by CoachAgent in the Go coaching service (server/chess_coach/).
    Retained as fallback only. See AGENTS.md.
"""
from __future__ import annotations

import warnings as _warnings
_warnings.warn(
    "CoachAgent (Python) is deprecated — use Go CoachAgent instead.",
    DeprecationWarning, stacklevel=2,
)

from typing import Any, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType
from .retrieval_request import RetrievalRequest


# ========================
#    BLUNDER THRESHOLDS
# ========================

BLUNDER_THRESHOLD = 200   # >= 200 centipawn loss
MISTAKE_THRESHOLD = 100   # 100-199 centipawn loss
INACCURACY_THRESHOLD = 50 # 50-99 centipawn loss


# ========================
#     COACHING MODES
# ========================

class CoachingMode:
    """Defines the coach's interaction style based on player skill."""
    BEGINNER = "beginner"      # Verbose explanations, simple language
    INTERMEDIATE = "intermediate"  # Moderate detail, some jargon OK
    ADVANCED = "advanced"      # Terse, assumes knowledge of concepts


# ========================
#      COACH AGENT
# ========================

class CoachAgent(AgentBase):
    """Generates coaching responses: warnings, explanations, hints, lessons.

    Integrates with RAG for knowledge retrieval and LLM for response generation.
    Falls back to rule-based templates when LLM is unavailable.
    """

    def __init__(
        self,
        rag_agent: Any = None,
        llm_client: Any = None,
        memory_agent: Any = None,
        enabled: bool = True,
    ):
        super().__init__(name="CoachAgent", enabled=enabled)
        self._rag = rag_agent          # RAGManagerAgent instance
        self._llm = llm_client         # tools.llm_client.LLMClient instance
        self._memory = memory_agent    # MemoryAgent instance
        self._coaching_mode = CoachingMode.BEGINNER

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Route to the appropriate coaching sub-handler.

        Expected kwargs:
            coaching_action (str): One of "blunder_warning", "explain_move",
                "why_question", "hint", "teach", "general_chat"
            move_analysis (dict): From GameEngineAgent (for blunder detection)
            user_input (str): The player's question/text
            move_str (str): Move to explain
            topic (str): Teaching topic
        """
        action = kwargs.get("coaching_action", "general_chat")

        dispatch = {
            "blunder_warning": self._handle_blunder,
            "explain_move": self._handle_explain_move,
            "why_question": self._handle_why_question,
            "hint": self._handle_hint,
            "teach": self._handle_teach,
            "general_chat": self._handle_general_chat,
        }

        handler = dispatch.get(action, self._handle_general_chat)
        return await handler(state, **kwargs)

    # ---- Sub-handlers ----

    async def _handle_blunder(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Warn the player about a blunder and suggest alternatives."""
        from ..LLM.prompts import coach_blunder_warning_prompt

        analysis = kwargs.get("move_analysis", {})
        eval_delta = analysis.get("eval_delta", 0)
        player_move = analysis.get("player_move", "")
        engine_best = analysis.get("engine_best_move", "")

        # Determine severity
        if eval_delta >= BLUNDER_THRESHOLD:
            severity = "blunder"
            severity_msg = "This is a serious mistake."
        elif eval_delta >= MISTAKE_THRESHOLD:
            severity = "mistake"
            severity_msg = "This move is not optimal."
        else:
            severity = "inaccuracy"
            severity_msg = "A slightly better move was available."

        # Build base warning message (rule-based fallback)
        message = (
            f"{severity_msg} You played {player_move}, "
            f"but {engine_best} was stronger "
            f"(evaluation difference: {eval_delta} centipawns)."
        )

        # RAG enrichment via RetrievalRequest
        rag_context = ""
        if self._rag:
            request = RetrievalRequest(
                query_text=f"Xiangqi tactic {player_move} vs {engine_best}",
                user_intent="blunder_warning",
                game_phase=self._detect_game_phase(state),
                player_skill=self._coaching_mode,
            )
            rag_response = await self._rag.safe_handle(
                state, retrieval_request=request,
            )
            if rag_response.data.get("documents"):
                rag_context = "\n".join(rag_response.data["documents"][:2])

        # LLM enrichment using prompts.py template
        if self._llm:
            fen = getattr(state, "board_fen", "") if state else ""
            prompt = coach_blunder_warning_prompt(
                player_move=player_move,
                engine_best=engine_best,
                eval_delta=eval_delta,
                fen=fen,
                rag_context=rag_context,
                player_skill=self._coaching_mode,
            )
            message = await self._generate_llm_response(prompt)

        # Track mistake in memory
        if self._memory:
            await self._memory.safe_handle(
                state,
                memory_action="record_mistake",
                mistake_type=severity,
                move=player_move,
                better_move=engine_best,
                eval_delta=eval_delta,
            )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.WARNING,
            message=message,
            data={
                "severity": severity,
                "player_move": player_move,
                "engine_best": engine_best,
                "eval_delta": eval_delta,
                "rag_context": rag_context[:200] if rag_context else "",
            },
        )

    async def _handle_explain_move(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Explain why a specific move is good or bad."""
        from ..LLM.prompts import coach_explain_move_prompt

        move_str = kwargs.get("move_str", "")
        side = kwargs.get("side", "computer")

        # RAG via RetrievalRequest
        rag_context = ""
        if self._rag:
            request = RetrievalRequest(
                query_text=f"Xiangqi move explanation {move_str}",
                user_intent="explain_move",
                game_phase=self._detect_game_phase(state),
                player_skill=self._coaching_mode,
            )
            rag_response = await self._rag.safe_handle(
                state, retrieval_request=request,
            )
            if rag_response.data.get("documents"):
                rag_context = "\n".join(rag_response.data["documents"][:2])

        # Rule-based fallback
        message = f"The {side} played {move_str}."

        if self._llm:
            fen = getattr(state, "board_fen", "") if state else ""
            prompt = coach_explain_move_prompt(
                move_str=move_str,
                side=side,
                fen=fen,
                rag_context=rag_context,
                player_skill=self._coaching_mode,
            )
            message = await self._generate_llm_response(prompt)

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.TEXT,
            message=message,
            data={"move": move_str, "side": side},
        )

    async def _handle_why_question(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Answer a 'why' question from the player."""
        from ..LLM.prompts import coach_why_question_prompt

        user_input = kwargs.get("user_input", "")

        # RAG via RetrievalRequest
        rag_context = ""
        if self._rag:
            request = RetrievalRequest(
                query_text=user_input,
                user_intent="why_question",
                game_phase=self._detect_game_phase(state),
                player_skill=self._coaching_mode,
            )
            rag_response = await self._rag.safe_handle(
                state, retrieval_request=request,
            )
            if rag_response.data.get("documents"):
                rag_context = "\n".join(rag_response.data["documents"][:3])

        # Generate response
        if self._llm:
            fen = getattr(state, "board_fen", "") if state else ""
            last_move = getattr(state, "last_move", "") if state else ""
            conv_ctx = (
                state.get_conversation_context(3)
                if state and hasattr(state, "get_conversation_context")
                else None
            )
            prompt = coach_why_question_prompt(
                user_question=user_input,
                fen=fen,
                last_move=last_move,
                rag_context=rag_context,
                conversation_context=conv_ctx,
                player_skill=self._coaching_mode,
            )
            message = await self._generate_llm_response(prompt)
        else:
            message = (
                "That's a great question! "
                "I'll be able to give detailed explanations once "
                "the knowledge base is connected."
            )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.TEXT,
            message=message,
            data={"question": user_input},
        )

    async def _handle_hint(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Provide a hint without directly giving away the best move.

        Progressive hinting:
        1. First hint: general direction ("look at your rook")
        2. Second hint: more specific ("your rook can attack the cannon")
        3. Third hint: reveals the move
        """
        hint_level = kwargs.get("hint_level", 1)

        # TODO: Use engine suggestion + RAG to generate progressive hints
        # For now, delegate to engine for suggestion and wrap it
        messages_by_level = {
            1: "Look for a piece that can create a threat on the next move.",
            2: "Consider how your strongest piece can put pressure on your opponent.",
            3: "Ask for the full suggestion to see the best move.",
        }

        message = messages_by_level.get(hint_level, messages_by_level[1])

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.SUGGESTION,
            message=message,
            data={"hint_level": hint_level},
            # On level 3, suggest the orchestrator also invoke the engine for the move
            follow_up_agent="GameEngineAgent" if hint_level >= 3 else None,
        )

    async def _handle_teach(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Deliver a mini-lesson on a Xiangqi topic."""
        from ..LLM.prompts import coach_teach_prompt

        topic = kwargs.get("topic", kwargs.get("user_input", "basics"))

        # RAG via RetrievalRequest (teach queries all collections)
        rag_content = ""
        if self._rag:
            request = RetrievalRequest(
                query_text=topic,
                user_intent="teach",
                game_phase=self._detect_game_phase(state),
                player_skill=self._coaching_mode,
                top_k=5,
            )
            rag_response = await self._rag.safe_handle(
                state, retrieval_request=request,
            )
            docs = rag_response.data.get("documents", [])
            if docs:
                rag_content = "\n".join(docs)

        if self._llm and rag_content:
            prompt = coach_teach_prompt(
                topic=topic,
                rag_context=rag_content,
                player_skill=self._coaching_mode,
            )
            message = await self._generate_llm_response(prompt)
        else:
            message = (
                f"Let me tell you about {topic} in Chinese Chess. "
                f"This feature will provide detailed lessons once "
                f"the knowledge base is fully loaded."
            )

        # Track in memory that this topic was taught
        if self._memory:
            await self._memory.safe_handle(
                state, memory_action="record_lesson", topic=topic,
            )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.LESSON,
            message=message,
            data={"topic": topic},
        )

    async def _handle_general_chat(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Handle general conversation, optionally weaving in chess knowledge."""
        user_input = kwargs.get("user_input", "")

        if self._llm:
            message = await self._generate_llm_response(
                f"You are a friendly Xiangqi (Chinese Chess) coach. "
                f"The player says: '{user_input}'. Respond helpfully."
            )
        else:
            message = (
                "I'm your Chinese Chess coach! "
                "I can help with move explanations, hints, and lessons. "
                "Try asking 'why' about a move, or say 'teach me' to learn more."
            )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.TEXT,
            message=message,
            data={"input": user_input},
        )

    # ---- Helpers ----

    async def _generate_llm_response(self, prompt: str) -> str:
        """Generate a response using the LLM client.

        Falls back to the raw prompt if LLM is unavailable.
        """
        try:
            if self._llm:
                return await self._llm.generate(prompt)
        except Exception as e:
            self.logger.error(f"LLM generation failed: {e}")
            return f"[LLM error: {e}] I'm having trouble connecting to the language model. Please try again in a moment."

    def set_coaching_mode(self, mode: str) -> None:
        """Set the coaching verbosity level."""
        self._coaching_mode = mode
        self.logger.info(f"Coaching mode set to: {mode}")

    @staticmethod
    def _detect_game_phase(state: Any) -> str:
        """Estimate game phase from state (opening/middlegame/endgame)."""
        if state is None:
            return ""
        move_num = getattr(state, "move_number", 0)
        if move_num <= 10:
            return "opening"
        elif move_num <= 40:
            return "middlegame"
        elif move_num > 40:
            return "endgame"
        return ""
