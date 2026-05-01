from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_BRIDGE_ROOT = REPO_ROOT / "server" / "state_bridge"
LED_ROOT = REPO_ROOT / "ledsystem"

for path in (str(STATE_BRIDGE_ROOT), str(LED_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

# Set the auth token before importing the bridge so the module-level
# constant picks it up during import.
TEST_BRIDGE_TOKEN = "test-bridge-token-for-pytest"
os.environ["STATE_BRIDGE_TOKEN"] = TEST_BRIDGE_TOKEN
TEST_AUTH_HEADERS = {"Authorization": f"Bearer {TEST_BRIDGE_TOKEN}"}


from events import EventBus  # noqa: E402
from state import GameStateBridge, STARTING_FEN  # noqa: E402
import app as bridge_app  # noqa: E402


class FakeRelay:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.run_calls = 0
        self._stop = False
        self.connected = True
        self.legal_moves_by_square: dict[str, list[str]] = {
            "b0": ["a2", "c2"],
            "e3": ["e4", "e5"],
            "a0": ["a1", "a2"],
        }
        self.suggestion_response: dict[str, Any] = {
            "type": "suggestion",
            "move": "b0c2",
            "score": 120,
        }
        self.make_move_results: dict[tuple[str, str], dict[str, Any]] = {}

    async def run(self) -> None:
        self.run_calls += 1
        while not self._stop:
            await asyncio.sleep(0.01)

    def stop(self) -> None:
        self._stop = True

    async def send_get_state(self) -> None:
        self.calls.append(("get_state",))

    async def send_move(self, move_str: str, *, command_id: str | None = None) -> None:
        self.calls.append(("move", move_str, command_id))

    async def send_move_and_wait(
        self,
        move_str: str,
        *,
        command_id: str | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        self.calls.append(("move_and_wait", move_str, command_id, timeout))
        return {
            "type": "move_result",
            "valid": True,
            "move": move_str,
            "fen": "fen-after-move",
            "result": "in_progress",
            "is_check": False,
            "command_id": command_id,
        }

    async def send_legal_moves(self, square: str) -> None:
        self.calls.append(("legal_moves", square))

    async def send_legal_moves_for_square(self, fen: str, square: str) -> dict[str, Any]:
        self.calls.append(("legal_moves_for_square", fen, square))
        return {
            "type": "legal_moves",
            "square": square,
            "targets": list(self.legal_moves_by_square.get(square, [])),
        }

    async def send_ai_move(self, difficulty: int | None = None) -> None:
        self.calls.append(("ai_move", difficulty))

    async def send_ai_move_and_wait(
        self,
        difficulty: int | None = None,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        self.calls.append(("ai_move_and_wait", difficulty, timeout))
        return {
            "type": "ai_move",
            "move": "b0c2",
            "fen": "fen-after-ai",
            "score": 50,
            "result": "in_progress",
            "is_check": False,
        }

    async def send_set_position(self, fen: str, *, resume_seq: int | None = None) -> None:
        self.calls.append(("set_position", fen, resume_seq))

    async def send_reset(self, *, command_id: str | None = None) -> None:
        self.calls.append(("reset", command_id))

    async def send_reset_and_wait(
        self,
        *,
        command_id: str | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        self.calls.append(("reset_and_wait", command_id, timeout))
        return {
            "type": "state",
            "fen": STARTING_FEN,
            "side_to_move": "red",
            "result": "in_progress",
            "is_check": False,
            "seq": 0,
        }

    async def send_suggest(self, fen: str, depth: int) -> dict[str, Any]:
        self.calls.append(("suggest", fen, depth))
        return dict(self.suggestion_response)

    async def send_validate_fen(self, fen: str) -> dict[str, Any]:
        self.calls.append(("validate_fen", fen))
        return {
            "type": "validation",
            "valid": True,
            "normalized_fen": fen,
            "reason": None,
        }

    async def send_make_move(self, fen: str, move: str) -> dict[str, Any]:
        self.calls.append(("make_move", fen, move))
        if (fen, move) in self.make_move_results:
            return dict(self.make_move_results[(fen, move)])
        return {
            "type": "move_result",
            "valid": True,
            "move": move,
            "fen": f"{fen}|{move}",
            "result": "in_progress",
            "is_check": False,
        }

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "last_connected_at": None,
            "last_disconnected_at": None,
            "last_message_at": None,
            "last_authoritative_sync_at": None,
            "last_engine_seq": 0,
            "pending_requests": 0,
            "queued_messages": 0,
            "last_error": None,
        }


@pytest.fixture
def bridge_testbed(monkeypatch):
    state = GameStateBridge()
    bus = EventBus()
    relay = FakeRelay()

    monkeypatch.setattr(bridge_app, "state", state)
    monkeypatch.setattr(bridge_app, "bus", bus)
    monkeypatch.setattr(bridge_app, "relay", relay)
    bridge_app._seen_command_ids.clear()
    bridge_app._seen_command_order.clear()
    bridge_app._recent_cv_fens.clear()

    yield bridge_app, state, bus, relay

    relay.stop()


@pytest.fixture
def client(bridge_testbed):
    app_module, _, _, relay = bridge_testbed
    with TestClient(app_module.app, headers=TEST_AUTH_HEADERS) as test_client:
        yield test_client
    relay.stop()


class _ConnectedRequest:
    """Stand-in for FastAPI's Request used when invoking handler functions
    directly (bypassing the HTTP middleware in async unit tests)."""

    headers: dict[str, str] = TEST_AUTH_HEADERS
    query_params: dict[str, str] = {}

    async def is_disconnected(self) -> bool:
        return False


@pytest.fixture
def capture_sse_events(bridge_testbed):
    app_module, _, _, _ = bridge_testbed

    async def _capture(
        expected: int = 1,
        *,
        include_state_sync: bool = False,
    ) -> asyncio.Task[list[dict[str, Any]]]:
        response = await app_module.sse_events(_ConnectedRequest())

        async def _reader() -> list[dict[str, Any]]:
            events: list[dict[str, Any]] = []
            try:
                async for chunk in response.body_iterator:
                    text = chunk.decode() if isinstance(chunk, bytes) else chunk
                    for line in text.splitlines():
                        if line.startswith("data: "):
                            payload = json.loads(line[6:])
                            if not include_state_sync and payload.get("type") == "state_sync":
                                continue
                            events.append(payload)
                            if len(events) >= expected:
                                return events
                return events
            finally:
                await response.body_iterator.aclose()

        task = asyncio.create_task(_reader())
        await asyncio.sleep(0)
        return task

    return _capture


def parse_sse_payload(raw_line: str) -> dict[str, Any]:
    assert raw_line.startswith("data: ")
    return json.loads(raw_line[6:])
