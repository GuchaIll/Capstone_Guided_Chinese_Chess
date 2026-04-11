"""
Tests for Token Limiter Agent
==============================
"""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent_orchestration.agents.token_limiter_agent import (
    TokenLimiterAgent,
    TokenBudget,
)
from agent_orchestration.services.session_state import SessionState


@pytest.fixture
def limiter():
    return TokenLimiterAgent(budget=TokenBudget(per_request=100, per_session=500, daily=1000))


@pytest.fixture
def state():
    return SessionState()


class TestBudgetCheck:
    def test_within_budget(self, limiter):
        allowed, reason = limiter.check_budget(50)
        assert allowed
        assert reason == "Within budget"

    def test_exceeds_per_request(self, limiter):
        allowed, reason = limiter.check_budget(150)
        assert not allowed
        assert "per-request" in reason

    def test_exceeds_session_budget(self, limiter):
        limiter.record_usage(450)
        allowed, reason = limiter.check_budget(60)
        assert not allowed
        assert "Session budget" in reason

    def test_within_session_after_usage(self, limiter):
        limiter.record_usage(400)
        allowed, _ = limiter.check_budget(90)
        assert allowed

    def test_exceeds_daily_budget(self, limiter):
        limiter._usage.daily_tokens = 960
        allowed, reason = limiter.check_budget(50)
        assert not allowed
        assert "Daily budget" in reason


class TestRecordUsage:
    def test_record_increments(self, limiter):
        limiter.record_usage(100, agent_name="CoachAgent", provider="mock")
        assert limiter.usage.session_tokens == 100
        assert limiter.usage.daily_tokens == 100
        assert limiter.usage.total_tokens == 100
        assert limiter.usage.request_count == 1

    def test_multiple_records(self, limiter):
        limiter.record_usage(50)
        limiter.record_usage(75)
        assert limiter.usage.session_tokens == 125
        assert limiter.usage.request_count == 2

    def test_history_recorded(self, limiter):
        limiter.record_usage(42, agent_name="TestAgent")
        assert len(limiter.usage.history) == 1
        assert limiter.usage.history[0]["tokens"] == 42
        assert limiter.usage.history[0]["agent"] == "TestAgent"

    def test_rejected_count(self, limiter):
        limiter.check_budget(200)  # exceeds per_request=100
        assert limiter.usage.rejected_count == 1


class TestEstimate:
    def test_estimate_tokens(self, limiter):
        text = "This is a test sentence with eight words"
        est = limiter.estimate_tokens(text)
        assert est >= 8  # at least as many as word count


class TestHandleActions:
    @pytest.mark.asyncio
    async def test_stats_action(self, limiter, state):
        response = await limiter.handle(state, token_action="stats")
        assert "usage" in response.data
        assert "budget" in response.data

    @pytest.mark.asyncio
    async def test_check_action(self, limiter, state):
        response = await limiter.handle(
            state, token_action="check", estimated_tokens=50, agent_name="Test"
        )
        assert response.data["allowed"] is True

    @pytest.mark.asyncio
    async def test_record_action(self, limiter, state):
        response = await limiter.handle(
            state, token_action="record", actual_tokens=30, agent_name="Test"
        )
        assert response.data["recorded"] is True
        assert limiter.usage.session_tokens == 30

    @pytest.mark.asyncio
    async def test_reset_action(self, limiter, state):
        limiter.record_usage(100)
        response = await limiter.handle(state, token_action="reset")
        assert response.data["reset"] is True
        assert limiter.usage.session_tokens == 0

    @pytest.mark.asyncio
    async def test_set_budget_action(self, limiter, state):
        response = await limiter.handle(
            state, token_action="set_budget", per_session=9999
        )
        assert limiter.budget.per_session == 9999


class TestGameLifecycle:
    @pytest.mark.asyncio
    async def test_on_game_start_resets(self, limiter):
        limiter.record_usage(200)
        await limiter.on_game_start()
        assert limiter.usage.session_tokens == 0
        assert limiter.usage.request_count == 0
