"""
Base Agent Module
=================

Abstract base class for all agents in the Guided Chinese Chess coaching system.
Follows the Anthropic-style agent pattern with:
  - Typed input/output via AgentResponse
  - Built-in logging mixin
  - Error fallback handling
  - Feature flag support for toggling agent capabilities

All agents inherit from AgentBase and implement handle().
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ========================
#     AGENT RESPONSE
# ========================

class ResponseType(str, Enum):
    """Classification of agent response for downstream routing."""
    TEXT = "text"
    BOARD_ACTION = "board_action"
    SUGGESTION = "suggestion"
    PUZZLE = "puzzle"
    WARNING = "warning"
    LESSON = "lesson"
    ERROR = "error"
    STATE_UPDATE = "state_update"
    LED_COMMAND = "led_command"
    ONBOARDING = "onboarding"
    COACHING = "coaching"
    INFO = "info"


@dataclass
class AgentResponse:
    """Standardized response returned by every agent.

    Attributes:
        source: Name of the agent that produced this response.
        response_type: Category of the response for routing.
        message: Human-readable text for the user (if applicable).
        data: Structured data payload (agent-specific).
        metadata: Additional context (timing, confidence, etc.).
        follow_up_agent: If set, the orchestrator should invoke this agent next.
        error: Error message if the agent encountered a failure.
    """
    source: str
    response_type: ResponseType
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    follow_up_agent: Optional[str] = None
    error: Optional[str] = None

    @staticmethod
    def from_error(source: str, error_msg: str) -> "AgentResponse":
        return AgentResponse(
            source=source,
            response_type=ResponseType.ERROR,
            message=f"An error occurred: {error_msg}",
            error=error_msg,
        )


# ========================
#     AGENT BASE CLASS
# ========================

class AgentBase(ABC):
    """Abstract base class for all orchestration agents.

    Provides:
    - Structured logging via self.logger
    - Feature flag checking via self.is_enabled
    - Error-safe handle wrapper via safe_handle()
    - Abstract handle() for subclass implementation
    """

    def __init__(self, name: str, enabled: bool = True):
        self._name = name
        self._enabled = enabled
        self.logger = logging.getLogger(f"agent.{name}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        self.logger.info(f"{self._name} enabled")

    def disable(self) -> None:
        self._enabled = False
        self.logger.info(f"{self._name} disabled")

    @abstractmethod
    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Process input and return a response.

        Args:
            state: The current SessionState (shared across agents).
            **kwargs: Additional context passed by the orchestrator.

        Returns:
            AgentResponse with the agent's output.
        """
        ...

    async def safe_handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Error-safe wrapper around handle(). Returns error response on exception."""
        if not self._enabled:
            return AgentResponse(
                source=self._name,
                response_type=ResponseType.STATE_UPDATE,
                message="",
                metadata={"skipped": True, "reason": "agent_disabled"},
            )
        try:
            self.logger.debug(f"{self._name}.handle() invoked")
            response = await self.handle(state, **kwargs)
            self.logger.debug(
                f"{self._name}.handle() completed: type={response.response_type.value}"
            )
            return response
        except Exception as e:
            self.logger.exception(f"{self._name}.handle() failed: {e}")
            return AgentResponse.from_error(self._name, str(e))

    # ---- Lifecycle Hooks ----

    async def on_game_start(self) -> None:
        """Called when a new game begins. Override for per-game init."""
        self.logger.debug(f"{self._name}: on_game_start")

    async def on_game_end(self, result: str) -> None:
        """Called when a game ends. Override for cleanup."""
        self.logger.debug(f"{self._name}: on_game_end result={result}")

    async def on_turn_start(self, side: str) -> None:
        """Called at the start of each turn."""
        pass

    def __repr__(self) -> str:
        status = "enabled" if self._enabled else "disabled"
        return f"<{self._name} ({status})>"
