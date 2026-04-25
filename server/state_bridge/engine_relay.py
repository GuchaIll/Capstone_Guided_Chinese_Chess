"""WebSocket relay between the Rust chess engine and the state bridge.

Connects to the engine WS, listens for state/move/ai_move messages, and
publishes corresponding events on the bridge EventBus.  Also accepts
commands from the bridge (piece selection, move requests) and forwards
them to the engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress

import websockets
from websockets.exceptions import ConnectionClosed

from events import Event, EventBus, EventType
from state import GameStateBridge

logger = logging.getLogger("engine_relay")

ENGINE_WS_URL = os.getenv("ENGINE_WS_URL", "ws://engine:8080/ws")
RECONNECT_DELAY = 2.0  # seconds between reconnection attempts
MAX_RECONNECT_DELAY = 30.0


class EngineRelay:
    """Maintains a persistent WS connection to the Rust engine and
    synchronises state changes with the bridge."""

    def __init__(self, state: GameStateBridge, bus: EventBus) -> None:
        self.state = state
        self.bus = bus
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._outbox: asyncio.Queue[str] = asyncio.Queue()
        # Request-response support: pending futures keyed by expected msg type.
        # The bool marks whether bridge state/event side effects should be
        # suppressed for the matching response.
        self._pending: dict[str, tuple[asyncio.Future, bool]] = {}

    # ------------------------------------------------------------------
    # Public API — called by the bridge app to send commands to engine
    # ------------------------------------------------------------------

    async def send_get_state(self) -> None:
        await self._send({"type": "get_state"})

    async def send_move(self, move_str: str) -> None:
        await self._send({"type": "move", "move": move_str})

    async def send_legal_moves(self, square: str) -> None:
        await self._send({"type": "legal_moves", "square": square})

    async def send_ai_move(self, difficulty: int | None = None) -> None:
        msg: dict = {"type": "ai_move"}
        if difficulty is not None:
            msg["difficulty"] = difficulty
        await self._send(msg)

    async def send_set_position(self, fen: str) -> None:
        await self._send({"type": "set_position", "fen": fen})

    async def send_reset(self) -> None:
        await self._send({"type": "reset"})

    # ── Request-response methods (wait for engine reply) ─────────────

    async def _send_and_wait(
        self,
        msg: dict,
        expect_type: str,
        timeout: float = 15.0,
        *,
        suppress_side_effects: bool = False,
    ) -> dict:
        """Send *msg* and wait for the first inbound message with
        type == *expect_type*, returning it as a dict."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[expect_type] = (fut, suppress_side_effects)
        await self._send(msg)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(expect_type, None)
            raise
        finally:
            self._pending.pop(expect_type, None)

    async def send_analyze(self, fen: str, depth: int) -> dict:
        """Analyze a position — waits for the engine reply."""
        return await self._send_and_wait(
            {"type": "analyze_position", "fen": fen, "difficulty": depth},
            expect_type="analysis",
            timeout=60.0,
        )

    async def send_batch_analyze(self, moves: list[dict]) -> dict:
        """Batch analyze moves — waits for the engine reply."""
        return await self._send_and_wait(
            {"type": "batch_analyze", "moves": moves},
            expect_type="batch_analysis",
            timeout=60.0,
        )

    async def send_suggest(self, fen: str, depth: int) -> dict:
        """Request best move suggestion — waits for the engine reply."""
        await self._send_and_wait(
            {"type": "set_position", "fen": fen},
            expect_type="state",
            suppress_side_effects=True,
        )
        return await self._send_and_wait(
            {"type": "suggest", "difficulty": depth},
            expect_type="suggestion",
            timeout=30.0,
        )

    async def send_detect_puzzle(self, fen: str, depth: int) -> dict:
        """Analyse a position for tactical puzzle characteristics — waits for reply."""
        return await self._send_and_wait(
            {"type": "detect_puzzle", "fen": fen, "depth": depth},
            expect_type="puzzle_detection",
            timeout=60.0,
        )

    async def send_validate_fen(self, fen: str) -> dict:
        """Validate a FEN by attempting set_position — waits for reply."""
        return await self._send_and_wait(
            {"type": "set_position", "fen": fen},
            expect_type="state",  # successful set_position returns "state"
            suppress_side_effects=True,
        )

    async def send_legal_moves_for_square(self, fen: str, square: str) -> dict:
        """Set position then get legal moves for a square — waits for reply."""
        await self._send_and_wait(
            {"type": "set_position", "fen": fen},
            expect_type="state",
            suppress_side_effects=True,
        )
        return await self._send_and_wait(
            {"type": "legal_moves", "square": square},
            expect_type="legal_moves",
            suppress_side_effects=True,
        )

    async def send_make_move(self, fen: str, move: str) -> dict:
        """Set position then make a move — waits for move_result."""
        await self._send_and_wait(
            {"type": "set_position", "fen": fen},
            expect_type="state",
            suppress_side_effects=True,
        )
        return await self._send_and_wait(
            {"type": "move", "move": move},
            expect_type="move_result",
            suppress_side_effects=True,
        )

    # ------------------------------------------------------------------
    # Background task — run as asyncio.create_task(relay.run())
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect to the engine WS and relay messages forever.
        Automatically reconnects with exponential back-off."""
        delay = RECONNECT_DELAY
        while True:
            reader: asyncio.Task[None] | None = None
            writer: asyncio.Task[None] | None = None
            try:
                logger.info("Connecting to engine at %s", ENGINE_WS_URL)
                async with websockets.connect(ENGINE_WS_URL) as ws:
                    self._ws = ws
                    delay = RECONNECT_DELAY  # reset on successful connect
                    logger.info("Engine relay connected")
                    reader = asyncio.create_task(self._reader(ws))
                    writer = asyncio.create_task(self._writer(ws))
                    done, pending = await asyncio.wait(
                        {reader, writer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    for task in pending:
                        with suppress(asyncio.CancelledError):
                            await task
                    for task in done:
                        exc = task.exception()
                        if exc is not None:
                            raise exc
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, OSError) as exc:
                logger.warning("Engine connection lost: %s — reconnecting in %.0fs",
                               exc, delay)
            except Exception:
                logger.exception("Unexpected relay error — reconnecting in %.0fs", delay)
            finally:
                for task in (reader, writer):
                    if task is not None and not task.done():
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                self._ws = None

            await asyncio.sleep(delay)
            delay = min(delay * 1.5, MAX_RECONNECT_DELAY)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send(self, msg: dict) -> None:
        self._outbox.put_nowait(json.dumps(msg))

    async def _writer(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            try:
                raw = await self._outbox.get()
            except asyncio.CancelledError:
                raise
            try:
                await ws.send(raw)
            except ConnectionClosed:
                # Put the message back so it can be retried after reconnect.
                self._outbox.put_nowait(raw)
                raise

    async def _reader(self, ws: websockets.WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await self._handle_message(msg)

    async def _handle_message(self, msg: dict) -> None:
        msg_type = msg.get("type")

        # ── Resolve pending request-response futures ─────────────────
        if msg_type in self._pending:
            fut, suppress_side_effects = self._pending.pop(msg_type)
            if not fut.done():
                fut.set_result(msg)
                if suppress_side_effects:
                    return
                # For live engine-originated messages, still fall through to
                # update bridge state and publish events.
                if msg_type not in ("state", "legal_moves", "move_result", "ai_move"):
                    return
        # Also resolve "state" futures when we get an error (validate_fen).
        if msg_type == "error" and "state" in self._pending:
            fut, suppress_side_effects = self._pending.pop("state")
            if not fut.done():
                fut.set_result(msg)
                if suppress_side_effects:
                    return
                # Still fall through to log the error.

        if msg_type == "state":
            fen = msg["fen"]
            self.state.apply_fen(fen)
            self.state.side_to_move = msg.get("side_to_move", "red")
            self.state.game_result = msg.get("result", "in_progress")
            self.state.is_check = msg.get("is_check", False)
            await self.bus.publish(Event(
                type=EventType.FEN_UPDATE,
                data={"fen": fen, "source": "engine",
                      "side_to_move": self.state.side_to_move,
                      "result": self.state.game_result,
                      "is_check": self.state.is_check},
            ))

        elif msg_type == "move_result":
            if msg.get("valid"):
                move_str = msg.get("move", "")
                fen = msg["fen"]
                from_sq = move_str[:2] if len(move_str) >= 4 else ""
                to_sq = move_str[2:4] if len(move_str) >= 4 else ""
                self.state.apply_move(from_sq, to_sq, fen_after=fen)
                self.state.game_result = msg.get("result", "in_progress")
                self.state.is_check = msg.get("is_check", False)
                await self.bus.publish(Event(
                    type=EventType.MOVE_MADE,
                    data={"from": from_sq, "to": to_sq, "fen": fen,
                          "source": "player",
                          "result": self.state.game_result,
                          "is_check": self.state.is_check},
                ))

        elif msg_type == "ai_move":
            move_str = msg.get("move", "")
            fen = msg["fen"]
            from_sq = move_str[:2] if len(move_str) >= 4 else ""
            to_sq = move_str[2:4] if len(move_str) >= 4 else ""
            self.state.apply_move(from_sq, to_sq, fen_after=fen)
            self.state.game_result = msg.get("result", "in_progress")
            self.state.is_check = msg.get("is_check", False)
            await self.bus.publish(Event(
                type=EventType.MOVE_MADE,
                data={"from": from_sq, "to": to_sq, "fen": fen,
                      "source": "ai",
                      "score": msg.get("score", 0),
                      "result": self.state.game_result,
                      "is_check": self.state.is_check},
            ))

        elif msg_type == "legal_moves":
            square = msg.get("square", "")
            targets = msg.get("targets", [])
            self.state.set_selection(square, targets)
            await self.bus.publish(Event(
                type=EventType.PIECE_SELECTED,
                data={"square": square, "targets": targets},
            ))

        elif msg_type == "error":
            logger.error("Engine error: %s", msg.get("message", "unknown"))
