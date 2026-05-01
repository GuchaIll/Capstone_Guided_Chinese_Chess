"""State Bridge — event bus between engine, CV, LED, coaching, and client.

Modelled after ledsystem/led_server.py (Flask REST → LED hardware).
Evolved to FastAPI with SSE streaming and engine WebSocket relay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
import urllib.error
import urllib.request
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

from cv_validation import FenDiffError, derive_move_from_fen_diff
from events import Event, EventBus, EventType
from event_models import (
    BestMoveData,
    CvCaptureData,
    CvCaptureRequestedData,
    CvCaptureResultData,
    CvValidationErrorData,
    FenUpdateData,
    KiboTriggerData,
    LedEngineTurnData,
    LedCommandData,
    LedGameResultData,
    LedPlayerTurnData,
    LedResetData,
    MoveMadeData,
    PieceSelectedData,
    StateSyncData,
)
from state import GameStateBridge, STARTING_FEN
from engine_relay import EngineRelay

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s  %(message)s")
logger = logging.getLogger("state_bridge")


def _load_local_env_files() -> None:
    """Load repo-local env files for standalone bridge runs."""
    file_path = Path(__file__).resolve()
    search_roots = [file_path.parent, *file_path.parents]
    seen: set[Path] = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        for candidate in (root / ".env", root / ".ENV"):
            if candidate.exists():
                load_dotenv(candidate, override=False)


def _resolve_led_server_url(env: dict[str, str] | None = None) -> str:
    """Resolve the direct LED control base URL from explicit URL or Pi host."""
    env_map = os.environ if env is None else env

    explicit_url = (
        env_map.get("LED_SERVER_URL")
        or env_map.get("LED_URL")
        or ""
    ).strip()
    if explicit_url:
        return explicit_url.rstrip("/")

    pi_host = (
        env_map.get("RASPBERRY_PI_IP")
        or env_map.get("RASPBERY_PI_IP")
        or ""
    ).strip()
    if not pi_host:
        return ""

    if "://" in pi_host:
        return pi_host.rstrip("/")

    led_port = (env_map.get("LED_SERVER_PORT") or "5000").strip() or "5000"
    return f"http://{pi_host}:{led_port}".rstrip("/")


_load_local_env_files()

# ── Shared singletons ────────────────────────────────────────────────
state = GameStateBridge()
bus = EventBus()
relay = EngineRelay(state, bus)
DEFAULT_SUGGEST_DEPTH = 5
DEFAULT_AI_DIFFICULTY = 4
MAX_TRACKED_COMMAND_IDS = 4096
CV_DEDUP_WINDOW_SECONDS = 0.5
CV_SERVICE_URL = os.getenv("CV_SERVICE_URL", "http://localhost:5005").rstrip("/")
CV_CAPTURE_TIMEOUT_SECONDS = float(os.getenv("CV_CAPTURE_TIMEOUT_SECONDS", "20"))
CV_HEALTH_TIMEOUT_SECONDS = float(os.getenv("CV_HEALTH_TIMEOUT_SECONDS", "3"))
CV_LED_BLACKOUT_SECONDS = float(os.getenv("CV_LED_BLACKOUT_SECONDS", "0.2"))
LED_SERVER_URL = _resolve_led_server_url()
LED_CONTROL_TIMEOUT_SECONDS = float(os.getenv("LED_CONTROL_TIMEOUT_SECONDS", "1.5"))
_seen_command_ids: set[str] = set()
_seen_command_order: deque[str] = deque()
_recent_cv_fens: dict[str, float] = {}

# ── Authorization ────────────────────────────────────────────────────
# Mutating endpoints, the SSE event stream, and both WebSocket surfaces
# require a Bearer token presented in the Authorization header, or a
# `?token=` query parameter for callers that cannot set headers (notably
# the browser EventSource API).
STATE_BRIDGE_TOKEN = os.getenv("STATE_BRIDGE_TOKEN", "").strip()
# /health stays open so liveness probes and load-balancers don't need the
# secret. Everything else is gated.
PUBLIC_PATHS: frozenset[str] = frozenset({"/health"})

if not STATE_BRIDGE_TOKEN:
    logger.warning(
        "STATE_BRIDGE_TOKEN is unset — the bridge will refuse every gated "
        "request with HTTP 503. Set STATE_BRIDGE_TOKEN in the environment "
        "before exposing this service."
    )


def _extract_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _check_token(presented: str | None) -> bool:
    if not STATE_BRIDGE_TOKEN or presented is None:
        return False
    return secrets.compare_digest(presented, STATE_BRIDGE_TOKEN)


def _authorize_request(request: Request) -> JSONResponse | None:
    """Return a 401/503 response if the request is not authorized, else None."""
    if not STATE_BRIDGE_TOKEN:
        return JSONResponse(
            {"error": "Bridge misconfigured: STATE_BRIDGE_TOKEN unset"},
            status_code=503,
        )
    auth_header = request.headers.get("authorization")
    query_token = request.query_params.get("token")
    presented = _extract_bearer(auth_header) or query_token
    if not _check_token(presented):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


async def _authorize_websocket(websocket: WebSocket) -> bool:
    """Validate the WS handshake; close with 1008 and return False on failure."""
    presented = (
        _extract_bearer(websocket.headers.get("authorization"))
        or websocket.query_params.get("token")
    )
    if not _check_token(presented):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False
    return True


_CV_TO_ENGINE_FEN_TRANSLATION = str.maketrans(
    {
        "H": "N",
        "h": "n",
        "E": "B",
        "e": "b",
        "G": "K",
        "g": "k",
        "S": "P",
        "s": "p",
    }
)


def _normalize_xiangqi_fen(fen: str) -> str:
    parts = fen.strip().split()
    if not parts:
        return fen.strip()
    parts[0] = parts[0].translate(_CV_TO_ENGINE_FEN_TRANSLATION)
    return " ".join(parts)


def _fen_placements_equal(left_fen: str, right_fen: str) -> bool:
    left_parts = _normalize_xiangqi_fen(left_fen).split()
    right_parts = _normalize_xiangqi_fen(right_fen).split()
    if not left_parts or not right_parts:
        return False
    return left_parts[0] == right_parts[0]


def _looks_like_xiangqi_fen(fen: str) -> bool:
    """Best-effort FEN format validation before delegating to the engine.

    The recovered engine loader is permissive and silently accepts malformed
    input by producing an empty/default board. The bridge should reject clearly
    invalid payloads up front so downstream services get a reliable contract.
    """
    parts = _normalize_xiangqi_fen(fen).split()
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


@app.middleware("http")
async def authorization_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    rejection = _authorize_request(request)
    if rejection is not None:
        return rejection
    return await call_next(request)

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
    command_id: str | None = None


class AiMovePayload(BaseModel):
    difficulty: int | None = None


class ResetPayload(BaseModel):
    command_id: str | None = None


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


# Valid trigger names must match KiboTrigger in Kibo/src/types.ts
_VALID_KIBO_TRIGGERS = frozenset({
    "player_win", "player_lose", "material_gain", "high_accuracy",
    "avoids_blunder", "optimal_move", "misses_move", "illegal_move",
})


class KiboTriggerPayload(BaseModel):
    trigger: str    # one of _VALID_KIBO_TRIGGERS
    duration: float | None = None   # animation crossfade duration (seconds)


class CvCaptureResult(BaseModel):
    """Validated shape of the CV /capture response.

    Mirror of the React-side BridgeCaptureResult schema. Fields the bridge
    doesn't republish (e.g. image_base64) are accepted but ignored via
    `model_config = {"extra": "ignore"}`.
    """

    model_config = {"extra": "ignore"}

    status: str = "unknown"
    fen: str | None = None
    issues: list[str] = []
    # CV service emits capture_id as an int sequence number; accept either
    # form so a future change in the upstream encoding doesn't desync the
    # bridge contract.
    capture_id: str | int | None = None
    captured_at: str | None = None
    image_path: str | None = None
    image_mime: str | None = None

    @field_validator("captured_at", mode="before")
    @classmethod
    def _normalize_captured_at(cls, value):
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        return str(value)


def _bridge_state_message() -> dict[str, object]:
    return {
        "type": "state",
        "fen": state.fen,
        "side_to_move": state.side_to_move,
        "result": state.game_result,
        "is_check": state.is_check,
        "seq": state.event_seq,
    }


def _normalize_suggestion_message(result: dict[str, object]) -> dict[str, object]:
    """Return the browser-facing suggestion shape.

    The engine relay commonly returns {"type":"suggestion","move":"b0c2"} while
    the React client expects explicit `from` / `to` fields. Keep the original
    payload fields when present, but always derive the split squares when we can.
    """
    normalized = dict(result)
    move = str(normalized.get("move", "") or "")
    if "from" not in normalized and len(move) >= 4:
        normalized["from"] = move[:2]
    if "to" not in normalized and len(move) >= 4:
        normalized["to"] = move[2:4]
    return normalized


# =====================================================================
# GET — state snapshot
# =====================================================================

@app.get("/state")
async def get_state():
    return JSONResponse(state.to_dict())


@app.get("/health")
async def health():
    authoritative_bundle_healthy = relay.connected
    cv_service_healthy, cv_health_detail = await _check_cv_service_health()
    return {
        "status": "ok",
        "authoritative_bundle_healthy": authoritative_bundle_healthy,
        "cv_service_healthy": cv_service_healthy,
        "relay": relay.status(),
        "cv_service": {
            "healthy": cv_service_healthy,
            "url": CV_SERVICE_URL,
            "detail": cv_health_detail,
        },
        "snapshot": {
            "fen": state.fen,
            "side_to_move": state.side_to_move,
            "move_count": len(state.move_history),
            "event_seq": state.event_seq,
        },
    }


def _claim_command_id(command_id: str | None) -> tuple[str, bool]:
    normalized = (command_id or "").strip() or uuid.uuid4().hex
    if normalized in _seen_command_ids:
        return normalized, False

    _seen_command_ids.add(normalized)
    _seen_command_order.append(normalized)
    while len(_seen_command_order) > MAX_TRACKED_COMMAND_IDS:
        expired = _seen_command_order.popleft()
        _seen_command_ids.discard(expired)
    return normalized, True


def _is_duplicate_cv_capture(fen: str) -> bool:
    now = time.monotonic()
    expired = [
        cached_fen
        for cached_fen, seen_at in _recent_cv_fens.items()
        if now - seen_at > CV_DEDUP_WINDOW_SECONDS
    ]
    for cached_fen in expired:
        _recent_cv_fens.pop(cached_fen, None)

    previous = _recent_cv_fens.get(fen)
    _recent_cv_fens[fen] = now
    return previous is not None and now - previous <= CV_DEDUP_WINDOW_SECONDS


async def _publish_led_command(command: str, *, source: str | None = None) -> None:
    state.leds_off = command == "off"
    await bus.publish(Event.from_model(
        EventType.LED_COMMAND,
        LedCommandData(command=command, source=source),
    ))


async def _publish_led_player_turn() -> None:
    await bus.publish(Event.from_model(
        EventType.LED_PLAYER_TURN,
        LedPlayerTurnData(
            fen=state.fen,
            side_to_move=state.side_to_move,
            selected_square=state.selected_square,
            legal_targets=list(state.legal_moves),
            best_move_from=state.best_move_from,
            best_move_to=state.best_move_to,
        ),
    ))


async def _store_selection(square: str, targets: list[str]) -> None:
    state.set_selection(square, targets)
    await bus.publish(Event.from_model(
        EventType.PIECE_SELECTED,
        PieceSelectedData(square=square, targets=list(targets)),
    ))
    await _publish_led_player_turn()


async def _clear_selection() -> None:
    state.set_selection(None, [])
    await _publish_led_player_turn()


async def _store_best_move(from_sq: str, to_sq: str) -> None:
    state.set_best_move(from_sq, to_sq)
    await bus.publish(Event.from_model(
        EventType.BEST_MOVE,
        BestMoveData.model_validate({"from": from_sq, "to": to_sq}),
    ))
    await _publish_led_player_turn()


async def _publish_led_game_result(result: str) -> None:
    winner: str | None = None
    if result == "red_wins":
        winner = "red"
    elif result == "black_wins":
        winner = "black"
    await bus.publish(Event.from_model(
        EventType.LED_GAME_RESULT,
        LedGameResultData(result=result, winner=winner),
    ))


async def _publish_led_reset(reason: str = "reset") -> None:
    await bus.publish(Event.from_model(
        EventType.LED_RESET,
        LedResetData(reason=reason),
    ))


async def _publish_led_engine_turn(from_sq: str, to_sq: str, *, fen: str, result: str | None = None) -> None:
    await bus.publish(Event.from_model(
        EventType.LED_ENGINE_TURN,
        LedEngineTurnData(
            fen=fen,
            side_to_move=state.side_to_move,
            from_=from_sq,
            to=to_sq,
            result=result,
        ),
    ))


async def _publish_cv_validation_error(cv_fen: str, reason: str, *, status_code: int) -> JSONResponse:
    await bus.publish(Event.from_model(
        EventType.CV_VALIDATION_ERROR,
        CvValidationErrorData(
            source="cv",
            cv_fen=cv_fen,
            current_fen=state.fen,
            reason=reason,
        ),
    ))
    await _publish_led_command("on")
    return JSONResponse(
        {
            "accepted": False,
            "source": "cv",
            "reason": reason,
        },
        status_code=status_code,
    )


async def _publish_best_move_from_suggestion(fen: str) -> None:
    try:
        result = await relay.send_suggest(fen, DEFAULT_SUGGEST_DEPTH)
    except asyncio.TimeoutError:
        logger.warning("Timed out retrieving best move suggestion for accepted CV FEN")
        return

    move = result.get("move", "")
    if len(move) < 4:
        return

    from_sq = move[:2]
    to_sq = move[2:4]
    await _store_best_move(from_sq, to_sq)


def _engine_bundle_unavailable_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "Engine session bundle unavailable",
            "relay": relay.status(),
        },
        status_code=503,
    )


def _blocking_json_request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout: float = CV_CAPTURE_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, object]]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"error": raw or str(exc)}
        return exc.code, parsed


async def _request_cv_capture() -> tuple[int, dict[str, object]]:
    return await asyncio.to_thread(
        _blocking_json_request,
        f"{CV_SERVICE_URL}/capture",
        method="POST",
        body={"post_to_bridge": False},
    )


async def _call_led_server(path: str) -> bool:
    """Best-effort direct LED control for timing-critical capture blackout."""
    if not LED_SERVER_URL:
        return False
    try:
        status_code, payload = await asyncio.to_thread(
            _blocking_json_request,
            f"{LED_SERVER_URL}{path}",
            method="POST",
            body={},
            timeout=LED_CONTROL_TIMEOUT_SECONDS,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.warning("Direct LED control failed for %s: %s", path, exc)
        return False

    if 200 <= status_code < 300:
        return True

    logger.warning("Direct LED control returned %s for %s: %s", status_code, path, payload)
    return False


async def _check_cv_service_health() -> tuple[bool, dict[str, object]]:
    try:
        status_code, payload = await asyncio.to_thread(
            _blocking_json_request,
            f"{CV_SERVICE_URL}/health",
            method="GET",
            timeout=CV_HEALTH_TIMEOUT_SECONDS,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, {"error": str(exc)}

    healthy = status_code == 200 and payload.get("status") == "ok"
    return healthy, payload


# =====================================================================
# POST — state mutations (each publishes an event)
# =====================================================================

@app.post("/state/fen")
async def post_fen(body: FenPayload):
    if body.source == "cv":
        if not relay.connected:
            return _engine_bundle_unavailable_response()
        normalized_cv_fen = _normalize_xiangqi_fen(body.fen)
        state.apply_fen(normalized_cv_fen, source="cv")
        if _is_duplicate_cv_capture(normalized_cv_fen):
            return {
                "accepted": True,
                "duplicate": True,
                "source": body.source,
                "status": "Duplicate CV capture ignored",
            }
        if not _looks_like_xiangqi_fen(normalized_cv_fen):
            return await _publish_cv_validation_error(
                normalized_cv_fen,
                "malformed FEN",
                status_code=400,
            )

        try:
            derived_move = derive_move_from_fen_diff(state.fen, normalized_cv_fen)
        except FenDiffError as exc:
            return await _publish_cv_validation_error(
                normalized_cv_fen,
                str(exc),
                status_code=422,
            )

        try:
            legal = await relay.send_legal_moves_for_square(state.fen, derived_move.from_sq)
        except asyncio.TimeoutError:
            return JSONResponse({"error": "Engine timeout"}, status_code=504)

        if derived_move.to_sq not in legal.get("targets", []):
            return await _publish_cv_validation_error(
                normalized_cv_fen,
                "move not in legal moves",
                status_code=422,
            )

        try:
            move_result = await relay.send_make_move(state.fen, derived_move.move)
        except asyncio.TimeoutError:
            return JSONResponse({"error": "Engine timeout"}, status_code=504)

        authoritative_fen = move_result.get("fen")
        if move_result.get("valid") is not True or not isinstance(authoritative_fen, str):
            return await _publish_cv_validation_error(
                normalized_cv_fen,
                "engine could not materialize derived move",
                status_code=502,
            )
        if not _fen_placements_equal(normalized_cv_fen, authoritative_fen):
            return await _publish_cv_validation_error(
                normalized_cv_fen,
                "captured board does not match authoritative post-move position",
                status_code=422,
            )

        state.apply_move(
            derived_move.from_sq,
            derived_move.to_sq,
            piece=derived_move.piece,
            fen_after=authoritative_fen,
        )
        state.apply_fen(authoritative_fen, source="cv")
        await _publish_led_command("on")
        await bus.publish(Event.from_model(
            EventType.CV_CAPTURE,
            CvCaptureData(
                fen=authoritative_fen,
                source="cv",
                side_to_move=state.side_to_move,
                result=state.game_result,
                is_check=state.is_check,
            ),
        ))
        await _publish_best_move_from_suggestion(authoritative_fen)
        await relay.send_ai_move(DEFAULT_AI_DIFFICULTY)
        return {
            "accepted": True,
            "status": "FEN updated",
            "source": body.source,
            "move": derived_move.move,
        }

    state.apply_fen(body.fen, source=body.source)
    await bus.publish(Event.from_model(
        EventType.FEN_UPDATE,
        FenUpdateData(
            fen=body.fen,
            source=body.source,
            side_to_move=state.side_to_move,
            result=state.game_result,
            is_check=state.is_check,
        ),
    ))
    return {"status": "FEN updated", "source": body.source}


@app.post("/state/move")
async def post_move(body: MovePayload):
    rec = state.apply_move(body.from_sq, body.to_sq, piece=body.piece)
    await bus.publish(Event.from_model(
        EventType.MOVE_MADE,
        MoveMadeData.model_validate({
            "from": rec.from_sq,
            "to": rec.to_sq,
            "piece": rec.piece,
            "source": "bridge",
        }),
    ))
    return {"status": "Move recorded"}


@app.post("/state/select")
async def post_select(body: SelectPayload):
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    try:
        result = await relay.send_legal_moves_for_square(state.fen, body.square)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)

    targets = result.get("targets", [])
    await _store_selection(body.square, list(targets))
    return {"status": "Selection forwarded to engine", "targets": targets}


@app.post("/state/deselect")
async def post_deselect():
    await _clear_selection()
    return {"status": "Selection cleared"}


@app.post("/state/best-move")
async def post_best_move(body: BestMovePayload):
    await _store_best_move(body.from_sq, body.to_sq)
    return {"status": "Best move set"}


@app.post("/state/led-command")
async def post_led_command(body: LedCommandPayload):
    await _publish_led_command(body.command)
    return {"status": f"LED command '{body.command}' published"}


@app.post("/capture")
async def capture_board():
    led_paused_directly = await _call_led_server("/cv_pause")
    await _publish_led_command(
        "off",
        source="bridge_direct_http" if led_paused_directly else "event_bus_fallback",
    )
    if CV_LED_BLACKOUT_SECONDS > 0:
        await asyncio.sleep(CV_LED_BLACKOUT_SECONDS)

    await bus.publish(Event.from_model(
        EventType.CV_CAPTURE_REQUESTED,
        CvCaptureRequestedData(
            source="bridge",
            endpoint="/capture",
            cv_service_url=CV_SERVICE_URL,
        ),
    ))
    try:
        try:
            status_code, payload = await _request_cv_capture()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            logger.warning("CV capture request failed: %s", exc)
            await bus.publish(Event.from_model(
                EventType.CV_CAPTURE_RESULT,
                CvCaptureResultData(
                    status="unavailable",
                    fen=None,
                    issues=[str(exc)],
                    source="cv",
                ),
            ))
            return JSONResponse(
                {
                    "error": "CV capture service unavailable",
                    "cv_service_url": CV_SERVICE_URL,
                    "detail": str(exc),
                },
                status_code=503,
            )

        try:
            validated = CvCaptureResult.model_validate(payload)
        except Exception as exc:
            logger.warning("CV capture returned malformed payload: %s", exc)
            await bus.publish(Event.from_model(
                EventType.CV_CAPTURE_RESULT,
                CvCaptureResultData(
                    status="malformed",
                    fen=None,
                    issues=[f"malformed CV response: {exc}"],
                    source="cv",
                ),
            ))
            return JSONResponse(
                {"error": "CV service returned an unexpected payload shape"},
                status_code=502,
            )

        normalized_capture = validated.model_copy(
            update={
                "fen": _normalize_xiangqi_fen(validated.fen) if validated.fen else None,
            }
        )
        await bus.publish(Event.from_model(
            EventType.CV_CAPTURE_RESULT,
            CvCaptureResultData(**normalized_capture.model_dump(), source="cv"),
        ))
        return JSONResponse(normalized_capture.model_dump(exclude_none=True), status_code=status_code)
    finally:
        if led_paused_directly:
            await _call_led_server("/cv_resume")
        await _publish_led_command(
            "on",
            source="bridge_direct_http" if led_paused_directly else "event_bus_fallback",
        )


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
    await bus.publish(Event.from_model(
        EventType.MOVE_MADE,
        MoveMadeData.model_validate({
            "from": rec.from_sq,
            "to": rec.to_sq,
            "source": "opponent",
            "from_r": body.from_r,
            "from_c": body.from_c,
            "to_r": body.to_r,
            "to_c": body.to_c,
        }),
    ))
    await _publish_led_engine_turn(
        from_sq=from_sq,
        to_sq=to_sq,
        fen=state.fen,
        result=state.game_result,
    )
    return {"status": "Opponent move displayed"}


# ── Engine passthrough endpoints ────────────────────────────────────

@app.post("/engine/move")
async def engine_move(body: EngineMovePayload):
    """Forward a move to the Rust engine via the relay."""
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    command_id, accepted = _claim_command_id(body.command_id)
    if not accepted:
        return JSONResponse(
            {
                "error": "Duplicate command_id",
                "command_id": command_id,
            },
            status_code=409,
        )
    await relay.send_move(body.move, command_id=command_id)
    return {"status": "Move forwarded to engine", "command_id": command_id}


@app.post("/engine/ai-move")
async def engine_ai_move(body: AiMovePayload):
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    await relay.send_ai_move(body.difficulty)
    return {"status": "AI move requested"}


@app.post("/engine/reset")
async def engine_reset(body: ResetPayload | None = None):
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    command_id, accepted = _claim_command_id(body.command_id if body else None)
    if not accepted:
        return JSONResponse(
            {
                "error": "Duplicate command_id",
                "command_id": command_id,
            },
            status_code=409,
        )
    await relay.send_reset_and_wait(command_id=command_id)
    state.reset()
    await bus.publish(Event(type=EventType.GAME_RESET, data={}))
    await _publish_led_reset("engine_reset")
    return {"status": "Game reset", "command_id": command_id}


@app.post("/engine/set-position")
async def engine_set_position(body: FenPayload):
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    await relay.send_set_position(_normalize_xiangqi_fen(body.fen))
    return {"status": "Position forwarded to engine"}


# ── Request-response engine endpoints (Go coaching uses these) ──────

@app.post("/engine/analyze")
async def engine_analyze(body: AnalyzePayload):
    """Analyze a position — returns the full engine analysis response.

    The Rust engine returns {"type":"analysis","features":{...}}.
    Go coaching (BridgeClient/AnalysisResponse) expects the fields from
    `features` at the top level.  We unwrap the envelope here.
    """
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    try:
        result = await relay.send_analyze(_normalize_xiangqi_fen(body.fen), body.depth)
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
    if not relay.connected:
        return _engine_bundle_unavailable_response()
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
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    try:
        result = await relay.send_suggest(_normalize_xiangqi_fen(body.fen), body.depth)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/validate-fen")
async def engine_validate_fen(body: ValidateFenPayload):
    """Validate a FEN string via the engine."""
    normalized_fen = _normalize_xiangqi_fen(body.fen)
    if not _looks_like_xiangqi_fen(normalized_fen):
        return {
            "valid": False,
            "detail": {"type": "error", "message": "Invalid Xiangqi FEN format"},
        }
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    try:
        result = await relay.send_validate_fen(normalized_fen)
        valid = result.get("valid", False)
        return {"valid": valid, "detail": result}
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


def _moving_side_squares(fen: str) -> list[str]:
    """Return squares (algebraic) holding pieces of the side-to-move.

    Reduces the legal-moves enumeration from 90 squares to ~16 by skipping
    empty squares and pieces that cannot move on this turn. Avoids flooding
    the engine WebSocket and starving concurrent game messages.
    """
    parts = fen.split()
    if len(parts) < 2:
        return []
    red_to_move = parts[1].lower() == "w"
    ranks = parts[0].split("/")
    if len(ranks) != 10:
        return []

    squares: list[str] = []
    for rank_idx, rank_str in enumerate(ranks):
        rank = 9 - rank_idx  # FEN lists rank 9 first
        col = 0
        for ch in rank_str:
            if ch.isdigit():
                col += int(ch)
                continue
            if col >= 9:
                break
            piece_is_red = ch.isupper()
            if piece_is_red == red_to_move:
                squares.append(f"{chr(ord('a') + col)}{rank}")
            col += 1
    return squares


@app.post("/engine/legal-moves")
async def engine_legal_moves(body: LegalMovesPayload):
    """Get legal moves for a square (or all squares) at a given FEN."""
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    normalized_fen = _normalize_xiangqi_fen(body.fen)
    try:
        if body.square:
            result = await relay.send_legal_moves_for_square(normalized_fen, body.square)
            return JSONResponse(result)
        else:
            # Only iterate squares with pieces of the side-to-move (~16 vs 90)
            all_moves: list[str] = []
            for sq in _moving_side_squares(normalized_fen):
                try:
                    result = await relay.send_legal_moves_for_square(normalized_fen, sq)
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
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    try:
        result = await relay.send_make_move(_normalize_xiangqi_fen(body.fen), body.move)
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


@app.post("/engine/is-move-legal")
async def engine_is_move_legal(body: IsMoveLegalPayload):
    """Check if a move is legal at a given FEN."""
    if len(body.move) < 4:
        return {"legal": False, "error": "Invalid move format"}
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    from_sq = body.move[:2]
    to_sq = body.move[2:]
    normalized_fen = _normalize_xiangqi_fen(body.fen)
    try:
        result = await relay.send_legal_moves_for_square(normalized_fen, from_sq)
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
    if not relay.connected:
        return _engine_bundle_unavailable_response()
    try:
        result = await relay.send_detect_puzzle(_normalize_xiangqi_fen(body.fen), body.depth)
        # Unwrap envelope: {"type":"puzzle_detection","detection":{...}} → detection
        if isinstance(result, dict) and "detection" in result:
            return JSONResponse(result["detection"])
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Engine timeout"}, status_code=504)


# =====================================================================
# Kibo animation trigger
# =====================================================================

# Connected Kibo WebSocket clients
_kibo_clients: list[WebSocket] = []


@app.post("/kibo/trigger")
async def post_kibo_trigger(body: KiboTriggerPayload):
    """Publish a Kibo animation trigger to the event bus.

    The coaching agent (or any other service) calls this endpoint to
    drive a Kibo reaction without needing a direct WebSocket connection.
    The trigger is broadcast to all connected Kibo clients via /ws/kibo.
    """
    if body.trigger not in _VALID_KIBO_TRIGGERS:
        return JSONResponse(
            {"error": f"Unknown trigger '{body.trigger}'. Valid triggers: {sorted(_VALID_KIBO_TRIGGERS)}"},
            status_code=422,
        )
    await bus.publish(Event.from_model(
        EventType.KIBO_TRIGGER,
        KiboTriggerData(trigger=body.trigger, duration=body.duration),
    ))
    return {"status": "trigger published", "trigger": body.trigger}


@app.websocket("/ws/kibo")
async def kibo_ws(websocket: WebSocket):
    """WebSocket endpoint for the Kibo 3D character viewer.

    Subscribes to KIBO_TRIGGER events on the bus and forwards them as
    KiboCommand JSON to the connected browser client.
    """
    if not await _authorize_websocket(websocket):
        return
    await websocket.accept()
    _kibo_clients.append(websocket)
    logger.info("Kibo client connected (%d total)", len(_kibo_clients))

    q = bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=25.0)
            except asyncio.TimeoutError:
                # Send a keepalive ping so the connection stays alive through
                # proxies/load-balancers that close idle WebSocket connections
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            if event.type == EventType.KIBO_TRIGGER:
                cmd: dict = {
                    "type": "playTrigger",
                    "trigger": event.data["trigger"],
                }
                if event.data.get("duration") is not None:
                    cmd["duration"] = event.data["duration"]
                try:
                    await websocket.send_json(cmd)
                except Exception:
                    break  # client disconnected
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
        try:
            _kibo_clients.remove(websocket)
        except ValueError:
            pass
        logger.info("Kibo client disconnected (%d remaining)", len(_kibo_clients))


# =====================================================================
# SSE — real-time event stream
# =====================================================================

@app.get("/state/events")
async def sse_events(request: Request):
    """Server-Sent Events stream.  Subscribers receive every bridge event."""
    raw_types = request.query_params.get("types", "").strip()
    filter_types: set[EventType] | None = None
    if raw_types:
        filter_types = set()
        for item in raw_types.split(","):
            name = item.strip()
            if not name:
                continue
            try:
                filter_types.add(EventType(name))
            except ValueError:
                continue

    async def generate():
        if filter_types is None or EventType.STATE_SYNC in filter_types:
            seed = Event.from_model(
                EventType.STATE_SYNC,
                StateSyncData.model_validate(state.to_dict()),
            )
            seed.sequence = bus.last_sequence
            yield seed.to_sse()
        async for event in bus.stream(filter_types):
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


@app.websocket("/ws")
async def bridge_ws(websocket: WebSocket):
    if not await _authorize_websocket(websocket):
        return
    await websocket.accept()
    await websocket.send_json(_bridge_state_message())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
                continue

            msg_type = message.get("type")

            try:
                if msg_type == "get_state":
                    await websocket.send_json(_bridge_state_message())
                    continue

                if not relay.connected:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Engine session bundle unavailable",
                        "relay": relay.status(),
                    })
                    continue

                if msg_type == "select" or msg_type == "legal_moves":
                    square = str(message.get("square", ""))
                    result = await relay.send_legal_moves_for_square(state.fen, square)
                    targets = list(result.get("targets", []))
                    await _store_selection(square, targets)
                    await websocket.send_json(result)
                elif msg_type == "deselect":
                    await _clear_selection()
                    await websocket.send_json({"type": "selection_cleared"})
                elif msg_type == "suggest":
                    difficulty = message.get("difficulty", DEFAULT_AI_DIFFICULTY)
                    result = _normalize_suggestion_message(
                        await relay.send_suggest(state.fen, int(difficulty))
                    )
                    from_sq = str(result.get("from", "") or "")
                    to_sq = str(result.get("to", "") or "")
                    if from_sq and to_sq:
                        await _store_best_move(from_sq, to_sq)
                    await websocket.send_json(result)
                elif msg_type == "move":
                    move = str(message.get("move", ""))
                    command_id, accepted = _claim_command_id(message.get("command_id"))
                    if not accepted:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Duplicate command_id",
                            "command_id": command_id,
                        })
                        continue
                    await websocket.send_json(
                        await relay.send_move_and_wait(move, command_id=command_id)
                    )
                elif msg_type == "reset":
                    command_id, accepted = _claim_command_id(message.get("command_id"))
                    if not accepted:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Duplicate command_id",
                            "command_id": command_id,
                        })
                        continue
                    response = await relay.send_reset_and_wait(command_id=command_id)
                    state.reset()
                    await bus.publish(Event(type=EventType.GAME_RESET, data={}))
                    await _publish_led_reset("websocket_reset")
                    await websocket.send_json(response)
                elif msg_type == "ai_move":
                    difficulty = message.get("difficulty")
                    await websocket.send_json(
                        await relay.send_ai_move_and_wait(
                            int(difficulty) if difficulty is not None else None
                        )
                    )
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unsupported bridge command: {msg_type}",
                    })
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "error", "message": "Engine timeout"})
    except WebSocketDisconnect:
        return


# =====================================================================
# Main
# =====================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("BRIDGE_PORT", "5003"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="info")
