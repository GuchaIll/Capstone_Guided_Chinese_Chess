from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field

import pytest

import engine_relay as relay_module
from events import EventBus
from state import GameStateBridge


@dataclass
class FakeWebSocket:
    server: "FakeEngineServer"
    incoming: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    closed: bool = False

    async def send(self, raw: str) -> None:
        if self.closed:
            raise RuntimeError("websocket is closed")
        await self.server.received.put(json.loads(raw))

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            await self.incoming.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self.incoming.get()
        if item is None:
            raise StopAsyncIteration
        return item


class FakeConnect:
    def __init__(self, server: "FakeEngineServer") -> None:
        self.server = server
        self.websocket: FakeWebSocket | None = None

    async def __aenter__(self) -> FakeWebSocket:
        self.websocket = FakeWebSocket(self.server)
        self.server.connections.append(self.websocket)
        self.server.connection_count += 1
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self.websocket is not None:
            await self.websocket.close()
        return False


class FakeEngineServer:
    def __init__(self) -> None:
        self.received: asyncio.Queue[dict] = asyncio.Queue()
        self.connections: list[FakeWebSocket] = []
        self.connection_count = 0

    def _connection_at_role(self, offset: int) -> FakeWebSocket:
        for index in range(len(self.connections) - 1 - offset, -1, -2):
            candidate = self.connections[index]
            if not candidate.closed:
                return candidate
        raise AssertionError(f"No live engine connection for offset {offset}")

    async def send_to(self, index: int, payload: dict) -> None:
        assert len(self.connections) > index, f"No engine connection at index {index}"
        await self.connections[index].incoming.put(json.dumps(payload))

    async def send_observer(self, payload: dict) -> None:
        await self._connection_at_role(1).incoming.put(json.dumps(payload))

    async def send_command(self, payload: dict) -> None:
        await self._connection_at_role(0).incoming.put(json.dumps(payload))

    async def close_latest(self) -> None:
        assert self.connections, "No engine connection available"
        await self.connections[-1].close()

    async def close_observer(self) -> None:
        assert self.connections, "No engine connection available"
        await self.connections[0].close()

    async def next_message(self, timeout: float = 1.0) -> dict:
        return await asyncio.wait_for(self.received.get(), timeout)

    async def wait_for_connections(self, expected: int, timeout: float = 2.0) -> None:
        async def _wait():
            while self.connection_count < expected:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(_wait(), timeout)


@pytest.fixture
async def running_relay(monkeypatch):
    server = FakeEngineServer()
    monkeypatch.setattr(relay_module.websockets, "connect", lambda _url: FakeConnect(server))
    monkeypatch.setattr(relay_module, "ENGINE_WS_URL", "ws://fake-engine/ws")
    monkeypatch.setattr(relay_module, "RECONNECT_DELAY", 0.05)
    monkeypatch.setattr(relay_module, "MAX_RECONNECT_DELAY", 0.1)

    state = GameStateBridge()
    bus = EventBus()
    relay = relay_module.EngineRelay(state, bus)
    task = asyncio.create_task(relay.run())
    await server.wait_for_connections(2)
    assert await server.next_message() == {"type": "get_state"}
    await server.send_command(
        {
            "type": "state",
            "fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
            "side_to_move": "red",
            "result": "in_progress",
            "is_check": False,
            "seq": 0,
        }
    )
    await asyncio.wait_for(_relay_ready(relay), 1.0)

    try:
        yield relay, state, bus, server
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _read_event(queue: asyncio.Queue, timeout: float = 1.0):
    return await asyncio.wait_for(queue.get(), timeout)


async def _relay_ready(relay) -> None:
    while not relay.connected:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_relay_sends_expected_outbound_commands(running_relay):
    relay, _, _, server = running_relay

    await relay.send_get_state()
    await relay.send_move("a0a1")
    await relay.send_legal_moves("b2")
    await relay.send_ai_move(4)
    await relay.send_set_position("9/9/9/9/9/9/9/9/9/9 b - - 0 1")
    await relay.send_reset()

    assert await server.next_message() == {"type": "get_state"}
    assert await server.next_message() == {"type": "move", "move": "a0a1"}
    assert await server.next_message() == {"type": "legal_moves", "square": "b2"}
    assert await server.next_message() == {"type": "ai_move", "difficulty": 4}
    assert await server.next_message() == {
        "type": "set_position",
        "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
    }
    assert await server.next_message() == {"type": "reset"}


