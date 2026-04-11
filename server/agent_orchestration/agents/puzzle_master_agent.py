"""
Puzzle Master Agent
===================

Manages the puzzle lifecycle for interactive Xiangqi learning.

Responsibilities:
  - Create puzzles from tactical patterns detected by the engine
  - Present puzzles to the player (hide the best move, show the position)
  - Validate player solutions against the engine's answer
  - Provide progressive hints (3 levels)
  - Track puzzle success rate via MemoryAgent
  - Transition in/out of puzzle mode

Puzzle Types:
  - Tactical: Find the best move (checkmate in N, winning capture)
  - Defensive: Find the only move that avoids losing material
  - Positional: Choose the best strategic move (harder, requires RAG context)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#     PUZZLE TYPES
# ========================

class PuzzleType(str, Enum):
    TACTICAL = "tactical"       # Find the best attacking move
    DEFENSIVE = "defensive"     # Find the saving move
    POSITIONAL = "positional"   # Best strategic move
    CHECKMATE = "checkmate"     # Mate in N


class PuzzleDifficulty(str, Enum):
    EASY = "easy"         # 1-move solutions
    MEDIUM = "medium"     # 2-move solutions
    HARD = "hard"         # 3+ move solutions


# ========================
#     PUZZLE DATA
# ========================

@dataclass
class Puzzle:
    """Represents a single puzzle instance."""
    puzzle_id: str
    puzzle_type: PuzzleType
    difficulty: PuzzleDifficulty
    fen: str                           # Starting position
    solution_moves: list[str]          # Correct move sequence
    hint_texts: list[str] = field(default_factory=list)  # Progressive hints
    description: str = ""              # What the player should look for
    theme: str = ""                    # Tactical theme (fork, pin, skewer, etc.)
    attempts: int = 0                  # Number of attempts by the player
    solved: bool = False

    def to_dict(self) -> dict:
        return {
            "puzzle_id": self.puzzle_id,
            "type": self.puzzle_type.value,
            "difficulty": self.difficulty.value,
            "fen": self.fen,
            "description": self.description,
            "theme": self.theme,
            "attempts": self.attempts,
            "solved": self.solved,
            # NOTE: solution_moves intentionally excluded (don't leak answer)
        }


# ========================
#   PUZZLE MASTER AGENT
# ========================

class PuzzleMasterAgent(AgentBase):
    """Manages puzzle creation, presentation, validation, and hints.

    Works with GameEngineAgent for position analysis and MemoryAgent
    for tracking player puzzle performance.
    """

    def __init__(
        self,
        engine_agent: Any = None,
        memory_agent: Any = None,
        enabled: bool = True,
    ):
        super().__init__(name="PuzzleMasterAgent", enabled=enabled)
        self._engine = engine_agent
        self._memory = memory_agent
        self._active_puzzle: Optional[Puzzle] = None
        self._puzzle_mode: bool = False
        self._hint_level: int = 0
        self._puzzle_counter: int = 0

    @property
    def puzzle_mode(self) -> bool:
        return self._puzzle_mode

    @property
    def active_puzzle(self) -> Optional[Puzzle]:
        return self._active_puzzle

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Dispatch puzzle operations.

        Expected kwargs:
            puzzle_action (str): One of "create", "present", "validate",
                "hint", "skip", "exit_puzzle_mode"
            fen (str): Position for puzzle creation
            player_move (str): Player's attempted solution
            puzzle_type (str): Type of puzzle to create
        """
        action = kwargs.get("puzzle_action", "present")

        dispatch = {
            "create": self._handle_create,
            "present": self._handle_present,
            "validate": self._handle_validate,
            "hint": self._handle_hint,
            "skip": self._handle_skip,
            "exit_puzzle_mode": self._handle_exit,
        }

        handler = dispatch.get(action, self._handle_present)
        return await handler(state, **kwargs)

    # ---- Puzzle Lifecycle ----

    async def _handle_create(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Create a new puzzle from the current or given position.

        Uses the engine to find the best move sequence, then
        constructs a Puzzle object with hints.
        """
        fen = kwargs.get("fen", "")
        puzzle_type = PuzzleType(kwargs.get("puzzle_type", "tactical"))
        difficulty = PuzzleDifficulty(kwargs.get("difficulty", "easy"))

        self._puzzle_counter += 1
        puzzle_id = f"puzzle_{self._puzzle_counter:04d}"

        # Get engine's best move to use as solution
        solution_moves = []
        if self._engine:
            engine_response = await self._engine.safe_handle(
                state, action="suggest", difficulty=6,
            )
            best_move = engine_response.data.get("move", "")
            if best_move:
                solution_moves = [best_move]

        # Build progressive hints
        hints = [
            "Look carefully at the board. Which of your pieces has the most potential?",
            "Think about which piece can create a direct threat to the opponent's king.",
            f"The solution involves moving to one of these squares: "
            f"{', '.join(m[2:4] for m in solution_moves) if solution_moves else '...'}",
        ]

        self._active_puzzle = Puzzle(
            puzzle_id=puzzle_id,
            puzzle_type=puzzle_type,
            difficulty=difficulty,
            fen=fen,
            solution_moves=solution_moves,
            hint_texts=hints,
            description=f"Find the best {puzzle_type.value} move.",
            theme="general",
        )
        self._puzzle_mode = True
        self._hint_level = 0

        self.logger.info(
            f"Created puzzle {puzzle_id}: type={puzzle_type.value}, "
            f"solution={solution_moves}"
        )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.PUZZLE,
            message=self._active_puzzle.description,
            data=self._active_puzzle.to_dict(),
        )

    async def _handle_present(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Present the current active puzzle to the player."""
        if not self._active_puzzle:
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.TEXT,
                message="No active puzzle. Would you like me to create one?",
                data={"puzzle_active": False},
            )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.PUZZLE,
            message=self._active_puzzle.description,
            data=self._active_puzzle.to_dict(),
        )

    async def _handle_validate(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Validate the player's attempted solution.

        Compares the player's move against the puzzle's solution moves.
        """
        player_move = kwargs.get("player_move", "")

        if not self._active_puzzle:
            return AgentResponse.from_error(self.name, "No active puzzle to validate.")

        self._active_puzzle.attempts += 1

        if player_move in self._active_puzzle.solution_moves:
            # Correct!
            self._active_puzzle.solved = True
            self._puzzle_mode = False

            # Track success
            if self._memory:
                await self._memory.safe_handle(
                    state,
                    memory_action="record_puzzle_result",
                    puzzle_id=self._active_puzzle.puzzle_id,
                    solved=True,
                    attempts=self._active_puzzle.attempts,
                )

            message = (
                f"Correct! {player_move} is the best move. "
                f"You solved it in {self._active_puzzle.attempts} "
                f"attempt{'s' if self._active_puzzle.attempts > 1 else ''}."
            )

            return AgentResponse(
                source=self.name,
                response_type=ResponseType.PUZZLE,
                message=message,
                data={
                    **self._active_puzzle.to_dict(),
                    "result": "correct",
                },
            )
        else:
            # Incorrect
            message = (
                f"Not quite. {player_move} is not the best move here. "
                f"Try again, or ask for a hint."
            )
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.PUZZLE,
                message=message,
                data={
                    **self._active_puzzle.to_dict(),
                    "result": "incorrect",
                    "player_move": player_move,
                },
            )

    async def _handle_hint(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Provide a progressive hint for the active puzzle."""
        if not self._active_puzzle:
            return AgentResponse.from_error(self.name, "No active puzzle.")

        if self._hint_level < len(self._active_puzzle.hint_texts):
            hint = self._active_puzzle.hint_texts[self._hint_level]
            self._hint_level += 1
        else:
            # All hints exhausted: reveal the solution
            solution = self._active_puzzle.solution_moves
            hint = f"The solution is: {', '.join(solution)}"

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.PUZZLE,
            message=hint,
            data={
                "hint_level": self._hint_level,
                "hints_remaining": max(
                    0,
                    len(self._active_puzzle.hint_texts) - self._hint_level
                ),
            },
        )

    async def _handle_skip(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Skip the current puzzle and reveal the solution."""
        if not self._active_puzzle:
            return AgentResponse.from_error(self.name, "No active puzzle to skip.")

        solution = self._active_puzzle.solution_moves
        puzzle_id = self._active_puzzle.puzzle_id
        self._active_puzzle = None
        self._puzzle_mode = False
        self._hint_level = 0

        # Track skip in memory
        if self._memory:
            await self._memory.safe_handle(
                state,
                memory_action="record_puzzle_result",
                puzzle_id=puzzle_id,
                solved=False,
                skipped=True,
            )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.PUZZLE,
            message=f"Puzzle skipped. The solution was: {', '.join(solution)}",
            data={"action": "skipped", "solution": solution},
        )

    async def _handle_exit(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Exit puzzle mode and return to normal play."""
        self._puzzle_mode = False
        self._active_puzzle = None
        self._hint_level = 0

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message="Puzzle mode deactivated. Returning to normal play.",
            data={"puzzle_mode": False},
        )

    # ---- Puzzle Detection (called by orchestrator) ----

    def should_create_puzzle(self, eval_delta: int, move_number: int) -> bool:
        """Determine if the current position warrants a puzzle.

        Heuristics:
        - After a significant tactical opportunity (eval swing > 300)
        - Not too early in the game (move > 10)
        - Not already in puzzle mode
        """
        if self._puzzle_mode:
            return False
        if move_number < 10:
            return False
        if abs(eval_delta) >= 300:
            return True
        return False
