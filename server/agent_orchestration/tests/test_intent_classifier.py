"""
Tests for Intent Classifier Agent
==================================

Validates intent classification across all input types:
  - Move inputs (coordinate notation, natural language)
  - Why questions
  - Hint requests
  - Teach me requests
  - General chat
  - Undo / resign commands
"""

import asyncio
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent_orchestration.agents.intent_classifier import (
    IntentClassifierAgent,
    Intent,
)
from agent_orchestration.services.session_state import SessionState


# ========================
#     TEST FIXTURES
# ========================

@pytest.fixture
def classifier():
    return IntentClassifierAgent()


@pytest.fixture
def state():
    return SessionState()


# ========================
#     MOVE INTENT
# ========================

class TestMoveIntent:
    """Test that move inputs are correctly classified."""

    @pytest.mark.asyncio
    async def test_coordinate_notation(self, classifier, state):
        """e3e4 style moves should be classified as MOVE."""
        result = await classifier.handle(state, user_input="e3e4")
        assert result.data["intent"] == Intent.MOVE

    @pytest.mark.asyncio
    async def test_coordinate_edge(self, classifier, state):
        """Edge square coordinates like a0i9."""
        result = await classifier.handle(state, user_input="a0i9")
        assert result.data["intent"] == Intent.MOVE

    @pytest.mark.asyncio
    async def test_natural_language_move(self, classifier, state):
        """'move knight to c5' should be MOVE."""
        result = await classifier.handle(state, user_input="move knight to c5")
        assert result.data["intent"] == Intent.MOVE

    @pytest.mark.asyncio
    async def test_play_phrasing(self, classifier, state):
        """'play rook to e5' should be MOVE."""
        result = await classifier.handle(state, user_input="play rook to e5")
        assert result.data["intent"] == Intent.MOVE


# ========================
#   WHY QUESTION INTENT
# ========================

class TestWhyIntent:
    """Test that why questions are correctly classified."""

    @pytest.mark.asyncio
    async def test_why_question(self, classifier, state):
        result = await classifier.handle(state, user_input="why did you move there?")
        assert result.data["intent"] == Intent.WHY_QUESTION

    @pytest.mark.asyncio
    async def test_explain_question(self, classifier, state):
        result = await classifier.handle(state, user_input="explain that move")
        assert result.data["intent"] == Intent.WHY_QUESTION

    @pytest.mark.asyncio
    async def test_how_come(self, classifier, state):
        result = await classifier.handle(state, user_input="how come the rook went there?")
        assert result.data["intent"] == Intent.WHY_QUESTION


# ========================
#    HINT INTENT
# ========================

class TestHintIntent:
    """Test that hint requests are correctly classified."""

    @pytest.mark.asyncio
    async def test_hint_request(self, classifier, state):
        result = await classifier.handle(state, user_input="give me a hint")
        assert result.data["intent"] == Intent.HINT_REQUEST

    @pytest.mark.asyncio
    async def test_what_should(self, classifier, state):
        result = await classifier.handle(state, user_input="what should I do?")
        assert result.data["intent"] == Intent.HINT_REQUEST

    @pytest.mark.asyncio
    async def test_best_move(self, classifier, state):
        result = await classifier.handle(state, user_input="what's the best move?")
        assert result.data["intent"] == Intent.HINT_REQUEST

    @pytest.mark.asyncio
    async def test_suggest(self, classifier, state):
        result = await classifier.handle(state, user_input="suggest a move")
        assert result.data["intent"] == Intent.HINT_REQUEST


# ========================
#    TEACH INTENT
# ========================

class TestTeachIntent:
    """Test that teaching requests are correctly classified."""

    @pytest.mark.asyncio
    async def test_teach_me(self, classifier, state):
        result = await classifier.handle(state, user_input="teach me about cannons")
        assert result.data["intent"] == Intent.TEACH_ME

    @pytest.mark.asyncio
    async def test_how_to(self, classifier, state):
        result = await classifier.handle(state, user_input="how to use the rook effectively?")
        assert result.data["intent"] == Intent.TEACH_ME

    @pytest.mark.asyncio
    async def test_tell_me_about(self, classifier, state):
        result = await classifier.handle(state, user_input="tell me about opening strategy")
        assert result.data["intent"] == Intent.TEACH_ME


# ========================
#   UNDO / RESIGN INTENT
# ========================

class TestControlIntents:
    """Test undo and resign commands."""

    @pytest.mark.asyncio
    async def test_undo(self, classifier, state):
        result = await classifier.handle(state, user_input="undo")
        assert result.data["intent"] == Intent.UNDO

    @pytest.mark.asyncio
    async def test_take_back(self, classifier, state):
        result = await classifier.handle(state, user_input="take back my move")
        assert result.data["intent"] == Intent.UNDO

    @pytest.mark.asyncio
    async def test_resign(self, classifier, state):
        result = await classifier.handle(state, user_input="I resign")
        assert result.data["intent"] == Intent.RESIGN

    @pytest.mark.asyncio
    async def test_give_up(self, classifier, state):
        result = await classifier.handle(state, user_input="give up")
        assert result.data["intent"] == Intent.RESIGN


# ========================
#   GENERAL CHAT INTENT
# ========================

class TestGeneralChat:
    """Test that unrecognized input falls through to GENERAL_CHAT."""

    @pytest.mark.asyncio
    async def test_general_greeting(self, classifier, state):
        result = await classifier.handle(state, user_input="hello")
        assert result.data["intent"] == Intent.GENERAL_CHAT

    @pytest.mark.asyncio
    async def test_empty_input(self, classifier, state):
        result = await classifier.handle(state, user_input="")
        assert result.data["intent"] == Intent.UNKNOWN


# ========================
#   ROUTING TESTS
# ========================

class TestRouting:
    """Test that intents map to the correct follow-up agent."""

    @pytest.mark.asyncio
    async def test_move_routes_to_engine(self, classifier, state):
        result = await classifier.handle(state, user_input="e3e4")
        assert result.follow_up_agent == "GameEngineAgent"

    @pytest.mark.asyncio
    async def test_why_routes_to_coach(self, classifier, state):
        result = await classifier.handle(state, user_input="why that move?")
        assert result.follow_up_agent == "CoachAgent"

    @pytest.mark.asyncio
    async def test_hint_routes_to_coach(self, classifier, state):
        result = await classifier.handle(state, user_input="give me a hint")
        assert result.follow_up_agent == "CoachAgent"

    @pytest.mark.asyncio
    async def test_undo_routes_to_engine(self, classifier, state):
        result = await classifier.handle(state, user_input="undo")
        assert result.follow_up_agent == "GameEngineAgent"

    @pytest.mark.asyncio
    async def test_resign_routes_to_engine(self, classifier, state):
        result = await classifier.handle(state, user_input="resign")
        assert result.follow_up_agent == "GameEngineAgent"
