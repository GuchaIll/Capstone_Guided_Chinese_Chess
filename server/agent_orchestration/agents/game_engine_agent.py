"""
Game Engine Agent
=================

Proxies interactions with the Rust Chinese Chess engine via WebSocket.
Wraps all engine commands: move, ai_move, legal_moves, suggest, reset, set_position.

Responsibilities:
  - Translate player move requests into engine protocol messages
  - Forward AI move requests to the engine
  - Relay legal move queries for UI highlighting
  - Detect tactical patterns from engine evaluation for puzzle creation
  - Undo/resign handling

This agent does NOT generate coaching content -- it only manages
board state via the engine. Coaching is handled by CoachAgent.
"""

from __future__ import annotations

from typing import Any, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#   MOVE ANALYSIS RESULT
# ========================

class MoveAnalysis:
    """Result of analyzing a player's move against the engine's suggestion."""

    def __init__(
        self,
        player_move: str,
        engine_best_move: str,
        player_eval: int,
        engine_eval: int,
    ):
        self.player_move = player_move
        self.engine_best_move = engine_best_move
        self.player_eval = player_eval
        self.engine_eval = engine_eval

    @property
    def eval_delta(self) -> int:
        """Centipawn loss: how much worse the player's move is vs engine's best."""
        return self.engine_eval - self.player_eval

    @property
    def is_blunder(self) -> bool:
        """A move losing >= 200 centipawns is considered a blunder."""
        return self.eval_delta >= 200

    @property
    def is_mistake(self) -> bool:
        """A move losing 100-199 centipawns is considered a mistake."""
        return 100 <= self.eval_delta < 200

    @property
    def is_inaccuracy(self) -> bool:
        """A move losing 50-99 centipawns is considered an inaccuracy."""
        return 50 <= self.eval_delta < 100

    def to_dict(self) -> dict:
        return {
            "player_move": self.player_move,
            "engine_best_move": self.engine_best_move,
            "player_eval": self.player_eval,
            "engine_eval": self.engine_eval,
            "eval_delta": self.eval_delta,
            "is_blunder": self.is_blunder,
            "is_mistake": self.is_mistake,
            "is_inaccuracy": self.is_inaccuracy,
        }


# ========================
#    GAME ENGINE AGENT
# ========================