@pytest.mark.asyncio
async def test_relay_request_response_helpers_cover_analyze_suggest_validate_and_make_move(running_relay):
    relay, _, _, server = running_relay

    analyze_task = asyncio.create_task(relay.send_analyze("fen-a", 3))
    assert await server.next_message() == {"type": "analyze_position", "fen": "fen-a", "difficulty": 3}
    await server.send_command({"type": "analysis", "score": 42, "features": {"fen": "fen-a"}})
    assert await asyncio.wait_for(analyze_task, 1.0) == {
        "type": "analysis",
        "score": 42,
        "features": {"fen": "fen-a"},
    }

    suggest_task = asyncio.create_task(relay.send_suggest("fen-b", 5))
    assert await server.next_message() == {"type": "suggest_for_fen", "fen": "fen-b", "difficulty": 5}
    await server.send_command({"type": "suggestion", "move": "b0c2", "score": 100})
    assert await asyncio.wait_for(suggest_task, 1.0) == {
        "type": "suggestion",
        "move": "b0c2",
        "score": 100,
    }

    validate_task = asyncio.create_task(relay.send_validate_fen("fen-c"))
    assert await server.next_message() == {"type": "validate_fen", "fen": "fen-c"}
    await server.send_command({"type": "validation", "valid": True, "normalized_fen": "fen-c", "reason": None})
    assert await asyncio.wait_for(validate_task, 1.0) == {
        "type": "validation",
        "valid": True,
        "normalized_fen": "fen-c",
        "reason": None,
    }

    make_move_task = asyncio.create_task(relay.send_make_move("fen-d", "a0a1"))
    assert await server.next_message() == {"type": "make_move_for_fen", "fen": "fen-d", "move": "a0a1"}
    await server.send_command(
        {
            "type": "move_result",
            "valid": True,
            "move": "a0a1",
            "fen": "fen-after",
            "result": "in_progress",
            "is_check": False,
        }
    )
    assert await asyncio.wait_for(make_move_task, 1.0) == {
        "type": "move_result",
        "valid": True,
        "move": "a0a1",
        "fen": "fen-after",
        "result": "in_progress",
        "is_check": False,
    }


@pytest.mark.asyncio
async def test_request_response_helpers_do_not_publish_or_mutate_bridge_state(running_relay):
    relay, state, bus, server = running_relay
    queue = bus.subscribe()

    try:
        legal_task = asyncio.create_task(relay.send_legal_moves_for_square("fen-e", "b0"))
        assert await server.next_message() == {"type": "legal_moves_for_fen", "fen": "fen-e", "square": "b0"}
        await server.send_command({"type": "legal_moves", "square": "b0", "targets": ["c2"]})
        assert await asyncio.wait_for(legal_task, 1.0) == {
            "type": "legal_moves",
            "square": "b0",
            "targets": ["c2"],
        }

        assert state.fen != "fen-e"
        assert state.selected_square is None
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), 0.05)
    finally:
        bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_relay_translates_state_message_into_bridge_state_and_event(running_relay):
    _, state, bus, server = running_relay
    queue = bus.subscribe()

    try:
        await server.send_observer(
            {
                "type": "state",
                "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
                "side_to_move": "black",
                "result": "in_progress",
                "is_check": True,
                "seq": 1,
            }
        )
        event = await _read_event(queue)
    finally:
        bus.unsubscribe(queue)

    assert event.type.value == "fen_update"
    assert event.data["source"] == "engine"
    assert state.fen == "9/9/9/9/9/9/9/9/9/9 b - - 0 1"
    assert state.side_to_move == "black"
    assert state.game_result == "in_progress"
    assert state.is_check is True
    assert state.event_seq == 1


@pytest.mark.asyncio
async def test_relay_translates_valid_player_move_result(running_relay):
    _, state, bus, server = running_relay
    queue = bus.subscribe()

    try:
        await server.send_observer(
            {
                "type": "move_result",
                "valid": True,
                "move": "a0a1",
                "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
                "result": "in_progress",
                "is_check": False,
                "seq": 1,
                "command_id": "cmd-1",
            }
        )
        event = await _read_event(queue)
    finally:
        bus.unsubscribe(queue)

    assert event.type.value == "move_made"
    assert event.data["source"] == "player"
    assert event.data["from"] == "a0"
    assert event.data["to"] == "a1"
    assert event.data["command_id"] == "cmd-1"
    assert state.last_move is not None
    assert state.last_move.from_sq == "a0"
    assert state.last_move.to_sq == "a1"
    assert state.fen == "9/9/9/9/9/9/9/9/9/9 b - - 0 1"
    assert state.event_seq == 1


