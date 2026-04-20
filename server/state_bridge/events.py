"""Async pub/sub event bus for the state bridge.

Subscribers receive events via asyncio queues.  The bus is process-local
(single-process FastAPI) — no external broker needed.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


class EventType(str, Enum):
    FEN_UPDATE = "fen_update"
    MOVE_MADE = "move_made"
    CV_CAPTURE = "cv_capture"
    LED_COMMAND = "led_command"
    BEST_MOVE = "best_move"
    PIECE_SELECTED = "piece_selected"
    GAME_RESET = "game_reset"
    STATE_SYNC = "state_sync"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        """Format as an SSE message line."""
        payload = json.dumps({"type": self.type.value, "data": self.data,
                              "ts": self.timestamp})
        return f"data: {payload}\n\n"


class EventBus:
    """Simple broadcast bus: publish sends to every subscriber queue."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, event: Event) -> None:
        dead: list[asyncio.Queue[Event]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        # Drop slow/dead subscribers
        for q in dead:
            self.unsubscribe(q)

    async def stream(self) -> AsyncIterator[Event]:
        """Yield events as they arrive.  Cleans up on exit."""
        q = self.subscribe()
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self.unsubscribe(q)
