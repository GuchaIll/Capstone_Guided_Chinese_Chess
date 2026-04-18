"""
Session State
=============

Shared state dataclass passed between agents during orchestration.
Tracks the current game context, conversation history, and ephemeral
flags (puzzle mode, warning state, etc.).

This is the single source of truth for the current session.
Agents read from and write to this state via the Orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ========================
#     TURN PHASE
# ========================

class TurnPhase(str, Enum):
    """Current phase of the game turn cycle."""
    COMPUTER_TURN = "computer_turn"     # AI is making a move
    PLAYER_TURN = "player_turn"         # Waiting for player input
    OUTPUT = "output"                   # Formatting and delivering response
    PUZZLE = "puzzle"                   # Player is solving a puzzle
    IDLE = "idle"                       # Between games or waiting


# ========================
#   CONVERSATION ENTRY
# ========================

@dataclass
class ConversationEntry:
    """A single entry in the conversation history."""
    role: str               # "user", "coach", "system", "puzzle_master"
    content: str
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ========================
#     SESSION STATE
# ========================

@dataclass
class SessionState:
    """Complete session state shared across all agents.

    This dataclass is passed to every agent's handle() method.
    Agents can read any field but should only write through
    the Orchestrator's update methods.

    Attributes:
        board_fen: Current board position in FEN notation
        side_to_move: "red" or "black"
        game_result: "in_progress", "red_wins", "black_wins", "draw"
        turn_phase: Current turn phase
        move_number: Current full-move number
        last_move: Last move played (coordinate notation)
        last_eval: Engine evaluation of current position (centipawns)
        is_check: Whether the current side is in check
        puzzle_mode: Whether puzzle mode is active
        warning_state: Whether a warning is pending acknowledgment
        player_side: Which side the human is playing ("red" or "black")
        difficulty: AI search depth / difficulty level
        conversation_history: Recent conversation for context
        pending_actions: Queue of actions for the orchestrator to process
    """
    # Board state (synced with Rust engine)
    board_fen: str = ""
    side_to_move: str = "red"
    game_result: str = "in_progress"
    is_check: bool = False

    # Turn management
    turn_phase: TurnPhase = TurnPhase.IDLE
    move_number: int = 0
    last_move: str = ""
    last_eval: int = 0

    # Mode flags
    puzzle_mode: bool = False
    warning_state: bool = False
    onboarding_complete: bool = False

    # Player settings
    player_side: str = "red"
    difficulty: int = 4

    # Conversation context (keep last N entries for LLM context window)
    conversation_history: list[ConversationEntry] = field(default_factory=list)

    # Pending actions queue (processed by orchestrator)
    pending_actions: list[dict[str, Any]] = field(default_factory=list)

    # ---- Convenience Methods ----

    def is_player_turn(self) -> bool:
        """Check if it's currently the human player's turn."""
        return self.side_to_move == self.player_side

    def is_game_over(self) -> bool:
        """Check if the game has ended."""
        return self.game_result != "in_progress"

    def add_conversation(self, role: str, content: str, **metadata: Any) -> None:
        """Add an entry to conversation history (max 50 entries)."""
        entry = ConversationEntry(role=role, content=content, metadata=metadata)
        self.conversation_history.append(entry)
        # Keep only the last 50 entries for context window management
        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-50:]

    def get_conversation_context(self, last_n: int = 10) -> list[dict]:
        """Get recent conversation history for LLM context injection."""
        entries = self.conversation_history[-last_n:]
        return [e.to_dict() for e in entries]

    def update_from_engine(self, engine_data: dict) -> None:
        """Update board state from an engine response."""
        if "fen" in engine_data:
            self.board_fen = engine_data["fen"]
        if "side_to_move" in engine_data:
            self.side_to_move = engine_data["side_to_move"]
        if "result" in engine_data:
            self.game_result = engine_data["result"]
        if "is_check" in engine_data:
            self.is_check = engine_data["is_check"]

    def reset(self) -> None:
        """Reset session state for a new game."""
        self.board_fen = ""
        self.side_to_move = "red"
        self.game_result = "in_progress"
        self.is_check = False
        self.turn_phase = TurnPhase.IDLE
        self.move_number = 0
        self.last_move = ""
        self.last_eval = 0
        self.puzzle_mode = False
        self.warning_state = False
        self.onboarding_complete = False
        self.conversation_history.clear()
        self.pending_actions.clear()

    def to_dict(self) -> dict:
        """Serialize state for debugging or transmission."""
        return {
            "board_fen": self.board_fen,
            "side_to_move": self.side_to_move,
            "game_result": self.game_result,
            "is_check": self.is_check,
            "turn_phase": self.turn_phase.value,
            "move_number": self.move_number,
            "last_move": self.last_move,
            "last_eval": self.last_eval,
            "puzzle_mode": self.puzzle_mode,
            "warning_state": self.warning_state,
            "onboarding_complete": self.onboarding_complete,
            "player_side": self.player_side,
            "difficulty": self.difficulty,
            "conversation_count": len(self.conversation_history),
        }
