"""
Onboarding Agent
================

Guides new players through a short questionnaire at the start of every
session to calibrate the coaching experience (skill level, board-game
background, play style, coaching verbosity).

The questionnaire is four steps and is purely session-based — no profiles
are persisted to disk. Collected preferences are stored in the in-memory
MemoryAgent PlayerProfile for the duration of the game.

Onboarding Flow::

    WELCOME → SKILL_LEVEL → BOARD_GAME_EXPOSURE → PLAY_STYLE
    → COACHING_VERBOSITY → DONE

Each step sends a structured ``onboarding`` message to the client with:
  - ``step``: current step name
  - ``prompt``: question text
  - ``options``: list of {value, label} choices (for button UI)
  - ``onboarding_complete``: True only on the final confirmation
  - ``preferences``: completed profile dict (only when complete)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#   ONBOARDING STEPS
# ========================

class OnboardingStep(str, Enum):
    WELCOME             = "welcome"
    SKILL_LEVEL         = "skill_level"
    BOARD_GAME_EXPOSURE = "board_game_exposure"
    PLAY_STYLE          = "play_style"
    COACHING_VERBOSITY  = "coaching_verbosity"
    DONE                = "done"


# ========================
#   STEP DEFINITIONS
# ========================

_STEPS = [
    OnboardingStep.WELCOME,
    OnboardingStep.SKILL_LEVEL,
    OnboardingStep.BOARD_GAME_EXPOSURE,
    OnboardingStep.PLAY_STYLE,
    OnboardingStep.COACHING_VERBOSITY,
    OnboardingStep.DONE,
]

_PROMPTS: Dict[OnboardingStep, str] = {
    OnboardingStep.WELCOME: (
        "欢迎！Welcome to Guided Xiangqi (Chinese Chess)!\n\n"
        "I'm Kibo, your AI chess coach. Before we begin let me ask you a few "
        "quick questions so I can tailor my coaching to you."
    ),
    OnboardingStep.SKILL_LEVEL: "How would you describe your Xiangqi experience?",
    OnboardingStep.BOARD_GAME_EXPOSURE: "Have you played other strategy board games?",
    OnboardingStep.PLAY_STYLE: "What play style sounds most like you?",
    OnboardingStep.COACHING_VERBOSITY: "How much coaching detail would you like?",
    OnboardingStep.DONE: (
        "Great — I've set up your coaching profile. "
        "Red moves first, so whenever you're ready, make your opening move!"
    ),
}

_OPTIONS: Dict[OnboardingStep, List[Dict[str, str]]] = {
    OnboardingStep.WELCOME: [
        {"value": "ready", "label": "Let's go!"},
    ],
    OnboardingStep.SKILL_LEVEL: [
        {"value": "beginner",     "label": "Beginner — I'm new to Xiangqi"},
        {"value": "intermediate", "label": "Intermediate — I know the rules"},
        {"value": "advanced",     "label": "Advanced — I play regularly"},
    ],
    OnboardingStep.BOARD_GAME_EXPOSURE: [
        {"value": "none",   "label": "No — this is my first strategy game"},
        {"value": "chess",  "label": "Yes — Chess"},
        {"value": "shogi",  "label": "Yes — Shogi"},
        {"value": "go",     "label": "Yes — Go (Weiqi)"},
        {"value": "other",  "label": "Yes — other board games"},
    ],
    OnboardingStep.PLAY_STYLE: [
        {"value": "offensive", "label": "Offensive — I like attacking"},
        {"value": "defensive", "label": "Defensive — I prefer solid positions"},
        {"value": "neutral",   "label": "Balanced — I adapt to the game"},
    ],
    OnboardingStep.COACHING_VERBOSITY: [
        {"value": "brief",    "label": "Brief — just the key points"},
        {"value": "normal",   "label": "Normal — good balance"},
        {"value": "detailed", "label": "Detailed — explain everything"},
    ],
    OnboardingStep.DONE: [],
}

# Maps a step to the preference key it collects
_STEP_PREF_KEY: Dict[OnboardingStep, Optional[str]] = {
    OnboardingStep.WELCOME:             None,
    OnboardingStep.SKILL_LEVEL:         "skill_level",
    OnboardingStep.BOARD_GAME_EXPOSURE: "board_game_exposure",
    OnboardingStep.PLAY_STYLE:          "play_style",
    OnboardingStep.COACHING_VERBOSITY:  "coaching_verbosity",
    OnboardingStep.DONE:                None,
}

# Valid values per step (used for input validation / unknown fallback)
_VALID_VALUES: Dict[OnboardingStep, List[str]] = {
    step: [opt["value"] for opt in opts]
    for step, opts in _OPTIONS.items()
}


# ========================
#   ONBOARDING AGENT
# ========================

class OnboardingAgent(AgentBase):
    """Guides the player through a session-start preference questionnaire.

    Attributes:
        _current_step: The step currently awaiting player input.
        _preferences:  Collected answers so far this session.
    """

    def __init__(self, memory_agent: Any = None) -> None:
        super().__init__(name="OnboardingAgent")
        self._memory = memory_agent
        self._current_step: OnboardingStep = OnboardingStep.WELCOME
        self._preferences: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # AgentBase implementation
    # ------------------------------------------------------------------

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        action = kwargs.get("onboarding_action", "start")

        if action == "start":
            return self._send_step(OnboardingStep.WELCOME)

        if action == "answer":
            return await self._handle_answer(state, kwargs.get("selection", ""))

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.ONBOARDING,
            message=_PROMPTS[self._current_step],
            data=self._step_data(self._current_step),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_answer(self, state: Any, selection: str) -> AgentResponse:
        """Process player selection and advance to the next step."""
        current = self._current_step

        # Record the answer for the current step
        pref_key = _STEP_PREF_KEY.get(current)
        if pref_key:
            # Validate; accept any value but fall back to first option if unknown
            valid = _VALID_VALUES.get(current, [])
            value = selection if selection in valid else (valid[0] if valid else selection)
            self._preferences[pref_key] = value

        # Advance to next step
        next_step = self._next_step(current)
        self._current_step = next_step

        if next_step == OnboardingStep.DONE:
            return self._finalize()

        return self._send_step(next_step)

    def _next_step(self, current: OnboardingStep) -> OnboardingStep:
        idx = _STEPS.index(current)
        if idx + 1 < len(_STEPS):
            return _STEPS[idx + 1]
        return OnboardingStep.DONE

    def _send_step(self, step: OnboardingStep) -> AgentResponse:
        self._current_step = step
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.ONBOARDING,
            message=_PROMPTS[step],
            data=self._step_data(step),
        )

    def _finalize(self) -> AgentResponse:
        """Build the completion response with full preferences dict."""
        prefs = {
            "skill_level":         self._preferences.get("skill_level", "beginner"),
            "board_game_exposure": self._preferences.get("board_game_exposure", "none"),
            "play_style":          self._preferences.get("play_style", "neutral"),
            "coaching_verbosity":  self._preferences.get("coaching_verbosity", "normal"),
        }
        data = {
            "step": OnboardingStep.DONE.value,
            "prompt": _PROMPTS[OnboardingStep.DONE],
            "options": [],
            "onboarding_complete": True,
            "preferences": prefs,
        }
        return AgentResponse(
            source=self.name,
            response_type=ResponseType.ONBOARDING,
            message=_PROMPTS[OnboardingStep.DONE],
            data=data,
        )

    @staticmethod
    def _step_data(step: OnboardingStep) -> Dict[str, Any]:
        return {
            "step": step.value,
            "prompt": _PROMPTS[step],
            "options": _OPTIONS[step],
            "onboarding_complete": False,
            "preferences": {},
        }
