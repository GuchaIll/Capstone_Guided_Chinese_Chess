"""
Token Limiter Agent
====================

Guards LLM token usage across all agents with budget enforcement.

Responsibilities:
  - Track tokens consumed per request, per session, and cumulative
  - Enforce per-request, per-session, and daily token budgets
  - Gate LLM calls: reject if budget exceeded, allow if within limits
  - Log every token transaction to the agent log file
  - Provide usage statistics via handle() queries

Token Counting:
  Phase 1: Estimate tokens as word_count * 1.3 (rough approximation)
  Phase 2: Use tiktoken for exact counts (pip install tiktoken)

Budgets:
  per_request:  Max tokens in a single LLM call (default 512)
  per_session:  Max tokens across all calls in one session (default 10000)
  daily:        Max tokens across all sessions in a day (default 50000)

.. deprecated::
    Replaced by Prometheus metrics in the Go coaching service (server/chess_coach/).
    Retained as fallback only. See AGENTS.md.
"""
from __future__ import annotations

import warnings as _warnings
_warnings.warn(
    "TokenLimiterAgent is deprecated — use Go Prometheus metrics instead.",
    DeprecationWarning, stacklevel=2,
)

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .base_agent import AgentBase, AgentResponse, ResponseType


# ========================
#    TOKEN BUDGET
# ========================

@dataclass
class TokenBudget:
    """Configuration for token spending limits."""
    per_request: int = 512
    per_session: int = 10000
    daily: int = 50000


@dataclass
class TokenUsage:
    """Running token usage counters."""
    session_tokens: int = 0
    daily_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0
    rejected_count: int = 0
    last_reset_day: str = ""
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_tokens": self.session_tokens,
            "daily_tokens": self.daily_tokens,
            "total_tokens": self.total_tokens,
            "request_count": self.request_count,
            "rejected_count": self.rejected_count,
            "history_count": len(self.history),
        }


# ========================
#  TOKEN LIMITER AGENT
# ========================

