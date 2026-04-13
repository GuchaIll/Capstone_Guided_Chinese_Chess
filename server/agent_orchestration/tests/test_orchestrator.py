"""
Tests for Orchestrator
======================

Integration tests for the orchestration flow using mock engine + mock LLM.
"""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent_orchestration.agents.base_agent import ResponseType
from agent_orchestration.services.orchestrator import Orchestrator
from agent_orchestration.services.session_state import SessionState, TurnPhase


@pytest.fixture
def orchestrator():
    return Orchestrator(engine_client=None, rag_retriever=None, llm_client=None)


class TestInit:
    def test_agents_registered(self, orchestrator):
        assert len(orchestrator._agents) == 9

    def test_all_agents_enabled(self, orchestrator):
        for name, agent in orchestrator._agents.items():
            assert agent.is_enabled, f"{name} should be enabled"

    def test_state_initialized(self, orchestrator):
        assert orchestrator.state.turn_phase == TurnPhase.IDLE
        assert orchestrator.state.move_number == 0

    @pytest.mark.asyncio
    async def test_initialize(self, orchestrator):
        await orchestrator.initialize()

    @pytest.mark.asyncio
    async def test_new_game(self, orchestrator):
        orchestrator.state.move_number = 10
        await orchestrator.new_game()
        assert orchestrator.state.move_number == 0


class TestInputProcessing:
    @pytest.mark.asyncio
    async def test_general_chat(self, orchestrator):
        response = await orchestrator.process_input("hello there")
        assert response is not None
        assert response.response_type != ResponseType.ERROR

    @pytest.mark.asyncio
    async def test_move_input_stub(self, orchestrator):
        response = await orchestrator.process_input("e3e4")
        assert response is not None

    @pytest.mark.asyncio
    async def test_conversation_tracked(self, orchestrator):
        await orchestrator.process_input("hello")
        assert len(orchestrator.state.conversation_history) >= 1
        assert orchestrator.state.conversation_history[0].content == "hello"


class TestAgentManagement:
    def test_disable_agent(self, orchestrator):
        assert orchestrator.disable_agent("CoachAgent")
        assert not orchestrator.get_agent("CoachAgent").is_enabled

    def test_enable_agent(self, orchestrator):
        orchestrator.disable_agent("CoachAgent")
        orchestrator.enable_agent("CoachAgent")
        assert orchestrator.get_agent("CoachAgent").is_enabled

    def test_disable_unknown(self, orchestrator):
        assert not orchestrator.disable_agent("NonExistent")

    @pytest.mark.asyncio
    async def test_disabled_agent_skipped(self, orchestrator):
        orchestrator.disable_agent("CoachAgent")
        agent = orchestrator.get_agent("CoachAgent")
        response = await agent.safe_handle(orchestrator.state)
        assert response.metadata.get("skipped") is True


class TestSessionState:
    def test_is_player_turn(self):
        state = SessionState(side_to_move="red", player_side="red")
        assert state.is_player_turn()

    def test_game_over(self):
        state = SessionState(game_result="red_wins")
        assert state.is_game_over()

    def test_conversation_limit(self):
        state = SessionState()
        for i in range(60):
            state.add_conversation("user", f"msg {i}")
        assert len(state.conversation_history) == 50

    def test_reset(self):
        state = SessionState(move_number=15, puzzle_mode=True)
        state.reset()
        assert state.move_number == 0
        assert not state.puzzle_mode

    def test_update_from_engine(self):
        state = SessionState()
        state.update_from_engine({"fen": "test", "side_to_move": "black"})
        assert state.board_fen == "test"
        assert state.side_to_move == "black"


# ========================
#  RAG INTEGRATION TESTS
# ========================


class TestRAGIntegration:
    """Verify RAG wiring in the orchestrator."""

    def test_rag_agent_registered(self, orchestrator):
        assert "RAGManagerAgent" in orchestrator._agents

    def test_rag_agent_is_enabled(self, orchestrator):
        rag = orchestrator.get_agent("RAGManagerAgent")
        assert rag.is_enabled

    def test_coach_has_rag_reference(self, orchestrator):
        """CoachAgent should hold a reference to RAGManagerAgent."""
        coach = orchestrator.get_agent("CoachAgent")
        assert coach._rag is orchestrator.rag_agent

    @pytest.mark.asyncio
    async def test_rag_retrieve_mock(self, orchestrator):
        """RAGManagerAgent should work with no retriever (mock fallback)."""
        rag = orchestrator.get_agent("RAGManagerAgent")
        response = await rag.handle(
            orchestrator.state, query="cannon opening", collection="openings"
        )
        assert response is not None
        assert "documents" in response.data

    @pytest.mark.asyncio
    async def test_coach_blunder_with_rag(self, orchestrator):
        """Coach blunder handler should invoke RAG without error."""
        coach = orchestrator.get_agent("CoachAgent")
        response = await coach.handle(
            orchestrator.state,
            coaching_action="blunder_warning",
            move_analysis={
                "eval_delta": 250,
                "player_move": "h2h6",
                "engine_best_move": "c2c4",
            },
        )
        assert response.response_type == ResponseType.WARNING

    @pytest.mark.asyncio
    async def test_coach_teach_with_rag(self, orchestrator):
        """Coach teach handler should invoke RAG without error."""
        coach = orchestrator.get_agent("CoachAgent")
        response = await coach.handle(
            orchestrator.state,
            coaching_action="teach",
            topic="central cannon opening",
        )
        assert response.response_type == ResponseType.LESSON

    @pytest.mark.asyncio
    async def test_disable_rag_does_not_crash_coach(self, orchestrator):
        """Disabling RAG should not crash CoachAgent."""
        orchestrator.disable_agent("RAGManagerAgent")
        coach = orchestrator.get_agent("CoachAgent")
        response = await coach.handle(
            orchestrator.state,
            coaching_action="why_question",
            user_input="Why is the chariot important?",
        )
        assert response is not None
        orchestrator.enable_agent("RAGManagerAgent")