@pytest.mark.asyncio
async def test_relay_translates_ai_move_and_legal_moves(running_relay):
    _, state, bus, server = running_relay
    queue = bus.subscribe()

    try:
        await server.send_observer(
            {
                "type": "ai_move",
                "move": "b2b3",
                "fen": "9/9/9/9/9/9/9/9/9/9 w - - 0 1",
                "score": 42,
                "result": "in_progress",
                "is_check": True,
                "seq": 1,
            }
        )
        ai_event = await _read_event(queue)
        assert ai_event.type.value == "move_made"
        assert ai_event.data["source"] == "ai"
        assert ai_event.data["score"] == 42

        await server.send_observer({"type": "legal_moves", "square": "c3", "targets": ["c4", "c5"]})
        selection_event = await _read_event(queue)
    finally:
        bus.unsubscribe(queue)

    assert selection_event.type.value == "piece_selected"
    assert selection_event.data == {"square": "c3", "targets": ["c4", "c5"]}
    assert state.selected_square == "c3"
    assert state.legal_moves == ["c4", "c5"]


@pytest.mark.asyncio
async def test_error_message_does_not_corrupt_state(running_relay):
    _, state, bus, server = running_relay
    state.apply_fen("9/9/9/9/9/9/9/9/9/9 w - - 0 1")
    queue = bus.subscribe()

    try:
        await server.send_observer({"type": "error", "message": "boom"})
        await asyncio.sleep(0.05)
        assert queue.empty()
        assert state.fen == "9/9/9/9/9/9/9/9/9/9 w - - 0 1"
        assert state.last_move is None
    finally:
        bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_relay_resyncs_after_authoritative_seq_gap(running_relay):
    _, state, bus, server = running_relay
    queue = bus.subscribe()

    try:
        await server.send_observer(
            {
                "type": "move_result",
                "valid": True,
                "move": "a0a1",
                "fen": "fen-gap",
                "result": "in_progress",
                "is_check": False,
                "seq": 2,
            }
        )
        assert await server.next_message() == {"type": "get_state"}
        await server.send_command(
            {
                "type": "state",
                "fen": "fen-resynced",
                "side_to_move": "black",
                "result": "in_progress",
                "is_check": False,
                "seq": 5,
            }
        )
        event = await _read_event(queue)
    finally:
        bus.unsubscribe(queue)

    assert event.type.value == "state_sync"
    assert state.fen == "fen-resynced"
    assert state.event_seq == 5


@pytest.mark.asyncio
async def test_relay_reconnects_after_engine_disconnect(running_relay):
    relay, _, _, server = running_relay

    await server.close_observer()
    await server.wait_for_connections(4)
    assert await server.next_message(timeout=2.0) == {"type": "get_state"}
    await server.send_command(
        {
            "type": "state",
            "fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
            "side_to_move": "red",
            "result": "in_progress",
            "is_check": False,
            "seq": 0,
        }
    )
    await relay.send_get_state()
    assert await server.next_message(timeout=2.0) == {"type": "get_state"}


@pytest.mark.asyncio
async def test_relay_restores_engine_snapshot_before_refresh(running_relay):
    relay, state, _, server = running_relay
    state.apply_fen("9/9/9/9/9/9/9/9/9/9 b - - 0 1")
    state.event_seq = 7

    await server.close_observer()
    await server.wait_for_connections(4)
    assert await server.next_message(timeout=2.0) == {
        "type": "set_position",
        "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
        "resume_seq": 7,
    }
    await server.send_command(
        {
            "type": "state",
            "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
            "side_to_move": "black",
            "result": "in_progress",
            "is_check": False,
            "seq": 7,
        }
    )
    assert await server.next_message(timeout=2.0) == {"type": "get_state"}
    await server.send_command(
        {
            "type": "state",
            "fen": "9/9/9/9/9/9/9/9/9/9 b - - 0 1",
            "side_to_move": "black",
            "result": "in_progress",
            "is_check": False,
            "seq": 7,
        }
    )

    await relay.send_get_state()
    assert await server.next_message(timeout=2.0) == {"type": "get_state"}
