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
import time
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass

import websockets
from websockets.exceptions import ConnectionClosed

from events import Event, EventBus, EventType
from state import GameStateBridge, STARTING_FEN

logger = logging.getLogger("engine_relay")

ENGINE_WS_URL = os.getenv("ENGINE_WS_URL", "ws://engine:8080/ws")
RECONNECT_DELAY = 2.0  # seconds between reconnection attempts
MAX_RECONNECT_DELAY = 30.0


@dataclass
class PendingReply:
    future: asyncio.Future | None
    suppress_side_effects: bool


class EngineRelay:
    """Maintains a persistent WS connection to the Rust engine and
    synchronises state changes with the bridge."""

    def __init__(self, state: GameStateBridge, bus: EventBus) -> None:
        self.state = state
        self.bus = bus
        self._observer_ws: websockets.WebSocketClientProtocol | None = None
        self._command_ws: websockets.WebSocketClientProtocol | None = None
        self._command_outbox: asyncio.Queue[str] = asyncio.Queue()
        self._pending: dict[str, deque[PendingReply]] = defaultdict(deque)
        self._dispatch_lock = asyncio.Lock()
        self.connected = False
        self.observer_connected = False
        self.command_connected = False
        self.last_connected_at: float | None = None
        self.last_disconnected_at: float | None = None
        self.last_message_at: float | None = None
        self.last_authoritative_sync_at: float | None = None
        self.last_error: str | None = None
        self.last_engine_seq = 0

    # ------------------------------------------------------------------
    # Public API — called by the bridge app to send commands to engine
    # ------------------------------------------------------------------

    async def send_get_state(self) -> None:
        await self._send_serialized({"type": "get_state"})

    async def send_move(self, move_str: str, *, command_id: str | None = None) -> None:
        msg: dict[str, str] = {"type": "move", "move": move_str}
        if command_id:
            msg["command_id"] = command_id
        await self._send_serialized(msg)

    async def send_move_and_wait(
        self,
        move_str: str,
        *,
        command_id: str | None = None,
        timeout: float = 15.0,
    ) -> dict:
        msg: dict[str, str] = {"type": "move", "move": move_str}
        if command_id:
            msg["command_id"] = command_id
        return await self._send_and_wait(msg, expect_type="move_result", timeout=timeout)

    async def send_legal_moves(self, square: str) -> None:
        await self._send_serialized({"type": "legal_moves", "square": square})

    async def send_ai_move(self, difficulty: int | None = None) -> None:
        msg: dict = {"type": "ai_move"}
        if difficulty is not None:
            msg["difficulty"] = difficulty
        await self._send_serialized(msg)

    async def send_ai_move_and_wait(
        self,
        difficulty: int | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict:
        msg: dict = {"type": "ai_move"}
        if difficulty is not None:
            msg["difficulty"] = difficulty
        return await self._send_and_wait(msg, expect_type="ai_move", timeout=timeout)

    async def send_set_position(self, fen: str, *, resume_seq: int | None = None) -> None:
        msg: dict[str, str | int] = {"type": "set_position", "fen": fen}
        if resume_seq is not None:
            msg["resume_seq"] = resume_seq
        await self._send_serialized(msg)

    async def send_reset(self, *, command_id: str | None = None) -> None:
        msg: dict[str, str] = {"type": "reset"}
        if command_id:
            msg["command_id"] = command_id
        await self._send_serialized(msg)

    async def send_reset_and_wait(
        self,
        *,
        command_id: str | None = None,
        timeout: float = 15.0,
    ) -> dict:
        msg: dict[str, str] = {"type": "reset"}
        if command_id:
            msg["command_id"] = command_id
        result = await self._send_and_wait(msg, expect_type="state", timeout=timeout)
        # Sync last_engine_seq with the engine's post-reset seq so that
        # subsequent observer events are not discarded as stale.
        new_seq = result.get("seq")
        if isinstance(new_seq, int):
            self.last_engine_seq = new_seq
        else:
            self.last_engine_seq = 0
        return result

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
        async with self._dispatch_lock:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[dict] = loop.create_future()
            self._pending[expect_type].append(PendingReply(
                future=fut,
                suppress_side_effects=suppress_side_effects,
            ))
            await self._send(msg)
            try:
                return await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                self._discard_pending(expect_type, fut)
                raise
            finally:
                self._discard_pending(expect_type, fut)

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
        return await self._send_and_wait(
            {"type": "suggest_for_fen", "fen": fen, "difficulty": depth},
            expect_type="suggestion",
            timeout=30.0,
            suppress_side_effects=True,
        )

    async def send_detect_puzzle(self, fen: str, depth: int) -> dict:
        """Analyse a position for tactical puzzle characteristics — waits for reply."""
        return await self._send_and_wait(
            {"type": "detect_puzzle", "fen": fen, "depth": depth},
            expect_type="puzzle_detection",
            timeout=90.0,
        )

    async def send_validate_fen(self, fen: str) -> dict:
        """Validate a FEN by attempting set_position — waits for reply."""
        return await self._send_and_wait(
            {"type": "validate_fen", "fen": fen},
            expect_type="validation",
            suppress_side_effects=True,
        )

    async def send_legal_moves_for_square(self, fen: str, square: str) -> dict:
        """Set position then get legal moves for a square — waits for reply."""
        return await self._send_and_wait(
            {"type": "legal_moves_for_fen", "fen": fen, "square": square},
            expect_type="legal_moves",
            suppress_side_effects=True,
        )

    async def send_make_move(self, fen: str, move: str) -> dict:
        """Set position then make a move — waits for move_result."""
        return await self._send_and_wait(
            {"type": "make_move_for_fen", "fen": fen, "move": move},
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
            observer_reader: asyncio.Task[None] | None = None
            command_reader: asyncio.Task[None] | None = None
            command_writer: asyncio.Task[None] | None = None
            try:
                logger.info("Connecting to engine at %s", ENGINE_WS_URL)
                async with websockets.connect(
                    ENGINE_WS_URL,
                    ping_interval=30,
                    ping_timeout=120,
                    close_timeout=5,
                ) as observer_ws:
                    self._observer_ws = observer_ws
                    self.observer_connected = True
                    async with websockets.connect(
                        ENGINE_WS_URL,
                        ping_interval=30,
                        ping_timeout=120,
                        close_timeout=5,
                    ) as command_ws:
                        self._command_ws = command_ws
                        self.command_connected = True
                        self.connected = True
                        self.last_connected_at = time.time()
                        self.last_error = None
                        delay = RECONNECT_DELAY  # reset on successful connect
                        logger.info("Engine relay connected (observer + command channels)")
                        observer_reader = asyncio.create_task(
                            self._observer_reader(observer_ws)
                        )
                        command_reader = asyncio.create_task(
                            self._command_reader(command_ws)
                        )
                        command_writer = asyncio.create_task(
                            self._command_writer(command_ws)
                        )
                        await self._restore_engine_session()
                        await self._refresh_snapshot_from_command()
                        watched = {observer_reader, command_reader, command_writer}
                        done, pending = await asyncio.wait(
                            watched,
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
                self.last_error = str(exc)
                logger.warning("Engine connection lost: %s — reconnecting in %.0fs",
                               exc, delay)
            except Exception:
                self.last_error = "unexpected relay error"
                logger.exception("Unexpected relay error — reconnecting in %.0fs", delay)
            finally:
                for task in (observer_reader, command_reader, command_writer):
                    if task is not None and not task.done():
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
                if self.connected:
                    self.last_disconnected_at = time.time()
                self.connected = False
                self.observer_connected = False
                self.command_connected = False
                self._observer_ws = None
                self._command_ws = None

            await asyncio.sleep(delay)
            delay = min(delay * 1.5, MAX_RECONNECT_DELAY)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send(self, msg: dict) -> None:
        self._command_outbox.put_nowait(json.dumps(msg))

    async def _send_serialized(self, msg: dict) -> None:
        async with self._dispatch_lock:
            await self._send(msg)

    def _discard_pending(self, expect_type: str, fut: asyncio.Future) -> None:
        queue = self._pending.get(expect_type)
        if not queue:
            return
        remaining = deque(item for item in queue if item.future is not fut)
        if remaining:
            self._pending[expect_type] = remaining
        else:
            self._pending.pop(expect_type, None)

    def _pop_pending(self, expect_type: str) -> PendingReply | None:
        queue = self._pending.get(expect_type)
        if not queue:
            return None
        item = queue.popleft()
        if not queue:
            self._pending.pop(expect_type, None)
        return item

    async def _restore_engine_session(self) -> None:
        if self.state.fen == STARTING_FEN and self.state.event_seq == 0:
            return

        await self._send_and_wait(
            {
                "type": "set_position",
                "fen": self.state.fen,
                "resume_seq": self.state.event_seq,
            },
            expect_type="state",
            timeout=15.0,
            suppress_side_effects=True,
        )

    async def _refresh_snapshot_from_command(self, *, publish_sync: bool = False) -> None:
        snapshot = await self._send_and_wait(
            {"type": "get_state"},
            expect_type="state",
            timeout=15.0,
            suppress_side_effects=True,
        )
        await self._apply_state_message(snapshot, publish_event=False)
        if publish_sync:
            await self.bus.publish(Event(
                type=EventType.STATE_SYNC,
                data=self.state.to_dict(),
                sequence=self.last_engine_seq,
            ))

    async def _command_writer(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            try:
                raw = await self._command_outbox.get()
            except asyncio.CancelledError:
                raise
            try:
                await ws.send(raw)
            except ConnectionClosed:
                # Put the message back so it can be retried after reconnect.
                self._command_outbox.put_nowait(raw)
                raise

    async def _observer_reader(self, ws: websockets.WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await self._handle_authoritative_message(msg)

    async def _command_reader(self, ws: websockets.WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await self._handle_command_response(msg)

    async def _handle_command_response(self, msg: dict) -> None:
        msg_type = msg.get("type")
        self.last_message_at = time.time()
        pending = self._pop_pending(msg_type) if msg_type is not None else None
        if pending is None:
            if msg_type == "error":
                for pending_type in list(self._pending):
                    pending = self._pop_pending(pending_type)
                    if pending is not None:
                        break
            if pending is None and msg_type == "error":
                logger.error("Engine command error: %s", msg.get("message", "unknown"))
                self.last_error = msg.get("message", "unknown")
                return

        if pending is None:
            return

        if pending.future is not None and not pending.future.done():
            pending.future.set_result(msg)
        if pending.suppress_side_effects:
            return

    def _authoritative_seq(self, msg: dict) -> int | None:
        seq = msg.get("seq")
        return seq if isinstance(seq, int) and seq >= 0 else None

    def _is_authoritative_event(self, msg_type: str | None) -> bool:
        return msg_type in {"state", "move_result", "ai_move"}

    async def _resync_snapshot(self, reason: str) -> None:
        logger.warning("Resyncing bridge snapshot: %s", reason)
        await self._refresh_snapshot_from_command(publish_sync=True)

    async def _apply_state_message(self, msg: dict, *, publish_event: bool) -> None:
        fen = msg["fen"]
        self.state.apply_fen(fen)
        self.state.side_to_move = msg.get("side_to_move", "red")
        self.state.game_result = msg.get("result", "in_progress")
        self.state.is_check = msg.get("is_check", False)
        seq = self._authoritative_seq(msg)
        if seq is not None:
            self.state.event_seq = seq
            self.last_engine_seq = seq
        self.last_authoritative_sync_at = time.time()
        if publish_event:
            await self.bus.publish(Event(
                type=EventType.FEN_UPDATE,
                data={"fen": fen, "source": "engine",
                      "side_to_move": self.state.side_to_move,
                      "result": self.state.game_result,
                      "is_check": self.state.is_check,
                      "engine_seq": self.state.event_seq},
                sequence=self.state.event_seq,
            ))

    async def _handle_authoritative_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        self.last_message_at = time.time()

        if self._is_authoritative_event(msg_type):
            seq = self._authoritative_seq(msg)
            if seq is None:
                await self._resync_snapshot(f"missing seq on {msg_type}")
                return
            if seq > self.last_engine_seq + 1:
                await self._resync_snapshot(
                    f"observer gap detected: last_seq={self.last_engine_seq}, incoming_seq={seq}"
                )
                return
            if self.last_engine_seq and seq <= self.last_engine_seq:
                logger.warning(
                    "Ignoring stale authoritative event: type=%s seq=%s last_seq=%s",
                    msg_type,
                    seq,
                    self.last_engine_seq,
                )
                return

        if msg_type == "state":
            await self._apply_state_message(msg, publish_event=True)

        elif msg_type == "move_result":
            if msg.get("valid"):
                move_str = msg.get("move", "")
                fen = msg["fen"]
                seq = self._authoritative_seq(msg)
                from_sq = move_str[:2] if len(move_str) >= 4 else ""
                to_sq = move_str[2:4] if len(move_str) >= 4 else ""
                self.state.apply_move(from_sq, to_sq, fen_after=fen)
                self.state.game_result = msg.get("result", "in_progress")
                self.state.is_check = msg.get("is_check", False)
                if seq is not None:
                    self.state.event_seq = seq
                    self.last_engine_seq = seq
                self.last_authoritative_sync_at = time.time()
                await self.bus.publish(Event(
                    type=EventType.MOVE_MADE,
                    data={"from": from_sq, "to": to_sq, "fen": fen,
                           "source": "player",
                           "result": self.state.game_result,
                           "is_check": self.state.is_check,
                           "engine_seq": self.state.event_seq,
                           "command_id": msg.get("command_id")},
                    sequence=self.state.event_seq,
                ))

        elif msg_type == "ai_move":
            move_str = msg.get("move", "")
            fen = msg["fen"]
            seq = self._authoritative_seq(msg)
            from_sq = move_str[:2] if len(move_str) >= 4 else ""
            to_sq = move_str[2:4] if len(move_str) >= 4 else ""
            self.state.apply_move(from_sq, to_sq, fen_after=fen)
            self.state.game_result = msg.get("result", "in_progress")
            self.state.is_check = msg.get("is_check", False)
            if seq is not None:
                self.state.event_seq = seq
                self.last_engine_seq = seq
            self.last_authoritative_sync_at = time.time()
            await self.bus.publish(Event(
                type=EventType.MOVE_MADE,
                data={"from": from_sq, "to": to_sq, "fen": fen,
                      "source": "ai",
                      "score": msg.get("score", 0),
                      "result": self.state.game_result,
                      "is_check": self.state.is_check,
                      "engine_seq": self.state.event_seq},
                sequence=self.state.event_seq,
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
            self.last_error = msg.get("message", "unknown")

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "bundle_healthy": self.connected,
            "observer_connected": self.observer_connected,
            "command_connected": self.command_connected,
            "last_connected_at": self.last_connected_at,
            "last_disconnected_at": self.last_disconnected_at,
            "last_message_at": self.last_message_at,
            "last_authoritative_sync_at": self.last_authoritative_sync_at,
            "last_engine_seq": self.last_engine_seq,
            "pending_requests": sum(len(queue) for queue in self._pending.values()),
            "queued_messages": self._command_outbox.qsize(),
            "last_error": self.last_error,
        }