class GameEngineAgent(AgentBase):
    """Proxy agent for the Rust Xiangqi engine.

    Communicates with the engine through EngineClient (tools/engine_client.py).
    All board-mutating operations go through this agent.
    """

    def __init__(self, engine_client: Any = None, enabled: bool = True):
        super().__init__(name="GameEngineAgent", enabled=enabled)
        self._engine = engine_client  # tools.engine_client.EngineClient instance
        self._last_eval: Optional[int] = None  # Track eval for blunder detection

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Dispatch engine operations based on the action kwarg.

        Expected kwargs:
            action (str): One of "move", "ai_move", "legal_moves",
                          "suggest", "reset", "set_position", "undo", "resign"
            move_str (str): Move in coordinate notation (for "move")
            square (str): Square coordinate (for "legal_moves")
            difficulty (int): AI depth (for "ai_move", "suggest")
            fen (str): FEN string (for "set_position")

        Returns:
            AgentResponse with engine result data.
        """
        action = kwargs.get("action", "")
        dispatch = {
            "move": self._handle_move,
            "ai_move": self._handle_ai_move,
            "legal_moves": self._handle_legal_moves,
            "suggest": self._handle_suggest,
            "reset": self._handle_reset,
            "set_position": self._handle_set_position,
            "undo": self._handle_undo,
            "resign": self._handle_resign,
        }

        handler = dispatch.get(action)
        if handler is None:
            return AgentResponse.from_error(
                self.name, f"Unknown engine action: {action}"
            )

        return await handler(state, **kwargs)

    # ---- Action Handlers ----

    async def _handle_move(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Validate and apply a player move.

        Before applying, gets the engine's suggestion to compute eval delta.
        Returns move analysis data for the CoachAgent to potentially warn.
        """
        move_str = kwargs.get("move_str", "")

        if not self._engine:
            return self._stub_response("move", {"move": move_str, "valid": True})

        # Step 1: Get engine's best move BEFORE applying player's move
        suggestion = await self._engine.get_suggestion(difficulty=4)
        engine_eval = suggestion.get("score", 0) if suggestion else 0
        engine_best = suggestion.get("move", "") if suggestion else ""

        # Step 2: Apply the player's move
        result = await self._engine.send_move(move_str)

        if result and result.get("valid"):
            # Compute blunder analysis
            analysis = MoveAnalysis(
                player_move=move_str,
                engine_best_move=engine_best,
                player_eval=result.get("score", 0),
                engine_eval=engine_eval,
            )
            self._last_eval = engine_eval

            return AgentResponse(
                source=self.name,
                response_type=ResponseType.BOARD_ACTION,
                message="Move applied.",
                data={
                    "move_result": result,
                    "analysis": analysis.to_dict(),
                    "fen": result.get("fen", ""),
                },
                # If it was a blunder, trigger coach warning
                follow_up_agent="CoachAgent" if analysis.is_blunder else None,
            )
        else:
            reason = result.get("reason", "Invalid move") if result else "Engine unavailable"
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.ERROR,
                message=f"Move rejected: {reason}",
                data={"move": move_str, "reason": reason},
            )

    async def _handle_ai_move(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Request the AI to generate and apply a move."""
        difficulty = kwargs.get("difficulty", 4)

        if not self._engine:
            return self._stub_response("ai_move", {"difficulty": difficulty})

        result = await self._engine.request_ai_move(difficulty=difficulty)

        if result and result.get("move"):
            self._last_eval = result.get("score", 0)
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.BOARD_ACTION,
                message=f"AI played: {result['move']}",
                data={
                    "ai_result": result,
                    "fen": result.get("fen", ""),
                    "move": result["move"],
                    "score": result.get("score", 0),
                    "nodes": result.get("nodes_searched", 0),
                },
            )
        else:
            return AgentResponse.from_error(
                self.name, result.get("message", "AI failed to generate a move")
            )

    async def _handle_legal_moves(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Return legal target squares for a piece at the given square."""
        square = kwargs.get("square", "")

        if not self._engine:
            return self._stub_response("legal_moves", {"square": square, "targets": []})

        result = await self._engine.get_legal_moves(square)

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={
                "square": square,
                "targets": result.get("targets", []) if result else [],
            },
        )

    async def _handle_suggest(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Get a suggestion without applying it."""
        difficulty = kwargs.get("difficulty", 4)

        if not self._engine:
            return self._stub_response("suggest", {"move": "e3e4", "score": 0})

        result = await self._engine.get_suggestion(difficulty=difficulty)

        if result and result.get("move"):
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.SUGGESTION,
                message=f"Suggested move: {result['move']}",
                data={
                    "move": result["move"],
                    "from": result.get("from", ""),
                    "to": result.get("to", ""),
                    "score": result.get("score", 0),
                    "nodes": result.get("nodes_searched", 0),
                },
            )
        else:
            return AgentResponse.from_error(self.name, "No suggestion available")

    async def _handle_reset(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Reset the board to starting position."""
        if self._engine:
            result = await self._engine.reset()
            fen = result.get("fen", "") if result else ""
        else:
            fen = ""

        self._last_eval = None
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.BOARD_ACTION,
            message="Game reset.",
            data={"fen": fen, "action": "reset"},
        )

    async def _handle_set_position(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Set the board to a specific FEN position."""
        fen = kwargs.get("fen", "")

        if self._engine:
            result = await self._engine.set_position(fen)
        else:
            result = {"fen": fen}

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.BOARD_ACTION,
            message="Position set.",
            data={"fen": fen, "action": "set_position"},
        )

    async def _handle_undo(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Undo the last move.

        TODO: Engine does not currently support undo via WebSocket.
        This will need a new engine endpoint or client-side state rollback.
        """
        self.logger.warning("Undo not yet implemented in engine protocol")
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.ERROR,
            message="Undo is not yet supported.",
            data={"action": "undo"},
        )

    async def _handle_resign(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Player resigns the game.

        TODO: Engine does not have a resign command. Handle client-side.
        """
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.BOARD_ACTION,
            message="You have resigned the game.",
            data={"action": "resign", "result": "opponent_wins"},
        )

    # ---- Helpers ----

    def _stub_response(self, action: str, data: dict) -> AgentResponse:
        """Return a stub response when engine client is not connected."""
        self.logger.warning(f"Engine client not connected. Stub for: {action}")
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message=f"[STUB] Engine action: {action}",
            data=data,
            metadata={"stub": True},
        )

    @property
    def last_eval(self) -> Optional[int]:
        return self._last_eval
