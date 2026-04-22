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


def _looks_like_xiangqi_fen(fen: str) -> bool:
    """Best-effort FEN format validation before delegating to the engine.

    The recovered engine loader is permissive and silently accepts malformed
    input by producing an empty/default board. The bridge should reject clearly
    invalid payloads up front so downstream services get a reliable contract.
    """
    parts = fen.split()
    if len(parts) < 2:
        return False

    ranks = parts[0].split("/")
    if len(ranks) != 10:
        return False

    allowed_pieces = set("rnbakcpRNBAKCPehEH")
    for rank in ranks:
        width = 0
        for ch in rank:
            if ch.isdigit():
                width += int(ch)
            elif ch in allowed_pieces:
                width += 1
            else:
                return False
        if width != 9:
            return False

    if parts[1].lower() not in {"w", "b"}:
        return False

    if len(parts) >= 5 and not parts[4].isdigit():
        return False
    if len(parts) >= 6 and not parts[5].isdigit():
        return False

    return True


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


class AnalyzePayload(BaseModel):
    fen: str
    depth: int = 5


class BatchAnalyzePayload(BaseModel):
    moves: list[dict]  # each: {"fen": "...", "move_str": "..."}


class SuggestPayload(BaseModel):
    fen: str
    depth: int = 5


class ValidateFenPayload(BaseModel):
    fen: str


class LegalMovesPayload(BaseModel):
    fen: str
    square: str = ""  # if empty, return all legal moves


class MakeMovePayload(BaseModel):
    fen: str
    move: str  # e.g. "e3e4"


class IsMoveLegalPayload(BaseModel):
    fen: str
    move: str  # e.g. "e3e4"


class DetectPuzzlePayload(BaseModel):
    fen: str
    depth: int = 5
    best_move: str | None = None


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


# ── Request-response engine endpoints (Go coaching uses these) ──────

@app.post("/engine/analyze")
async def engine_analyze(body: AnalyzePayload):
    """Analyze a position — returns the full engine analysis response.

    The Rust engine returns {"type":"analysis","features":{...}}.
    Go coaching (BridgeClient/AnalysisResponse) expects the fields from
    `features` at the top level.  We unwrap the envelope here.
    """
    try:
        result = await relay.send_analyze(body.fen, body.depth)
        # Unwrap envelope: return the features object directly so Go can
        # decode top-level fields (search_score, phase_name, material, …).
        if isinstance(result, dict) and "features" in result:
            return JSONResponse(result["features"])
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/batch-analyze")
async def engine_batch_analyze(body: BatchAnalyzePayload):
    """Batch analyze multiple moves.

    The Rust engine returns {"type":"batch_analysis","results":[{"features":{...},...}]}.
    Go coaching expects []MoveFeatureVector — a plain JSON array of feature objects.
    We unwrap the envelope here so the shapes match.
    """
    try:
        result = await relay.send_batch_analyze(body.moves)
        # Unwrap envelope: extract features from each BatchResult
        raw_results = result.get("results", [])
        features = [r.get("features", r) for r in raw_results]
        return JSONResponse(features)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/suggest")
async def engine_suggest(body: SuggestPayload):
    """Get best move suggestion for a position."""
    try:
        result = await relay.send_suggest(body.fen, body.depth)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/validate-fen")
async def engine_validate_fen(body: ValidateFenPayload):
    """Validate a FEN string via the engine."""
    if not _looks_like_xiangqi_fen(body.fen):
        return {
            "valid": False,
            "detail": {"type": "error", "message": "Invalid Xiangqi FEN format"},
        }
    try:
        result = await relay.send_validate_fen(body.fen)
        valid = result.get("type") != "error"
        return {"valid": valid, "detail": result}
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/legal-moves")
async def engine_legal_moves(body: LegalMovesPayload):
    """Get legal moves for a square (or all squares) at a given FEN."""
    try:
        if body.square:
            result = await relay.send_legal_moves_for_square(body.fen, body.square)
            return JSONResponse(result)
        else:
            # All legal moves: iterate a-i × 0-9
            all_moves: list[str] = []
            for col_ch in "abcdefghi":
                for row in range(10):
                    sq = f"{col_ch}{row}"
                    try:
                        result = await relay.send_legal_moves_for_square(body.fen, sq)
                        targets = result.get("targets", [])
                        for t in targets:
                            all_moves.append(f"{sq}{t}")
                    except asyncio.TimeoutError:
                        continue
            return {"type": "all_legal_moves", "moves": all_moves}
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/make-move")
async def engine_make_move(body: MakeMovePayload):
    """Set position then apply a move — returns move_result."""
    try:
        result = await relay.send_make_move(body.fen, body.move)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/is-move-legal")
async def engine_is_move_legal(body: IsMoveLegalPayload):
    """Check if a move is legal at a given FEN."""
    if len(body.move) < 4:
        return {"legal": False, "error": "Invalid move format"}
    from_sq = body.move[:2]
    to_sq = body.move[2:]
    try:
        result = await relay.send_legal_moves_for_square(body.fen, from_sq)
        targets = result.get("targets", [])
        return {"legal": to_sq in targets, "targets": targets}
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/puzzle-detect")
async def engine_puzzle_detect(body: DetectPuzzlePayload):
    """Analyse a position for tactical puzzle characteristics.

    Returns the ``PuzzleDetection`` payload produced by the Rust engine's
    ``puzzle_detector`` module, unwrapped from its WebSocket envelope so that
    the Go coaching service can decode it directly.
    """
    try:
        result = await relay.send_detect_puzzle(body.fen, body.depth)
        # Unwrap envelope: {"type":"puzzle_detection","detection":{...}} → detection
        if isinstance(result, dict) and "detection" in result:
            return JSONResponse(result["detection"])
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


# =====================================================================
# SSE — real-time event stream
# =====================================================================

@app.get("/state/events")
async def sse_events(request: Request):
    """Server-Sent Events stream.  Subscribers receive every bridge event."""

    async def generate():
        yield Event(type=EventType.STATE_SYNC, data=state.to_dict()).to_sse()
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
