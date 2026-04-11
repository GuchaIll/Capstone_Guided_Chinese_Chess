"""
Engine Client
=============

Async WebSocket client for communicating with the Rust Chinese Chess engine.

Connects to: ws://localhost:8080/ws

Protocol Messages (matching Engine/src/api.rs):
  -> { type: "move", move: "e3e4" }
  -> { type: "reset" }
  -> { type: "get_state" }
  -> { type: "ai_move", difficulty?: u8 }
  -> { type: "set_position", fen: "..." }
  -> { type: "legal_moves", square: "e0" }
  -> { type: "suggest", difficulty?: u8 }

  <- { type: "state", fen, side_to_move, result, is_check }
  <- { type: "move_result", valid, fen, reason?, move?, is_check, result }
  <- { type: "ai_move", move, fen, score, nodes_searched, is_check, result }
  <- { type: "legal_moves", square, targets: [...] }
  <- { type: "suggestion", move, from, to, score, nodes_searched }
  <- { type: "error", message }

Features:
  - Auto-reconnection with exponential backoff
  - Request-response correlation via asyncio Events
  - Connection health monitoring
  - Typed method interface for each engine command
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional


logger = logging.getLogger("tools.engine_client")


# ========================
#     ENGINE CLIENT
# ========================

class EngineClient:
    """Async WebSocket client for the Rust Xiangqi engine.

    Usage:
        client = EngineClient("ws://localhost:8080/ws")
        await client.connect()
        result = await client.send_move("e3e4")
        await client.disconnect()
    """

    def __init__(
        self,
        url: str = "ws://localhost:8080/ws",
        reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
    ):
        self._url = url
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._connected = False
        self._response_event = asyncio.Event()
        self._last_response: Optional[dict] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._response_timeout: float = 30.0  # seconds

    # ---- Connection Management ----

    async def connect(self) -> bool:
        """Establish WebSocket connection to the engine.

        Returns True if connection was successful.
        """
        try:
            import websockets
            self._ws = await websockets.connect(self._url)
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.info(f"Connected to engine at {self._url}")

            # Engine sends initial state on connect -- consume it
            initial_state = await self._wait_for_response(timeout=5.0)
            logger.debug(f"Initial state: {initial_state}")
            return True
        except ImportError:
            logger.error(
                "websockets package not installed. "
                "Run: pip install websockets"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to connect to engine: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        logger.info("Disconnected from engine")

    async def reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        await self.disconnect()
        delay = self._reconnect_delay

        for attempt in range(1, self._reconnect_attempts + 1):
            logger.info(
                f"Reconnection attempt {attempt}/{self._reconnect_attempts} "
                f"(delay={delay:.1f}s)"
            )
            await asyncio.sleep(delay)
            if await self.connect():
                return True
            delay = min(delay * 2, 30.0)  # Cap at 30s

        logger.error("All reconnection attempts failed")
        return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ---- Engine Commands ----

    async def send_move(self, move_str: str) -> Optional[dict]:
        """Send a player move to the engine.

        Args:
            move_str: Move in coordinate notation (e.g., "e3e4")

        Returns:
            Engine's move_result response dict, or None on failure.
        """
        return await self._send_and_receive({
            "type": "move",
            "move": move_str,
        })

    async def request_ai_move(self, difficulty: int = 4) -> Optional[dict]:
        """Request the AI to generate and apply a move.

        Args:
            difficulty: Search depth (1-8)

        Returns:
            Engine's ai_move response dict, or None on failure.
        """
        return await self._send_and_receive(
            {"type": "ai_move", "difficulty": difficulty},
            timeout=self._response_timeout,
        )

    async def get_legal_moves(self, square: str) -> Optional[dict]:
        """Get legal target squares for a piece.

        Args:
            square: Source square (e.g., "e0")

        Returns:
            Dict with "square" and "targets" list, or None.
        """
        return await self._send_and_receive({
            "type": "legal_moves",
            "square": square,
        })

    async def get_suggestion(self, difficulty: int = 4) -> Optional[dict]:
        """Get AI's best move suggestion without applying it.

        Args:
            difficulty: Search depth (1-8)

        Returns:
            Dict with "move", "from", "to", "score", or None.
        """
        return await self._send_and_receive(
            {"type": "suggest", "difficulty": difficulty},
            timeout=self._response_timeout,
        )

    async def reset(self) -> Optional[dict]:
        """Reset the board to starting position.

        Returns:
            State dict with new FEN, or None.
        """
        return await self._send_and_receive({"type": "reset"})

    async def set_position(self, fen: str) -> Optional[dict]:
        """Set the board to a specific FEN position.

        Args:
            fen: FEN string representing the desired position.

        Returns:
            State dict with the set FEN, or None.
        """
        return await self._send_and_receive({
            "type": "set_position",
            "fen": fen,
        })

    async def get_state(self) -> Optional[dict]:
        """Get the current board state.

        Returns:
            State dict with fen, side_to_move, result, is_check.
        """
        return await self._send_and_receive({"type": "get_state"})

    # ---- Internal Communication ----

    async def _send_and_receive(
        self, message: dict, timeout: Optional[float] = None,
    ) -> Optional[dict]:
        """Send a message and wait for the response.

        Args:
            message: Dict to serialize as JSON and send.
            timeout: Max seconds to wait for response.

        Returns:
            Parsed response dict, or None on failure.
        """
        if not self._connected or not self._ws:
            logger.warning("Not connected to engine")
            if not await self.reconnect():
                return None

        timeout = timeout or 10.0

        try:
            self._response_event.clear()
            self._last_response = None

            payload = json.dumps(message)
            await self._ws.send(payload)
            logger.debug(f"Sent: {payload[:120]}")

            response = await self._wait_for_response(timeout=timeout)
            return response
        except Exception as e:
            logger.error(f"Send/receive failed: {e}")
            self._connected = False
            return None

    async def _wait_for_response(self, timeout: float = 10.0) -> Optional[dict]:
        """Wait for a response from the receive loop."""
        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=timeout
            )
            return self._last_response
        except asyncio.TimeoutError:
            logger.error(f"Response timeout after {timeout}s")
            return None

    async def _receive_loop(self) -> None:
        """Background task to receive WebSocket messages."""
        try:
            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)
                    logger.debug(f"Received: {str(data)[:120]}")
                    self._last_response = data
                    self._response_event.set()
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from engine: {e}")
        except Exception as e:
            if self._connected:
                logger.error(f"Receive loop error: {e}")
                self._connected = False
