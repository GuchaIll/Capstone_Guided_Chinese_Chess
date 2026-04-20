from __future__ import annotations

import asyncio
import json
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


from events import EventBus  # noqa: E402
from state import GameStateBridge  # noqa: E402
import app as bridge_app  # noqa: E402


class FakeRelay:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.run_calls = 0
        self._stop = False

    async def run(self) -> None:
        self.run_calls += 1
        while not self._stop:
            await asyncio.sleep(0.01)

    def stop(self) -> None:
        self._stop = True

    async def send_get_state(self) -> None:
        self.calls.append(("get_state",))

    async def send_move(self, move_str: str) -> None:
        self.calls.append(("move", move_str))

    async def send_legal_moves(self, square: str) -> None:
        self.calls.append(("legal_moves", square))

    async def send_ai_move(self, difficulty: int | None = None) -> None:
        self.calls.append(("ai_move", difficulty))

    async def send_set_position(self, fen: str) -> None:
        self.calls.append(("set_position", fen))

    async def send_reset(self) -> None:
        self.calls.append(("reset",))


@pytest.fixture
def bridge_testbed(monkeypatch):
    state = GameStateBridge()
    bus = EventBus()
    relay = FakeRelay()

    monkeypatch.setattr(bridge_app, "state", state)
    monkeypatch.setattr(bridge_app, "bus", bus)
    monkeypatch.setattr(bridge_app, "relay", relay)

    yield bridge_app, state, bus, relay

    relay.stop()


@pytest.fixture
def client(bridge_testbed):
    app_module, _, _, relay = bridge_testbed
    with TestClient(app_module.app) as test_client:
        yield test_client
    relay.stop()


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


@pytest.fixture
def capture_sse_events(bridge_testbed):
    app_module, _, _, _ = bridge_testbed

    async def _capture(expected: int = 1) -> asyncio.Task[list[dict[str, Any]]]:
        response = await app_module.sse_events(_ConnectedRequest())

        async def _reader() -> list[dict[str, Any]]:
            events: list[dict[str, Any]] = []
            async for chunk in response.body_iterator:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                for line in text.splitlines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
                        if len(events) >= expected:
                            return events
            return events

        task = asyncio.create_task(_reader())
        await asyncio.sleep(0)
        return task

    return _capture


def parse_sse_payload(raw_line: str) -> dict[str, Any]:
    assert raw_line.startswith("data: ")
    return json.loads(raw_line[6:])