class TokenLimiterAgent(AgentBase):
    """Guards LLM token usage with configurable budgets.

    Sits in the pipeline before every LLM call. Other agents call
    check_budget() before invoking the LLM, and record_usage() after.

    Usage:
        limiter = TokenLimiterAgent(budget=TokenBudget(per_request=256))
        allowed, reason = limiter.check_budget(estimated_tokens=200)
        if allowed:
            response = await llm_client.generate(...)
            limiter.record_usage(actual_tokens=len(response.split()))
    """

    def __init__(
        self,
        budget: Optional[TokenBudget] = None,
        enabled: bool = True,
    ):
        super().__init__(name="TokenLimiterAgent", enabled=enabled)
        self._budget = budget or TokenBudget()
        self._usage = TokenUsage()
        self._daily_reset()

    @property
    def budget(self) -> TokenBudget:
        return self._budget

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    async def handle(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Dispatch token limiter operations.

        Expected kwargs:
            token_action (str): One of "check", "record", "stats", "reset",
                                "set_budget"
            estimated_tokens (int): For "check" - how many tokens the caller wants
            actual_tokens (int): For "record" - how many tokens were consumed
            agent_name (str): Which agent is requesting tokens
            per_request / per_session / daily (int): For "set_budget"

        Returns:
            AgentResponse with allowed/denied status or usage stats.
        """
        action = kwargs.get("token_action", "stats")

        dispatch = {
            "check": self._handle_check,
            "record": self._handle_record,
            "stats": self._handle_stats,
            "reset": self._handle_reset,
            "set_budget": self._handle_set_budget,
        }

        handler = dispatch.get(action, self._handle_stats)
        return await handler(state, **kwargs)

    # ---- Core Operations ----

    async def _handle_check(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Check if a token request is within budget."""
        estimated = kwargs.get("estimated_tokens", 0)
        agent_name = kwargs.get("agent_name", "unknown")

        self._daily_reset()
        allowed, reason = self.check_budget(estimated)

        self.logger.info(
            f"Token check: agent={agent_name}, estimated={estimated}, "
            f"allowed={allowed}, reason={reason}"
        )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message=reason,
            data={
                "allowed": allowed,
                "reason": reason,
                "estimated_tokens": estimated,
                "remaining_session": max(0, self._budget.per_session - self._usage.session_tokens),
                "remaining_daily": max(0, self._budget.daily - self._usage.daily_tokens),
            },
        )

    async def _handle_record(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Record actual token usage after an LLM call."""
        actual = kwargs.get("actual_tokens", 0)
        agent_name = kwargs.get("agent_name", "unknown")
        provider = kwargs.get("provider", "unknown")

        self.record_usage(actual, agent_name=agent_name, provider=provider)

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            data={
                "recorded": True,
                "tokens": actual,
                "agent": agent_name,
                "usage": self._usage.to_dict(),
            },
        )

    async def _handle_stats(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Return current token usage statistics."""
        self._daily_reset()

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message=(
                f"Session: {self._usage.session_tokens}/{self._budget.per_session} | "
                f"Daily: {self._usage.daily_tokens}/{self._budget.daily} | "
                f"Requests: {self._usage.request_count} | "
                f"Rejected: {self._usage.rejected_count}"
            ),
            data={
                "usage": self._usage.to_dict(),
                "budget": {
                    "per_request": self._budget.per_request,
                    "per_session": self._budget.per_session,
                    "daily": self._budget.daily,
                },
            },
        )

    async def _handle_reset(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Reset session counters (daily keeps accumulating)."""
        self._usage.session_tokens = 0
        self._usage.request_count = 0
        self._usage.rejected_count = 0
        self._usage.history.clear()
        self.logger.info("Token limiter session counters reset")

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message="Token usage counters reset.",
            data={"reset": True, "usage": self._usage.to_dict()},
        )

    async def _handle_set_budget(self, state: Any, **kwargs: Any) -> AgentResponse:
        """Update budget limits."""
        if "per_request" in kwargs:
            self._budget.per_request = kwargs["per_request"]
        if "per_session" in kwargs:
            self._budget.per_session = kwargs["per_session"]
        if "daily" in kwargs:
            self._budget.daily = kwargs["daily"]

        self.logger.info(
            f"Budget updated: per_request={self._budget.per_request}, "
            f"per_session={self._budget.per_session}, daily={self._budget.daily}"
        )

        return AgentResponse(
            source=self.name,
            response_type=ResponseType.STATE_UPDATE,
            message="Token budget updated.",
            data={
                "budget": {
                    "per_request": self._budget.per_request,
                    "per_session": self._budget.per_session,
                    "daily": self._budget.daily,
                },
            },
        )

    # ---- Synchronous Helpers (called by other agents directly) ----

    def check_budget(self, estimated_tokens: int) -> tuple[bool, str]:
        """Check if a token request is within budget.

        Returns:
            (allowed: bool, reason: str)
        """
        if estimated_tokens > self._budget.per_request:
            self._usage.rejected_count += 1
            return False, (
                f"Exceeds per-request limit: {estimated_tokens} > "
                f"{self._budget.per_request}"
            )

        if self._usage.session_tokens + estimated_tokens > self._budget.per_session:
            self._usage.rejected_count += 1
            remaining = self._budget.per_session - self._usage.session_tokens
            return False, (
                f"Session budget exhausted: {remaining} tokens remaining, "
                f"requested {estimated_tokens}"
            )

        if self._usage.daily_tokens + estimated_tokens > self._budget.daily:
            self._usage.rejected_count += 1
            remaining = self._budget.daily - self._usage.daily_tokens
            return False, (
                f"Daily budget exhausted: {remaining} tokens remaining, "
                f"requested {estimated_tokens}"
            )

        return True, "Within budget"

    def record_usage(
        self,
        actual_tokens: int,
        agent_name: str = "unknown",
        provider: str = "unknown",
    ) -> None:
        """Record actual token consumption after an LLM call."""
        self._usage.session_tokens += actual_tokens
        self._usage.daily_tokens += actual_tokens
        self._usage.total_tokens += actual_tokens
        self._usage.request_count += 1

        entry = {
            "tokens": actual_tokens,
            "agent": agent_name,
            "provider": provider,
            "session_total": self._usage.session_tokens,
            "timestamp": time.time(),
        }
        self._usage.history.append(entry)

        # Keep history bounded
        if len(self._usage.history) > 200:
            self._usage.history = self._usage.history[-200:]

        self.logger.info(
            f"Token usage: +{actual_tokens} by {agent_name} via {provider} "
            f"(session={self._usage.session_tokens}/{self._budget.per_session})"
        )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text (rough: words * 1.3)."""
        return max(1, int(len(text.split()) * 1.3))

    def _daily_reset(self) -> None:
        """Reset daily counter at midnight."""
        today = time.strftime("%Y-%m-%d")
        if self._usage.last_reset_day != today:
            self._usage.daily_tokens = 0
            self._usage.last_reset_day = today
            self.logger.info(f"Daily token counter reset for {today}")

    async def on_game_start(self) -> None:
        """Reset session counters when a new game starts."""
        self._usage.session_tokens = 0
        self._usage.request_count = 0
        self._usage.rejected_count = 0
        self._usage.history.clear()
        await super().on_game_start()
