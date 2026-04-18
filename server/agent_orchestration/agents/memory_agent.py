"""
Memory Agent
=============

Persistent player profile and session state management.

Stores:
  - Player skill level (estimated from game performance)
  - Mistake history (blunders, mistakes, inaccuracies with context)
  - Concepts taught (which lessons the player has seen)
  - Puzzle statistics (success rate, average attempts, skips)
  - Session state (puzzle mode, last move, conversation history)

Storage Backend:
  Phase 1: JSON file on disk (simple, no dependencies)
  Phase 2: SQLite or PostgreSQL (for multi-user support)

The Memory Agent is queried by the Coach Agent for adaptive coaching
and by the Puzzle Master for difficulty calibration.

.. deprecated::
    Replaced by User Memory Store tool in the Go coaching service (server/chess_coach/).
    Retained as fallback only. See AGENTS.md.
"""
from __future__ import annotations

import warnings as _warnings
_warnings.warn(
    "MemoryAgent is deprecated — use Go User Memory Store tool instead.",
    DeprecationWarning, stacklevel=2,
)

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#    PLAYER PROFILE
# ========================

@dataclass
class MistakeRecord:
    """Record of a single mistake for tracking patterns."""
    move: str
    better_move: str
    eval_delta: int
    severity: str       # "blunder", "mistake", "inaccuracy"
    move_number: int = 0
    timestamp: str = ""


@dataclass
class PuzzleRecord:
    """Record of a puzzle attempt."""
    puzzle_id: str
    solved: bool
    attempts: int = 1
    skipped: bool = False
    timestamp: str = ""


@dataclass
class PlayerProfile:
    """Complete player profile for adaptive coaching.

    Attributes:
        player_id: Unique identifier (default "local" for single-user)
        skill_level: Estimated skill (beginner, intermediate, advanced)
        games_played: Total games completed
        mistakes: History of mistakes for pattern detection
        concepts_taught: Set of lesson topics already delivered
        puzzle_stats: Puzzle attempt records
        common_mistake_types: Counter of mistake categories
        board_game_exposure: Prior board game experience (none, chess, shogi, go, other)
        play_style: Preferred play style (offensive, defensive, neutral)
        coaching_verbosity: Coaching detail level (brief, normal, detailed)
        onboarding_complete: Whether onboarding questionnaire has been completed
    """
    player_id: str = "local"
    skill_level: str = "beginner"
    games_played: int = 0
    total_moves: int = 0
    mistakes: list[dict] = field(default_factory=list)
    concepts_taught: list[str] = field(default_factory=list)
    puzzle_stats: list[dict] = field(default_factory=list)
    common_mistake_types: dict[str, int] = field(default_factory=dict)
    # Onboarding preferences
    board_game_exposure: str = "none"
    play_style: str = "neutral"
    coaching_verbosity: str = "normal"
    onboarding_complete: bool = False

    @property
    def mistake_rate(self) -> float:
        """Proportion of moves that were mistakes/blunders."""
        if self.total_moves == 0:
            return 0.0
        return len(self.mistakes) / self.total_moves

    @property
    def puzzle_success_rate(self) -> float:
        """Proportion of puzzles solved."""
        if not self.puzzle_stats:
            return 0.0
        solved = sum(1 for p in self.puzzle_stats if p.get("solved"))
        return solved / len(self.puzzle_stats)

    def needs_skill_update(self) -> bool:
        """Check if enough data has been collected to re-evaluate skill."""
        return self.games_played > 0 and self.total_moves % 20 == 0

    def to_dict(self) -> dict:
        return asdict(self)


# ========================
#     MEMORY AGENT
# ========================

