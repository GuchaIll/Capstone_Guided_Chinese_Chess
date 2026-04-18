"""
Agent modules for the Guided Chinese Chess coaching system.

Each agent inherits from AgentBase and handles a specific responsibility
in the orchestration pipeline.

.. deprecated::
    Most agents in this package are deprecated in favour of the Go Agent
    Framework implementation (server/chess_coach/).  The Python pipeline is
    retained as a fallback only.  See AGENTS.md for the migration map.
"""
import warnings
warnings.warn(
    "agent_orchestration.agents is deprecated — use the Go coaching service "
    "(server/chess_coach/) instead.  Retained as fallback only.",
    DeprecationWarning,
    stacklevel=2,
)

from .base_agent import AgentBase, AgentResponse
from .intent_classifier import IntentClassifierAgent, Intent
from .game_engine_agent import GameEngineAgent
from .coach_agent import CoachAgent
from .puzzle_master_agent import PuzzleMasterAgent
from .rag_manager_agent import RAGManagerAgent
from .memory_agent import MemoryAgent
from .output_agent import OutputAgent
from .token_limiter_agent import TokenLimiterAgent
from .onboarding_agent import OnboardingAgent

__all__ = [
    "AgentBase",
    "AgentResponse",
    "IntentClassifierAgent",
    "Intent",
    "GameEngineAgent",
    "CoachAgent",
    "PuzzleMasterAgent",
    "RAGManagerAgent",
    "MemoryAgent",
    "OutputAgent",
    "TokenLimiterAgent",
    "OnboardingAgent",
]
