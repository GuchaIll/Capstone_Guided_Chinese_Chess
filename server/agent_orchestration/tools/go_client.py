"""
Go Coaching Client
==================

Async HTTP client that forwards coaching requests to the Go Agent Framework
service (server/chess_coach/).  Used by the Python Orchestrator as a bridge
during the migration period.

Endpoints consumed:
  POST /coach              — full coaching pipeline
  POST /coach/analyze      — position analysis only
  POST /coach/blunder      — blunder detection only
  POST /coach/puzzle       — puzzle generation only
  POST /coach/features     — position features extraction
  POST /coach/classify-move — single move classification
  GET  /health             — liveness check
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import aiohttp

from ..agents.base_agent import AgentResponse, ResponseType


logger = logging.getLogger("tools.go_client")

# ========================
#   GO COACHING CLIENT
# ========================

# Map Go response "type" field to Python ResponseType
_GO_TYPE_MAP: dict[str, ResponseType] = {
    "coaching":     ResponseType.COACHING,
    "board_action": ResponseType.BOARD_ACTION,
    "puzzle":       ResponseType.PUZZLE,
    "error":        ResponseType.ERROR,
    "info":         ResponseType.INFO,
}


class GoCoachingClient:
    """Async HTTP client for the Go coaching service.

    Usage:
        client = GoCoachingClient()
        resp = await client.coach(fen="...", user_input="explain this")
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 15.0,
    ):
        self._base_url = (
            base_url
            or os.environ.get("GO_COACHING_URL", "http://localhost:5002")
        ).rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    # ---- Lifecycle ----

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---- Health ----

    async def is_available(self) -> bool:
        """Return True if the Go service is reachable and healthy."""
        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/health") as resp:
                return resp.status == 200
        except Exception:
            return False

    # ---- Coaching Endpoints ----

    async def coach(
        self,
        fen: str,
        user_input: str = "",
        move_history: list[str] | None = None,
        difficulty: int = 3,
    ) -> AgentResponse:
        """Full coaching pipeline via POST /coach."""
        return await self._post("/coach", {
            "fen": fen,
            "user_input": user_input,
            "move_history": move_history or [],
            "difficulty": difficulty,
        })

    async def analyze(self, fen: str) -> AgentResponse:
        """Position analysis via POST /coach/analyze."""
        return await self._post("/coach/analyze", {"fen": fen})

    async def detect_blunders(
        self,
        fen: str,
        move_history: list[str] | None = None,
    ) -> AgentResponse:
        """Blunder detection via POST /coach/blunder."""
        return await self._post("/coach/blunder", {
            "fen": fen,
            "move_history": move_history or [],
        })

    async def generate_puzzle(self, fen: str) -> AgentResponse:
        """Puzzle generation via POST /coach/puzzle."""
        return await self._post("/coach/puzzle", {"fen": fen})

    async def get_features(
        self,
        fen: str,
        features: str = "material,mobility,king_safety,hanging_pieces,forks,pins,cannon_screens",
    ) -> AgentResponse:
        """Position feature extraction via POST /coach/features."""
        return await self._post("/coach/features", {
            "fen": fen,
            "features": features,
        })

    async def classify_move(self, fen: str, move: str) -> AgentResponse:
        """Move classification via POST /coach/classify-move."""
        return await self._post("/coach/classify-move", {
            "fen": fen,
            "move": move,
        })

    # ---- Internal ----

    async def _post(self, path: str, payload: dict[str, Any]) -> AgentResponse:
        """POST JSON to the Go service and translate the response."""
        url = f"{self._base_url}{path}"
        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as resp:
                body = await resp.json()
                if resp.status != 200:
                    return AgentResponse(
                        source="GoCoachingService",
                        response_type=ResponseType.ERROR,
                        message=body.get("error", f"Go service returned {resp.status}"),
                        data=body,
                    )
                return self._translate(body)
        except asyncio.TimeoutError:
            logger.warning("Go coaching service timed out: %s", url)
            return AgentResponse(
                source="GoCoachingService",
                response_type=ResponseType.ERROR,
                message="Go coaching service timed out",
            )
        except aiohttp.ClientError as exc:
            logger.warning("Go coaching service unreachable: %s", exc)
            return AgentResponse(
                source="GoCoachingService",
                response_type=ResponseType.ERROR,
                message=f"Go coaching service unreachable: {exc}",
            )

    @staticmethod
    def _translate(body: dict[str, Any]) -> AgentResponse:
        """Convert a Go JSON coaching response into a Python AgentResponse."""
        resp_type = _GO_TYPE_MAP.get(
            body.get("type", "info"), ResponseType.INFO
        )
        return AgentResponse(
            source="GoCoachingService",
            response_type=resp_type,
            message=body.get("message", ""),
            data=body.get("data", {}),
            follow_up_agent=body.get("follow_up_agent"),
        )