class MemoryAgent(AgentBase):
    """Manages persistent player profiles and session state.

    Stores profile to disk as JSON. Provides query/update interface
    for other agents to access player history.
    """

    DEFAULT_PROFILE_DIR = "server/agent_orchestration/.agent/profiles"

    def __init__(
        self,
        profile_dir: Optional[str] = None,
        enabled: bool = True,
    ):
        super().__init__(name="MemoryAgent", enabled=enabled)
        self._profile_dir = profile_dir or self.DEFAULT_PROFILE_DIR
        self._profile: PlayerProfile = PlayerProfile()
        self._session_data: dict[str, Any] = {}  # Ephemeral session state
        self._dirty: bool = False  # Flag for unsaved changes

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Dispatch memory operations.

        Expected kwargs:
            memory_action (str): One of "get_profile", "update_profile",
                "record_mistake", "record_lesson", "record_puzzle_result",
                "get_session", "set_session", "estimate_skill"
            Additional kwargs vary by action.

        Returns:
            AgentResponse with profile or session data.
        """
        action = kwargs.get("memory_action", "get_profile")

        dispatch = {
            "get_profile": self._handle_get_profile,
            "update_profile": self._handle_update_profile,
            "record_mistake": self._handle_record_mistake,
            "record_lesson": self._handle_record_lesson,
            "record_puzzle_result": self._handle_record_puzzle,
            "get_session": self._handle_get_session,
            "set_session": self._handle_set_session,
            "estimate_skill": self._handle_estimate_skill,
            "record_game_end": self._handle_record_game_end,
        }

        handler = dispatch.get(action, self._handle_get_profile)
        return await handler(state, **kwargs)

    # ---- Profile Operations ----

    async def _handle_get_profile(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Return the current player profile."""
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"profile": self._profile.to_dict()},
        )

    async def _handle_update_profile(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Update specific profile fields."""
        if "skill_level" in kwargs:
            self._profile.skill_level = kwargs["skill_level"]
        if "player_id" in kwargs:
            self._profile.player_id = kwargs["player_id"]
        self._dirty = True

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"profile": self._profile.to_dict(), "updated": True},
        )

    async def _handle_record_mistake(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Record a player mistake for pattern tracking."""
        record = {
            "move": kwargs.get("move", ""),
            "better_move": kwargs.get("better_move", ""),
            "eval_delta": kwargs.get("eval_delta", 0),
            "severity": kwargs.get("mistake_type", "mistake"),
            "move_number": self._profile.total_moves,
        }
        self._profile.mistakes.append(record)
        self._profile.total_moves += 1

        # Update common mistake type counter
        severity = record["severity"]
        self._profile.common_mistake_types[severity] = (
            self._profile.common_mistake_types.get(severity, 0) + 1
        )

        self._dirty = True
        self.logger.info(f"Recorded {severity}: {record['move']}")

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"recorded": True, "mistake": record},
        )

    async def _handle_record_lesson(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Record that a lesson topic was taught."""
        topic = kwargs.get("topic", "")
        if topic and topic not in self._profile.concepts_taught:
            self._profile.concepts_taught.append(topic)
            self._dirty = True

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"recorded": True, "topic": topic},
        )

    async def _handle_record_puzzle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Record a puzzle attempt result."""
        record = {
            "puzzle_id": kwargs.get("puzzle_id", ""),
            "solved": kwargs.get("solved", False),
            "attempts": kwargs.get("attempts", 1),
            "skipped": kwargs.get("skipped", False),
        }
        self._profile.puzzle_stats.append(record)
        self._dirty = True

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"recorded": True, "puzzle": record},
        )

    async def _handle_record_game_end(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Record end of game and increment game counter."""
        self._profile.games_played += 1
        self._dirty = True
        await self._save_profile()

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"games_played": self._profile.games_played},
        )

    # ---- Session State ----

    async def _handle_get_session(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Return ephemeral session data."""
        key = kwargs.get("key")
        if key:
            value = self._session_data.get(key)
            return AgentResponse(
                source=self.name,
                response_type=ResponseType.STATE_UPDATE,
                data={"key": key, "value": value},
            )
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"session": self._session_data},
        )

    async def _handle_set_session(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Set a session state value."""
        key = kwargs.get("key", "")
        value = kwargs.get("value")
        if key:
            self._session_data[key] = value

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={"key": key, "value": value, "set": True},
        )

    # ---- Skill Estimation ----

    async def _handle_estimate_skill(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Re-estimate the player's skill level from performance data.

        Uses:
        - Mistake rate (blunders/mistakes per move)
        - Puzzle success rate
        - Number of games played
        """
        profile = self._profile

        if profile.total_moves < 10:
            level = "beginner"
        elif profile.mistake_rate > 0.2:
            level = "beginner"
        elif profile.mistake_rate > 0.1:
            level = "intermediate"
        elif profile.puzzle_success_rate > 0.7 and profile.games_played > 5:
            level = "advanced"
        else:
            level = "intermediate"

        old_level = profile.skill_level
        profile.skill_level = level
        self._dirty = True

        if old_level != level:
            self.logger.info(f"Skill level updated: {old_level} -> {level}")

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message=(
                f"Skill level: {level} "
                f"(mistake rate: {profile.mistake_rate:.1%}, "
                f"puzzle rate: {profile.puzzle_success_rate:.1%})"
            ),
            data={"skill_level": level, "changed": old_level != level},
        )

    # ---- Persistence ----

    async def _save_profile(self) -> None:
        """Save the player profile to disk as JSON."""
        try:
            os.makedirs(self._profile_dir, exist_ok=True)
            path = os.path.join(
                self._profile_dir, f"{self._profile.player_id}.json"
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._profile.to_dict(), f, indent=2)
            self._dirty = False
            self.logger.debug(f"Profile saved to {path}")
        except Exception as e:
            self.logger.error(f"Failed to save profile: {e}")

    async def load_profile(self, player_id: str = "local") -> None:
        """Load a player profile from disk."""
        path = os.path.join(self._profile_dir, f"{player_id}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._profile = PlayerProfile(**data)
                self.logger.info(f"Profile loaded for {player_id}")
            except Exception as e:
                self.logger.error(f"Failed to load profile: {e}")
                self._profile = PlayerProfile(player_id=player_id)
        else:
            self._profile = PlayerProfile(player_id=player_id)
            self.logger.info(f"New profile created for {player_id}")

    async def on_game_start(self) -> None:
        """Load profile at game start."""
        await self.load_profile()
        self._session_data.clear()
        await super().on_game_start()

    async def on_game_end(self, result: str) -> None:
        """Save profile at game end."""
        self._profile.games_played += 1
        await self._save_profile()
        await super().on_game_end(result)
