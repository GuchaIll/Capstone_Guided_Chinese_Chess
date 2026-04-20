"""State Bridge — event bus between engine, CV, LED, coaching, and client.

Modelled after ledsystem/led_server.py (Flask REST → LED hardware).
Evolved to FastAPI with SSE streaming and engine WebSocket relay.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from events import Event, EventBus, EventType
from state import GameStateBridge, STARTING_FEN
from engine_relay import EngineRelay

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s  %(message)s")
logger = logging.getLogger("state_bridge")

# ── Shared singletons ────────────────────────────────────────────────
state = GameStateBridge()
bus = EventBus()
relay = EngineRelay(state, bus)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the engine relay on startup; cancel on shutdown."""
    task = asyncio.create_task(relay.run())
    logger.info("State bridge started — relay task launched")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("State bridge shut down")


app = FastAPI(title="State Bridge", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================================
# Request models (mirrors led_server.py JSON contracts, extended)
# =====================================================================


class FenPayload(BaseModel):
    fen: str
    source: str = "engine"  # "engine" | "cv"


class MovePayload(BaseModel):
    from_sq: str          # e.g. "e3"  (algebraic)
    to_sq: str            # e.g. "e4"
    piece: str = ""


class SelectPayload(BaseModel):
    square: str           # e.g. "e3"


class BestMovePayload(BaseModel):
    from_sq: str
    to_sq: str


class OpponentMovePayload(BaseModel):
    """Compat with led_server.py POST /opponent format (row/col indices)."""
    from_r: int
    from_c: int
    to_r: int
    to_c: int


class LedCommandPayload(BaseModel):
    command: str = "off"   # "off" | "on" | "clear"


class EngineMovePayload(BaseModel):
    """Tell the engine to apply a move in algebraic notation."""
    move: str              # e.g. "e3e4"


class AiMovePayload(BaseModel):
    difficulty: int | None = None


# =====================================================================
# GET — state snapshot
# =====================================================================

@app.get("/state")
async def get_state():
    return JSONResponse(state.to_dict())


@app.get("/health")
async def health():
    return {"status": "ok"}


# =====================================================================
# POST — state mutations (each publishes an event)
# =====================================================================

@app.post("/state/fen")
async def post_fen(body: FenPayload):
    state.apply_fen(body.fen, source=body.source)
    event_type = EventType.CV_CAPTURE if body.source == "cv" else EventType.FEN_UPDATE
    await bus.publish(Event(
        type=event_type,
        data={"fen": body.fen, "source": body.source},
    ))
    return {"status": "FEN updated", "source": body.source}


@app.post("/state/move")
async def post_move(body: MovePayload):
    rec = state.apply_move(body.from_sq, body.to_sq, piece=body.piece)
    await bus.publish(Event(
        type=EventType.MOVE_MADE,
        data={"from": rec.from_sq, "to": rec.to_sq, "piece": rec.piece,
              "source": "bridge"},
    ))
    return {"status": "Move recorded"}


@app.post("/state/select")
async def post_select(body: SelectPayload):
    # Ask the engine for legal moves — relay will publish PIECE_SELECTED
    await relay.send_legal_moves(body.square)
    return {"status": "Selection forwarded to engine"}


@app.post("/state/best-move")
async def post_best_move(body: BestMovePayload):
    state.set_best_move(body.from_sq, body.to_sq)
    await bus.publish(Event(
        type=EventType.BEST_MOVE,
        data={"from": body.from_sq, "to": body.to_sq},
    ))
    return {"status": "Best move set"}


@app.post("/state/led-command")
async def post_led_command(body: LedCommandPayload):
    state.leds_off = body.command == "off"
    await bus.publish(Event(
        type=EventType.LED_COMMAND,
        data={"command": body.command},
    ))
    return {"status": f"LED command '{body.command}' published"}


# ── LED-server-compatible endpoints ──────────────────────────────────
# These mirror the original led_server.py contract so the LED board code
# can POST here directly without changes.

@app.post("/fen")
async def compat_fen(body: FenPayload):
    """Compat with led_server.py POST /fen."""
    return await post_fen(body)


@app.post("/opponent")
async def compat_opponent(body: OpponentMovePayload):
    """Compat with led_server.py POST /opponent."""
    # Convert row/col to algebraic (col a-i, row 0-9)
    from_sq = f"{chr(ord('a') + body.from_c)}{body.from_r}"
    to_sq = f"{chr(ord('a') + body.to_c)}{body.to_r}"
    rec = state.apply_move(from_sq, to_sq)
    await bus.publish(Event(
        type=EventType.MOVE_MADE,
        data={"from": rec.from_sq, "to": rec.to_sq, "source": "opponent",
              "from_r": body.from_r, "from_c": body.from_c,
              "to_r": body.to_r, "to_c": body.to_c},
    ))
    return {"status": "Opponent move displayed"}


# ── Engine passthrough endpoints ────────────────────────────────────

@app.post("/engine/move")
async def engine_move(body: EngineMovePayload):
    """Forward a move to the Rust engine via the relay."""
    await relay.send_move(body.move)
    return {"status": "Move forwarded to engine"}


@app.post("/engine/ai-move")
async def engine_ai_move(body: AiMovePayload):
    await relay.send_ai_move(body.difficulty)
    return {"status": "AI move requested"}


@app.post("/engine/reset")
async def engine_reset():
    await relay.send_reset()
    state.move_history.clear()
    state.last_move = None
    state.selected_square = None
    state.legal_moves = []
    state.best_move_from = None
    state.best_move_to = None
    await bus.publish(Event(type=EventType.GAME_RESET, data={}))
    return {"status": "Game reset"}


@app.post("/engine/set-position")
async def engine_set_position(body: FenPayload):
    await relay.send_set_position(body.fen)
    return {"status": "Position forwarded to engine"}


# =====================================================================
# SSE — real-time event stream
# =====================================================================

@app.get("/state/events")
async def sse_events(request: Request):
    """Server-Sent Events stream.  Subscribers receive every bridge event."""

    async def generate():
        async for event in bus.stream():
            if await request.is_disconnected():
                break
            yield event.to_sse()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("BRIDGE_PORT", "5003"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
